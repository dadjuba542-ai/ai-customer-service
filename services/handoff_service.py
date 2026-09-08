import csv
import io
import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime

from config import Config
from models import create_user, get_agent_config, get_chat_history_by_ids, get_db_connection, get_setting, get_user_by_username, set_setting
from services import feature_flags


OPEN_STATUSES = ('queued', 'assigned', 'active')
MESSAGE_STATUSES = ('queued', 'assigned', 'active')
DEFAULTS = {
    # 开关状态统一由 services/feature_flags.py 决定（settings 表 > 环境变量 > 默认值）
    'enabled': feature_flags.default_enabled(feature_flags.HANDOFF_SYSTEM),
    'ai_agent_id': Config.HANDOFF_AI_AGENT_ID,
    'button_label': '联系在线营养师',
    'queue_msg': '客服忙线中，您前面还有 {position} 位',
    'offline_msg': '当前营养师暂未在线，已为您留言',
    'welcome_msg': '营养师已接入，本次咨询将由真人为您解答',
    'avg_handle_sec': Config.HANDOFF_AVG_HANDLE_SEC,
    'live_wait_sec': Config.HANDOFF_LIVE_WAIT_SEC,
}


_reconcile_thread = None
_reconcile_stop = threading.Event()
_reconcile_started_lock = threading.Lock()


class HandoffError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def handoff_enabled():
    """人工客服系统总开关（案例系统互不影响，各自独立）。"""
    return feature_flags.is_enabled(feature_flags.HANDOFF_SYSTEM)


def _require_handoff_enabled():
    """服务层兜底：绕过 HTTP 入口的内部调用也必须被开关拦住。"""
    if not handoff_enabled():
        raise HandoffError('人工客服系统当前已关闭', 403)


def _bool_setting(key, default=False, values=None):
    raw = str((values or {}).get(key, get_setting(key, '1' if default else '0'))).strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


def _int_setting(key, default, minimum=1, maximum=86400, values=None):
    try:
        value = int((values or {}).get(key, get_setting(key, str(default))))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _read_settings(conn=None):
    keys = (
        'handoff_enabled', 'handoff_ai_agent_id', 'handoff_button_label', 'handoff_queue_msg',
        'handoff_offline_msg', 'handoff_welcome_msg', 'handoff_avg_handle_sec', 'handoff_live_wait_sec',
    )
    if conn is None:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                f'SELECT key, value FROM settings WHERE key IN ({",".join("?" for _ in keys)})',
                keys,
            ).fetchall()
        finally:
            conn.close()
    else:
        rows = conn.execute(
            f'SELECT key, value FROM settings WHERE key IN ({",".join("?" for _ in keys)})',
            keys,
        ).fetchall()
    return {row['key']: row['value'] for row in rows}


