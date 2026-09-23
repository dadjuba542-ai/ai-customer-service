"""MCP（Model Context Protocol）只读工具层。

被两种传输复用：
- 本地开发：`scripts/mcp_server.py`（stdio）
- 线上：`routes/mcp.py`（Streamable HTTP，Bearer token 鉴权）

只读原则：这里不注册任何写库工具。敏感字段（留资联系方式）默认脱敏，
智能体的 `prompt` / `bot_id` 不返回。
"""

import json
from datetime import datetime, timedelta

from models import (
    get_all_agent_configs,
    get_case_document_by_id,
    get_db_connection,
    get_news_by_id,
    get_news_page,
    search_case_documents_page,
)

PROTOCOL_VERSION = '2024-11-05'
SERVER_INFO = {'name': 'ai-customer-service', 'version': '0.1.0'}
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


def _to_text(payload):
    return _truncate(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


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
