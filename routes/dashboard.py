from flask import Blueprint, request, jsonify
from models import get_db_connection, get_setting, set_setting
from routes.auth import admin_required

dashboard_bp = Blueprint('dashboard', __name__)

def date_filter():
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    clause = ''
    params = []
    if start:
        clause += ' AND created_at >= ?'
        params.append(start)
    if end:
        clause += ' AND created_at <= ?'
        params.append(end + ' 23:59:59')
    return clause, params

@dashboard_bp.route('/stats')
@admin_required
def get_stats(current_user):
    dclause, dparams = date_filter()
    conn = get_db_connection()
    total_conversations = conn.execute(
        f'SELECT COUNT(*) as cnt FROM chat_history WHERE 1=1{dclause}', dparams
    ).fetchone()['cnt']
    unique_users = conn.execute(
        f'SELECT COUNT(DISTINCT user_id) as cnt FROM chat_history WHERE 1=1{dclause}', dparams
    ).fetchone()['cnt']
    total_agents = conn.execute('SELECT COUNT(*) as cnt FROM agent_configs').fetchone()['cnt']
    total_news = conn.execute('SELECT COUNT(*) as cnt FROM news').fetchone()['cnt']
    today_conversations = conn.execute(
        "SELECT COUNT(*) as cnt FROM chat_history WHERE date(created_at) = date('now')"
    ).fetchone()['cnt']
    today_users = conn.execute(
        "SELECT COUNT(DISTINCT user_id) as cnt FROM chat_history WHERE date(created_at) = date('now')"
    ).fetchone()['cnt']
    conn.close()
    return jsonify({
        'total_conversations': total_conversations,
        'unique_users': unique_users,
        'total_agents': total_agents,
        'total_news': total_news,
        'today_conversations': today_conversations,
        'today_users': today_users,
    })

@dashboard_bp.route('/trends')
@admin_required
def get_trends(current_user):
    days = min(request.args.get('days', 30, type=int), 90)
    dclause, dparams = date_filter()
    conn = get_db_connection()
    query = '''
        SELECT date(created_at) as day, COUNT(*) as cnt
        FROM chat_history
        WHERE created_at >= datetime('now', ?)''' + dclause + '''
        GROUP BY day
        ORDER BY day ASC
    '''
    params = [f'-{days} days'] + dparams
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify({'trends': [dict(r) for r in rows]})

@dashboard_bp.route('/agent-usage')
@admin_required
def get_agent_usage(current_user):
    dclause, dparams = date_filter()
    conn = get_db_connection()
    rows = conn.execute(
        f'SELECT query_type, COUNT(*) as cnt, COUNT(DISTINCT user_id) as users FROM chat_history WHERE 1=1{dclause} GROUP BY query_type ORDER BY cnt DESC',
        dparams
    ).fetchall()
    conn.close()
    return jsonify({'usage': [dict(r) for r in rows]})

@dashboard_bp.route('/recent')
@admin_required
def get_recent(current_user):
    limit = request.args.get('limit', 15, type=int)
    dclause, dparams = date_filter()
    conn = get_db_connection()
    rows = conn.execute(
        f'SELECT id, user_message, query_type, created_at, user_id FROM chat_history WHERE 1=1{dclause} ORDER BY created_at DESC LIMIT ?',
        dparams + [limit]
    ).fetchall()
    conn.close()
    return jsonify({'recent': [dict(r) for r in rows]})

