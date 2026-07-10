from flask import Blueprint, jsonify, request

from models import create_share_event, get_chat_history_by_id
from routes.auth import identity_required
from services.security_service import rate_limit

share_bp = Blueprint('share', __name__)


@share_bp.route('/share-events', methods=['POST'])
@identity_required
@rate_limit('share-event', limit=20, window_seconds=60)
def record_share_event(identity):
    data = request.get_json(silent=True) or {}
    history_id = data.get('history_id') or None
    if history_id and not get_chat_history_by_id(history_id, identity['user_id']):
        return jsonify({'error': 'History record not found'}), 404
    event_id = create_share_event({
        'user_id': identity['user_id'],
        'team_name': identity.get('team_name'),
        'member_name': identity.get('member_name'),
        'query_type': data.get('query_type'),
        'history_id': history_id,
        'share_type': data.get('share_type') or 'answer_card',
    })
    return jsonify({'id': event_id, 'message': 'Share event recorded'}), 201
