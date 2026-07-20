import csv
import io
import json
import sqlite3
import uuid
from datetime import datetime

from config import Config
from models import get_agent_config, get_chat_history_by_ids, get_db_connection, get_setting, set_setting


OPEN_STATUSES = ('queued', 'assigned', 'active')
MESSAGE_STATUSES = ('queued', 'assigned', 'active')
DEFAULTS = {
    'enabled': Config.HANDOFF_ENABLED,
    'ai_agent_id': Config.HANDOFF_AI_AGENT_ID,
    'button_label': '联系在线营养师',
    'queue_msg': '客服忙线中，您前面还有 {position} 位',
    'offline_msg': '当前营养师暂未在线，已为您留言',
    'welcome_msg': '营养师已接入，本次咨询将由真人为您解答',
    'avg_handle_sec': Config.HANDOFF_AVG_HANDLE_SEC,
    'live_wait_sec': Config.HANDOFF_LIVE_WAIT_SEC,
}


class HandoffError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _bool_setting(key, default=False):
    raw = str(get_setting(key, '1' if default else '0')).strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


def _int_setting(key, default, minimum=1, maximum=86400):
    try:
        value = int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def get_handoff_settings():
    return {
        'enabled': _bool_setting('handoff_enabled', DEFAULTS['enabled']),
        'ai_agent_id': get_setting('handoff_ai_agent_id', DEFAULTS['ai_agent_id']).strip(),
        'button_label': get_setting('handoff_button_label', DEFAULTS['button_label']).strip() or DEFAULTS['button_label'],
        'queue_msg': get_setting('handoff_queue_msg', DEFAULTS['queue_msg']).strip() or DEFAULTS['queue_msg'],
        'offline_msg': get_setting('handoff_offline_msg', DEFAULTS['offline_msg']).strip() or DEFAULTS['offline_msg'],
        'welcome_msg': get_setting('handoff_welcome_msg', DEFAULTS['welcome_msg']).strip() or DEFAULTS['welcome_msg'],
        'avg_handle_sec': _int_setting('handoff_avg_handle_sec', DEFAULTS['avg_handle_sec'], 30, 86400),
        'live_wait_sec': _int_setting('handoff_live_wait_sec', DEFAULTS['live_wait_sec'], 30, 3600),
    }


def update_handoff_settings(data):
    current = get_handoff_settings()
    enabled = bool(data.get('enabled', current['enabled']))
    ai_agent_id = str(data.get('ai_agent_id', current['ai_agent_id']) or '').strip()[:64]
    if enabled and not ai_agent_id:
        raise HandoffError('启用在线营养咨询前，请先选择营养咨询 AI 智能体')
    if ai_agent_id:
        agent = get_agent_config(ai_agent_id)
        if not agent or not (agent.get('bot_id') or '').strip():
            raise HandoffError('请选择已配置 Bot ID 的有效智能体')
    values = {
        'handoff_enabled': '1' if enabled else '0',
        'handoff_ai_agent_id': ai_agent_id,
        'handoff_button_label': str(data.get('button_label', current['button_label']) or '').strip()[:40] or DEFAULTS['button_label'],
        'handoff_queue_msg': str(data.get('queue_msg', current['queue_msg']) or '').strip()[:200] or DEFAULTS['queue_msg'],
        'handoff_offline_msg': str(data.get('offline_msg', current['offline_msg']) or '').strip()[:200] or DEFAULTS['offline_msg'],
        'handoff_welcome_msg': str(data.get('welcome_msg', current['welcome_msg']) or '').strip()[:200] or DEFAULTS['welcome_msg'],
        'handoff_avg_handle_sec': str(max(30, min(86400, int(data.get('avg_handle_sec', current['avg_handle_sec']) or current['avg_handle_sec'])))),
        'handoff_live_wait_sec': str(max(30, min(3600, int(data.get('live_wait_sec', current['live_wait_sec']) or current['live_wait_sec'])))),
    }
    for key, value in values.items():
        set_setting(key, value)
    return get_handoff_settings()


def _open_status_sql():
    return "'queued','assigned','active'"


def has_open_handoff_session(user_id):
    conn = get_db_connection()
    row = conn.execute(
        f'''SELECT 1 FROM handoff_sessions WHERE user_id = ?
            AND status IN ({_open_status_sql()}) AND COALESCE(service_mode, 'live') = 'live' LIMIT 1''',
        (user_id,),
    ).fetchone()
    conn.close()
    return bool(row)


