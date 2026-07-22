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
        'version': '202606290001',
        'name': 'create_case_documents_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS case_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                content TEXT DEFAULT '',
                symptom_tags TEXT DEFAULT '',
                product_tags TEXT DEFAULT '',
                source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''
        ],
    },
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
    {
        'version': '202607060001',
        'name': 'create_share_events_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS share_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT '',
                team_name TEXT DEFAULT '',
                member_name TEXT DEFAULT '',
                query_type TEXT DEFAULT '',
                history_id INTEGER DEFAULT NULL,
                share_type TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            'CREATE INDEX IF NOT EXISTS idx_share_events_created ON share_events(created_at DESC)',
            'CREATE INDEX IF NOT EXISTS idx_share_events_history ON share_events(history_id)',
        ],
    },
    {
        'version': '202607130001',
        'name': 'create_lead_requests_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS lead_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                customer_type TEXT NOT NULL DEFAULT '',
                product_name TEXT DEFAULT '',
                description TEXT NOT NULL,
                phone TEXT DEFAULT '',
                wechat TEXT DEFAULT '',
                query_type TEXT DEFAULT '',
                agent_id TEXT DEFAULT '',
                history_id INTEGER DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                admin_note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            'CREATE INDEX IF NOT EXISTS idx_lead_requests_created ON lead_requests(created_at DESC)',
            'CREATE INDEX IF NOT EXISTS idx_lead_requests_status_created ON lead_requests(status, created_at DESC)',
            'CREATE INDEX IF NOT EXISTS idx_lead_requests_user_created ON lead_requests(user_id, created_at DESC)',
        ],
    },
    {
        'version': '202607200001',
        'name': 'create_handoff_support_tables',
        'columns': [
            ('chat_history', 'agent_id', 'TEXT DEFAULT ""'),
        ],
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS handoff_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                team_name TEXT DEFAULT '',
                member_name TEXT DEFAULT '',
                query_type TEXT DEFAULT '',
                ai_agent_id TEXT DEFAULT '',
                agent_id TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued'
                    CHECK(status IN ('queued', 'assigned', 'active', 'closed', 'abandoned')),
                ai_context_json TEXT DEFAULT '[]',
                priority INTEGER DEFAULT 0,
                enqueued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                assigned_at TIMESTAMP,
                active_at TIMESTAMP,
                agent_claim_deadline TIMESTAMP,
                last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_last_read_message_id INTEGER DEFAULT 0,
                agent_last_read_message_id INTEGER DEFAULT 0,
                closed_at TIMESTAMP,
                close_reason TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS handoff_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sender_role TEXT NOT NULL CHECK(sender_role IN ('user', 'agent', 'system')),
                sender_id TEXT DEFAULT '',
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES handoff_sessions(session_id) ON DELETE CASCADE
            )''',
            '''CREATE TABLE IF NOT EXISTS cs_agents (
                user_id TEXT PRIMARY KEY,
                display_name TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                online INTEGER DEFAULT 0,
                max_concurrent INTEGER DEFAULT 3,
                current_load INTEGER DEFAULT 0,
                last_seen_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )''',
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_one_open_per_user ON handoff_sessions(user_id) WHERE status IN ("queued", "assigned", "active")',
            'CREATE INDEX IF NOT EXISTS idx_handoff_queue ON handoff_sessions(status, priority DESC, enqueued_at ASC, id ASC)',
            'CREATE INDEX IF NOT EXISTS idx_handoff_agent_status ON handoff_sessions(agent_id, status, last_message_at DESC)',
            'CREATE INDEX IF NOT EXISTS idx_handoff_user_recent ON handoff_sessions(user_id, id DESC)',
            'CREATE INDEX IF NOT EXISTS idx_handoff_message_session_id ON handoff_messages(session_id, id ASC)',
            'CREATE INDEX IF NOT EXISTS idx_handoff_message_role_id ON handoff_messages(sender_role, id ASC)',
            'CREATE INDEX IF NOT EXISTS idx_cs_agents_availability ON cs_agents(online, current_load, last_seen_at)',
        ],
    },
    {
        'version': '202607200002',
        'name': 'add_handoff_message_mode',
        'columns': [
            ('handoff_sessions', 'service_mode', 'TEXT NOT NULL DEFAULT "live"'),
            ('handoff_sessions', 'live_deadline_at', 'TIMESTAMP'),
            ('handoff_sessions', 'message_converted_at', 'TIMESTAMP'),
        ],
        'sqls': [
            'CREATE INDEX IF NOT EXISTS idx_handoff_mode_status ON handoff_sessions(service_mode, status, live_deadline_at)',
        ],
    },
    {
        'version': '202607200003',
        'name': 'create_handoff_export_audit_log',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS handoff_export_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exported_by TEXT NOT NULL,
                export_scope TEXT NOT NULL,
                request_json TEXT DEFAULT '{}',
                row_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            'CREATE INDEX IF NOT EXISTS idx_handoff_export_logs_user_time ON handoff_export_logs(exported_by, created_at DESC)',
        ],
    },
    {
        'version': '202607220001',
        'name': 'create_chat_jobs_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS chat_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                identity_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued'
                    CHECK(status IN ('queued', 'running', 'completed', 'failed', 'expired', 'cancelled')),
                worker_pid TEXT DEFAULT '',
                result_json TEXT DEFAULT '{}',
                error_code TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP DEFAULT NULL,
                finished_at TIMESTAMP DEFAULT NULL,
                expires_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            'CREATE INDEX IF NOT EXISTS idx_chat_jobs_status_id ON chat_jobs(status, id ASC)',
            'CREATE INDEX IF NOT EXISTS idx_chat_jobs_user_status ON chat_jobs(user_id, status)',
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_jobs_user_active ON chat_jobs(user_id) WHERE status IN ('queued', 'running')",
        ],
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


if __name__ == '__main__':
    import os
    db_path = os.environ.get('AI_DB_PATH', 'ai_customer_service.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.close()
    print(f"migrations applied to {db_path}")
