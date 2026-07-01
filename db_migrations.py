import sqlite3


def _split_tags(value):
    tags = []
    for part in str(value or '').replace('，', ',').replace('、', ',').split(','):
        tag = part.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _get_or_create_case_tag(conn, tag_type, name):
    row = conn.execute(
        'SELECT id FROM case_tags WHERE type = ? AND name = ?',
        (tag_type, name),
    ).fetchone()
    if row:
        return row['id'] if isinstance(row, sqlite3.Row) else row[0]
    cursor = conn.execute(
        'INSERT INTO case_tags (name, type) VALUES (?, ?)',
        (name, tag_type),
    )
    return cursor.lastrowid


def _backfill_case_document_tags(conn):
    rows = conn.execute('SELECT id, symptom_tags, product_tags FROM case_documents').fetchall()
    for row in rows:
        case_id = row['id'] if isinstance(row, sqlite3.Row) else row[0]
        symptom_tags = row['symptom_tags'] if isinstance(row, sqlite3.Row) else row[1]
        product_tags = row['product_tags'] if isinstance(row, sqlite3.Row) else row[2]
        for tag_type, value in (('symptom', symptom_tags), ('product', product_tags)):
            for tag in _split_tags(value):
                tag_id = _get_or_create_case_tag(conn, tag_type, tag)
                conn.execute(
                    'INSERT OR IGNORE INTO case_document_tags (case_id, tag_id) VALUES (?, ?)',
                    (case_id, tag_id),
                )


MIGRATIONS = [
    {
        'version': '202606300001',
        'name': 'add_historical_compat_columns',
        'columns': [
            ('users', 'is_admin', 'INTEGER DEFAULT 0'),
            ('chat_history', 'feedback', 'INTEGER DEFAULT NULL'),
            ('chat_history', 'feedback_reason', 'TEXT DEFAULT NULL'),
            ('chat_history', 'team_name', 'TEXT DEFAULT ""'),
            ('chat_history', 'member_name', 'TEXT DEFAULT ""'),
            ('news', 'views', 'INTEGER DEFAULT 0'),
            ('news', 'pinned', 'INTEGER DEFAULT 0'),
            ('news', 'featured', 'INTEGER DEFAULT 0'),
            ('news', 'category', 'TEXT DEFAULT ""'),
            ('agent_configs', 'icon', 'TEXT DEFAULT "robot"'),
            ('agent_configs', 'chat_desc', 'TEXT DEFAULT ""'),
            ('replies', 'author_key', 'TEXT DEFAULT ""'),
            ('replies', 'like_count', 'INTEGER DEFAULT 0'),
            ('case_documents', 'external_url', 'TEXT DEFAULT ""'),
        ],
    },
    {
        'version': '202607010001',
        'name': 'create_case_tag_tables',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS case_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('symptom', 'product')),
                aliases TEXT DEFAULT '',
                status INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(type, name)
            )''',
            '''CREATE TABLE IF NOT EXISTS case_document_tags (
                case_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (case_id, tag_id),
                FOREIGN KEY (case_id) REFERENCES case_documents(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES case_tags(id) ON DELETE CASCADE
            )''',
            'CREATE INDEX IF NOT EXISTS idx_case_tags_type_status_sort ON case_tags(type, status, sort_order ASC, id DESC)',
            'CREATE INDEX IF NOT EXISTS idx_case_document_tags_tag_case ON case_document_tags(tag_id, case_id)',
        ],
        'fn': _backfill_case_document_tags,
    },
]


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def ensure_migration_table(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


def column_exists(conn, table, column):
    rows = conn.execute(f'PRAGMA table_info({quote_identifier(table)})').fetchall()
    return any(row['name'] == column if isinstance(row, sqlite3.Row) else row[1] == column for row in rows)


def ensure_column(conn, table, column, definition):
    if column_exists(conn, table, column):
        return False
    conn.execute(
        f'ALTER TABLE {quote_identifier(table)} '
        f'ADD COLUMN {quote_identifier(column)} {definition}'
    )
    return True


def run_migrations(conn, migrations=None):
    ensure_migration_table(conn)
    conn.commit()
    migrations = migrations or MIGRATIONS
    applied = {
        row['version'] if isinstance(row, sqlite3.Row) else row[0]
        for row in conn.execute('SELECT version FROM schema_migrations').fetchall()
    }

    for migration in migrations:
        version = migration['version']
        if version in applied:
            continue

        try:
            conn.execute('BEGIN')
            for table, column, definition in migration.get('columns', []):
                ensure_column(conn, table, column, definition)
            for sql in migration.get('sqls', []):
                conn.execute(sql)
            if migration.get('fn'):
                migration['fn'](conn)
            conn.execute(
                'INSERT INTO schema_migrations (version, name) VALUES (?, ?)',
                (version, migration['name']),
            )
            conn.commit()
            applied.add(version)
        except Exception:
            conn.rollback()
            raise
