#!/usr/bin/env python3
"""部署环境对照：默认只读配置；--live 直接调用 V3，不创建本地问答记录。"""
import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config
from services.coze_diagnostics import CozeDiagnostics, safe_url
from services.secret_service import decrypt_secret

DEFAULT_QUESTION = '今天想发一个咖啡灌肠每日坚持的文案'


def deployment_config(agent_id, bot_override=None):
    """与网页一致：数据库 Bot/密钥优先；不导入 app，不建库或迁移。"""
    agent = None
    stored_key = ''
    db_state = 'missing'
    database = Path(Config.DATABASE_PATH).resolve()
    if database.is_file():
        conn = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute('SELECT bot_id, type FROM agent_configs WHERE agent_id = ?', (agent_id,)).fetchone()
            agent = dict(row) if row else None
            row = conn.execute("SELECT value FROM settings WHERE key = 'coze_api_key'").fetchone()
            stored_key = row['value'] if row else ''
            db_state = 'read_only'
        finally:
            conn.close()
    query_type = agent.get('type') if agent else ('朋友圈帮写' if agent_id == 'translator' else '其他')
    bot_id = bot_override or (agent or {}).get('bot_id') or Config.BOT_MAPPING.get(query_type, Config.DEFAULT_BOT_ID)
    bot_source = 'command_line' if bot_override else ('database' if (agent or {}).get('bot_id') else 'environment_or_default')
    api_key = Config.COZE_API_KEY
    key_source = 'environment' if api_key else 'missing'
    if stored_key:
        try:
            api_key = decrypt_secret(stored_key)
            key_source = 'database'
        except RuntimeError:
            # 与网页的 get_secret_setting 回退规则一致，仅报告来源，不输出密钥。
            key_source = 'environment_after_decryption_failure' if api_key else 'missing_after_decryption_failure'
    summary = {
        'mode': 'config_only', 'configured_chat_api_version': Config.COZE_CHAT_API_VERSION,
        'configured_chat_api_url': safe_url(Config.COZE_V3_CHAT_URL if Config.COZE_CHAT_API_VERSION == 'v3' else Config.COZE_API_URL),
        'direct_test_api_url': safe_url(Config.COZE_V3_CHAT_URL),
        'agent_id': agent_id, 'bot_id': bot_id, 'bot_source': bot_source,
        'api_key_configured': bool(api_key), 'api_key_source': key_source,
        'database_state': db_state, 'diagnostics_enabled': Config.COZE_DIAGNOSTICS_ENABLED,
        'history_rounds': Config.CHAT_CONTEXT_ROUNDS,
    }
    return summary, api_key


def run_direct_test(bot_id, api_key, message, user_id=None, post=None):
    """直接保留原始 SSE 事件；不经过网页过滤、流式拼接或数据库持久化。"""
    import requests
    from services.chat_service import _iter_sse_events

    payload = {
        'bot_id': bot_id, 'user_id': user_id or 'coze-diagnostic-' + uuid.uuid4().hex,
        'publish_status': 'published_online', 'stream': True, 'auto_save_history': True,
        'additional_messages': [{'role': 'user', 'type': 'question', 'content_type': 'text', 'content': message}],
    }
    ctx = SimpleNamespace(request_id=uuid.uuid4().hex[:12], agent_id='direct_api', message=message)
    diagnostic = CozeDiagnostics(ctx, payload, Config.COZE_V3_CHAT_URL, enabled=True)
    answers = {}
    completed_answers = set()
    failed = False
    completed = False
    try:
        with (post or requests.post)(Config.COZE_V3_CHAT_URL,
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json=payload, stream=True, timeout=(5, 90)) as response:
            response.raise_for_status()
            if 'application/json' in response.headers.get('Content-Type', '').lower():
                diagnostic.observe('error', response.json())
                diagnostic.error_category = 'unexpected_json_response'
                failed = True
            else:
                for event, raw in _iter_sse_events(response):
                    if raw == '[DONE]':
                        diagnostic.observe('done', raw)
                        break
                    try:
                        item = json.loads(raw)
                    except (ValueError, TypeError):
                        item = None
                    diagnostic.observe(event, item)
                    if not isinstance(item, dict):
                        failed = True
                        diagnostic.error_category = 'invalid_sse'
                        continue
                    if diagnostic.error_events:
                        failed = True
                        break
                    if event == 'conversation.chat.completed':
                        completed = True
                        break
                    if (event in {'conversation.message.delta', 'conversation.message.completed'}
                            and item.get('role') == 'assistant' and item.get('type') == 'answer'
                            and isinstance(item.get('content'), str)):
                        message_id = item.get('id') or 'answer'
                        if event == 'conversation.message.completed':
                            answers[message_id] = item['content']
                            completed_answers.add(message_id)
                        elif message_id not in completed_answers:
                            answers[message_id] = answers.get(message_id, '') + item['content']
    except requests.exceptions.RequestException as exc:
        # 不打印异常正文（可能包含请求 URL 的敏感 query）；HTTP 状态另列。
        diagnostic.error_category = 'timeout' if isinstance(exc, requests.exceptions.Timeout) else 'network_or_http_error'
        failed = True
    diagnostic.outcome = 'error' if failed else ('success' if completed and any(answers.values()) else 'incomplete')
    return {'mode': 'live', 'diagnostic': diagnostic.report(), 'answers': list(answers.values()),
            'answer_complete': diagnostic.outcome == 'success', 'user_id_source': 'provided' if user_id else 'new_diagnostic_user'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='显式调用真实 COZE API；默认不发送问题')
    parser.add_argument('--agent-id', default='translator')
    parser.add_argument('--bot-id', help='可选：覆盖 Bot ID，输出中会标明覆盖来源')
    parser.add_argument('--message', default=DEFAULT_QUESTION)
    parser.add_argument('--user-id', help='可选：使用失败请求的同一 COZE user_id；默认创建独立诊断用户')
    args = parser.parse_args(argv)
    try:
        summary, api_key = deployment_config(args.agent_id, args.bot_id)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if not args.live:
            return 0
        if not api_key or not summary['bot_id']:
            print('无法执行：缺少有效 API Key 或 Bot ID。', file=sys.stderr)
            return 1
        if not args.message.strip() or len(args.message.strip()) > 4000:
            print('无法执行：问题为空或超过 4000 字符。', file=sys.stderr)
            return 1
        result = run_direct_test(summary['bot_id'], api_key, args.message.strip(), args.user_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['diagnostic']['outcome'] == 'success' else 1
    except (sqlite3.Error, ValueError):
        print('无法读取部署配置，请检查数据库结构和接口地址。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
