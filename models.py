import sqlite3
import uuid
import re
from datetime import datetime
from config import Config

def get_db_connection():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
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
    try:
        cursor.execute('ALTER TABLE chat_history ADD COLUMN team_name TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE chat_history ADD COLUMN member_name TEXT DEFAULT ""')
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
            author_key TEXT DEFAULT '',
            like_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')
    try:
        cursor.execute('ALTER TABLE replies ADD COLUMN author_key TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE replies ADD COLUMN like_count INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS case_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            customer_profile TEXT DEFAULT '',
            symptom_tags TEXT DEFAULT '',
            product_tags TEXT DEFAULT '',
            scenario TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            content TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            external_url TEXT DEFAULT '',
            status INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cursor.execute('ALTER TABLE case_documents ADD COLUMN external_url TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS case_documents_fts USING fts5(
            title,
            customer_profile,
            symptom_tags,
            product_tags,
            scenario,
            summary,
            content,
            tokenize='trigram'
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_user_created ON chat_history(user_id, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_user_type_created ON chat_history(user_id, query_type, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_feedback_created ON chat_history(feedback, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_query_type_created ON chat_history(query_type, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_created ON news(created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_featured_created ON news(featured, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_pinned_created ON news(pinned, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_category_created ON news(category, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_sort_id ON products(sort_order ASC, id DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_questions_status_category_created ON questions(status, category, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_replies_question_status_created ON replies(question_id, status, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_case_documents_status_sort ON case_documents(status, sort_order ASC, id DESC)')

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

    seed_case_documents()

    # 自动清理30天前的聊天记录
    cleanup_old_history()

# ===== Cleanup =====
def cleanup_old_history():
    conn = get_db_connection()
    conn.execute("DELETE FROM chat_history WHERE created_at < datetime('now', '-30 days')")
    conn.commit()
    conn.close()

def delete_chat_history_batch(ids, user_id=None):
    if not ids:
        return 0
    conn = get_db_connection()
    placeholders = ','.join(['?'] * len(ids))
    if user_id:
        cursor = conn.execute(
            f'DELETE FROM chat_history WHERE user_id = ? AND id IN ({placeholders})',
            [user_id] + ids
        )
    else:
        cursor = conn.execute(
            f'DELETE FROM chat_history WHERE id IN ({placeholders})',
            ids
        )
    conn.commit()
    deleted = cursor.rowcount if cursor.rowcount is not None else 0
    conn.close()
    return deleted

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
    cursor.execute('SELECT id, title, summary, image_url, created_at, views, pinned, featured, category FROM news ORDER BY created_at DESC')
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
        'SELECT id, title, summary, image_url, created_at, views, pinned, featured, category FROM news WHERE pinned = 1 ORDER BY created_at DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_featured_news(limit=3):
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT id, title, summary, image_url, created_at, views, pinned, featured, category FROM news WHERE featured = 1 ORDER BY created_at DESC LIMIT ?', (limit,)
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
        f'SELECT id, title, summary, image_url, created_at, views, pinned, featured, category FROM news {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
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

def get_product_category_order():
    import json
    raw = get_setting('product_category_order', '[]')
    try:
        return json.loads(raw)
    except:
        return []

def set_product_category_order(order_list):
    import json
    set_setting('product_category_order', json.dumps(order_list, ensure_ascii=False))

# ===== Case Documents =====
CASE_DOCUMENT_FIELDS = (
    'title', 'customer_profile', 'symptom_tags', 'product_tags', 'scenario',
    'summary', 'content', 'image_url', 'external_url', 'status', 'sort_order'
)

SEED_CASE_DOCUMENTS = [
    {
        'title': '长期便秘客户调理记录',
        'customer_profile': '45岁女性，久坐办公室，饮食不规律',
        'symptom_tags': '便秘,腹胀,排便困难',
        'product_tags': '益生菌,膳食纤维',
        'scenario': '连续使用两周后反馈排便频率提升',
        'summary': '客户主要困扰是三四天排便一次，搭配益生菌和膳食纤维后，反馈腹胀减轻。',
        'content': '客户长期久坐，饮水少，排便频率低。建议从日常饮食、饮水、规律作息配合益生菌和膳食纤维做基础调理。两周后反馈排便频率提升，腹胀感减轻。',
        'sort_order': 10,
    },
    {
        'title': '饭后腹胀人群使用反馈',
        'customer_profile': '38岁男性，经常外食，应酬多',
        'symptom_tags': '腹胀,饭后不适,消化慢',
        'product_tags': '益生菌,酵素',
        'scenario': '饭后胀气明显，关注消化舒适度',
        'summary': '客户反馈晚餐后胀气明显，使用后饭后负担感有所下降。',
        'content': '客户经常外食，晚餐较油腻，饭后胀气和饱胀感明显。案例记录中以饮食调整配合益生菌、酵素作为日常方案，反馈饭后负担感下降。',
        'sort_order': 20,
    },
    {
        'title': '口臭与肠道状态改善案例',
        'customer_profile': '32岁女性，熬夜多，口气困扰明显',
        'symptom_tags': '口臭,肠胃不适,熬夜',
        'product_tags': '益生菌',
        'scenario': '关注口气和肠道状态',
        'summary': '客户将口气问题和肠胃状态一起调理，反馈早起口气减轻。',
        'content': '客户反馈早起口气明显，作息不规律。沟通中重点围绕肠道状态、饮食清淡和规律作息展开，配合益生菌后反馈早起口气有所减轻。',
        'sort_order': 30,
    },
    {
        'title': '中老年免疫力维护反馈',
        'customer_profile': '56岁女性，换季容易不舒服',
        'symptom_tags': '免疫力低,换季不适,疲劳',
        'product_tags': '益生菌,营养组合',
        'scenario': '家人帮长辈咨询日常维护方案',
        'summary': '家属关注长辈换季状态，使用后反馈精神状态和日常规律性更稳定。',
        'content': '家属为长辈咨询换季维护方案，关注疲劳、换季不适和日常状态。案例中以益生菌和营养组合做基础维护，反馈精神状态更稳定。',
        'sort_order': 40,
    },
    {
        'title': '皮肤状态与肠道调理反馈',
        'customer_profile': '29岁女性，饮食辛辣，皮肤反复',
        'symptom_tags': '皮肤问题,长痘,肠胃不适',
        'product_tags': '益生菌,膳食纤维',
        'scenario': '希望从肠道管理角度改善皮肤状态',
        'summary': '客户关注皮肤反复和饮食习惯，调理后反馈排便更规律，皮肤状态有改善。',
        'content': '客户饮食辛辣，皮肤状态反复，同时有肠胃不适。案例中从饮食、排便规律和肠道管理入手，配合益生菌和膳食纤维，反馈排便更规律。',
        'sort_order': 50,
    },
]

def normalize_case_tags(value):
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r'[,，、\s]+', str(value or ''))
    tags = []
    for part in parts:
        tag = str(part).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return ','.join(tags)

def _case_payload(data):
    data = data or {}
    title = (data.get('title') or '').strip()
    if not title:
        raise ValueError('title is required')
    return {
        'title': title,
        'customer_profile': (data.get('customer_profile') or '').strip(),
        'symptom_tags': normalize_case_tags(data.get('symptom_tags')),
        'product_tags': normalize_case_tags(data.get('product_tags')),
        'scenario': (data.get('scenario') or '').strip(),
        'summary': (data.get('summary') or '').strip(),
        'content': (data.get('content') or '').strip(),
        'image_url': (data.get('image_url') or '').strip(),
        'external_url': (data.get('external_url') or '').strip(),
        'status': 1 if int(data.get('status', 1) or 0) else 0,
        'sort_order': int(data.get('sort_order', 0) or 0),
    }

def _sync_case_document_fts(conn, case_id, payload):
    conn.execute('DELETE FROM case_documents_fts WHERE rowid = ?', (case_id,))
    conn.execute(
        '''INSERT INTO case_documents_fts
           (rowid, title, customer_profile, symptom_tags, product_tags, scenario, summary, content)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            case_id,
            payload.get('title', ''),
            payload.get('customer_profile', ''),
            payload.get('symptom_tags', ''),
            payload.get('product_tags', ''),
            payload.get('scenario', ''),
            payload.get('summary', ''),
            payload.get('content', ''),
        )
    )

def create_case_document(data):
    payload = _case_payload(data)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO case_documents
           (title, customer_profile, symptom_tags, product_tags, scenario, summary, content, image_url, external_url, status, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        tuple(payload[field] for field in CASE_DOCUMENT_FIELDS)
    )
    case_id = cursor.lastrowid
    _sync_case_document_fts(conn, case_id, payload)
    conn.commit()
    conn.close()
    return case_id

def update_case_document(case_id, data):
    payload = _case_payload(data)
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM case_documents WHERE id = ?', (case_id,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        '''UPDATE case_documents
           SET title=?, customer_profile=?, symptom_tags=?, product_tags=?, scenario=?,
               summary=?, content=?, image_url=?, external_url=?, status=?, sort_order=?, updated_at=CURRENT_TIMESTAMP
           WHERE id=?''',
        tuple(payload[field] for field in CASE_DOCUMENT_FIELDS) + (case_id,)
    )
    _sync_case_document_fts(conn, case_id, payload)
    conn.commit()
    conn.close()
    return True

def delete_case_document(case_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM case_documents WHERE id = ?', (case_id,))
    conn.execute('DELETE FROM case_documents_fts WHERE rowid = ?', (case_id,))
    conn.commit()
    conn.close()

def set_case_document_status(case_id, status):
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM case_documents WHERE id = ?', (case_id,)).fetchone()
    if not row:
        conn.close()
        return None
    val = 1 if int(status) else 0
    conn.execute('UPDATE case_documents SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (val, case_id))
    conn.commit()
    conn.close()
    return val

def get_all_case_documents(include_hidden=True):
    conn = get_db_connection()
    where = '' if include_hidden else 'WHERE status = 1'
    rows = conn.execute(
        f'SELECT * FROM case_documents {where} ORDER BY sort_order ASC, id DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_case_documents_page(page=1, limit=10, tag_type='', tag=''):
    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 10), 50))
    conditions = ['status = 1']
    params = []
    tag = (tag or '').strip()
    tag_column = ''
    if tag_type == 'symptom':
        tag_column = 'symptom_tags'
    elif tag_type == 'product':
        tag_column = 'product_tags'
    if tag and tag_column:
        conditions.append(f"(',' || {tag_column} || ',') LIKE ?")
        params.append(f'%,{tag},%')
    where = 'WHERE ' + ' AND '.join(conditions)
    offset = (page - 1) * limit
    conn = get_db_connection()
    total = conn.execute(f'SELECT COUNT(*) as cnt FROM case_documents {where}', params).fetchone()['cnt']
    rows = conn.execute(
        f'''SELECT id, title, customer_profile, symptom_tags, product_tags, scenario, summary, image_url, external_url
            FROM case_documents {where}
            ORDER BY sort_order ASC, id DESC
            LIMIT ? OFFSET ?''',
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return {
        'items': [dict(r) for r in rows],
        'total': total,
        'page': page,
        'pages': max(1, (total + limit - 1) // limit),
    }

def get_case_document_by_id(case_id, public_only=False):
    conn = get_db_connection()
    if public_only:
        row = conn.execute('SELECT * FROM case_documents WHERE id = ? AND status = 1', (case_id,)).fetchone()
    else:
        row = conn.execute('SELECT * FROM case_documents WHERE id = ?', (case_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def _split_case_tags(value):
    return [t.strip() for t in str(value or '').split(',') if t.strip()]

def _case_preview(row):
    item = dict(row)
    return {
        'id': item['id'],
        'title': item['title'],
        'customer_profile': item.get('customer_profile', ''),
        'symptom_tags': item.get('symptom_tags', ''),
        'product_tags': item.get('product_tags', ''),
        'scenario': item.get('scenario', ''),
        'summary': item.get('summary', ''),
        'image_url': item.get('image_url', ''),
        'external_url': item.get('external_url', ''),
    }

def _fts_match_expr(query):
    tokens = []
    for token in re.split(r'[\s,，。！？、；;:：]+', query or ''):
        token = token.strip()
        if len(token) >= 2:
            tokens.append('"' + token.replace('"', '""') + '"')
    return ' OR '.join(tokens[:8])

def _score_case_documents(query):
    query = (query or '').strip()
    if not query:
        return []
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM case_documents WHERE status = 1').fetchall()
    fts_ids = set()
    expr = _fts_match_expr(query)
    if expr:
        try:
            fts_rows = conn.execute(
                'SELECT rowid FROM case_documents_fts WHERE case_documents_fts MATCH ? LIMIT 20',
                (expr,)
            ).fetchall()
            fts_ids = {r['rowid'] for r in fts_rows}
        except sqlite3.OperationalError:
            fts_ids = set()
    conn.close()

    scored = []
    for row in rows:
        item = dict(row)
        symptom_hits = sum(1 for tag in _split_case_tags(item.get('symptom_tags')) if tag and tag in query)
        product_hits = sum(1 for tag in _split_case_tags(item.get('product_tags')) if tag and tag in query)
        haystack = ' '.join(str(item.get(k, '')) for k in ('title', 'customer_profile', 'scenario', 'summary', 'content'))
        text_hit = 1 if any(part and part in haystack for part in re.split(r'[\s,，。！？、；;:：]+', query)) else 0
        fts_hit = 1 if item['id'] in fts_ids else 0
        score = symptom_hits * 100 + product_hits * 60 + fts_hit * 25 + text_hit * 10 - int(item.get('sort_order') or 0) * 0.01
        if score > 0:
            scored.append((score, int(item.get('sort_order') or 0), item['id'], item))

    scored.sort(key=lambda x: (-x[0], x[1], -x[2]))
    return [_case_preview(item) for _, _, _, item in scored]

def search_case_documents(query, limit=3):
    limit = max(1, int(limit or 3))
    return _score_case_documents(query)[:limit]

def search_case_documents_page(query, page=1, limit=10):
    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 10), 50))
    items = _score_case_documents(query)
    total = len(items)
    start = (page - 1) * limit
    return {
        'items': items[start:start + limit],
        'total': total,
        'page': page,
        'pages': max(1, (total + limit - 1) // limit),
    }

def seed_case_documents():
    conn = get_db_connection()
    existing = conn.execute('SELECT COUNT(*) as cnt FROM case_documents').fetchone()['cnt']
    conn.close()
    if existing:
        return
    for item in SEED_CASE_DOCUMENTS:
        payload = dict(item)
        payload.setdefault('image_url', '')
        payload.setdefault('status', 1)
        create_case_document(payload)

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

def update_user_password_hash(user_id, password_hash):
    conn = get_db_connection()
    conn.execute(
        'UPDATE users SET password_hash = ? WHERE user_id = ?',
        (password_hash, user_id)
    )
    conn.commit()
    conn.close()

# ===== Chat History =====
def save_chat_history(user_id, query_type, user_message, bot_response=None, coze_message_id=None, team_name='', member_name=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO chat_history
           (user_id, query_type, user_message, bot_response, coze_message_id, team_name, member_name)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (user_id, query_type, user_message, bot_response, coze_message_id, team_name, member_name)
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
    conditions = []
    params = []
    if status is not None:
        conditions.append('q.status = ?')
        params.append(status)
    if category:
        conditions.append('q.category = ?')
        params.append(category)
    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    total = conn.execute(f'SELECT COUNT(*) as cnt FROM questions q {where}', params).fetchone()['cnt']
    offset = (page - 1) * limit
    rows = conn.execute(
        f'''
        SELECT q.id, q.nickname, q.title, q.content, q.category, q.status, q.view_count, q.created_at,
               (SELECT COUNT(*) FROM replies r WHERE r.question_id = q.id AND r.status = 1) as reply_count,
               (SELECT COUNT(*) FROM replies r WHERE r.question_id = q.id AND r.status = 0) as pending_reply_count
        FROM questions q
        {where}
        ORDER BY q.created_at DESC LIMIT ? OFFSET ?
        ''',
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': max(1, (total + limit - 1) // limit)}

def get_question_detail(id, viewer_id=None):
    conn = get_db_connection()
    conn.execute('UPDATE questions SET view_count = view_count + 1 WHERE id = ?', (id,))
    row = conn.execute('SELECT * FROM questions WHERE id = ?', (id,)).fetchone()
    if not row:
        conn.close()
        return None
    q = dict(row)
    q['reply_count'] = conn.execute(
        'SELECT COUNT(*) as cnt FROM replies WHERE question_id = ? AND status = 1',
        (id,)
    ).fetchone()['cnt']
    if viewer_id:
        replies_rows = conn.execute(
            '''
            SELECT *,
                   CASE WHEN status = 0 AND author_key = ? THEN 1 ELSE 0 END as is_own_pending
            FROM replies
            WHERE question_id = ? AND (status = 1 OR (status = 0 AND author_key = ?))
            ORDER BY status ASC, created_at ASC
            ''',
            (viewer_id, id, viewer_id)
        ).fetchall()
    else:
        replies_rows = conn.execute(
            'SELECT *, 0 as is_own_pending FROM replies WHERE question_id = ? AND status = 1 ORDER BY created_at ASC',
            (id,)
        ).fetchall()
    conn.close()
    q['replies'] = [mask_reply_author(dict(r)) for r in replies_rows]
    return q

def mask_reply_author(reply):
    reply['nickname'] = '匿名用户'
    return reply

def get_question_replies(question_id, status=None):
    conn = get_db_connection()
    if status is None:
        rows = conn.execute(
            'SELECT * FROM replies WHERE question_id = ? ORDER BY status ASC, created_at DESC',
            (question_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM replies WHERE question_id = ? AND status = ? ORDER BY created_at DESC',
            (question_id, status)
        ).fetchall()
    conn.close()
    return [mask_reply_author(dict(r)) for r in rows]

def create_reply(question_id, nickname, content, status=0, author_key=''):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO replies (question_id, nickname, content, status, author_key) VALUES (?, ?, ?, ?, ?)',
        (question_id, '匿名用户', content, status, author_key)
    )
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
    conn.commit()
    conn.close()

def set_reply_status(id, status):
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM replies WHERE id = ?', (id,)).fetchone()
    if not row:
        conn.close()
        return None
    val = 1 if int(status) else 0
    conn.execute('UPDATE replies SET status = ? WHERE id = ?', (val, id))
    conn.commit()
    conn.close()
    return val

def like_reply(id):
    conn = get_db_connection()
    row = conn.execute('SELECT like_count FROM replies WHERE id = ?', (id,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute('UPDATE replies SET like_count = COALESCE(like_count, 0) + 1 WHERE id = ?', (id,))
    conn.commit()
    count = conn.execute('SELECT like_count FROM replies WHERE id = ?', (id,)).fetchone()['like_count']
    conn.close()
    return count

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
