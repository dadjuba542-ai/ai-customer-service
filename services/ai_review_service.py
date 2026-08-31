import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from models import get_db_connection


SHANGHAI = ZoneInfo('Asia/Shanghai')


class AiReviewError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _parse_date(value, label):
    try:
        return date.fromisoformat(str(value or ''))
    except ValueError as exc:
        raise AiReviewError(f'{label}格式应为 YYYY-MM-DD') from exc


def _utc_sql(local_date):
    local_dt = datetime.combine(local_date, time.min, SHANGHAI)
    return local_dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _period_bounds(params):
    period = str(params.get('period') or 'all').strip()
    allowed = {'all', 'this_week', 'last_week', 'week', 'day', 'range'}
    if period not in allowed:
        raise AiReviewError('不支持的日期筛选方式')

    field_map = {
        'week': {'week_start'},
        'day': {'date'},
        'range': {'from_date', 'to_date'},
    }
    date_fields = {'week_start', 'date', 'from_date', 'to_date'}
    supplied = {field for field in date_fields if str(params.get(field) or '').strip()}
    expected = field_map.get(period, set())
    if supplied != expected:
        if supplied or expected:
            raise AiReviewError('日期筛选参数不完整或相互冲突')

    today = datetime.now(SHANGHAI).date()
    if period == 'all':
        return None, None, '近30天全部'
    if period == 'this_week':
        start = today - timedelta(days=today.weekday())
        return _utc_sql(start), None, f'{start.isoformat()} 至 {today.isoformat()}'
    if period == 'last_week':
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
        return _utc_sql(start), _utc_sql(end), f'{start.isoformat()} 至 {(end - timedelta(days=1)).isoformat()}'
    if period == 'week':
        start = _parse_date(params.get('week_start'), '周开始日期')
        if start.weekday() != 0:
            raise AiReviewError('week_start 必须是周一')
        end = start + timedelta(days=7)
        return _utc_sql(start), _utc_sql(end), f'{start.isoformat()} 至 {(end - timedelta(days=1)).isoformat()}'
    if period == 'day':
        start = _parse_date(params.get('date'), '指定日期')
        end = start + timedelta(days=1)
        return _utc_sql(start), _utc_sql(end), start.isoformat()

    start = _parse_date(params.get('from_date'), '开始日期')
    inclusive_end = _parse_date(params.get('to_date'), '结束日期')
    if start > inclusive_end:
        raise AiReviewError('开始日期不能晚于结束日期')
    return _utc_sql(start), _utc_sql(inclusive_end + timedelta(days=1)), f'{start.isoformat()} 至 {inclusive_end.isoformat()}'


def _public_note(row, prefix='note_'):
    note_id = row[f'{prefix}id'] if f'{prefix}id' in row.keys() else None
    if not note_id or row[f'{prefix}status'] != 'published':
        return None
    return {
        'id': note_id,
        'content': row[f'{prefix}content'],
        'revision': row[f'{prefix}revision'],
        'published_at': row[f'{prefix}published_at'],
        'updated_at': row[f'{prefix}updated_at'],
        'unread': row[f'{prefix}revision'] > row[f'{prefix}user_read_revision'],
    }


def enrich_history_records(records):
    ids = [int(item['id']) for item in records if item.get('id')]
    if not ids:
        return records
    conn = get_db_connection()
    placeholders = ','.join('?' for _ in ids)
    rows = conn.execute(
        f'''SELECT id, history_id, content, status, revision, user_read_revision,
                   published_at, updated_at
            FROM nutritionist_review_notes WHERE history_id IN ({placeholders})''',
        ids,
    ).fetchall()
    conn.close()
    notes = {}
    for row in rows:
        data = {
            'note_id': row['id'], 'note_content': row['content'], 'note_status': row['status'],
            'note_revision': row['revision'], 'note_user_read_revision': row['user_read_revision'],
            'note_published_at': row['published_at'], 'note_updated_at': row['updated_at'],
        }
        notes[row['history_id']] = _public_note(data)
    for item in records:
        item['nutritionist_note'] = notes.get(item.get('id'))
    return records