def get_handoff_settings(conn=None):
    values = _read_settings(conn)
    return {
        'enabled': handoff_enabled(),
        'ai_agent_id': values.get('handoff_ai_agent_id', DEFAULTS['ai_agent_id']).strip(),
        'button_label': values.get('handoff_button_label', DEFAULTS['button_label']).strip() or DEFAULTS['button_label'],
        'queue_msg': values.get('handoff_queue_msg', DEFAULTS['queue_msg']).strip() or DEFAULTS['queue_msg'],
        'offline_msg': values.get('handoff_offline_msg', DEFAULTS['offline_msg']).strip() or DEFAULTS['offline_msg'],
        'welcome_msg': values.get('handoff_welcome_msg', DEFAULTS['welcome_msg']).strip() or DEFAULTS['welcome_msg'],
        'avg_handle_sec': _int_setting('handoff_avg_handle_sec', DEFAULTS['avg_handle_sec'], 30, 86400, values=values),
        'live_wait_sec': _int_setting('handoff_live_wait_sec', DEFAULTS['live_wait_sec'], 30, 3600, values=values),
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
    # 开关统一走 feature_flags（settings 表同一个 key: handoff_enabled），
    # 放在最后写，保证开启时的「已配置 AI 智能体」校验读到刚写入的值。
    feature_flags.set_enabled(feature_flags.HANDOFF_SYSTEM, enabled)
    return get_handoff_settings()


def start_handoff_reconciler():
    """Start a process-local background thread that periodically runs assign_available().

    人工客服系统关闭时不启动；后台把开关打开会由 feature_flags 的 on_change 补启动。
    """
    global _reconcile_thread
    if not handoff_enabled():
        return None
    with _reconcile_started_lock:
        if _reconcile_thread and _reconcile_thread.is_alive():
            return _reconcile_thread
        _reconcile_stop.clear()
        thread = threading.Thread(
            target=_reconcile_loop,
            name='handoff-reconciler',
            daemon=True,
        )
        thread.start()
        _reconcile_thread = thread
        return thread


def stop_handoff_reconciler_for_tests():
    global _reconcile_thread
    _reconcile_stop.set()
    if _reconcile_thread:
        _reconcile_thread.join(timeout=2)
        _reconcile_thread = None


def _reconcile_loop():
    while not _reconcile_stop.is_set():
        try:
            # 开关可能在运行期被关掉，每轮都重新判断，避免定时任务继续派单。
            if handoff_enabled():
                assign_available()
        except Exception:
            logging.getLogger(__name__).exception('handoff.reconciler error')
        _reconcile_stop.wait(max(2, int(Config.HANDOFF_RECONCILE_INTERVAL_SECONDS)))


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
    settings = get_handoff_settings(conn)
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
    online_count = conn.execute(
        '''SELECT COUNT(*) AS cnt FROM cs_agents
           WHERE online = 1 AND last_seen_at >= datetime('now', ?)''',
        (f'-{Config.HANDOFF_AGENT_STALE_SEC} seconds',),
    ).fetchone()['cnt']
    if not online_count:
        offline_queued = conn.execute(
            '''SELECT id, session_id FROM handoff_sessions
               WHERE status = 'queued' AND COALESCE(service_mode, 'live') = 'live' '''
        ).fetchall()
        for item in offline_queued:
            conn.execute(
                '''UPDATE handoff_sessions SET service_mode = 'message',
                   live_deadline_at = NULL, message_converted_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (item['id'],),
            )
            conn.execute(
                '''INSERT INTO handoff_messages (session_id, sender_role, content)
                   VALUES (?, 'system', '营养师暂未在线，已直接转为留言。你可以继续使用 AI，营养师稍后回复。')''',
                (item['session_id'],),
            )
    # 留言多轮：留言会话在最后一次消息后超过 HANDOFF_MESSAGE_IDLE_SEC 无新消息即自动归档
    idle_cutoff = f"-{Config.HANDOFF_MESSAGE_IDLE_SEC} seconds"
    idle_sessions = conn.execute(
        f'''SELECT id, session_id FROM handoff_sessions
            WHERE COALESCE(service_mode, 'live') = 'message'
              AND status IN ({_open_status_sql()})
              AND last_message_at <= datetime('now', ?)''',
        (idle_cutoff,),
    ).fetchall()
    for item in idle_sessions:
        conn.execute(
            '''UPDATE handoff_sessions SET status = 'closed', close_reason = 'message_idle',
               closed_at = CURRENT_TIMESTAMP, agent_claim_deadline = NULL,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
            (item['id'],),
        )
        conn.execute(
            '''INSERT INTO handoff_messages (session_id, sender_role, content)
               VALUES (?, 'system', '留言已长时间未回复，已自动归档。如需帮助可再次发起咨询。')''',
            (item['session_id'],),
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
    if not handoff_enabled():
        return 0
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
    settings = get_handoff_settings(conn)
    data['queue_position'] = position
    data['live_wait_sec'] = settings['live_wait_sec']
    data['est_wait_sec'] = None if position and not online else (position * settings['avg_handle_sec'] // max(1, online) if position else 0)
    data['unread_count'] = conn.execute(
        '''SELECT COUNT(*) AS cnt FROM handoff_messages
           WHERE session_id = ? AND sender_role = 'agent' AND id > ?''',
        (row['session_id'], row['user_last_read_message_id'] or 0),
    ).fetchone()['cnt']
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


def start_handoff(identity, history_ids=None, query_type='', note='', service_mode='auto'):
    settings = get_handoff_settings()
    if not settings['enabled']:
        raise HandoffError('在线营养咨询暂未开启', 403)
    note = str(note or '').strip()[:2000]
    if not note:
        raise HandoffError('请先填写要咨询的问题，再联系营养师')
    service_mode = str(service_mode or 'auto').strip()
    if service_mode not in {'auto', 'live', 'message'}:
        raise HandoffError('服务方式无效')
    rows, context = _context_from_history(identity['user_id'], history_ids or [])
    ai_agent_id = settings['ai_agent_id'] or (rows[-1].get('agent_id') if rows else '') or ''
    session_id = uuid.uuid4().hex
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        online_count = conn.execute(
            '''SELECT COUNT(*) AS cnt FROM cs_agents
               WHERE online = 1 AND last_seen_at >= datetime('now', ?)''',
            (f'-{Config.HANDOFF_AGENT_STALE_SEC} seconds',),
        ).fetchone()['cnt']
        resolved_mode = 'message' if service_mode == 'message' or not online_count else 'live'
        existing = conn.execute(
            f'''SELECT * FROM handoff_sessions
                WHERE user_id = ? AND status IN ({_open_status_sql()})
                ORDER BY id DESC LIMIT 1''',
            (identity['user_id'],),
        ).fetchone()
        if existing:
            if resolved_mode == 'message' and (existing['service_mode'] or 'live') != 'message':
                conn.execute(
                    '''UPDATE handoff_sessions SET service_mode = 'message',
                       live_deadline_at = NULL, message_converted_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                    (existing['id'],),
                )
                conn.execute(
                    '''INSERT INTO handoff_messages (session_id, sender_role, content)
                       VALUES (?, 'system', '营养师暂未在线，已直接转为留言。你可以继续使用 AI，营养师稍后回复。')''',
                    (existing['session_id'],),
                )
                existing = conn.execute('SELECT * FROM handoff_sessions WHERE id = ?', (existing['id'],)).fetchone()
            conn.commit()
            return _session_payload(conn, existing)
        cursor = conn.execute(
            '''INSERT INTO handoff_sessions
               (session_id, user_id, team_name, member_name, query_type, ai_agent_id, ai_context_json,
                service_mode, live_deadline_at, message_converted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                       CASE WHEN ? = 'live' THEN datetime('now', ?) ELSE NULL END,
                       CASE WHEN ? = 'message' THEN CURRENT_TIMESTAMP ELSE NULL END)''',
            (
                session_id, identity['user_id'], identity.get('team_name', ''), identity.get('member_name', ''),
                str(query_type or '')[:50], ai_agent_id, json.dumps(context, ensure_ascii=False),
                resolved_mode, resolved_mode, f"+{settings['live_wait_sec']} seconds", resolved_mode,
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
    if not handoff_enabled():
        return None
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
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM handoff_sessions WHERE session_id = ? AND user_id = ?', (session_id, user_id)).fetchone()
    payload = _session_payload(conn, row, include_context=include_context)
    conn.close()
    return payload


def append_user_message(user_id, session_id, content):
    _require_handoff_enabled()
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
    _require_handoff_enabled()
    return _close_session(session_id, user_id=user_id, reason=reason)


def defer_user_session(user_id, session_id):
    _require_handoff_enabled()
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
    """坐席上线/下线。白名单制：仅已在 cs_agents 名单中的账号可操作，
    不再自动注册坐席（注册入口为 add_cs_agent，由管理员在后台维护）。"""
    _require_handoff_enabled()
    online = 1 if online else 0
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user['user_id'],)).fetchone()
        if not row:
            conn.rollback()
            raise HandoffError('尚未开通客服坐席权限，请联系管理员在后台添加', 403)
        if max_concurrent is None:
            max_concurrent = row['max_concurrent']
        max_concurrent = max(1, min(int(max_concurrent), 10))
        conn.execute(
            '''UPDATE cs_agents
               SET online = ?, max_concurrent = ?, last_seen_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE user_id = ?''',
            (online, max_concurrent, user['user_id']),
        )
        _reconcile_locked(conn)
        agent = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user['user_id'],)).fetchone()
        conn.commit()
        return dict(agent)
    finally:
        conn.close()


def list_cs_agents():
    """坐席名单列表（后台管理用），附 users 表用户名。"""
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT a.user_id, a.display_name, a.online, a.max_concurrent, a.current_load,
                  a.last_seen_at, a.updated_at, u.username
           FROM cs_agents a LEFT JOIN users u ON u.user_id = a.user_id
           ORDER BY a.online DESC, a.updated_at DESC, a.user_id ASC'''
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_cs_agent(operator_id, username, display_name='', max_concurrent=3, password=None):
    """添加坐席。人工账号体系：
    - 用户名不存在 + 提供初始密码 → 创建非管理员人工账号（is_admin=0）并加入名单；
    - 用户名已存在 → 直接加入名单（不再要求必须是管理员）；
    - 用户名不存在且未提供密码 → 引导填写初始密码。"""
    from routes.auth import hash_password
    username = str(username or '').strip()
    if not username:
        raise HandoffError('请填写人工账号用户名')
    display_name = str(display_name or '').strip()[:40]
    max_concurrent = max(1, min(int(max_concurrent if max_concurrent is not None else 3), 10))
    user = get_user_by_username(username)
    if not user:
        password = str(password or '')
        if not password:
            raise HandoffError('该用户名不存在。如需新建人工账号，请填写初始密码', 404)
        if not 10 <= len(password) <= 128:
            raise HandoffError('初始密码长度必须为 10 到 128 个字符', 400)
        new_user_id = create_user(username, hash_password(password), is_admin=0)
        if not new_user_id:
            raise HandoffError('创建人工账号失败，请稍后重试', 500)
        user = get_user_by_username(username)
        if not user:
            raise HandoffError('创建人工账号失败，请稍后重试', 500)
    if not display_name:
        display_name = user.get('username') or username
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT user_id FROM cs_agents WHERE user_id = ?', (user['user_id'],)).fetchone()
        if existing:
            conn.rollback()
            raise HandoffError('该账号已在坐席名单中', 409)
        conn.execute(
            '''INSERT INTO cs_agents (user_id, display_name, online, max_concurrent, current_load)
               VALUES (?, ?, 0, ?, 0)''',
            (user['user_id'], display_name, max_concurrent),
        )
        row = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user['user_id'],)).fetchone()
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def update_cs_agent(user_id, display_name=None, max_concurrent=None):
    """更新坐席显示名/并发上限（不影响在线状态）。"""
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone()
        if not row:
            conn.rollback()
            raise HandoffError('坐席不存在', 404)
        updates, params = [], []
        if display_name is not None:
            name = str(display_name).strip()[:40]
            if not name:
                raise HandoffError('显示名不能为空')
            updates.append('display_name = ?')
            params.append(name)
        if max_concurrent is not None:
            updates.append('max_concurrent = ?')
            params.append(max(1, min(int(max_concurrent), 10)))
        if updates:
            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(user_id)
            conn.execute(f"UPDATE cs_agents SET {', '.join(updates)} WHERE user_id = ?", params)
        row = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone()
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def remove_cs_agent(operator_id, user_id):
    """移除坐席。有进行中(active)会话时拒绝；已分配(assigned)会话释放回排队。"""
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone()
        if not row:
            conn.rollback()
            raise HandoffError('坐席不存在', 404)
        active_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM handoff_sessions WHERE agent_id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()['cnt']
        if active_count:
            conn.rollback()
            raise HandoffError('该坐席仍有进行中的会话，请先结束会话后再移除', 409)
        released = conn.execute(
            '''UPDATE handoff_sessions
               SET status = 'queued', agent_id = '', assigned_at = NULL, agent_claim_deadline = NULL,
                   updated_at = CURRENT_TIMESTAMP
               WHERE agent_id = ? AND status = 'assigned' ''',
            (user_id,),
        ).rowcount
        conn.execute('DELETE FROM cs_agents WHERE user_id = ?', (user_id,))
        _reconcile_locked(conn)
        conn.commit()
        return {'user_id': user_id, 'released_sessions': int(released or 0)}
    finally:
        conn.close()


def get_agent_me(user_id):
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


# ---------------------------------------------------------------------------
# 快捷话术库
# ---------------------------------------------------------------------------

def _quick_reply_validate(title, content):
    title = str(title or '').strip()
    content = str(content or '').strip()
    if not title:
        raise HandoffError('话术标题不能为空')
    if len(title) > 40:
        raise HandoffError('话术标题不能超过40字')
    if not content:
        raise HandoffError('话术内容不能为空')
    if len(content) > 1000:
        raise HandoffError('话术内容不能超过1000字')
    return title, content


def list_quick_replies(include_disabled=False):
    """快捷话术列表。坐席工作台默认只返回启用项；后台管理返回全部。"""
    conn = get_db_connection()
    sql = '''SELECT id, title, content, sort_order, enabled, created_by, created_at, updated_at
             FROM handoff_quick_replies'''
    if not include_disabled:
        sql += " WHERE enabled = 1"
    sql += ' ORDER BY sort_order ASC, id DESC'
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def create_quick_reply(operator_id, title, content, sort_order=0, enabled=True):
    title, content = _quick_reply_validate(title, content)
    try:
        sort_order = int(sort_order or 0)
    except (TypeError, ValueError):
        sort_order = 0
    enabled = 1 if enabled else 0
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            '''INSERT INTO handoff_quick_replies (title, content, sort_order, enabled, created_by)
               VALUES (?, ?, ?, ?, ?)''',
            (title, content, sort_order, enabled, str(operator_id or '')),
        )
        row = conn.execute('SELECT * FROM handoff_quick_replies WHERE id = ?', (cursor.lastrowid,)).fetchone()
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def update_quick_reply(operator_id, reply_id, title=None, content=None, sort_order=None, enabled=None):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM handoff_quick_replies WHERE id = ?', (reply_id,)).fetchone()
        if not row:
            conn.rollback()
            raise HandoffError('话术不存在', 404)
        updates, params = [], []
        if title is not None or content is not None:
            new_title, new_content = _quick_reply_validate(
                title if title is not None else row['title'],
                content if content is not None else row['content'],
            )
            updates.append('title = ?')
            params.append(new_title)
            updates.append('content = ?')
            params.append(new_content)
        if sort_order is not None:
            try:
                updates.append('sort_order = ?')
                params.append(int(sort_order or 0))
            except (TypeError, ValueError):
                raise HandoffError('排序值必须是整数', 400)
        if enabled is not None:
            updates.append('enabled = ?')
            params.append(1 if enabled else 0)
        if updates:
            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(reply_id)
            conn.execute(f"UPDATE handoff_quick_replies SET {', '.join(updates)} WHERE id = ?", params)
        row = conn.execute('SELECT * FROM handoff_quick_replies WHERE id = ?', (reply_id,)).fetchone()
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def delete_quick_reply(operator_id, reply_id):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id FROM handoff_quick_replies WHERE id = ?', (reply_id,)).fetchone()
        if not row:
            conn.rollback()
            raise HandoffError('话术不存在', 404)
        conn.execute('DELETE FROM handoff_quick_replies WHERE id = ?', (reply_id,))
        conn.commit()
        return {'id': reply_id}
    finally:
        conn.close()



def list_agent_queue(user_id):
    conn = get_db_connection()
    agent = conn.execute('SELECT * FROM cs_agents WHERE user_id = ?', (user_id,)).fetchone()
    if not agent:
        conn.close()
        raise HandoffError('当前管理员尚未开通客服坐席', 403)
    rows = conn.execute(
        '''SELECT s.*,
             COALESCE((SELECT content FROM handoff_messages m
                       WHERE m.session_id = s.session_id AND m.sender_role IN ('user', 'agent')
                       ORDER BY m.id DESC LIMIT 1), '') AS last_message,
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
    _require_handoff_enabled()
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
        handoff_settings = get_handoff_settings(conn)
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
    _require_handoff_enabled()
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
        # 留言多轮：留言会话首次回复后不再自动关闭，保持 active 供双方继续一来一回，
        # 由 _reconcile_locked 在超过 HANDOFF_MESSAGE_IDLE_SEC 无新消息时自动归档。
        conn.execute(
            '''UPDATE handoff_sessions SET last_message_at = CURRENT_TIMESTAMP,
               agent_last_read_message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
            (cursor.lastrowid, row['id']),
        )
        message = conn.execute('SELECT * FROM handoff_messages WHERE id = ?', (cursor.lastrowid,)).fetchone()
        conn.commit()
        data = dict(message)
        data['auto_closed'] = False
        return data
    except HandoffError:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_agent_read(user_id, session_id, message_id):
    try:
        message_id = max(0, int(message_id or 0))
    except (TypeError, ValueError):
        raise HandoffError('message_id 必须是整数', 400)
    conn = get_db_connection()
    cursor = conn.execute(
        '''UPDATE handoff_sessions SET agent_last_read_message_id = MAX(agent_last_read_message_id, ?)
           WHERE session_id = ? AND agent_id = ?''',
        (message_id, session_id, user_id),
    )
    conn.commit()
    conn.close()
    if cursor.rowcount != 1:
        raise HandoffError('会话不存在或无权操作', 404)
    return True


def close_agent_session(user_id, session_id, reason='agent_close'):
    _require_handoff_enabled()
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
