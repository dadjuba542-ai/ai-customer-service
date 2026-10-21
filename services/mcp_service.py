"""MCP（Model Context Protocol）只读工具层。

被两种传输复用：
- 本地开发：`scripts/mcp_server.py`（stdio）
- 线上：`routes/mcp.py`（Streamable HTTP，Bearer token 鉴权）

只读原则：这里不注册任何写库工具。敏感字段（留资联系方式）默认脱敏，
智能体的 `prompt` / `bot_id` 不返回。
"""

import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from config import Config
from models import (
    get_all_agent_configs,
    get_case_document_by_id,
    get_db_connection,
    get_news_by_id,
    get_news_page,
    search_case_documents_page,
)

PROTOCOL_VERSION = '2024-11-05'
SERVER_INFO = {'name': 'ai-customer-service', 'version': Config.APP_VERSION}
PROCESS_STARTED_AT = time.monotonic()
PROCESS_STARTED_UTC = datetime.utcnow()
MAX_FIELD_CHARS = 4000
MAX_ROWS = 50


# ============================================================
# 参数处理 / 脱敏
# ============================================================

def _since(days, default=7):
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = default
    days = max(1, min(days, 365))
    return (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')


def _int_arg(args, key, default, low=1, high=MAX_ROWS):
    try:
        value = int((args or {}).get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _truncate(value, limit=MAX_FIELD_CHARS):
    if value is None:
        return ''
    text = value if isinstance(value, str) else str(value)
    if len(text) > limit:
        return text[:limit] + '\n…（已截断，共 %d 字符）' % len(text)
    return text


def mask_phone(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if len(text) <= 4:
        return '*' * len(text)
    if len(text) <= 7:
        return text[:2] + '***'
    return text[:3] + '****' + text[-2:]


def mask_wechat(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if len(text) <= 2:
        return '*' * len(text)
    return text[0] + '***' + text[-1]


def _columns(conn, table):
    try:
        rows = conn.execute('PRAGMA table_info(%s)' % table).fetchall()
    except Exception:
        return set()
    return {row['name'] for row in rows}


def _to_text(payload, limit=MAX_FIELD_CHARS):
    return _truncate(json.dumps(payload, ensure_ascii=False, indent=2, default=str), limit)


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return bool(row)


def _safe_url(url):
    parts = urlsplit(url or '')
    host = parts.hostname or ''
    if ':' in host:
        host = '[%s]' % host
    if parts.port:
        host += ':%s' % parts.port
    return '%s://%s%s' % (parts.scheme, host, parts.path)


def _secret_configured(key, env_value):
    try:
        from services.secret_service import get_secret_setting
        return bool((get_secret_setting(key, env_value) or '').strip())
    except Exception:
        return bool((env_value or '').strip())


# ============================================================
# 工具实现（全部只读）
# ============================================================

def tool_chat_stats(args):
    days = _int_arg(args, 'days', 7, low=1, high=365)
    since = _since(days, 7)
    conn = get_db_connection()
    cols = _columns(conn, 'chat_history')
    total = conn.execute(
        'SELECT COUNT(*) AS c FROM chat_history WHERE created_at >= ?', (since,)
    ).fetchone()['c']
    users = conn.execute(
        'SELECT COUNT(DISTINCT user_id) AS c FROM chat_history WHERE created_at >= ?', (since,)
    ).fetchone()['c']
    by_type = [dict(r) for r in conn.execute(
        '''SELECT query_type, COUNT(*) AS cnt FROM chat_history
           WHERE created_at >= ? GROUP BY query_type ORDER BY cnt DESC''', (since,)
    ).fetchall()]
    by_agent = []
    if 'agent_id' in cols:
        by_agent = [dict(r) for r in conn.execute(
            '''SELECT agent_id, COUNT(*) AS cnt FROM chat_history
               WHERE created_at >= ? AND agent_id != '' GROUP BY agent_id ORDER BY cnt DESC''',
            (since,)
        ).fetchall()]
    feedback = dict(conn.execute(
        '''SELECT
             SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS likes,
             SUM(CASE WHEN feedback = 0 THEN 1 ELSE 0 END) AS dislikes
           FROM chat_history WHERE created_at >= ?''', (since,)
    ).fetchone())
    conn.close()
    return _to_text({
        'window_days': days,
        'since_utc': since,
        'total_messages': total,
        'unique_users': users,
        'by_query_type': by_type,
        'by_agent_id': by_agent,
        'feedback': {
            'likes': feedback.get('likes') or 0,
            'dislikes': feedback.get('dislikes') or 0,
        },
    })


def tool_search_chat_history(args):
    keyword = ((args or {}).get('keyword') or '').strip()
    if not keyword:
        raise ValueError('keyword 不能为空')
    days = _int_arg(args, 'days', 30, low=1, high=365)
    limit = _int_arg(args, 'limit', 20)
    like = '%' + keyword + '%'
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT id, query_type, user_message, bot_response, feedback, created_at
           FROM chat_history
           WHERE created_at >= ? AND (user_message LIKE ? OR bot_response LIKE ?)
           ORDER BY created_at DESC LIMIT ?''',
        (_since(days, 30), like, like, limit)
    ).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item['user_message'] = _truncate(item.get('user_message'), 500)
        item['bot_response'] = _truncate(item.get('bot_response'), 1500)
        items.append(item)
    return _to_text({'keyword': keyword, 'window_days': days, 'count': len(items), 'items': items})


def tool_recent_bad_feedback(args):
    days = _int_arg(args, 'days', 30, low=1, high=365)
    limit = _int_arg(args, 'limit', 20)
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT id, query_type, user_message, bot_response, feedback_reason, created_at
           FROM chat_history
           WHERE feedback = 0 AND created_at >= ?
           ORDER BY created_at DESC LIMIT ?''',
        (_since(days, 30), limit)
    ).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item['user_message'] = _truncate(item.get('user_message'), 500)
        item['bot_response'] = _truncate(item.get('bot_response'), 1200)
        items.append(item)
    return _to_text({'window_days': days, 'count': len(items), 'items': items})


_QUESTION_STRIP_CHARS = '。！？!?，,、；;：:.·"\'“”‘’()（）[]【】<>《》'


def _normalize_question(text):
    """轻量归一化：去掉全部空白与首尾标点，尽量把近义/错标点的同问合并。"""
    text = re.sub(r'\s+', '', text or '')
    return text.strip(_QUESTION_STRIP_CHARS)


def tool_top_user_questions(args):
    days = _int_arg(args, 'days', 30, low=1, high=365)
    limit = _int_arg(args, 'limit', 20)
    window = args.get('min_count') if isinstance(args, dict) else None
    try:
        min_count = max(1, int(window)) if window else 1
    except (TypeError, ValueError):
        min_count = 1
    since = _since(days, 30)
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT user_message, created_at FROM chat_history
           WHERE created_at >= ? AND TRIM(user_message) != \'\'''',
        (since,)
    ).fetchall()
    total = conn.execute(
        'SELECT COUNT(*) AS c FROM chat_history WHERE created_at >= ?', (since,)
    ).fetchone()['c']
    conn.close()

    groups = {}
    for row in rows:
        key = _normalize_question(row['user_message'])
        if not key:
            continue
        group = groups.setdefault(key, {'count': 0, 'last': '', 'sample': row['user_message']})
        group['count'] += 1
        if row['created_at'] >= group['last']:
            group['last'] = row['created_at']
            group['sample'] = row['user_message']
    ordered = sorted(groups.values(), key=lambda g: (g['count'], g['last']), reverse=True)
    items = [{
        'question': _truncate(g['sample'], 200),
        'count': g['count'],
        'last_asked_at': g['last'],
    } for g in ordered if g['count'] >= min_count][:limit]
    return _to_text({
        'window_days': days,
        'since_utc': since,
        'total_messages': total,
        'distinct_questions': len(groups),
        'count': len(items),
        'note': '已做轻量归一化（去空白/首尾标点）；明显近义但用词不同的提问仍分开计',
        'items': items,
    })


def tool_list_leads(args):
    status = ((args or {}).get('status') or '').strip()
    limit = _int_arg(args, 'limit', 20)
    conn = get_db_connection()
    where, params = '', []
    if status:
        where = 'WHERE status = ?'
        params.append(status)
    try:
        rows = conn.execute(
            '''SELECT id, customer_type, product_name, description, phone, wechat,
                      query_type, agent_id, status, admin_note, created_at
               FROM lead_requests%s ORDER BY created_at DESC LIMIT ?''' % where,
            params + [limit]
        ).fetchall()
    except Exception as exc:
        conn.close()
        return _to_text({'error': '读取 lead_requests 失败：%s' % exc})
    conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item['phone'] = mask_phone(item.get('phone'))
        item['wechat'] = mask_wechat(item.get('wechat'))
        item['description'] = _truncate(item.get('description'), 800)
        items.append(item)
    return _to_text({
        'status': status or 'all',
        'count': len(items),
        'contact_masked': True,
        'items': items,
    })


def tool_search_products(args):
    keyword = ((args or {}).get('keyword') or '').strip()
    limit = _int_arg(args, 'limit', 20)
    conn = get_db_connection()
    params = []
    where = ''
    if keyword:
        like = '%' + keyword + '%'
        where = 'WHERE (name LIKE ? OR summary LIKE ? OR highlights LIKE ? OR content LIKE ?)'
        params = [like, like, like, like]
    rows = conn.execute(
        '''SELECT id, category, name, summary, highlights
           FROM products %s ORDER BY sort_order ASC, id DESC LIMIT ?''' % where,
        params + [limit]
    ).fetchall()
    conn.close()
    return _to_text({'keyword': keyword, 'count': len(rows), 'items': [dict(r) for r in rows]})


def tool_get_product(args):
    product_id = _int_arg(args, 'product_id', 0, low=1, high=10 ** 9)
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    conn.close()
    if not row:
        return _to_text({'error': '未找到产品 id=%s' % product_id})
    item = dict(row)
    item['content'] = _truncate(item.get('content'))
    return _to_text({'product': item, 'note': 'content 为富文本内容' if item.get('content') else ''})


def tool_search_cases(args):
    query = ((args or {}).get('query') or '').strip()
    if not query:
        raise ValueError('query 不能为空')
    limit = _int_arg(args, 'limit', 10)
    result = search_case_documents_page(query, page=1, limit=limit)
    items = []
    for item in result.get('items', []):
        items.append({
            'id': item.get('id'),
            'title': item.get('title'),
            'summary': _truncate(item.get('summary'), 600),
            'customer_profile': item.get('customer_profile'),
            'symptom_tags': item.get('symptom_tags'),
            'product_tags': item.get('product_tags'),
            'scenario': item.get('scenario'),
        })
    return _to_text({'query': query, 'total': result.get('total'), 'items': items})


def tool_get_case(args):
    case_id = _int_arg(args, 'case_id', 0, low=1, high=10 ** 9)
    item = get_case_document_by_id(case_id, public_only=False)
    if not item:
        return _to_text({'error': '未找到案例 id=%s' % case_id})
    item = dict(item)
    item['content'] = _truncate(item.get('content'))
    return _to_text({'case': item})


def tool_list_news(args):
    limit = _int_arg(args, 'limit', 20)
    result = get_news_page(page=1, limit=limit)
    return _to_text({'total': result.get('total'), 'items': result.get('items', [])})


def tool_get_news(args):
    news_id = _int_arg(args, 'news_id', 0, low=1, high=10 ** 9)
    item = get_news_by_id(news_id)
    if not item:
        return _to_text({'error': '未找到资讯 id=%s' % news_id})
    item = dict(item)
    item['content'] = _truncate(item.get('content'))
    return _to_text({'news': item, 'note': 'content 为富文本内容'})


def tool_list_agents(args):
    agents = get_all_agent_configs()
    items = [{
        'agent_id': a.get('agent_id'),
        'name': a.get('name'),
        'type': a.get('type'),
        'description': a.get('description'),
        'chat_desc': a.get('chat_desc'),
        'icon': a.get('icon'),
        'has_bot_id': bool((a.get('bot_id') or '').strip()),
    } for a in agents]
    return _to_text({'count': len(items), 'items': items, 'note': 'prompt 与 bot_id 出于安全未返回'})


def tool_recent_chat_failures(args):
    days = _int_arg(args, 'days', 7, low=1, high=365)
    limit = _int_arg(args, 'limit', 20)
    agent_id = ((args or {}).get('agent_id') or '').strip()[:64]
    error_category = ((args or {}).get('error_category') or '').strip()[:40]
    since = _since(days, 7)

    conn = get_db_connection()
    try:
        if not _table_exists(conn, 'chat_request_log'):
            return _to_text({
                'window_days': days,
                'count': 0,
                'items': [],
                'note': 'chat_request_log 尚未创建，部署后产生的新请求才会记录',
            })
        where = ["created_at >= ?", "outcome != 'success'"]
        params = [since]
        if agent_id:
            where.append('agent_id = ?')
            params.append(agent_id)
        if error_category:
            where.append('error_category = ?')
            params.append(error_category)
        where_sql = ' AND '.join(where)
        rows = conn.execute(
            '''SELECT id, request_id, endpoint, agent_id, query_type, channel, outcome,
                      error_category, error_code, http_status, retryable, duration_ms,
                      first_token_ms, upstream_event_count, conversation_id, chat_id,
                      history_id, user_ref, message_fingerprint, message_length,
                      started_at, created_at
               FROM chat_request_log
               WHERE %s
               ORDER BY created_at DESC, id DESC LIMIT ?''' % where_sql,
            params + [limit],
        ).fetchall()
        summary = [dict(row) for row in conn.execute(
            '''SELECT outcome, error_category, COUNT(*) AS cnt
               FROM chat_request_log
               WHERE %s
               GROUP BY outcome, error_category
               ORDER BY cnt DESC''' % where_sql,
            params,
        ).fetchall()]
    finally:
        conn.close()

    items = [dict(row) for row in rows]
    return _to_text({
        'window_days': days,
        'since_utc': since,
        'count': len(items),
        'summary': summary,
        'items': items,
        'note': '仅含请求元信息，不保存问题正文；message_fingerprint 可用于关联同一提问',
    }, 12000)


def tool_chat_request_detail(args):
    request_id = ((args or {}).get('request_id') or '').strip()[:64]
    if not request_id:
        raise ValueError('request_id 不能为空')
    limit = _int_arg(args, 'limit', 20)
    conn = get_db_connection()
    try:
        if not _table_exists(conn, 'chat_request_log'):
            return _to_text({'request_id': request_id, 'count': 0, 'items': [],
                             'note': 'chat_request_log 尚未创建'})
        rows = conn.execute(
            '''SELECT id, request_id, endpoint, agent_id, query_type, channel, outcome,
                      error_category, error_code, http_status, retryable, duration_ms,
                      first_token_ms, upstream_event_count, conversation_id, chat_id,
                      history_id, user_ref, message_fingerprint, message_length,
                      started_at, created_at
               FROM chat_request_log
               WHERE request_id = ?
               ORDER BY id ASC LIMIT ?''',
            (request_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return _to_text({
        'request_id': request_id,
        'count': len(rows),
        'items': [dict(row) for row in rows],
        'note': '同一 request_id 可能有多条记录（流式失败后回退同步、重试或排队）',
    }, 12000)


def tool_server_health(args):
    coze_url = Config.COZE_V3_CHAT_URL if Config.COZE_CHAT_API_VERSION == 'v3' else Config.COZE_API_URL
    health = {
        'server_time_utc': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'started_at_utc': PROCESS_STARTED_UTC.strftime('%Y-%m-%d %H:%M:%S'),
        'process_uptime_seconds': int(time.monotonic() - PROCESS_STARTED_AT),
        'app_version': Config.APP_VERSION,
        'coze': {
            'api_version': Config.COZE_CHAT_API_VERSION,
            'api_url': _safe_url(coze_url),
            'api_key_configured': _secret_configured('coze_api_key', Config.COZE_API_KEY),
            'diagnostics_enabled': Config.COZE_DIAGNOSTICS_ENABLED,
            'context_rounds': Config.CHAT_CONTEXT_ROUNDS,
        },
        'mcp': {
            'token_configured': _secret_configured('mcp_token', Config.MCP_TOKEN),
        },
    }
    conn = None
    try:
        conn = get_db_connection()
        conn.execute('SELECT 1').fetchone()
        counts = {}
        for table in ('chat_history', 'chat_request_log', 'chat_jobs', 'settings', 'agent_configs'):
            if _table_exists(conn, table):
                counts[table] = conn.execute('SELECT COUNT(*) AS c FROM %s' % table).fetchone()['c']
        queue = {}
        if _table_exists(conn, 'chat_jobs'):
            queue = {row['status']: row['c'] for row in conn.execute(
                "SELECT status, COUNT(*) AS c FROM chat_jobs WHERE status IN ('queued', 'running') GROUP BY status"
            ).fetchall()}
        latest_migration = None
        if _table_exists(conn, 'schema_migrations'):
            row = conn.execute(
                'SELECT version, name, applied_at FROM schema_migrations ORDER BY applied_at DESC, version DESC LIMIT 1'
            ).fetchone()
            latest_migration = dict(row) if row else None
        recent_failures = None
        if _table_exists(conn, 'chat_request_log'):
            recent_failures = conn.execute(
                '''SELECT COUNT(*) AS c FROM chat_request_log
                   WHERE outcome != 'success' AND created_at >= datetime('now', '-1 day')'''
            ).fetchone()['c']
        health['database'] = {
            'ok': True,
            'table_counts': counts,
            'queue': queue,
            'latest_migration': latest_migration,
            'recent_failures_24h': recent_failures,
            'request_log_available': _table_exists(conn, 'chat_request_log'),
        }
    except Exception as exc:
        health['database'] = {'ok': False, 'error': exc.__class__.__name__}
    finally:
        if conn is not None:
            conn.close()
    return _to_text(health)


TOOLS = [
    {
        'name': 'chat_stats',
        'description': '统计最近 N 天客服问答量、独立用户数、各咨询类型/智能体分布与点赞点踩数。',
        'inputSchema': {
            'type': 'object',
            'properties': {'days': {'type': 'integer', 'description': '统计窗口（天），默认 7'}},
        },
        'handler': tool_chat_stats,
    },
    {
        'name': 'search_chat_history',
        'description': '按关键词搜索历史问答记录（匹配用户提问或 AI 回答），用于了解真实客户诉求与回答质量。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'keyword': {'type': 'string', 'description': '必填，关键词'},
                'days': {'type': 'integer', 'description': '窗口（天），默认 30'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 20，最大 50'},
            },
            'required': ['keyword'],
        },
        'handler': tool_search_chat_history,
    },
    {
        'name': 'recent_bad_feedback',
        'description': '列出最近被用户点“踩”的回答及原因，用于客服质检和知识库纠错。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'description': '窗口（天），默认 30'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 20'},
            },
        },
        'handler': tool_recent_bad_feedback,
    },
    {
        'name': 'top_user_questions',
        'description': '统计最近 N 天用户提问频次排行榜（按提问原文分组计数），用于发现高频诉求与知识库缺口。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'description': '统计窗口（天），默认 30'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 20'},
                'min_count': {'type': 'integer', 'description': '只保留出现次数 ≥ 该值的提问，默认 1'},
            },
        },
        'handler': tool_top_user_questions,
    },
    {
        'name': 'list_leads',
        'description': '列出客户留资线索（联系方式已脱敏）。含敏感信息，仅限内部使用。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'status': {'type': 'string', 'description': 'pending / contacted / completed，留空为全部'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 20'},
            },
        },
        'handler': tool_list_leads,
    },
    {
        'name': 'search_products',
        'description': '按关键词搜索产品（名称/简介/卖点/正文），返回产品清单与卖点，供写文案前取素材。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'keyword': {'type': 'string', 'description': '关键词，留空返回全部'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 20'},
            },
        },
        'handler': tool_search_products,
    },
    {
        'name': 'get_product',
        'description': '获取单个产品完整详情（含富文本正文），用于写产品文案/朋友圈/口播。',
        'inputSchema': {
            'type': 'object',
            'properties': {'product_id': {'type': 'integer', 'description': '产品 id'}},
            'required': ['product_id'],
        },
        'handler': tool_get_product,
    },
    {
        'name': 'search_cases',
        'description': '按关键词搜索客户案例库，返回案例要点，供内容创作或回答引用。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': '必填，查询词'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 10'},
            },
            'required': ['query'],
        },
        'handler': tool_search_cases,
    },
    {
        'name': 'get_case',
        'description': '获取单个案例完整内容。',
        'inputSchema': {
            'type': 'object',
            'properties': {'case_id': {'type': 'integer', 'description': '案例 id'}},
            'required': ['case_id'],
        },
        'handler': tool_get_case,
    },
    {
        'name': 'list_news',
        'description': '列出资讯文章（标题/摘要/分类/浏览数），供选题参考。',
        'inputSchema': {
            'type': 'object',
            'properties': {'limit': {'type': 'integer', 'description': '返回条数，默认 20'}},
        },
        'handler': tool_list_news,
    },
    {
        'name': 'get_news',
        'description': '获取单篇资讯完整正文（含富文本）。',
        'inputSchema': {
            'type': 'object',
            'properties': {'news_id': {'type': 'integer', 'description': '资讯 id'}},
            'required': ['news_id'],
        },
        'handler': tool_get_news,
    },
    {
        'name': 'list_agents',
        'description': '列出已配置的智能体（名称/类型/描述），了解现有 AI 能力边界。',
        'inputSchema': {'type': 'object', 'properties': {}},
        'handler': tool_list_agents,
    },
    {
        'name': 'recent_chat_failures',
        'description': '查询最近失败的聊天请求（含超时/上游错误/中断），用于定位“为什么只有这一问报错”。不返回问题正文。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'description': '窗口（天），默认 7'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 20，最大 50'},
                'agent_id': {'type': 'string', 'description': '可选，按智能体过滤'},
                'error_category': {'type': 'string', 'description': '可选，如 network_error / timeout / upstream_error'},
            },
        },
        'handler': tool_recent_chat_failures,
    },
    {
        'name': 'chat_request_detail',
        'description': '按 request_id 查看一次聊天请求的完整诊断记录（含流式失败后的回退/重试）。不返回问题正文。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'request_id': {'type': 'string', 'description': '必填，请求 id'},
                'limit': {'type': 'integer', 'description': '返回条数，默认 20'},
            },
            'required': ['request_id'],
        },
        'handler': tool_chat_request_detail,
    },
    {
        'name': 'server_health',
        'description': '查看服务健康摘要：版本、运行时长、数据库表数量、队列、Coze/MCP 配置是否存在（不返回密钥）。',
        'inputSchema': {'type': 'object', 'properties': {}},
        'handler': tool_server_health,
    },
]

