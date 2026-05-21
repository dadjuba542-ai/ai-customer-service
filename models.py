import sqlite3
import uuid
import re
from datetime import datetime
from config import Config

def get_db_connection():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            query_type TEXT NOT NULL,
            user_message TEXT NOT NULL,
            bot_response TEXT,
            coze_message_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    try:
        cursor.execute('ALTER TABLE chat_history ADD COLUMN feedback INTEGER DEFAULT NULL')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE chat_history ADD COLUMN feedback_reason TEXT DEFAULT NULL')
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT DEFAULT '',
            content TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cursor.execute('ALTER TABLE news ADD COLUMN views INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE news ADD COLUMN pinned INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE news ADD COLUMN featured INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE news ADD COLUMN category TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            summary TEXT DEFAULT '',
            content TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            highlights TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agent_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            description TEXT DEFAULT '',
            prompt TEXT DEFAULT '',
            avatar_url TEXT DEFAULT '',
            color TEXT DEFAULT '#4F46E5',
            bot_id TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cursor.execute('ALTER TABLE agent_configs ADD COLUMN icon TEXT DEFAULT "robot"')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE agent_configs ADD COLUMN chat_desc TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS satisfaction_surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT DEFAULT '',
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            category TEXT DEFAULT '',
            status INTEGER DEFAULT 1,
            view_count INTEGER DEFAULT 0,
            reply_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            nickname TEXT DEFAULT '',
            content TEXT DEFAULT '',
            status INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')

    conn.commit()

    default_agents = [
        ('aura', '产品资料查询', '产品咨询', '快速获取产品详情', '我想咨询一下产品资料', '', '#4F46E5', Config.BOT_MAPPING.get('产品咨询', ''), 'database'),
        ('coder', '产品使用答疑', '使用答疑', '解决使用中的困惑', '我在产品使用中遇到了问题，帮我看看', '', '#3B82F6', Config.BOT_MAPPING.get('使用答疑', ''), 'question'),
        ('translator', '个人IP打造', '朋友圈帮写', '建立个人影响力', '我想打造个人IP，帮我想想', '', '#059669', Config.BOT_MAPPING.get('朋友圈帮写', ''), 'lightning'),
        ('creative', '疑难问题解答', '口播文案帮写', '深度剖析核心难题', '我有一个疑难问题需要解答', '', '#EA580C', Config.BOT_MAPPING.get('口播文案帮写', ''), 'lifebuoy'),
    ]
    for agent in default_agents:
        cursor.execute('''
            INSERT OR IGNORE INTO agent_configs (agent_id, name, type, description, prompt, avatar_url, color, bot_id, icon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', agent)

    conn.commit()
    conn.close()

    # 自动清理30天前的聊天记录
    cleanup_old_history()

# ===== Cleanup =====
def cleanup_old_history():
    conn = get_db_connection()
    conn.execute("DELETE FROM chat_history WHERE created_at < datetime('now', '-30 days')")
    conn.commit()
    conn.close()

def delete_chat_history_batch(ids):
    if not ids:
        return
    conn = get_db_connection()
    placeholders = ','.join(['?'] * len(ids))
    conn.execute(f'DELETE FROM chat_history WHERE id IN ({placeholders})', ids)
    conn.commit()
    conn.close()

# ===== Settings =====
def get_setting(key, default=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    ''', (key, value))
    conn.commit()
    conn.close()

# ===== News =====
def create_news(title, summary='', content='', image_url='', category=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO news (title, summary, content, image_url, category) VALUES (?, ?, ?, ?, ?)',
        (title, summary, content, image_url, category)
    )
    conn.commit()
    id = cursor.lastrowid
    conn.close()
    return id

def get_all_news():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM news ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_news_by_id(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM news WHERE id = ?', (id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_news(id, title, summary, content, image_url, category=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE news SET title=?, summary=?, content=?, image_url=?, category=? WHERE id=?',
        (title, summary, content, image_url, category, id)
    )
    conn.commit()
    conn.close()

def delete_news(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM news WHERE id = ?', (id,))
    conn.commit()
    conn.close()

def increment_news_views(id):
    conn = get_db_connection()
    conn.execute('UPDATE news SET views = views + 1 WHERE id = ?', (id,))
    conn.commit()
    conn.close()

def get_pinned_news(limit=3):
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT * FROM news WHERE pinned = 1 ORDER BY created_at DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_featured_news(limit=3):
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT * FROM news WHERE featured = 1 ORDER BY created_at DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_news_page(page=1, limit=10, exclude_pinned=False, category=None):
    conn = get_db_connection()
    conditions = []
    params = []
    if exclude_pinned:
        conditions.append('pinned = 0')
    if category:
        conditions.append('category = ?')
        params.append(category)
    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    total = conn.execute(f'SELECT COUNT(*) as cnt FROM news {where}', params).fetchone()['cnt']
    offset = (page - 1) * limit
    rows = conn.execute(
        f'SELECT * FROM news {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': max(1, (total + limit - 1) // limit)}

def toggle_pin_news(id):
    conn = get_db_connection()
    row = conn.execute('SELECT pinned FROM news WHERE id = ?', (id,)).fetchone()
    if row:
        val = 0 if row['pinned'] else 1
        conn.execute('UPDATE news SET pinned = ? WHERE id = ?', (val, id))
        conn.commit()
        conn.close()
        return val
    conn.close()
    return 0

def toggle_featured_news(id):
    conn = get_db_connection()
    row = conn.execute('SELECT featured FROM news WHERE id = ?', (id,)).fetchone()
    if row:
        val = 0 if row['featured'] else 1
        conn.execute('UPDATE news SET featured = ? WHERE id = ?', (val, id))
        conn.commit()
        conn.close()
        return val
    conn.close()
    return 0

def get_news_categories():
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT DISTINCT category FROM news WHERE category IS NOT NULL AND category != "" ORDER BY category'
    ).fetchall()
    conn.close()
    return [r['category'] for r in rows]

# ===== Products =====
def create_product(category, name, summary, content, image_url, highlights, sort_order=0):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO products (category, name, summary, content, image_url, highlights, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (category, name, summary, content, image_url, highlights, sort_order)
    )
    conn.commit()
    id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return id

def get_all_products():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM products ORDER BY sort_order ASC, id DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_product_by_id(id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM products WHERE id = ?', (id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_product(id, category, name, summary, content, image_url, highlights, sort_order):
    conn = get_db_connection()
    conn.execute(
        'UPDATE products SET category=?, name=?, summary=?, content=?, image_url=?, highlights=?, sort_order=? WHERE id=?',
        (category, name, summary, content, image_url, highlights, sort_order, id)
    )
    conn.commit()
    conn.close()

def delete_product(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM products WHERE id = ?', (id,))
    conn.commit()
    conn.close()

def reorder_products(order_list):
    conn = get_db_connection()
    for id, order in order_list:
        conn.execute('UPDATE products SET sort_order = ? WHERE id = ?', (order, id))
    conn.commit()
    conn.close()

# ===== Agent Configs =====
def get_all_agent_configs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agent_configs')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_agent_config(agent_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agent_configs WHERE agent_id = ?', (agent_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_agent_config(agent_id, name, description, prompt, avatar_url, color, bot_id, icon, chat_desc=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE agent_configs SET name=?, description=?, prompt=?, avatar_url=?, color=?, bot_id=?, icon=?, chat_desc=?, updated_at=CURRENT_TIMESTAMP
        WHERE agent_id=?
    ''', (name, description, prompt, avatar_url, color, bot_id, icon, chat_desc, agent_id))
    conn.commit()
    conn.close()

def create_agent_config(agent_id, name, type_, description, prompt, avatar_url, color, bot_id, icon, chat_desc=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO agent_configs (agent_id, name, type, description, prompt, avatar_url, color, bot_id, icon, chat_desc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (agent_id, name, type_, description, prompt, avatar_url, color, bot_id, icon, chat_desc))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def delete_agent_config(agent_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM agent_configs WHERE agent_id = ?', (agent_id,))
    conn.commit()
    conn.close()

# ===== Users =====
def create_user(username, password_hash):
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = str(uuid.uuid4())
    is_admin = 1 if username == Config.ADMIN_USERNAME else 0
    try:
        cursor.execute(
            'INSERT INTO users (user_id, username, password_hash, is_admin) VALUES (?, ?, ?, ?)',
            (user_id, username, password_hash, is_admin)
        )
        conn.commit()
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def get_user_by_username(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_id(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

# ===== Chat History =====
def save_chat_history(user_id, query_type, user_message, bot_response=None, coze_message_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO chat_history (user_id, query_type, user_message, bot_response, coze_message_id) VALUES (?, ?, ?, ?, ?)',
        (user_id, query_type, user_message, bot_response, coze_message_id)
    )
    conn.commit()
    history_id = cursor.lastrowid
    conn.close()
    return history_id

def get_chat_history(user_id, query_type=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if query_type:
        cursor.execute(
            'SELECT * FROM chat_history WHERE user_id = ? AND query_type = ? ORDER BY created_at DESC',
            (user_id, query_type)
        )
    else:
        cursor.execute(
            'SELECT * FROM chat_history WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )
    history = cursor.fetchall()
    conn.close()
    return [dict(row) for row in history]

def get_chat_history_by_id(history_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM chat_history WHERE id = ? AND user_id = ?',
        (history_id, user_id)
    )
    history = cursor.fetchone()
    conn.close()
    return dict(history) if history else None

# ===== Feedback =====
def set_chat_feedback(history_id, feedback):
    conn = get_db_connection()
    conn.execute('UPDATE chat_history SET feedback = ? WHERE id = ?', (feedback, history_id))
    conn.commit()
    conn.close()

def get_feedback_stats(start_date=None, end_date=None):
    conn = get_db_connection()
    clause = ''
    params = []
    if start_date:
        clause += ' AND created_at >= ?'
        params.append(start_date)
    if end_date:
        clause += ' AND created_at <= ?'
        params.append(end_date + ' 23:59:59')
    likes = conn.execute(
        f'SELECT COUNT(*) as cnt FROM chat_history WHERE feedback = 1{clause}', params
    ).fetchone()['cnt']
    dislikes = conn.execute(
        f'SELECT COUNT(*) as cnt FROM chat_history WHERE feedback = 0{clause}', params
    ).fetchone()['cnt']
    conn.close()
    total = likes + dislikes
    ratio = round(likes / total * 100, 1) if total > 0 else 0
    return {'likes': likes, 'dislikes': dislikes, 'total': total, 'ratio': ratio}

def set_feedback_reason(history_id, reason):
    conn = get_db_connection()
    conn.execute('UPDATE chat_history SET feedback_reason = ? WHERE id = ?', (reason, history_id))
    conn.commit()
    conn.close()

def get_feedback_reasons(start_date=None, end_date=None):
    conn = get_db_connection()
    clause = ''
    params = []
    if start_date:
        clause += ' AND created_at >= ?'
        params.append(start_date)
    if end_date:
        clause += ' AND created_at <= ?'
        params.append(end_date + ' 23:59:59')
    rows = conn.execute(
        f'''SELECT query_type, feedback_reason, COUNT(*) as cnt
        FROM chat_history
        WHERE feedback = 0 AND feedback_reason IS NOT NULL{clause}
        GROUP BY query_type, feedback_reason
        ORDER BY cnt DESC''', params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_survey(score):
    conn = get_db_connection()
    conn.execute('INSERT INTO satisfaction_surveys (score) VALUES (?)', (score,))
    conn.commit()
    conn.close()

# ===== Chat Sessions =====
def get_chat_sessions(user_id='anonymous', query_type=None):
    conn = get_db_connection()
    if query_type:
        rows = conn.execute(
            'SELECT * FROM chat_history WHERE user_id = ? AND query_type = ? ORDER BY created_at DESC',
            (user_id, query_type)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM chat_history WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        ).fetchall()
    conn.close()

    items = [dict(r) for r in rows]
    sessions = []
    for item in items:
        item_dt = item['created_at']
        if sessions and sessions[-1]['query_type'] == item['query_type']:
            last = sessions[-1]
            last_dt = last['items'][-1]['created_at']
            try:
                from datetime import datetime
                t1 = datetime.strptime(item_dt, '%Y-%m-%d %H:%M:%S')
                t2 = datetime.strptime(last_dt, '%Y-%m-%d %H:%M:%S')
                if abs((t2 - t1).total_seconds()) < 3600:
                    last['items'].insert(0, item)
                    last['count'] = len(last['items'])
                    continue
            except:
                pass
        sessions.append({
            'query_type': item['query_type'],
            'date': item_dt,
            'items': [item],
            'count': 1,
        })

    return sessions

# ===== Community =====
def check_content(text):
    raw = get_setting('blocked_keywords', '')
    blocked = [k.strip() for k in raw.split(',') if k.strip()]
    if any(k in text for k in blocked):
        return False
    patterns = [r'1[3-9]\d{9}', r'(?:VX|vx|wx|微信|WeChat)\s*[:：]\s*\w+', r'^https?://\S+$']
    for p in patterns:
        if re.search(p, text):
            return False
    return True

def create_question(nickname, title, content='', category='', status=1):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO questions (nickname, title, content, category, status) VALUES (?, ?, ?, ?, ?)',
        (nickname, title, content, category, status)
    )
    conn.commit()
    id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return id

def update_question(id, title, content, category, status=1):
    conn = get_db_connection()
    conn.execute(
        'UPDATE questions SET title=?, content=?, category=?, status=? WHERE id=?',
        (title, content, category, status, id)
    )
    conn.commit()
    conn.close()

def get_questions(page=1, limit=10, category=None, status=1):
    conn = get_db_connection()
    conditions = ['status = ?']
    params = [status]
    if category:
        conditions.append('category = ?')
        params.append(category)
    where = 'WHERE ' + ' AND '.join(conditions)
    total = conn.execute(f'SELECT COUNT(*) as cnt FROM questions {where}', params).fetchone()['cnt']
    offset = (page - 1) * limit
    rows = conn.execute(
        f'SELECT * FROM questions {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': max(1, (total + limit - 1) // limit)}

def get_question_detail(id):
    conn = get_db_connection()
    conn.execute('UPDATE questions SET view_count = view_count + 1 WHERE id = ?', (id,))
    row = conn.execute('SELECT * FROM questions WHERE id = ?', (id,)).fetchone()
    if not row:
        conn.close()
        return None
    q = dict(row)
    replies_rows = conn.execute(
        'SELECT * FROM replies WHERE question_id = ? AND status = 1 ORDER BY created_at ASC',
        (id,)
    ).fetchall()
    conn.close()
    q['replies'] = [dict(r) for r in replies_rows]
    return q

def create_reply(question_id, nickname, content, status=1):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO replies (question_id, nickname, content, status) VALUES (?, ?, ?, ?)',
        (question_id, nickname, content, status)
    )
    conn.execute('UPDATE questions SET reply_count = reply_count + 1 WHERE id = ?', (question_id,))
    conn.commit()
    id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return id

def delete_question(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM questions WHERE id = ?', (id,))
    conn.execute('DELETE FROM replies WHERE question_id = ?', (id,))
    conn.commit()
    conn.close()

def delete_reply(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM replies WHERE id = ?', (id,))
    conn.close()

def toggle_question_status(id):
    conn = get_db_connection()
    row = conn.execute('SELECT status FROM questions WHERE id = ?', (id,)).fetchone()
    if row:
        new_val = 0 if row['status'] else 1
        conn.execute('UPDATE questions SET status = ? WHERE id = ?', (new_val, id))
        conn.commit()
        conn.close()
        return new_val
    conn.close()
    return 0

def get_question_categories():
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT DISTINCT category FROM questions WHERE category != "" AND status = 1 ORDER BY category'
    ).fetchall()
    conn.close()
    return [r['category'] for r in rows]
