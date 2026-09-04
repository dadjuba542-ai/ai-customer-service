from flask import Blueprint, request, jsonify
from models import get_chat_history, get_chat_history_by_id, get_setting, get_chat_sessions, delete_chat_history_batch
from models import resolve_question_bindings, MAX_PRESET_HOT_QUESTIONS
from routes.auth import identity_required
from services.security_service import rate_limit
from services.ai_review_service import enrich_history_records

history_bp = Blueprint('history', __name__)

@history_bp.route('', methods=['GET'])
@identity_required
def get_history(identity):
    uid = identity['user_id']
    query_type = request.args.get('query_type')
    history = enrich_history_records(get_chat_history(uid, query_type))
    return jsonify({'history': history})

@history_bp.route('/<int:history_id>', methods=['GET'])
@identity_required
def get_history_detail(identity, history_id):
    uid = identity['user_id']
    history = get_chat_history_by_id(history_id, uid)
    if not history:
        return jsonify({'error': 'Not found'}), 404
    enrich_history_records([history])
    return jsonify(history)

@history_bp.route('/sessions')
@identity_required
def get_sessions(identity):
    uid = identity['user_id']
    query_type = request.args.get('query_type')
    sessions = get_chat_sessions(uid, query_type)
    flat = [item for session in sessions for item in session.get('items', [])]
    enrich_history_records(flat)
    return jsonify({'sessions': sessions})

@history_bp.route('/batch-delete', methods=['POST'])
@identity_required
@rate_limit('history-delete', limit=10, window_seconds=60)
def batch_delete(identity):
    uid = identity['user_id']
    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])
    if not isinstance(ids, list) or not ids or len(ids) > 100:
        return jsonify({'error': 'ids required'}), 400
    try:
        ids = [int(item) for item in ids]
    except (TypeError, ValueError):
        return jsonify({'error': 'ids must contain integers'}), 400
    deleted = delete_chat_history_batch(ids, uid)
    return jsonify({'message': 'Deleted', 'count': deleted})

@history_bp.route('/hot-questions')
def hot_questions():
    raw = get_setting('approved_hot_questions', '[]')
    questions = resolve_question_bindings(raw, limit=MAX_PRESET_HOT_QUESTIONS)
    for index, item in enumerate(questions, start=1):
        item['count'] = len(questions) - index + 1
    return jsonify({'questions': questions})
