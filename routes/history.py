from flask import Blueprint, request, jsonify
from models import get_chat_history, get_chat_history_by_id, get_db_connection, get_setting, get_chat_sessions, delete_chat_history_batch

history_bp = Blueprint('history', __name__)

@history_bp.route('', methods=['GET'])
def get_history():
    query_type = request.args.get('query_type')
    history = get_chat_history('anonymous', query_type)
    return jsonify({'history': history})

@history_bp.route('/<int:history_id>', methods=['GET'])
def get_history_detail(history_id):
    history = get_chat_history_by_id(history_id, 'anonymous')
    if not history:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(history)

@history_bp.route('/sessions')
def get_sessions():
    query_type = request.args.get('query_type')
    sessions = get_chat_sessions('anonymous', query_type)
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
    raw = get_setting('blocked_keywords', '')
    blocked = [k.strip() for k in raw.split(',') if k.strip()]

    conn = get_db_connection()
    rows = conn.execute('''
        SELECT user_message, COUNT(DISTINCT user_id) as cnt
        FROM chat_history
        GROUP BY user_message
        ORDER BY cnt DESC
        LIMIT 30
    ''').fetchall()
    conn.close()

    result = []
    for r in rows:
        msg = r['user_message']
        if any(k in msg for k in blocked):
            continue
        result.append({'text': msg, 'count': r['cnt']})

    return jsonify({'questions': result[:12]})