def get_public_config():
    settings = get_handoff_settings()
    agent = get_agent_config(settings['ai_agent_id']) if settings['ai_agent_id'] else None
    conn = get_db_connection()
    online_count = conn.execute(
        '''SELECT COUNT(*) AS cnt FROM cs_agents
           WHERE online = 1 AND last_seen_at >= datetime('now', ?)''',
        (f'-{Config.HANDOFF_AGENT_STALE_SEC} seconds',),
    ).fetchone()['cnt']
    conn.close()
    return {
        'enabled': settings['enabled'],
        'button_label': settings['button_label'],
        'queue_msg': settings['queue_msg'],
        'offline_msg': settings['offline_msg'],
        'online': online_count > 0,
        'poll_sec': Config.HANDOFF_QUEUE_POLL_SEC,
        'live_wait_sec': settings['live_wait_sec'],
        'ai_agent': {
            'agent_id': agent['agent_id'],
            'name': agent['name'],
            'avatar_url': agent.get('avatar_url', ''),
            'chat_desc': agent.get('chat_desc', ''),
            'type': agent.get('type', ''),
        } if agent and (agent.get('bot_id') or '').strip() else None,
    }


def _context_from_history(user_id, history_ids):
    rows = get_chat_history_by_ids(history_ids, user_id, limit=20)
    context = []
    for row in rows:
        context.append({'role': 'user', 'text': row.get('user_message') or '', 'at': row.get('created_at')})
        if row.get('bot_response'):
            context.append({'role': 'ai', 'text': row['bot_response'], 'at': row.get('created_at')})
    return rows, context


def _reconcile_locked(conn):
    settings = get_handoff_settings()
    deadline_modifier = f"+{settings['live_wait_sec']} seconds"
    conn.execute(
        f'''UPDATE handoff_sessions
            SET live_deadline_at = datetime(enqueued_at, ?), updated_at = CURRENT_TIMESTAMP
            WHERE status IN ({_open_status_sql()})
              AND COALESCE(service_mode, 'live') = 'live' AND live_deadline_at IS NULL''',
        (deadline_modifier,),
    )
    expired = conn.execute(
        f'''SELECT id, session_id FROM handoff_sessions
            WHERE status IN ({_open_status_sql()})
              AND COALESCE(service_mode, 'live') = 'live'
              AND live_deadline_at IS NOT NULL AND live_deadline_at <= CURRENT_TIMESTAMP
              AND NOT EXISTS (
                SELECT 1 FROM handoff_messages m
                WHERE m.session_id = handoff_sessions.session_id AND m.sender_role = 'agent'
              )'''
    ).fetchall()
    for item in expired:
        conn.execute(
            '''UPDATE handoff_sessions SET service_mode = 'message', message_converted_at = CURRENT_TIMESTAMP,
               updated_at = CURRENT_TIMESTAMP WHERE id = ? AND COALESCE(service_mode, 'live') = 'live' ''',
            (item['id'],),
        )
        conn.execute(
            '''INSERT INTO handoff_messages (session_id, sender_role, content)
               VALUES (?, 'system', '在线等待超时，已自动转为留言。你可以继续使用 AI，营养师稍后回复。')''',
            (item['session_id'],),
        )
    conn.execute(
        '''UPDATE handoff_sessions
           SET status = 'queued', agent_id = '', assigned_at = NULL,
               agent_claim_deadline = NULL, updated_at = CURRENT_TIMESTAMP
           WHERE status = 'assigned' AND agent_claim_deadline IS NOT NULL
             AND agent_claim_deadline <= CURRENT_TIMESTAMP'''
    )
    conn.execute(
        '''UPDATE cs_agents SET online = 0, updated_at = CURRENT_TIMESTAMP
           WHERE online = 1 AND (last_seen_at IS NULL OR last_seen_at < datetime('now', ?))''',
        (f'-{Config.HANDOFF_AGENT_STALE_SEC} seconds',),
    )
    conn.execute(
        '''UPDATE cs_agents
           SET current_load = (
               SELECT COUNT(*) FROM handoff_sessions s
               WHERE s.agent_id = cs_agents.user_id AND s.status IN ('assigned', 'active')
           ), updated_at = CURRENT_TIMESTAMP'''
    )

    assigned = 0
    while True:
        agent = conn.execute(
            '''SELECT * FROM cs_agents
               WHERE online = 1 AND last_seen_at >= datetime('now', ?)
                 AND current_load < max_concurrent
               ORDER BY current_load ASC, updated_at ASC, user_id ASC LIMIT 1''',
            (f'-{Config.HANDOFF_AGENT_STALE_SEC} seconds',),
        ).fetchone()
        queued = conn.execute(
            '''SELECT id FROM handoff_sessions WHERE status = 'queued'
               ORDER BY priority DESC, enqueued_at ASC, id ASC LIMIT 1'''
        ).fetchone()
        if not agent or not queued:
            break
        cursor = conn.execute(
            '''UPDATE handoff_sessions
               SET status = 'assigned', agent_id = ?, assigned_at = CURRENT_TIMESTAMP,
                   agent_claim_deadline = datetime('now', ?), updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'queued' ''',
            (agent['user_id'], f'+{Config.HANDOFF_CLAIM_TIMEOUT_SEC} seconds', queued['id']),
        )
        if cursor.rowcount != 1:
            continue
        conn.execute(
            'UPDATE cs_agents SET current_load = current_load + 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (agent['user_id'],),
        )
        assigned += 1
    return assigned


