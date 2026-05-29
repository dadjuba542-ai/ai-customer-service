from flask import Blueprint, request, jsonify
from models import get_chat_history, get_chat_history_by_id, get_setting, get_chat_sessions, delete_chat_history_batch
import jwt
from config import Config

history_bp = Blueprint('history', __name__)

def _get_uid():
    # Strict mode: always trust JWT user_id.
    if Config.STRICT_SECURITY:
        token = request.headers.get('Authorization')
        if not token:
            return None
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            return data.get('user_id')
        except jwt.InvalidTokenError:
            return None

    # Compatibility mode: keep legacy behavior, prefer JWT if provided.
    token = request.headers.get('Authorization')
    if token and Config.SECRET_KEY:
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            if data.get('user_id'):
                return data['user_id']
        except jwt.InvalidTokenError:
            pass
    return request.args.get('user_id', 'anonymous')

@history_bp.route('', methods=['GET'])
def get_history():
    uid = _get_uid()
    if Config.STRICT_SECURITY and not uid:
        return jsonify({'error': 'Token is missing or invalid'}), 401
    query_type = request.args.get('query_type')
    history = get_chat_history(uid, query_type)
    return jsonify({'history': history})

@history_bp.route('/<int:history_id>', methods=['GET'])
def get_history_detail(history_id):
    uid = _get_uid()
    if Config.STRICT_SECURITY and not uid:
        return jsonify({'error': 'Token is missing or invalid'}), 401
    history = get_chat_history_by_id(history_id, uid)
    if not history:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(history)

@history_bp.route('/sessions')
def get_sessions():
    uid = _get_uid()
    if Config.STRICT_SECURITY and not uid:
        return jsonify({'error': 'Token is missing or invalid'}), 401
    query_type = request.args.get('query_type')
    sessions = get_chat_sessions(uid, query_type)
    return jsonify({'sessions': sessions})

@history_bp.route('/batch-delete', methods=['POST'])
def batch_delete():
    uid = _get_uid()
    if Config.STRICT_SECURITY and not uid:
        return jsonify({'error': 'Token is missing or invalid'}), 401
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'error': 'ids required'}), 400
    deleted = delete_chat_history_batch(ids, uid if Config.STRICT_SECURITY else None)
    return jsonify({'message': 'Deleted', 'count': deleted})

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
