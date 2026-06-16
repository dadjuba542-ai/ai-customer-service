import json

from flask import Blueprint, Response, jsonify, request, stream_with_context

from services.chat_service import ChatServiceError, build_chat_context, execute_sync_chat, iter_coze_stream

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/send', methods=['POST'])
def send_to_coze():
    try:
        ctx = build_chat_context(request.get_json(silent=True) or {})
        return jsonify(execute_sync_chat(ctx))
    except ChatServiceError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code


@chat_bp.route('/stream', methods=['POST'])
def stream_to_coze():
    try:
        ctx = build_chat_context(request.get_json(silent=True) or {})
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
def submit_feedback():
    data = request.get_json()
    history_id = data.get('history_id')
    feedback = data.get('feedback')
    reason = (data.get('reason') or '').strip()

    if not history_id or feedback not in (0, 1):
        return jsonify({'error': 'history_id and feedback(0/1) are required'}), 400

    from models import set_chat_feedback, set_feedback_reason
    set_chat_feedback(history_id, feedback)
    if feedback == 0 and reason:
        set_feedback_reason(history_id, reason)
    return jsonify({'message': 'Feedback saved'})


def _format_sse(event_name, payload):
    return f'event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
