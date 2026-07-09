from flask import Blueprint, jsonify, request

from models import create_share_event

share_bp = Blueprint('share', __name__)


@share_bp.route('/share-events', methods=['POST'])
def record_share_event():
    data = request.get_json(silent=True) or {}
    event_id = create_share_event({
        'user_id': data.get('user_id'),
        'team_name': data.get('team_name'),
        'member_name': data.get('member_name'),
        'query_type': data.get('query_type'),
        'history_id': data.get('history_id'),
        'share_type': data.get('share_type') or 'answer_card',
    })
    return jsonify({'id': event_id, 'message': 'Share event recorded'}), 201
