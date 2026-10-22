import sqlite3
from services.practice_schema import SQLS as PRACTICE_SQLS
from services.practice_bank import seed_bank


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
    {
        'version': '202607230001',
        'name': 'create_nutritionist_review_notes',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS nutritionist_review_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'published'
                    CHECK(status IN ('published', 'withdrawn')),
                revision INTEGER NOT NULL DEFAULT 1,
                user_read_revision INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                withdrawn_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (history_id) REFERENCES chat_history(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (created_by) REFERENCES users(user_id),
                FOREIGN KEY (updated_by) REFERENCES users(user_id)
            )''',
            'CREATE INDEX IF NOT EXISTS idx_review_notes_user_unread ON nutritionist_review_notes(user_id, status, revision, user_read_revision)',
            'CREATE INDEX IF NOT EXISTS idx_review_notes_status_updated ON nutritionist_review_notes(status, updated_at DESC)',
        ],
    },
    {
        'version': '202607240001',
        'name': 'add_chat_job_attempt_and_worker_token',
        'columns': [
            ('chat_jobs', 'attempt', 'INTEGER NOT NULL DEFAULT 0'),
            ('chat_jobs', 'worker_token', 'TEXT DEFAULT ""'),
        ],
    },
    {
        'version': '202609020001',
        'name': 'create_handoff_quick_replies_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS handoff_quick_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_by TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            'CREATE INDEX IF NOT EXISTS idx_handoff_quick_replies_order ON handoff_quick_replies(enabled, sort_order ASC, id DESC)',
        ],
    },
    {
        'version': '202609140001',
        'name': 'create_audio_courses_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS audio_courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                series TEXT DEFAULT '',
                episode INTEGER DEFAULT 0,
                duration_seconds INTEGER DEFAULT 0,
                audio_url TEXT DEFAULT '',
                external_url TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                content TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                status INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            'CREATE INDEX IF NOT EXISTS idx_audio_courses_status_sort ON audio_courses(status, sort_order ASC, id DESC)',
            '''CREATE VIRTUAL TABLE IF NOT EXISTS audio_courses_fts USING fts5(
                title,
                series,
                summary,
                content,
                tags,
                tokenize='trigram'
            )''',
        ],
    },
    {
        'version': '202609140002',
        'name': 'add_audio_course_home_flags',
        'columns': [
            ('audio_courses', 'pinned', 'INTEGER DEFAULT 0'),
            ('audio_courses', 'show_on_home', 'INTEGER DEFAULT 0'),
        ],
    },
    {
        'version': '202609140003',
        'name': 'create_research_surveys_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS research_surveys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT '',
                user_type TEXT DEFAULT '',
                answers TEXT DEFAULT '{}',
                contact TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            'CREATE INDEX IF NOT EXISTS idx_research_surveys_created ON research_surveys(created_at DESC)',
        ],
    },
    {
        'version': '202610090001',
        'name': 'create_chat_context_state_table',
        'sqls': [
            '''CREATE TABLE IF NOT EXISTS chat_context_state (
                user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '*',
                floor_history_id INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, agent_id)
            )'''
        ],
    },
    {
        'version': '202610130001',
        'name': 'add_chat_history_user_deleted_at',
        'columns': [
            ('chat_history', 'user_deleted_at', 'TIMESTAMP DEFAULT NULL'),
        ],
    },
]


MIGRATIONS.append({'version': '202610140002', 'name': 'practice_decision_game', 'sqls': PRACTICE_SQLS,
                   'fn': seed_bank})

MIGRATIONS.append({'version': '202610140003', 'name': 'practice_bank_admin_operations', 'sqls': [
    '''CREATE TABLE practice_quiz_admin_operations (request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)'''
]})

MIGRATIONS.append({'version': '202610140004', 'name': 'practice_stage_banks', 'sqls': [
    '''CREATE TABLE practice_quiz_stages (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '', starts_on TEXT NOT NULL, ends_on TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)''',
    'ALTER TABLE practice_quiz_questions ADD COLUMN stage_id INTEGER NOT NULL DEFAULT 0',
    'ALTER TABLE practice_quiz_questions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0',
    'ALTER TABLE practice_quiz_sessions ADD COLUMN stage_id INTEGER NOT NULL DEFAULT 0',
    "ALTER TABLE practice_quiz_sessions ADD COLUMN stage_title TEXT NOT NULL DEFAULT ''",
    '''CREATE TABLE practice_quiz_stage_daily (day TEXT NOT NULL, stage_id INTEGER NOT NULL,
        batch_no INTEGER NOT NULL, snapshot TEXT NOT NULL, PRIMARY KEY(day,stage_id))''',
    'CREATE INDEX practice_quiz_stage_questions ON practice_quiz_questions(stage_id,batch_no,enabled)',
]})

MIGRATIONS.append({'version': '202610140005', 'name': 'practice_weekly_themes', 'sqls': [
    "ALTER TABLE practice_quiz_stages ADD COLUMN kind TEXT NOT NULL DEFAULT 'seasonal'",
    'ALTER TABLE practice_quiz_questions ADD COLUMN source_question_id INTEGER',
    'ALTER TABLE practice_quiz_questions ADD COLUMN weekly_new INTEGER NOT NULL DEFAULT 0',
    'ALTER TABLE practice_quiz_sessions ADD COLUMN entry INTEGER NOT NULL DEFAULT 0',
    'ALTER TABLE practice_quiz_sessions ADD COLUMN entry_cursor INTEGER NOT NULL DEFAULT 0',
    '''CREATE TABLE practice_quiz_weekly_selections (stage_id INTEGER NOT NULL, question_id INTEGER NOT NULL,
        is_new INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL, PRIMARY KEY(stage_id,question_id))''',
    '''CREATE TABLE practice_quiz_weekly_plans (stage_id INTEGER PRIMARY KEY, schedule TEXT NOT NULL, updated_at TEXT NOT NULL)''',
    '''CREATE TABLE practice_quiz_entry_events (user_id TEXT NOT NULL, stage_id INTEGER NOT NULL, day TEXT NOT NULL,
        event TEXT NOT NULL, PRIMARY KEY(user_id,stage_id,day,event))''',
    'CREATE INDEX practice_quiz_entry_events_stage ON practice_quiz_entry_events(stage_id,day,event)',
    '''CREATE TABLE practice_quiz_entry_requests (user_id TEXT NOT NULL, request_id TEXT NOT NULL, session_id TEXT NOT NULL, PRIMARY KEY(user_id,request_id))''',
]})

MIGRATIONS.append({'version': '202610190001', 'name': 'practice_learning_paths', 'sqls': [
    'ALTER TABLE practice_quiz_questions ADD COLUMN product_id INTEGER',
    "ALTER TABLE practice_quiz_questions ADD COLUMN skill_code TEXT NOT NULL DEFAULT ''",
    'ALTER TABLE practice_quiz_questions ADD COLUMN fact_id INTEGER',
    '''CREATE TABLE practice_learning_courses (
        product_id INTEGER PRIMARY KEY, published INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL)''',
    '''CREATE TABLE practice_learning_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
        unit_no INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
        source_url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
        version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
        UNIQUE(product_id,unit_no))''',
    '''CREATE TABLE practice_learning_unit_questions (
        product_id INTEGER NOT NULL, unit_no INTEGER NOT NULL, position INTEGER NOT NULL,
        question_id INTEGER NOT NULL, kind TEXT NOT NULL,
        PRIMARY KEY(product_id,unit_no,position), UNIQUE(product_id,unit_no,question_id))''',
    '''CREATE TABLE practice_learning_sessions (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, request_id TEXT NOT NULL,
        kind TEXT NOT NULL, product_id INTEGER, unit_no INTEGER,
        snapshot TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
        completed INTEGER NOT NULL DEFAULT 0, correct_count INTEGER NOT NULL DEFAULT 0,
        assigned_day TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT,
        UNIQUE(user_id,request_id))''',
    '''CREATE TABLE practice_learning_answers (
        session_id TEXT NOT NULL, position INTEGER NOT NULL, option_index INTEGER NOT NULL,
        correct INTEGER NOT NULL, request_id TEXT NOT NULL,
        PRIMARY KEY(session_id,position), UNIQUE(session_id,request_id))''',
    '''CREATE TABLE practice_learning_mastery (
        user_id TEXT NOT NULL, question_id INTEGER NOT NULL, question_version TEXT NOT NULL,
        correct_days INTEGER NOT NULL DEFAULT 0, last_correct_day TEXT,
        due_day TEXT, status TEXT NOT NULL DEFAULT 'learning', updated_at TEXT NOT NULL,
        PRIMARY KEY(user_id,question_id))''',
    '''CREATE TABLE practice_learning_activity (
        user_id TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
        PRIMARY KEY(user_id,day,kind))''',
    'CREATE INDEX practice_learning_due ON practice_learning_mastery(user_id,due_day)',
    'CREATE INDEX practice_learning_sessions_user ON practice_learning_sessions(user_id,created_at)',
]})


MIGRATIONS.append({'version': '202610210001', 'name': 'create_chat_request_log', 'sqls': [
    '''CREATE TABLE IF NOT EXISTS chat_request_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        endpoint TEXT NOT NULL DEFAULT '',
        agent_id TEXT DEFAULT '',
        query_type TEXT DEFAULT '',
        channel TEXT DEFAULT '',
        user_ref TEXT DEFAULT '',
        message_fingerprint TEXT DEFAULT '',
        message_length INTEGER DEFAULT 0,
        outcome TEXT NOT NULL DEFAULT '',
        error_category TEXT DEFAULT '',
        error_code TEXT DEFAULT '',
        http_status INTEGER DEFAULT NULL,
        retryable INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        first_token_ms INTEGER DEFAULT NULL,
        upstream_event_count INTEGER DEFAULT 0,
        conversation_id TEXT DEFAULT '',
        chat_id TEXT DEFAULT '',
        history_id INTEGER DEFAULT NULL,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    'CREATE INDEX IF NOT EXISTS idx_chat_request_log_created ON chat_request_log(created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_chat_request_log_failure ON chat_request_log(outcome, created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_chat_request_log_request ON chat_request_log(request_id)',
    'CREATE INDEX IF NOT EXISTS idx_chat_request_log_agent ON chat_request_log(agent_id, created_at DESC)',
]})


