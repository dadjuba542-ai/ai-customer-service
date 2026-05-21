from flask import Blueprint, request, jsonify
from models import get_chat_history, get_chat_history_by_id, get_db_connection, get_setting, get_chat_sessions, delete_chat_history_batch

history_bp = Blueprint('history', __name__)

def _get_uid():
    return request.args.get('user_id', 'anonymous')

@history_bp.route('', methods=['GET'])
def get_history():
    query_type = request.args.get('query_type')
    history = get_chat_history(_get_uid(), query_type)
    return jsonify({'history': history})

@history_bp.route('/<int:history_id>', methods=['GET'])
def get_history_detail(history_id):
    history = get_chat_history_by_id(history_id, _get_uid())
    if not history:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(history)

@history_bp.route('/sessions')
def get_sessions():
    query_type = request.args.get('query_type')
    sessions = get_chat_sessions(_get_uid(), query_type)
    return jsonify({'sessions': sessions})

@history_bp.route('/batch-delete', methods=['POST'])
def batch_delete():
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'error': 'ids required'}), 400
    delete_chat_history_batch(ids)
    return jsonify({'message': 'Deleted', 'count': len(ids)})

@history_bp.route('/hot-questions')
def hot_questions():
    import json
    raw = get_setting('approved_hot_questions', '[]')
    try:
        questions = json.loads(raw)
    except:
        questions = []
    result = [{'text': q, 'count': 1} for q in questions[:5]]
    return jsonify({'questions': result})