HANDLERS = {tool['name']: tool['handler'] for tool in TOOLS}

_SAFE_TOOL_FIELDS = ('name', 'description', 'inputSchema')


def list_tools():
    return [{key: tool[key] for key in _SAFE_TOOL_FIELDS} for tool in TOOLS]


def call_tool(name, arguments):
    handler = HANDLERS.get(name)
    if not handler:
        raise KeyError('未知工具：%s' % name)
    return handler(arguments or {})


# ============================================================
# JSON-RPC dispatch（返回响应 dict；通知返回 None）
# ============================================================

def _result(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def _handle_tools_call(request_id, params):
    name = params.get('name')
    try:
        text = call_tool(name, params.get('arguments'))
        return _result(request_id, {'content': [{'type': 'text', 'text': text}]})
    except KeyError:
        return _result(request_id, {
            'isError': True,
            'content': [{'type': 'text', 'text': '未知工具：%s' % name}],
        })
    except Exception as exc:  # 单个工具失败不影响会话
        return _result(request_id, {
            'isError': True,
            'content': [{'type': 'text', 'text': '工具 %s 执行失败：%s' % (name, exc)}],
        })


def dispatch(message):
    """处理单条 JSON-RPC 消息。通知（无 id）返回 None。"""
    if not isinstance(message, dict):
        return _error(None, -32600, 'Invalid Request')
    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params') or {}

    if method == 'initialize':
        client_version = params.get('protocolVersion') or PROTOCOL_VERSION
        return _result(request_id, {
            'protocolVersion': client_version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': SERVER_INFO,
        })
    if method in ('notifications/initialized', 'initialized'):
        return None
    if method == 'tools/list':
        return _result(request_id, {'tools': list_tools()})
    if method == 'tools/call':
        return _handle_tools_call(request_id, params)
    if method == 'ping':
        return _result(request_id, {})
    if method and method.startswith('notifications/'):
        return None
    if request_id is not None:
        return _error(request_id, -32601, 'Method not found: %s' % method)
    return None
