import json

from flask import Blueprint, Response, jsonify, request, stream_with_context

from config import Config
from routes.auth import identity_required
from services.security_service import rate_limit
from services.chat_service import ChatServiceError, build_chat_context, execute_sync_chat, iter_coze_stream

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/send', methods=['POST'])
@identity_required
@rate_limit('chat', limit=Config.CHAT_RATE_LIMIT, window_seconds=60)
def send_to_coze(identity):
    try:
        ctx = build_chat_context(request.get_json(silent=True) or {}, identity)
        return jsonify(execute_sync_chat(ctx))
    except ChatServiceError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code


@chat_bp.route('/stream', methods=['POST'])
@identity_required
@rate_limit('chat', limit=Config.CHAT_RATE_LIMIT, window_seconds=60)
def stream_to_coze(identity):
    try:
        ctx = build_chat_context(request.get_json(silent=True) or {}, identity)
    except ChatServiceError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code

    @stream_with_context
    def generate():
        try:
            for event in iter_coze_stream(ctx):
                yield _format_sse(event['event'], event['data'])
        except ChatServiceError as exc:
            yield _format_sse(
                'error',
                {
                    'message': exc.message,
                    'retryable': exc.retryable,
                    'request_id': ctx.request_id,
                },
            )

    headers = {
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    }
    return Response(generate(), mimetype='text/event-stream', headers=headers)


@chat_bp.route('/feedback', methods=['POST'])
@identity_required
@rate_limit('feedback', limit=30, window_seconds=60)
def submit_feedback(identity):
    data = request.get_json(silent=True) or {}
    history_id = data.get('history_id')
    feedback = data.get('feedback')
    reason = (data.get('reason') or '').strip()[:200]

    if not history_id or feedback not in (0, 1):
        return jsonify({'error': 'history_id and feedback(0/1) are required'}), 400

    from models import set_chat_feedback, set_feedback_reason
    updated = set_chat_feedback(history_id, identity['user_id'], feedback)
    if not updated:
        return jsonify({'error': 'History record not found'}), 404
    if feedback == 0 and reason:
        set_feedback_reason(history_id, identity['user_id'], reason)
    return jsonify({'message': 'Feedback saved'})


def _format_sse(event_name, payload):
    return f'event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