def assign_available():
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        assigned = _reconcile_locked(conn)
        conn.commit()
        return assigned
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _queue_position(conn, row):
    if row['status'] != 'queued':
        return 0
    return conn.execute(
        '''SELECT COUNT(*) + 1 AS position FROM handoff_sessions
           WHERE status = 'queued' AND (
             priority > ? OR
             (priority = ? AND (enqueued_at < ? OR (enqueued_at = ? AND id < ?)))
           )''',
        (row['priority'], row['priority'], row['enqueued_at'], row['enqueued_at'], row['id']),
    ).fetchone()['position']


def _session_payload(conn, row, include_context=False):
    if not row:
        return None
    data = dict(row)
    position = _queue_position(conn, row)
    online = conn.execute(
        '''SELECT COUNT(*) AS cnt FROM cs_agents
           WHERE online = 1 AND last_seen_at >= datetime('now', ?)''',
        (f'-{Config.HANDOFF_AGENT_STALE_SEC} seconds',),
    ).fetchone()['cnt']
    data['queue_position'] = position
    data['live_wait_sec'] = get_handoff_settings()['live_wait_sec']
    data['est_wait_sec'] = None if position and not online else (position * get_handoff_settings()['avg_handle_sec'] // max(1, online) if position else 0)
    if data.get('agent_id'):
        agent = conn.execute('SELECT display_name, avatar_url FROM cs_agents WHERE user_id = ?', (data['agent_id'],)).fetchone()
        data['agent'] = dict(agent) if agent else None
    else:
        data['agent'] = None
    if include_context:
        try:
            data['ai_context'] = json.loads(data.pop('ai_context_json') or '[]')
        except (TypeError, ValueError):
            data['ai_context'] = []
    else:
        data.pop('ai_context_json', None)
    data.pop('id', None)
    return data


def start_handoff(identity, history_ids=None, query_type='', note=''):
    settings = get_handoff_settings()
    if not settings['enabled']:
        raise HandoffError('在线营养咨询暂未开启', 403)
    rows, context = _context_from_history(identity['user_id'], history_ids or [])
    ai_agent_id = settings['ai_agent_id'] or (rows[-1].get('agent_id') if rows else '') or ''
    session_id = uuid.uuid4().hex
    note = str(note or '').strip()[:2000]
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute(
            f'''SELECT * FROM handoff_sessions
                WHERE user_id = ? AND status IN ({_open_status_sql()})
                ORDER BY id DESC LIMIT 1''',
            (identity['user_id'],),
        ).fetchone()
        if existing:
            conn.commit()
            return _session_payload(conn, existing)
        cursor = conn.execute(
            '''INSERT INTO handoff_sessions
               (session_id, user_id, team_name, member_name, query_type, ai_agent_id, ai_context_json,
                service_mode, live_deadline_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'live', datetime('now', ?))''',
            (
                session_id, identity['user_id'], identity.get('team_name', ''), identity.get('member_name', ''),
                str(query_type or '')[:50], ai_agent_id, json.dumps(context, ensure_ascii=False),
                f"+{settings['live_wait_sec']} seconds",
            ),
        )
        if note:
            msg = conn.execute(
                '''INSERT INTO handoff_messages (session_id, sender_role, sender_id, content)
                   VALUES (?, 'user', ?, ?)''',
                (session_id, identity['user_id'], note),
            )
            conn.execute(
                'UPDATE handoff_sessions SET last_message_at = CURRENT_TIMESTAMP, user_last_read_message_id = ? WHERE id = ?',
                (msg.lastrowid, cursor.lastrowid),
            )
        _reconcile_locked(conn)
        row = conn.execute('SELECT * FROM handoff_sessions WHERE id = ?', (cursor.lastrowid,)).fetchone()
        conn.commit()
        return _session_payload(conn, row)
    except sqlite3.IntegrityError:
        conn.rollback()
        row = conn.execute(
            f'''SELECT * FROM handoff_sessions WHERE user_id = ?
                AND status IN ({_open_status_sql()}) ORDER BY id DESC LIMIT 1''',
            (identity['user_id'],),
        ).fetchone()
        if row:
            return _session_payload(conn, row)
        raise
    finally:
        conn.close()


def get_current_session(user_id):
    assign_available()
    conn = get_db_connection()
    row = conn.execute(
        f'''SELECT * FROM handoff_sessions WHERE user_id = ?
            AND status IN ({_open_status_sql()}) ORDER BY id DESC LIMIT 1''',
        (user_id,),
    ).fetchone()
    payload = _session_payload(conn, row, include_context=True)
    conn.close()
    return payload


def get_user_session(user_id, session_id, include_context=True):
    assign_available()
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM handoff_sessions WHERE session_id = ? AND user_id = ?', (session_id, user_id)).fetchone()
    payload = _session_payload(conn, row, include_context=include_context)
    conn.close()
    return payload


def append_user_message(user_id, session_id, content):
    content = str(content or '').strip()
    if not content:
        raise HandoffError('消息不能为空')
    if len(content) > 4000:
        raise HandoffError('消息不能超过4000字')
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        session = conn.execute(
            'SELECT * FROM handoff_sessions WHERE session_id = ? AND user_id = ?',
            (session_id, user_id),
        ).fetchone()
        if not session:
            raise HandoffError('咨询会话不存在', 404)
        if session['status'] not in MESSAGE_STATUSES:
            raise HandoffError('咨询已结束，不能继续发送', 409)
        cursor = conn.execute(
            '''INSERT INTO handoff_messages (session_id, sender_role, sender_id, content)
               VALUES (?, 'user', ?, ?)''',
            (session_id, user_id, content),
        )
        conn.execute(
            '''UPDATE handoff_sessions SET last_message_at = CURRENT_TIMESTAMP,
               user_last_read_message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?''',
            (cursor.lastrowid, session_id),
        )
        row = conn.execute('SELECT * FROM handoff_messages WHERE id = ?', (cursor.lastrowid,)).fetchone()
        conn.commit()
        return dict(row)
    except HandoffError:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_user_messages(user_id, session_id, after_id=0, limit=50):
    limit = max(1, min(int(limit or 50), 100))
    after_id = max(0, int(after_id or 0))
    conn = get_db_connection()
    session = conn.execute('SELECT id FROM handoff_sessions WHERE session_id = ? AND user_id = ?', (session_id, user_id)).fetchone()
    if not session:
        conn.close()
        raise HandoffError('咨询会话不存在', 404)
    if after_id:
        rows = conn.execute(
            'SELECT * FROM handoff_messages WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?',
            (session_id, after_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            '''SELECT * FROM (SELECT * FROM handoff_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?)
               ORDER BY id ASC''',
            (session_id, limit),
        ).fetchall()
    if rows:
        conn.execute(
            'UPDATE handoff_sessions SET user_last_read_message_id = MAX(user_last_read_message_id, ?) WHERE session_id = ?',
            (rows[-1]['id'], session_id),
        )
        conn.commit()
    conn.close()
    return [dict(row) for row in rows]


def list_recent_sessions(user_id, limit=20):
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT * FROM handoff_sessions WHERE user_id = ?
           ORDER BY id DESC LIMIT ?''',
        (user_id, max(1, min(int(limit or 20), 50))),
    ).fetchall()
    result = [_session_payload(conn, row) for row in rows]
    conn.close()
    return result


def close_user_session(user_id, session_id, reason='user_cancel'):
    return _close_session(session_id, user_id=user_id, reason=reason)


def defer_user_session(user_id, session_id):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            'SELECT * FROM handoff_sessions WHERE session_id = ? AND user_id = ?',
            (session_id, user_id),
        ).fetchone()
        if not row:
            raise HandoffError('咨询会话不存在', 404)
        if row['status'] not in OPEN_STATUSES:
            raise HandoffError('咨询已结束，不能转为留言', 409)
        if (row['service_mode'] or 'live') != 'message':
            conn.execute(
                '''UPDATE handoff_sessions SET service_mode = 'message', message_converted_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (row['id'],),
            )
            conn.execute(
                '''INSERT INTO handoff_messages (session_id, sender_role, content)
                   VALUES (?, 'system', '已转为留言。你可以继续使用 AI，营养师稍后回复。')''',
                (session_id,),
            )
        updated = conn.execute('SELECT * FROM handoff_sessions WHERE id = ?', (row['id'],)).fetchone()
        conn.commit()
        return _session_payload(conn, updated, include_context=True)
    except HandoffError:
        conn.rollback()
        raise
    finally:
        conn.close()


def _close_session(session_id, user_id=None, agent_id=None, reason='done'):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        params = [session_id]
        where = 'session_id = ?'
        if user_id is not None:
            where += ' AND user_id = ?'
            params.append(user_id)
        if agent_id is not None:
            where += ' AND agent_id = ?'
            params.append(agent_id)
        row = conn.execute(f'SELECT * FROM handoff_sessions WHERE {where}', params).fetchone()
        if not row:
            raise HandoffError('咨询会话不存在或无权操作', 404)
        if row['status'] in OPEN_STATUSES:
            conn.execute(
                '''UPDATE handoff_sessions SET status = 'closed', close_reason = ?, closed_at = CURRENT_TIMESTAMP,
                   agent_claim_deadline = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (str(reason or 'done')[:40], row['id']),
            )
            conn.execute(
                '''INSERT INTO handoff_messages (session_id, sender_role, content)
                   VALUES (?, 'system', ?)''',
                (session_id, '本次人工咨询已结束'),
            )
        _reconcile_locked(conn)
        updated = conn.execute('SELECT * FROM handoff_sessions WHERE id = ?', (row['id'],)).fetchone()
        conn.commit()
        return _session_payload(conn, updated)
    except HandoffError:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_agent_status(user, online, max_concurrent=None):
    online = 1 if online else 0
    if max_concurrent is None:
        max_concurrent = 3
    max_concurrent = max(1, min(int(max_concurrent), 10))
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            '''INSERT INTO cs_agents (user_id, display_name, online, max_concurrent, last_seen_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                 display_name = excluded.display_name,
                 online = excluded.online,
                 max_concurrent = excluded.max_concurrent,
                 last_seen_at = CURRENT_TIMESTAMP,
                 updated_at = CURRENT_TIMESTAMP''',
            (user['user_id'], user.get('username', ''), online, max_concurrent),
        )
        _reconcile_locked(conn)
        row = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user['user_id'],)).fetchone()
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def get_agent_me(user_id):
    assign_available()
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone()
    if not row:
        conn.close()
        return None
    data = dict(row)
    sessions = conn.execute(
        '''SELECT * FROM handoff_sessions WHERE agent_id = ? AND status IN ('assigned', 'active')
           ORDER BY last_message_at DESC, id DESC''',
        (user_id,),
    ).fetchall()
    data['sessions'] = [_session_payload(conn, item) for item in sessions]
    conn.close()
    return data


def list_agent_queue(user_id):
    assign_available()
    conn = get_db_connection()
    agent = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone()
    if not agent:
        conn.close()
        raise HandoffError('当前管理员尚未开通客服坐席', 403)
    rows = conn.execute(
        '''SELECT s.*,
             COALESCE((SELECT content FROM handoff_messages m WHERE m.session_id = s.session_id ORDER BY m.id DESC LIMIT 1), '') AS last_message,
             COALESCE((SELECT COUNT(*) FROM handoff_messages m WHERE m.session_id = s.session_id
                       AND m.sender_role = 'user' AND m.id > s.agent_last_read_message_id), 0) AS unread_count
           FROM handoff_sessions s
           WHERE s.status = 'queued' OR (s.agent_id = ? AND s.status IN ('assigned', 'active'))
           ORDER BY CASE s.status WHEN 'active' THEN 0 WHEN 'assigned' THEN 1 ELSE 2 END,
                    s.priority DESC, s.enqueued_at ASC, s.id ASC''',
        (user_id,),
    ).fetchall()
    result = [_session_payload(conn, row) for row in rows]
    conn.close()
    return {'agent': dict(agent), 'sessions': result}


def claim_session(user_id, session_id):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        _reconcile_locked(conn)
        agent = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone()
        if not agent or not agent['online']:
            raise HandoffError('请先上线后再接入会话', 409)
        row = conn.execute('SELECT * FROM handoff_sessions WHERE session_id = ?', (session_id,)).fetchone()
        if not row:
            raise HandoffError('咨询会话不存在', 404)
        if row['status'] == 'active' and row['agent_id'] == user_id:
            conn.commit()
            return _session_payload(conn, row, include_context=True)
        if row['status'] == 'assigned' and row['agent_id'] == user_id:
            pass
        elif row['status'] == 'queued' and agent['current_load'] < agent['max_concurrent']:
            conn.execute(
                '''UPDATE handoff_sessions SET agent_id = ?, status = 'assigned', assigned_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'queued' ''',
                (user_id, row['id']),
            )
            conn.execute('UPDATE cs_agents SET current_load = current_load + 1 WHERE user_id = ?', (user_id,))
        else:
            raise HandoffError('会话已被其他客服接入或当前接待已满', 409)
        handoff_settings = get_handoff_settings()
        conn.execute(
            '''UPDATE handoff_sessions SET status = 'active', active_at = CURRENT_TIMESTAMP,
               agent_claim_deadline = NULL, live_deadline_at = datetime('now', ?),
               updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
            (f"+{handoff_settings['live_wait_sec']} seconds", row['id']),
        )
        welcome = (
            '营养师正在处理你的留言，回复后会自动归档'
            if (row['service_mode'] or 'live') == 'message'
            else handoff_settings['welcome_msg']
        )
        conn.execute(
            '''INSERT INTO handoff_messages (session_id, sender_role, sender_id, content)
               VALUES (?, 'system', ?, ?)''',
            (session_id, user_id, welcome),
        )
        updated = conn.execute('SELECT * FROM handoff_sessions WHERE id = ?', (row['id'],)).fetchone()
        conn.commit()
        return _session_payload(conn, updated, include_context=True)
    except HandoffError:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_agent_session_detail(user_id, session_id):
    conn = get_db_connection()
    row = conn.execute(
        '''SELECT * FROM handoff_sessions WHERE session_id = ?
           AND (status = 'queued' OR agent_id = ?)''',
        (session_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        raise HandoffError('咨询会话不存在或未分配给当前客服', 404)
    session = _session_payload(conn, row, include_context=True)
    messages = conn.execute(
        'SELECT * FROM handoff_messages WHERE session_id = ? ORDER BY id ASC',
        (session_id,),
    ).fetchall()
    session['messages'] = [dict(item) for item in messages]
    conn.close()
    return session


def _archive_summary_payload(row):
    data = dict(row)
    data.pop('ai_context_json', None)
    data.pop('id', None)
    return data


def list_archived_sessions(page=1, limit=20, date_from='', date_to='', keyword='', team='', agent_id='', service_mode=''):
    try:
        page = max(1, int(page or 1))
        limit = max(1, min(int(limit or 20), 50))
    except (TypeError, ValueError):
        raise HandoffError('分页参数不正确')
    service_mode = str(service_mode or '').strip()
    if service_mode and service_mode not in {'live', 'message'}:
        raise HandoffError('服务方式不正确')

    where = ["s.status = 'closed'"]
    params = []
    if date_from:
        where.append("date(COALESCE(s.closed_at, s.updated_at)) >= date(?)")
        params.append(str(date_from).strip())
    if date_to:
        where.append("date(COALESCE(s.closed_at, s.updated_at)) <= date(?)")
        params.append(str(date_to).strip())
    if team:
        where.append('s.team_name = ?')
        params.append(str(team).strip())
    if agent_id:
        where.append('s.agent_id = ?')
        params.append(str(agent_id).strip())
    if service_mode:
        where.append("COALESCE(s.service_mode, 'live') = ?")
        params.append(service_mode)
    if keyword:
        pattern = f"%{str(keyword).strip()}%"
        where.append('''(s.member_name LIKE ? OR s.team_name LIKE ? OR EXISTS (
            SELECT 1 FROM handoff_messages search_message
            WHERE search_message.session_id = s.session_id AND search_message.content LIKE ?
        ))''')
        params.extend([pattern, pattern, pattern])

    where_sql = ' AND '.join(where)
    conn = get_db_connection()
    total = conn.execute(
        f'SELECT COUNT(*) AS total FROM handoff_sessions s WHERE {where_sql}',
        params,
    ).fetchone()['total']
    offset = (page - 1) * limit
    rows = conn.execute(
        f'''SELECT s.*, COALESCE(a.display_name, s.agent_id, '') AS agent_name,
              COALESCE((SELECT content FROM handoff_messages m
                        WHERE m.session_id = s.session_id AND m.sender_role = 'user'
                        ORDER BY m.id DESC LIMIT 1), '') AS last_question,
              COALESCE((SELECT content FROM handoff_messages m
                        WHERE m.session_id = s.session_id AND m.sender_role = 'agent'
                        ORDER BY m.id DESC LIMIT 1), '') AS last_reply
           FROM handoff_sessions s
           LEFT JOIN cs_agents a ON a.user_id = s.agent_id
           WHERE {where_sql}
           ORDER BY COALESCE(s.closed_at, s.updated_at) DESC, s.id DESC
           LIMIT ? OFFSET ?''',
        [*params, limit, offset],
    ).fetchall()
    conn.close()
    pages = max(1, (total + limit - 1) // limit)
    return {
        'items': [_archive_summary_payload(row) for row in rows],
        'pagination': {'page': page, 'limit': limit, 'total': total, 'pages': pages},
    }


def get_archived_session_detail(session_id):
    conn = get_db_connection()
    row = conn.execute(
        '''SELECT s.*, COALESCE(a.display_name, s.agent_id, '') AS agent_name
           FROM handoff_sessions s LEFT JOIN cs_agents a ON a.user_id = s.agent_id
           WHERE s.session_id = ? AND s.status = 'closed' ''',
        (session_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HandoffError('咨询档案不存在', 404)
    session = _session_payload(conn, row, include_context=True)
    session['agent_name'] = row['agent_name']
    messages = conn.execute(
        'SELECT * FROM handoff_messages WHERE session_id = ? ORDER BY id ASC',
        (session_id,),
    ).fetchall()
    session['messages'] = [dict(item) for item in messages]
    conn.close()
    return session


def list_user_archived_sessions(user_id, page=1, limit=20, exclude_session_id=''):
    try:
        page = max(1, int(page or 1))
        limit = max(1, min(int(limit or 20), 50))
    except (TypeError, ValueError):
        raise HandoffError('分页参数不正确')
    where = ["s.user_id = ?", "s.status = 'closed'"]
    params = [user_id]
    if exclude_session_id:
        where.append('s.session_id != ?')
        params.append(str(exclude_session_id))
    where_sql = ' AND '.join(where)
    conn = get_db_connection()
    total = conn.execute(
        f'SELECT COUNT(*) AS total FROM handoff_sessions s WHERE {where_sql}', params,
    ).fetchone()['total']
    rows = conn.execute(
        f'''SELECT s.*, COALESCE(a.display_name, s.agent_id, '') AS agent_name,
              COALESCE((SELECT content FROM handoff_messages m
                        WHERE m.session_id = s.session_id AND m.sender_role = 'user'
                        ORDER BY m.id DESC LIMIT 1), '') AS last_question,
              COALESCE((SELECT content FROM handoff_messages m
                        WHERE m.session_id = s.session_id AND m.sender_role = 'agent'
                        ORDER BY m.id DESC LIMIT 1), '') AS last_reply
           FROM handoff_sessions s
           LEFT JOIN cs_agents a ON a.user_id = s.agent_id
           WHERE {where_sql}
           ORDER BY COALESCE(s.closed_at, s.updated_at) DESC, s.id DESC
           LIMIT ? OFFSET ?''',
        [*params, limit, (page - 1) * limit],
    ).fetchall()
    conn.close()
    return {
        'items': [_archive_summary_payload(row) for row in rows],
        'pagination': {
            'page': page, 'limit': limit, 'total': total,
            'pages': max(1, (total + limit - 1) // limit),
        },
    }


def _export_filter_sql(filters):
    filters = filters if isinstance(filters, dict) else {}
    service_mode = str(filters.get('service_mode') or '').strip()
    if service_mode and service_mode not in {'live', 'message'}:
        raise HandoffError('服务方式不正确')
    where = ["s.status = 'closed'"]
    params = []
    if filters.get('from'):
        where.append("date(COALESCE(s.closed_at, s.updated_at)) >= date(?)")
        params.append(str(filters['from']).strip())
    if filters.get('to'):
        where.append("date(COALESCE(s.closed_at, s.updated_at)) <= date(?)")
        params.append(str(filters['to']).strip())
    if filters.get('team'):
        where.append('s.team_name = ?')
        params.append(str(filters['team']).strip())
    if filters.get('agent_id'):
        where.append('s.agent_id = ?')
        params.append(str(filters['agent_id']).strip())
    if service_mode:
        where.append("COALESCE(s.service_mode, 'live') = ?")
        params.append(service_mode)
    if filters.get('keyword'):
        pattern = f"%{str(filters['keyword']).strip()}%"
        where.append('''(s.member_name LIKE ? OR s.team_name LIKE ? OR EXISTS (
            SELECT 1 FROM handoff_messages search_message
            WHERE search_message.session_id = s.session_id AND search_message.content LIKE ?
        ))''')
        params.extend([pattern, pattern, pattern])
    return ' AND '.join(where), params


def _csv_safe(value):
    if value is None:
        return ''
    text = str(value)
    if text.startswith(('=', '+', '-', '@')):
        return "'" + text
    return text


def _duration_seconds(start, end):
    if not start or not end:
        return ''
    try:
        start_at = datetime.fromisoformat(str(start).replace('Z', '+00:00'))
        end_at = datetime.fromisoformat(str(end).replace('Z', '+00:00'))
        return max(0, int((end_at - start_at).total_seconds()))
    except (TypeError, ValueError):
        return ''


def export_archived_sessions(exported_by, session_ids=None, filters=None):
    session_ids = session_ids if isinstance(session_ids, list) else []
    session_ids = list(dict.fromkeys(str(item).strip() for item in session_ids if str(item).strip()))
    if len(session_ids) > 5000:
        raise HandoffError('单次最多导出 5000 条咨询档案', 413)
    if session_ids:
        placeholders = ','.join('?' for _ in session_ids)
        where_sql = f"s.status = 'closed' AND s.session_id IN ({placeholders})"
        params = session_ids
        scope = 'single' if len(session_ids) == 1 else 'selected'
        audit_request = {'session_ids': session_ids}
    else:
        where_sql, params = _export_filter_sql(filters or {})
        scope = 'filtered'
        audit_request = {'filters': filters or {}}

    conn = get_db_connection()
    rows = conn.execute(
        f'''SELECT s.*, COALESCE(NULLIF(a.display_name, ''), s.agent_id, '') AS agent_name
            FROM handoff_sessions s LEFT JOIN cs_agents a ON a.user_id = s.agent_id
            WHERE {where_sql}
            ORDER BY COALESCE(s.closed_at, s.updated_at) DESC, s.id DESC
            LIMIT 5001''',
        params,
    ).fetchall()
    if len(rows) > 5000:
        conn.close()
        raise HandoffError('符合条件的档案超过 5000 条，请缩小筛选范围', 413)

    messages_by_session = {row['session_id']: {'user': [], 'agent': []} for row in rows}
    row_session_ids = list(messages_by_session)
    for start in range(0, len(row_session_ids), 500):
        chunk = row_session_ids[start:start + 500]
        placeholders = ','.join('?' for _ in chunk)
        messages = conn.execute(
            f'''SELECT session_id, sender_role, content FROM handoff_messages
                WHERE session_id IN ({placeholders}) AND sender_role IN ('user', 'agent')
                ORDER BY session_id ASC, id ASC''',
            chunk,
        ).fetchall()
        for message in messages:
            messages_by_session[message['session_id']][message['sender_role']].append(message['content'])

    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([
        '会话编号', '用户姓名', '团队', '接待营养师', '咨询方式', '结束原因',
        '发起时间', '接入时间', '结束时间', '等待时长（秒）', '处理时长（秒）',
        '用户问题', '营养师回复',
    ])
    for row in rows:
        messages = messages_by_session[row['session_id']]
        values = [
            row['session_id'], row['member_name'], row['team_name'], row['agent_name'],
            '留言' if (row['service_mode'] or 'live') == 'message' else '在线咨询',
            row['close_reason'], row['enqueued_at'], row['active_at'], row['closed_at'],
            _duration_seconds(row['enqueued_at'], row['active_at'] or row['closed_at']),
            _duration_seconds(row['active_at'], row['closed_at']),
            '\n'.join(_csv_safe(message) for message in messages['user']),
            '\n'.join(_csv_safe(message) for message in messages['agent']),
        ]
        writer.writerow([_csv_safe(value) for value in values])

    conn.execute(
        '''INSERT INTO handoff_export_logs (exported_by, export_scope, request_json, row_count)
           VALUES (?, ?, ?, ?)''',
        (exported_by, scope, json.dumps(audit_request, ensure_ascii=False), len(rows)),
    )
    conn.commit()
    conn.close()
    filename = f"consultant_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return {'content': '\ufeff' + output.getvalue(), 'filename': filename, 'row_count': len(rows)}


def append_agent_reply(user_id, session_id, content):
    content = str(content or '').strip()
    if not content:
        raise HandoffError('回复不能为空')
    if len(content) > 4000:
        raise HandoffError('回复不能超过4000字')
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            '''SELECT * FROM handoff_sessions WHERE session_id = ? AND agent_id = ? AND status = 'active' ''',
            (session_id, user_id),
        ).fetchone()
        if not row:
            raise HandoffError('会话未接入、已结束或无权回复', 409)
        cursor = conn.execute(
            '''INSERT INTO handoff_messages (session_id, sender_role, sender_id, content)
               VALUES (?, 'agent', ?, ?)''',
            (session_id, user_id, content),
        )
        auto_closed = (row['service_mode'] or 'live') == 'message'
        if auto_closed:
            conn.execute(
                '''UPDATE handoff_sessions SET status = 'closed', close_reason = 'message_replied',
                   closed_at = CURRENT_TIMESTAMP, agent_claim_deadline = NULL,
                   last_message_at = CURRENT_TIMESTAMP, agent_last_read_message_id = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (cursor.lastrowid, row['id']),
            )
            _reconcile_locked(conn)
        else:
            conn.execute(
                '''UPDATE handoff_sessions SET last_message_at = CURRENT_TIMESTAMP,
                   agent_last_read_message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (cursor.lastrowid, row['id']),
            )
        message = conn.execute('SELECT * FROM handoff_messages WHERE id = ?', (cursor.lastrowid,)).fetchone()
        conn.commit()
        data = dict(message)
        data['auto_closed'] = auto_closed
        return data
    except HandoffError:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_agent_read(user_id, session_id, message_id):
    conn = get_db_connection()
    cursor = conn.execute(
        '''UPDATE handoff_sessions SET agent_last_read_message_id = MAX(agent_last_read_message_id, ?)
           WHERE session_id = ? AND agent_id = ?''',
        (max(0, int(message_id or 0)), session_id, user_id),
    )
    conn.commit()
    conn.close()
    if cursor.rowcount != 1:
        raise HandoffError('会话不存在或无权操作', 404)
    return True


def close_agent_session(user_id, session_id, reason='agent_close'):
    return _close_session(session_id, agent_id=user_id, reason=reason)


def list_notifications(user_id, after_session_id=0, after_message_id=0):
    conn = get_db_connection()
    if not conn.execute('SELECT 1 FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone():
        conn.close()
        raise HandoffError('当前管理员尚未开通客服坐席', 403)
    sessions = conn.execute(
        '''SELECT id, session_id, member_name, status, agent_id, enqueued_at
           FROM handoff_sessions
           WHERE id > ? AND (status = 'queued' OR agent_id = ?)
           ORDER BY id ASC LIMIT 50''',
        (max(0, int(after_session_id or 0)), user_id),
    ).fetchall()
    messages = conn.execute(
        '''SELECT m.id, m.session_id, m.content, m.created_at, s.member_name
           FROM handoff_messages m JOIN handoff_sessions s ON s.session_id = m.session_id
           WHERE m.id > ? AND m.sender_role = 'user' AND s.agent_id = ?
           ORDER BY m.id ASC LIMIT 100''',
        (max(0, int(after_message_id or 0)), user_id),
    ).fetchall()
    result = {
        'sessions': [dict(row) for row in sessions],
        'messages': [dict(row) for row in messages],
        'cursor': {
            'session_id': max([int(after_session_id or 0)] + [row['id'] for row in sessions]),
            'message_id': max([int(after_message_id or 0)] + [row['id'] for row in messages]),
        },
    }
    conn.close()
    return result
