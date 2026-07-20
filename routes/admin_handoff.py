from flask import Blueprint, Response, jsonify, request

from routes.auth import admin_required
from services.handoff_service import (
    HandoffError,
    append_agent_reply,
    claim_session,
    close_agent_session,
    export_archived_sessions,
    get_archived_session_detail,
    get_agent_me,
    get_agent_session_detail,
    list_archived_sessions,
    list_agent_queue,
    list_notifications,
    list_user_archived_sessions,
    mark_agent_read,
    set_agent_status,
)
from services.security_service import rate_limit


admin_handoff_bp = Blueprint('admin_handoff', __name__)


def _error_response(exc):
    return jsonify({'error': exc.message}), exc.status_code


@admin_handoff_bp.route('/queue', methods=['GET'])
@admin_required
def queue(current_user):
    try:
        return jsonify(list_agent_queue(current_user['user_id']))
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/archive', methods=['GET'])
@admin_required
def archive(current_user):
    try:
        return jsonify(list_archived_sessions(
            page=request.args.get('page', 1),
            limit=request.args.get('limit', 20),
            date_from=request.args.get('from', ''),
            date_to=request.args.get('to', ''),
            keyword=request.args.get('keyword', ''),
            team=request.args.get('team', ''),
            agent_id=request.args.get('agent_id', ''),
            service_mode=request.args.get('service_mode', ''),
        ))
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/archive/<session_id>', methods=['GET'])
@admin_required
def archive_detail(current_user, session_id):
    try:
        return jsonify({'session': get_archived_session_detail(session_id)})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/users/<user_id>/history', methods=['GET'])
@admin_required
def user_history(current_user, user_id):
    try:
        return jsonify(list_user_archived_sessions(
            user_id,
            page=request.args.get('page', 1),
            limit=request.args.get('limit', 20),
            exclude_session_id=request.args.get('exclude_session_id', ''),
        ))
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/export', methods=['POST'])
@admin_required
@rate_limit('handoff-export', limit=10, window_seconds=60)
def export_archive(current_user):
    data = request.get_json(silent=True) or {}
    try:
        result = export_archived_sessions(
            current_user['user_id'],
            session_ids=data.get('session_ids'),
            filters=data.get('filters'),
        )
        response = Response(result['content'], content_type='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = f'attachment; filename="{result["filename"]}"'
        response.headers['X-Export-Row-Count'] = str(result['row_count'])
        return response
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/claim', methods=['POST'])
@admin_required
@rate_limit('handoff-claim', limit=30, window_seconds=60)
def claim(current_user, session_id):
    try:
        return jsonify({'session': claim_session(current_user['user_id'], session_id)})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/detail', methods=['GET'])
@admin_required
def detail(current_user, session_id):
    try:
        return jsonify({'session': get_agent_session_detail(current_user['user_id'], session_id)})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/reply', methods=['POST'])
@admin_required
@rate_limit('handoff-reply', limit=60, window_seconds=60)
def reply(current_user, session_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({'message': append_agent_reply(current_user['user_id'], session_id, data.get('content'))}), 201
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/close', methods=['POST'])
@admin_required
def close(current_user, session_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({'session': close_agent_session(current_user['user_id'], session_id, str(data.get('reason') or 'agent_close')[:40])})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/read', methods=['POST'])
@admin_required
def read(current_user, session_id):
    data = request.get_json(silent=True) or {}
    try:
        mark_agent_read(current_user['user_id'], session_id, data.get('message_id', 0))
        return jsonify({'message': 'ok'})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/agent/status', methods=['POST'])
@admin_required
def agent_status(current_user):
    data = request.get_json(silent=True) or {}
    try:
        agent = set_agent_status(current_user, bool(data.get('online')), data.get('max_concurrent', 3))
        return jsonify({'agent': agent})
    except (TypeError, ValueError):
        return jsonify({'error': '接待上限必须是1到10之间的整数'}), 400


@admin_handoff_bp.route('/agent/me', methods=['GET'])
@admin_required
def agent_me(current_user):
    return jsonify({'agent': get_agent_me(current_user['user_id'])})


@admin_handoff_bp.route('/notifications', methods=['GET'])
@admin_required
def notifications(current_user):
    try:
        return jsonify(list_notifications(
            current_user['user_id'],
            request.args.get('after_session_id', 0, type=int),
            request.args.get('after_message_id', 0, type=int),
        ))
    except HandoffError as exc:
        return _error_response(exc)
