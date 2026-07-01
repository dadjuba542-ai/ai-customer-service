#!/usr/bin/env python3
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def set_database_path(path):
    from config import Config
    Config.DATABASE_DIR = str(Path(path).parent)
    Config.DATABASE_PATH = str(path)


def table_columns(conn, table):
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def migration_count(conn):
    return conn.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]


def assert_expected_columns(conn):
    expected = {
        'users': {'is_admin'},
        'chat_history': {'feedback', 'feedback_reason', 'team_name', 'member_name'},
        'news': {'views', 'pinned', 'featured', 'category'},
        'agent_configs': {'icon', 'chat_desc'},
        'replies': {'author_key', 'like_count'},
        'case_documents': {'external_url'},
        'case_tags': {'name', 'type', 'aliases', 'status', 'sort_order'},
        'case_document_tags': {'case_id', 'tag_id'},
    }
    for table, columns in expected.items():
        actual = table_columns(conn, table)
        missing = columns - actual
        assert_true(not missing, f'{table} missing columns: {missing}')


def create_old_schema(path):
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            query_type TEXT NOT NULL,
            user_message TEXT NOT NULL,
            bot_response TEXT,
            coze_message_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT DEFAULT '',
            content TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE agent_configs (
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
        );
        CREATE TABLE replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            nickname TEXT DEFAULT '',
            content TEXT DEFAULT '',
            status INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE case_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            customer_profile TEXT DEFAULT '',
            symptom_tags TEXT DEFAULT '',
            product_tags TEXT DEFAULT '',
            scenario TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            content TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            status INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    conn.close()


def main():
    os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
    os.environ['ADMIN_USERNAME'] = 'admin8'

    from db_migrations import MIGRATIONS, run_migrations
    from models import init_db

    with tempfile.TemporaryDirectory(prefix='acs-migrations-empty-') as tmpdir:
        db_path = Path(tmpdir) / 'ai_customer_service.db'
        set_database_path(db_path)
        init_db()
        conn = sqlite3.connect(db_path)
        assert_true(
            conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone(),
            'schema_migrations table missing',
        )
        assert_expected_columns(conn)
        first_count = migration_count(conn)
        assert_true(first_count == len(MIGRATIONS), f'migration count mismatch: {first_count}')
        conn.close()

        init_db()
        conn = sqlite3.connect(db_path)
        second_count = migration_count(conn)
        assert_true(second_count == first_count, f'migrations duplicated: {second_count} vs {first_count}')
        conn.close()

    with tempfile.TemporaryDirectory(prefix='acs-migrations-old-') as tmpdir:
        db_path = Path(tmpdir) / 'ai_customer_service.db'
        create_old_schema(db_path)
        set_database_path(db_path)
        init_db()
        conn = sqlite3.connect(db_path)
        assert_expected_columns(conn)
        assert_true(migration_count(conn) == len(MIGRATIONS), 'old schema migrations not recorded')
        conn.close()

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    bad_migration = [{'version': 'bad_001', 'name': 'bad migration', 'sqls': ['SELECT * FROM missing_table']}]
    try:
        run_migrations(conn, bad_migration)
        raise AssertionError('bad migration should fail')
    except sqlite3.OperationalError:
        pass
    row = conn.execute('SELECT version FROM schema_migrations WHERE version = ?', ('bad_001',)).fetchone()
    assert_true(row is None, 'failed migration should not be recorded')
    conn.close()

    print('PASS: migrations smoke test')


if __name__ == '__main__':
    main()
