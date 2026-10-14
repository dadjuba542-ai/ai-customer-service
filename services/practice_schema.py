"""Independent, durable decision-game tables (legacy practice tables stay intact)."""
SQLS = [
    '''CREATE TABLE practice_quiz_questions (
        id INTEGER PRIMARY KEY, batch_no INTEGER NOT NULL, category TEXT NOT NULL,
        title TEXT NOT NULL, options TEXT NOT NULL, answer_index INTEGER NOT NULL,
        explanation TEXT NOT NULL, method TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)''',
    '''CREATE TABLE practice_quiz_daily (
        day TEXT PRIMARY KEY, batch_no INTEGER NOT NULL, snapshot TEXT NOT NULL)''',
    '''CREATE TABLE practice_quiz_sessions (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, team_name TEXT NOT NULL, member_name TEXT NOT NULL,
        create_request_id TEXT NOT NULL, mode TEXT NOT NULL, assigned_day TEXT NOT NULL,
        batch_no INTEGER NOT NULL, snapshot TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
        completed INTEGER NOT NULL DEFAULT 0, correct_count INTEGER NOT NULL DEFAULT 0,
        points INTEGER NOT NULL DEFAULT 0, point_reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, completed_at TEXT, UNIQUE(user_id, create_request_id))''',
    "CREATE UNIQUE INDEX practice_quiz_daily_user ON practice_quiz_sessions(user_id, assigned_day) WHERE mode='daily'",
    '''CREATE TABLE practice_quiz_answers (
        session_id TEXT NOT NULL, question_id INTEGER NOT NULL, position INTEGER NOT NULL,
        option_index INTEGER NOT NULL, correct INTEGER NOT NULL, request_id TEXT NOT NULL,
        PRIMARY KEY(session_id, question_id), UNIQUE(session_id, request_id))''',
    '''CREATE TABLE practice_quiz_points (
        session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, team_name TEXT NOT NULL,
        member_name TEXT NOT NULL, day TEXT NOT NULL, points INTEGER NOT NULL,
        UNIQUE(user_id, day))''',
    '''CREATE TABLE practice_quiz_visits (
        user_id TEXT NOT NULL, day TEXT NOT NULL, team_name TEXT NOT NULL, PRIMARY KEY(user_id, day))''',
    'CREATE INDEX practice_quiz_sessions_user ON practice_quiz_sessions(user_id, created_at)',
    'CREATE INDEX practice_quiz_points_team ON practice_quiz_points(team_name, day)',
]