def list_ai_reviews(params):
    try:
        page = max(1, int(params.get('page') or 1))
        limit = min(100, max(1, int(params.get('limit') or 20)))
    except (TypeError, ValueError) as exc:
        raise AiReviewError('分页参数无效') from exc
    start_at, end_at, period_label = _period_bounds(params)
    where = ["h.bot_response IS NOT NULL", "TRIM(h.bot_response) != ''", "h.created_at >= datetime('now', '-30 days')"]
    values = []
    if start_at:
        where.append('h.created_at >= ?')
        values.append(start_at)
    if end_at:
        where.append('h.created_at < ?')
        values.append(end_at)
    keyword = str(params.get('keyword') or '').strip()
    if keyword:
        escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        where.append("(h.user_message LIKE ? ESCAPE '\\' OR h.bot_response LIKE ? ESCAPE '\\' OR h.member_name LIKE ? ESCAPE '\\' OR h.team_name LIKE ? ESCAPE '\\')")
        values.extend([f'%{escaped}%'] * 4)
    query_type = str(params.get('query_type') or '').strip()
    if query_type:
        where.append('h.query_type = ?')
        values.append(query_type)
    feedback = str(params.get('feedback') or 'all').strip()
    feedback_clauses = {'all': None, 'positive': 'h.feedback = 1', 'negative': 'h.feedback = 0', 'unrated': 'h.feedback IS NULL'}
    if feedback not in feedback_clauses:
        raise AiReviewError('反馈筛选无效')
    if feedback_clauses[feedback]:
        where.append(feedback_clauses[feedback])
    note_status = str(params.get('note_status') or 'all').strip()
    if note_status not in {'all', 'noted', 'unnoted'}:
        raise AiReviewError('留言状态筛选无效')
    if note_status == 'noted':
        where.append("n.status = 'published'")
    elif note_status == 'unnoted':
        where.append("(n.id IS NULL OR n.status != 'published')")

    where_sql = ' AND '.join(where)
    conn = get_db_connection()
    total = conn.execute(
        f'''SELECT COUNT(*) AS total FROM chat_history h
            LEFT JOIN nutritionist_review_notes n ON n.history_id = h.id
            WHERE {where_sql}''', values,
    ).fetchone()['total']
    rows = conn.execute(
        f'''SELECT h.id, h.user_id, h.user_message, h.bot_response, h.query_type,
                   h.agent_id, h.team_name, h.member_name, h.feedback, h.feedback_reason, h.created_at,
                   n.id AS note_id, n.content AS note_content, n.status AS note_status,
                   n.revision AS note_revision, n.user_read_revision AS note_user_read_revision,
                   n.created_by AS note_created_by, n.updated_by AS note_updated_by,
                   n.published_at AS note_published_at, n.withdrawn_at AS note_withdrawn_at,
                   n.updated_at AS note_updated_at
            FROM chat_history h LEFT JOIN nutritionist_review_notes n ON n.history_id = h.id
            WHERE {where_sql} ORDER BY h.created_at DESC, h.id DESC LIMIT ? OFFSET ?''',
        values + [limit, (page - 1) * limit],
    ).fetchall()
    types = [row['query_type'] for row in conn.execute(
        "SELECT DISTINCT query_type FROM chat_history WHERE bot_response IS NOT NULL AND TRIM(bot_response) != '' ORDER BY query_type"
    ).fetchall()]
    conn.close()
    items = []
    for row in rows:
        item = {key: row[key] for key in (
            'id', 'user_id', 'user_message', 'bot_response', 'query_type', 'agent_id',
            'team_name', 'member_name', 'feedback', 'feedback_reason', 'created_at')}
        item['nutritionist_note'] = _public_note(row)
        if row['note_id']:
            item['note_revision'] = row['note_revision']
            item['note_status'] = row['note_status']
        items.append(item)
    pages = max(1, math.ceil(total / limit))
    return {'items': items, 'pagination': {'page': page, 'limit': limit, 'total': total, 'pages': pages}, 'period_label': period_label, 'query_types': types}