@dashboard_bp.route('/hot-questions')
@admin_required
def get_hot_questions(current_user):
    raw = get_setting('blocked_keywords', '')
    blocked = [k.strip() for k in raw.split(',') if k.strip()]
    dclause, dparams = date_filter()
    conn = get_db_connection()
    rows = conn.execute(
        f'SELECT user_message, COUNT(DISTINCT user_id) as users, COUNT(*) as total FROM chat_history WHERE 1=1{dclause} GROUP BY user_message ORDER BY users DESC LIMIT 30',
        dparams
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        msg = r['user_message']
        if any(k in msg for k in blocked):
            continue
        result.append({'text': msg, 'users': r['users'], 'total': r['total']})
    return jsonify({'questions': result[:20]})

@dashboard_bp.route('/user-stats')
@admin_required
def get_user_stats(current_user):
    conn = get_db_connection()
    total = conn.execute('SELECT COUNT(*) as cnt FROM users').fetchone()['cnt']
    admins = conn.execute('SELECT COUNT(*) as cnt FROM users WHERE is_admin = 1').fetchone()['cnt']
    conn.close()
    return jsonify({'total_users': total, 'admin_users': admins})

@dashboard_bp.route('/feedback-stats')
@admin_required
def feedback_stats(current_user):
    dclause, dparams = date_filter()
    from models import get_feedback_stats
    return jsonify(get_feedback_stats(
        request.args.get('start_date'),
        request.args.get('end_date')
    ))

@dashboard_bp.route('/feedback-overview')
@admin_required
def feedback_overview(current_user):
    dclause, dparams = date_filter()
    conn = get_db_connection()
    row = conn.execute(
        f'''SELECT
            SUM(CASE WHEN feedback=1 THEN 1 ELSE 0 END) as likes,
            SUM(CASE WHEN feedback=0 THEN 1 ELSE 0 END) as dislikes,
            COUNT(*) as total
        FROM chat_history WHERE feedback IS NOT NULL{dclause}''', dparams
    ).fetchone()
    conn.close()
    likes = row['likes'] or 0
    dislikes = row['dislikes'] or 0
    total = row['total'] or 0
    ratio = round(likes / total * 100, 1) if total > 0 else 0
    return jsonify({'likes': likes, 'dislikes': dislikes, 'total': total, 'ratio': ratio})

@dashboard_bp.route('/feedback-by-agent')
@admin_required
def feedback_by_agent(current_user):
    dclause, dparams = date_filter()
    conn = get_db_connection()
    rows = conn.execute(
        f'''SELECT
            a.query_type,
            ac.name as agent_name,
            SUM(CASE WHEN a.feedback=1 THEN 1 ELSE 0 END) as likes,
            SUM(CASE WHEN a.feedback=0 THEN 1 ELSE 0 END) as dislikes,
            COUNT(*) as total
        FROM chat_history a
        LEFT JOIN agent_configs ac ON a.query_type = ac.type
        WHERE a.feedback IS NOT NULL{dclause}
        GROUP BY a.query_type
        ORDER BY total DESC''', dparams
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        likes = r['likes'] or 0
        dislikes = r['dislikes'] or 0
        total = r['total'] or 0
        ratio = round(likes / total * 100, 1) if total > 0 else 0
        result.append({
            'query_type': r['query_type'],
            'agent_name': r['agent_name'] or r['query_type'],
            'likes': likes,
            'dislikes': dislikes,
            'total': total,
            'ratio': ratio,
        })
    return jsonify({'agents': result})

@dashboard_bp.route('/negative-feedback')
@admin_required
def negative_feedback(current_user):
    dclause, dparams = date_filter()
    conn = get_db_connection()
    rows = conn.execute(
        f'''SELECT a.id, a.user_message, a.bot_response, a.query_type, a.created_at,
            ac.name as agent_name
        FROM chat_history a
        LEFT JOIN agent_configs ac ON a.query_type = ac.type
        WHERE a.feedback = 0{dclause}
        ORDER BY a.created_at DESC
        LIMIT 100''', dparams
    ).fetchall()
    conn.close()
    return jsonify({'items': [dict(r) for r in rows]})

@dashboard_bp.route('/feedback-reasons')
@admin_required
def feedback_reasons(current_user):
    from models import get_feedback_reasons
    rows = get_feedback_reasons(
        request.args.get('start_date'),
        request.args.get('end_date')
    )
    return jsonify({'reasons': rows})

@dashboard_bp.route('/hot-questions/save', methods=['POST'])
@admin_required
def save_hot_questions(current_user):
    import json
    data = request.get_json()
    questions = data.get('questions', [])
    set_setting('approved_hot_questions', json.dumps(questions, ensure_ascii=False))
    return jsonify({'message': 'Saved', 'count': len(questions)})