MIGRATIONS.append({'version': '202610220001', 'name': 'practice_guided_path', 'sqls': [
    "ALTER TABLE practice_quiz_questions ADD COLUMN learning_objective TEXT NOT NULL DEFAULT ''",
    'ALTER TABLE practice_quiz_questions ADD COLUMN difficulty_level INTEGER',
    'ALTER TABLE practice_quiz_questions ADD COLUMN suggested_unit_id INTEGER',
    'ALTER TABLE practice_learning_sessions ADD COLUMN path_unit_id INTEGER',
    '''CREATE TABLE practice_learning_path_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), product_name TEXT NOT NULL,
        legacy_product_id INTEGER,
        published INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)''',
    '''CREATE TABLE practice_learning_path_units (
        id INTEGER PRIMARY KEY AUTOINCREMENT, position INTEGER NOT NULL UNIQUE,
        kind TEXT NOT NULL, product_id INTEGER, product_unit_no INTEGER,
        title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', level INTEGER NOT NULL,
        updated_at TEXT NOT NULL)''',
    '''CREATE TABLE practice_learning_path_questions (
        unit_id INTEGER NOT NULL, position INTEGER NOT NULL, question_id INTEGER NOT NULL,
        PRIMARY KEY(unit_id,position), UNIQUE(question_id))''',
    '''CREATE TABLE practice_learning_path_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL,
        unit_id INTEGER NOT NULL, question_version TEXT NOT NULL, learning_objective TEXT NOT NULL,
        difficulty_level INTEGER NOT NULL, rationale TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
        reviewed_at TEXT)''',
    "CREATE UNIQUE INDEX practice_path_pending_unique ON practice_learning_path_suggestions(question_id,unit_id) WHERE status='pending'",
    'CREATE INDEX practice_path_suggestions_status ON practice_learning_path_suggestions(status,created_at)',
]})


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
