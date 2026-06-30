import sqlite3


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
            conn.execute(
                'INSERT INTO schema_migrations (version, name) VALUES (?, ?)',
                (version, migration['name']),
            )
            conn.commit()
            applied.add(version)
        except Exception:
            conn.rollback()
            raise