def upsert_review_note(history_id, agent_id, content, expected_revision):
    content = str(content or '').strip()
    if not content:
        raise AiReviewError('留言内容不能为空')
    if len(content) > 4000:
        raise AiReviewError('留言内容不能超过4000字')
    try:
        expected_revision = int(expected_revision or 0)
    except (TypeError, ValueError) as exc:
        raise AiReviewError('修订号无效') from exc
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        history = conn.execute('SELECT id, user_id FROM chat_history WHERE id = ?', (history_id,)).fetchone()
        if not history:
            raise AiReviewError('AI问答不存在或已被清理', 404)
        current = conn.execute('SELECT * FROM nutritionist_review_notes WHERE history_id = ?', (history_id,)).fetchone()
        if current and current['revision'] != expected_revision:
            raise AiReviewError('留言已被其他营养师更新，请刷新后重试', 409)
        if not current and expected_revision != 0:
            raise AiReviewError('留言状态已变化，请刷新后重试', 409)
        if current:
            revision = current['revision'] + 1
            conn.execute(
                '''UPDATE nutritionist_review_notes SET content = ?, status = 'published', revision = ?,
                   updated_by = ?, published_at = CURRENT_TIMESTAMP, withdrawn_at = NULL,
                   updated_at = CURRENT_TIMESTAMP WHERE history_id = ?''',
                (content, revision, agent_id, history_id),
            )
        else:
            revision = 1
            conn.execute(
                '''INSERT INTO nutritionist_review_notes
                   (history_id, user_id, content, revision, created_by, updated_by)
                   VALUES (?, ?, ?, 1, ?, ?)''',
                (history_id, history['user_id'], content, agent_id, agent_id),
            )
        row = conn.execute('SELECT * FROM nutritionist_review_notes WHERE history_id = ?', (history_id,)).fetchone()
        conn.commit()
        result = dict(row)
        result.pop('created_by', None); result.pop('updated_by', None); result.pop('user_id', None)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def withdraw_review_note(history_id, agent_id, expected_revision):
    try:
        expected_revision = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise AiReviewError('修订号无效') from exc
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM nutritionist_review_notes WHERE history_id = ?', (history_id,)).fetchone()
        if not row:
            raise AiReviewError('留言不存在', 404)
        if row['revision'] != expected_revision:
            raise AiReviewError('留言已被其他营养师更新，请刷新后重试', 409)
        revision = row['revision'] + 1
        conn.execute(
            '''UPDATE nutritionist_review_notes SET status = 'withdrawn', revision = ?,
               user_read_revision = ?, updated_by = ?, withdrawn_at = CURRENT_TIMESTAMP,
               updated_at = CURRENT_TIMESTAMP WHERE history_id = ?''',
            (revision, revision, agent_id, history_id),
        )
        conn.commit()
        return {'history_id': history_id, 'status': 'withdrawn', 'revision': revision}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_unread_notes(user_id, limit=20):
    try:
        limit = min(50, max(1, int(limit or 20)))
    except (TypeError, ValueError) as exc:
        raise AiReviewError('limit 无效') from exc
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT n.id, n.history_id, n.content, n.revision, n.published_at, n.updated_at,
                  h.user_message, h.bot_response, h.query_type, h.created_at
           FROM nutritionist_review_notes n JOIN chat_history h ON h.id = n.history_id
           WHERE n.user_id = ? AND n.status = 'published' AND n.revision > n.user_read_revision
           ORDER BY n.updated_at DESC LIMIT ?''',
        (user_id, limit),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) AS total FROM nutritionist_review_notes WHERE user_id = ? AND status = 'published' AND revision > user_read_revision",
        (user_id,),
    ).fetchone()['total']
    conn.close()
    return {'items': [dict(row) for row in rows], 'total': total}


def mark_note_read(user_id, note_id):
    conn = get_db_connection()
    cursor = conn.execute(
        '''UPDATE nutritionist_review_notes SET user_read_revision = revision
           WHERE id = ? AND user_id = ? AND status = 'published' ''',
        (note_id, user_id),
    )
    conn.commit(); conn.close()
    if cursor.rowcount <= 0:
        raise AiReviewError('留言不存在', 404)
    return True
