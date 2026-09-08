from flask import Blueprint, Response, jsonify, request

from routes.auth import admin_required, agent_required
from services import feature_flags
from services.handoff_service import (
    HandoffError,
    add_cs_agent,
    append_agent_reply,
    claim_session,
    close_agent_session,
    create_quick_reply,
    delete_quick_reply,
    export_archived_sessions,
    get_archived_session_detail,
    get_agent_me,
    get_agent_session_detail,
    list_agent_queue,
    list_archived_sessions,
    list_cs_agents,
    list_notifications,
    list_quick_replies,
    list_user_archived_sessions,
    mark_agent_read,
    remove_cs_agent,
    set_agent_status,
    update_cs_agent,
    update_quick_reply,
)
from services.security_service import rate_limit


admin_handoff_bp = Blueprint('admin_handoff', __name__)


@admin_handoff_bp.before_request
def _require_handoff_enabled():
    return feature_flags.guard_request(feature_flags.HANDOFF_SYSTEM)


def _error_response(exc):
    return jsonify({'error': exc.message}), exc.status_code


@admin_handoff_bp.route('/queue', methods=['GET'])
@agent_required
def queue(current_user):
    try:
        return jsonify(list_agent_queue(current_user['user_id']))
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/archive', methods=['GET'])
@agent_required
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
@agent_required
def archive_detail(current_user, session_id):
    try:
        return jsonify({'session': get_archived_session_detail(session_id)})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/users/<user_id>/history', methods=['GET'])
@agent_required
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
@agent_required
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
@agent_required
@rate_limit('handoff-claim', limit=30, window_seconds=60)
def claim(current_user, session_id):
    try:
        return jsonify({'session': claim_session(current_user['user_id'], session_id)})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/detail', methods=['GET'])
@agent_required
def detail(current_user, session_id):
    try:
        return jsonify({'session': get_agent_session_detail(current_user['user_id'], session_id)})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/reply', methods=['POST'])
@agent_required
@rate_limit('handoff-reply', limit=60, window_seconds=60)
def reply(current_user, session_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({'message': append_agent_reply(current_user['user_id'], session_id, data.get('content'))}), 201
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/close', methods=['POST'])
@agent_required
def close(current_user, session_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({'session': close_agent_session(current_user['user_id'], session_id, str(data.get('reason') or 'agent_close')[:40])})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/<session_id>/read', methods=['POST'])
@agent_required
def read(current_user, session_id):
    data = request.get_json(silent=True) or {}
    try:
        mark_agent_read(current_user['user_id'], session_id, data.get('message_id', 0))
        return jsonify({'message': 'ok'})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/agent/status', methods=['POST'])
@agent_required
def agent_status(current_user):
    data = request.get_json(silent=True) or {}
    try:
        agent = set_agent_status(current_user, bool(data.get('online')), data.get('max_concurrent', 3))
        return jsonify({'agent': agent})
    except HandoffError as exc:
        return _error_response(exc)
    except (TypeError, ValueError):
        return jsonify({'error': '接待上限必须是1到10之间的整数'}), 400


@admin_handoff_bp.route('/agent/me', methods=['GET'])
@agent_required
def agent_me(current_user):
    return jsonify({'agent': get_agent_me(current_user['user_id'])})


@admin_handoff_bp.route('/notifications', methods=['GET'])
@agent_required
def notifications(current_user):
    try:
        return jsonify(list_notifications(
            current_user['user_id'],
            request.args.get('after_session_id', 0, type=int),
            request.args.get('after_message_id', 0, type=int),
        ))
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/agents', methods=['GET'])
@admin_required
def cs_agents(current_user):
    return jsonify({'agents': list_cs_agents()})


@admin_handoff_bp.route('/agents', methods=['POST'])
@admin_required
@rate_limit('handoff-agent-admin', limit=20, window_seconds=600)
def cs_agent_add(current_user):
    data = request.get_json(silent=True) or {}
    try:
        agent = add_cs_agent(
            current_user['user_id'],
            data.get('username'),
            data.get('display_name', ''),
            data.get('max_concurrent', 3),
            password=data.get('password'),
        )
        return jsonify({'agent': agent}), 201
    except HandoffError as exc:
        return _error_response(exc)
    except (TypeError, ValueError):
        return jsonify({'error': '接待上限必须是1到10之间的整数'}), 400


@admin_handoff_bp.route('/agents/<user_id>', methods=['PUT'])
@admin_required
@rate_limit('handoff-agent-admin', limit=20, window_seconds=600)
def cs_agent_edit(current_user, user_id):
    data = request.get_json(silent=True) or {}
    try:
        agent = update_cs_agent(
            user_id,
            display_name=data.get('display_name'),
            max_concurrent=data.get('max_concurrent'),
        )
        return jsonify({'agent': agent})
    except HandoffError as exc:
        return _error_response(exc)
    except (TypeError, ValueError):
        return jsonify({'error': '接待上限必须是1到10之间的整数'}), 400


@admin_handoff_bp.route('/agents/<user_id>', methods=['DELETE'])
@admin_required
@rate_limit('handoff-agent-admin', limit=20, window_seconds=600)
def cs_agent_remove(current_user, user_id):
    try:
        return jsonify(remove_cs_agent(current_user['user_id'], user_id))
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/quick-replies', methods=['GET'])
@agent_required
def quick_replies(current_user):
    enabled_only = request.args.get('enabled') == '1'
    return jsonify({'quick_replies': list_quick_replies(include_disabled=not enabled_only)})


@admin_handoff_bp.route('/quick-replies', methods=['POST'])
@admin_required
@rate_limit('handoff-quick-reply-admin', limit=60, window_seconds=600)
def quick_reply_add(current_user):
    data = request.get_json(silent=True) or {}
    try:
        item = create_quick_reply(
            current_user['user_id'],
            data.get('title'),
            data.get('content'),
            data.get('sort_order', 0),
            bool(data.get('enabled', True)),
        )
        return jsonify({'quick_reply': item}), 201
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/quick-replies/<int:reply_id>', methods=['PUT'])
@admin_required
@rate_limit('handoff-quick-reply-admin', limit=60, window_seconds=600)
def quick_reply_edit(current_user, reply_id):
    data = request.get_json(silent=True) or {}
    try:
        item = update_quick_reply(
            current_user['user_id'],
            reply_id,
            title=data.get('title'),
            content=data.get('content'),
            sort_order=data.get('sort_order'),
            enabled=data.get('enabled'),
        )
        return jsonify({'quick_reply': item})
    except HandoffError as exc:
        return _error_response(exc)


@admin_handoff_bp.route('/quick-replies/<int:reply_id>', methods=['DELETE'])
@admin_required
@rate_limit('handoff-quick-reply-admin', limit=60, window_seconds=600)
def quick_reply_remove(current_user, reply_id):
    try:
        return jsonify(delete_quick_reply(current_user['user_id'], reply_id))
    except HandoffError as exc:
        return _error_response(exc)
