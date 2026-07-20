from flask import Blueprint, jsonify, request

from routes.auth import identity_required
from services.handoff_service import (
    HandoffError,
    append_user_message,
    close_user_session,
    defer_user_session,
    get_current_session,
    get_public_config,
    get_user_session,
    list_recent_sessions,
    list_user_messages,
    start_handoff,
)
from services.security_service import rate_limit


handoff_bp = Blueprint('handoff', __name__)


def _error_response(exc):
    return jsonify({'error': exc.message}), exc.status_code


@handoff_bp.route('/config', methods=['GET'])
def public_config():
    return jsonify(get_public_config())


@handoff_bp.route('/start', methods=['POST'])
@identity_required
@rate_limit('handoff-start', limit=5, window_seconds=600)
def start(identity):
    data = request.get_json(silent=True) or {}
    history_ids = data.get('history_ids') or []
    if not isinstance(history_ids, list) or len(history_ids) > 20:
        return jsonify({'error': 'history_ids 格式错误或数量超过20条'}), 400
    try:
        session = start_handoff(
            identity,
            history_ids=history_ids,
            query_type=str(data.get('query_type') or '')[:50],
            note=str(data.get('note') or '')[:2000],
        )
        return jsonify({'session': session}), 201
    except HandoffError as exc:
        return _error_response(exc)


@handoff_bp.route('/current', methods=['GET'])
@identity_required
def current(identity):
    return jsonify({'session': get_current_session(identity['user_id'])})


@handoff_bp.route('/session/<session_id>', methods=['GET'])
@identity_required
def session_status(identity, session_id):
    session = get_user_session(identity['user_id'], session_id)
    if not session:
        return jsonify({'error': '咨询会话不存在'}), 404
    return jsonify({'session': session})


@handoff_bp.route('/message', methods=['POST'])
@identity_required
@rate_limit('handoff-message', limit=30, window_seconds=60)
def message(identity):
    data = request.get_json(silent=True) or {}
    try:
        item = append_user_message(identity['user_id'], str(data.get('session_id') or ''), data.get('content'))
        return jsonify({'message': item}), 201
    except HandoffError as exc:
        return _error_response(exc)


@handoff_bp.route('/messages/<session_id>', methods=['GET'])
@identity_required
def messages(identity, session_id):
    try:
        items = list_user_messages(
            identity['user_id'], session_id,
            request.args.get('after_id', 0, type=int),
            request.args.get('limit', 50, type=int),
        )
        return jsonify({'messages': items})
    except HandoffError as exc:
        return _error_response(exc)


@handoff_bp.route('/recent', methods=['GET'])
@identity_required
def recent(identity):
    return jsonify({'sessions': list_recent_sessions(identity['user_id'], request.args.get('limit', 20, type=int))})


@handoff_bp.route('/close', methods=['POST'])
@identity_required
def close(identity):
    data = request.get_json(silent=True) or {}
    reason = str(data.get('reason') or 'user_cancel')[:40]
    if reason not in {'user_cancel', 'done'}:
        reason = 'user_cancel'
    try:
        session = close_user_session(identity['user_id'], str(data.get('session_id') or ''), reason)
        return jsonify({'session': session})
    except HandoffError as exc:
        return _error_response(exc)


@handoff_bp.route('/defer', methods=['POST'])
@identity_required
def defer(identity):
    data = request.get_json(silent=True) or {}
    try:
        session = defer_user_session(identity['user_id'], str(data.get('session_id') or ''))
        return jsonify({'session': session})
    except HandoffError as exc:
        return _error_response(exc)
