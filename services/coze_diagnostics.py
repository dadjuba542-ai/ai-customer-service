"""只记录 COZE 请求元信息和事件摘要，不记录 headers、消息正文或工具参数。"""
import json
import logging
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from config import Config

logger = logging.getLogger(__name__)
MESSAGE_TYPES = {'knowledge', 'function_call', 'tool_output', 'tool_response', 'answer',
                 'assistant_answer', 'follow_up', 'verbose', 'question'}
EVENT_NAMES = {'conversation.chat.created', 'conversation.chat.in_progress',
               'conversation.message.delta', 'conversation.message.completed',
               'conversation.chat.completed', 'conversation.chat.failed',
               'conversation.chat.canceled', 'conversation.chat.requires_action',
               'error', 'done', 'message', 'chat.created', 'sync.message', 'sync.response'}


def safe_url(url):
    """去掉 URL 中可能含凭据的 userinfo、query、fragment。"""
    parts = urlsplit(url)
    host = parts.hostname or ''
    if ':' in host:
        host = f'[{host}]'
    if parts.port:
        host += f':{parts.port}'
    return f'{parts.scheme}://{host}{parts.path}'


class CozeDiagnostics:
    def __init__(self, ctx, payload, url, enabled=None):
        self.enabled = Config.COZE_DIAGNOSTICS_ENABLED if enabled is None else enabled
        self.ctx = ctx
        self.payload = payload
        self.url = url
        self.events = Counter()
        self.message_events = Counter()
        self.message_ids = defaultdict(set)
        self.content_chars = {}
        self.tool_names = set()
        self.error_events = 0
        self.error_codes = set()
        self.conversation_id = ''
        self.chat_id = ''
        self.outcome = 'interrupted'
        self.error_category = ''

    def observe(self, event, payload):
        self.events[event if event in EVENT_NAMES else 'other'] += 1
        if not isinstance(payload, dict):
            if payload != '[DONE]':
                self.error_events += 1
            return
        conversation_id = payload.get('conversation_id')
        if isinstance(conversation_id, str) and conversation_id:
            self.conversation_id = conversation_id
        chat_id = payload.get('chat_id')
        if not chat_id and event.startswith('conversation.chat.'):
            chat_id = payload.get('id')
        if isinstance(chat_id, str) and chat_id:
            self.chat_id = chat_id
        error = payload.get('last_error')
        error = error if isinstance(error, dict) else {}
        codes = [code for code in (payload.get('code'), error.get('code'))
                 if isinstance(code, (int, float)) and code != 0]
        if codes or event in {'error', 'conversation.chat.failed', 'conversation.chat.canceled',
                             'conversation.chat.requires_action'} or payload.get('status') in {'failed', 'canceled', 'requires_action'}:
            self.error_events += 1
            self.error_codes.update(codes)
        message = payload.get('message') or payload.get('data')
        message = message if isinstance(message, dict) else payload
        kind = message.get('type')
        if not isinstance(kind, str) or kind not in MESSAGE_TYPES:
            return
        self.message_events[kind] += 1
        message_id = message.get('id') or kind
        self.message_ids[kind].add(str(message_id))
        text = message.get('content')
        if isinstance(text, str):
            # 只保留字符数，completed 的重复快照不会重复计数。
            if event != 'conversation.message.delta':
                self.content_chars[(kind, str(message_id))] = len(text)
            if kind == 'function_call':
                try:
                    call = json.loads(text)
                    name = call.get('name') if isinstance(call, dict) else None
                    if isinstance(name, str) and re.fullmatch(r'[\w.:-]{1,128}', name):
                        self.tool_names.add(name)
                except (ValueError, TypeError):
                    pass

    def report(self):
        is_v3 = 'additional_messages' in self.payload
        messages = self.payload.get('additional_messages') or []
        last = messages[-1] if messages else {}
        return {
            'request_id': self.ctx.request_id,
            'agent_id': self.ctx.agent_id,
            'api_version': 'v3' if is_v3 else 'v2',
            'api_url': safe_url(self.url),
            'bot_id': self.payload.get('bot_id', ''),
            'publish_status': self.payload.get('publish_status', 'published_online' if is_v3 else 'not_specified'),
            'bot_version': self.payload.get('bot_version', 'latest_published' if is_v3 else 'not_specified'),
            'history_message_count': (max(0, len(messages) - 1) if is_v3
                                      else len(self.payload['chat_history']) if 'chat_history' in self.payload
                                      else getattr(self.ctx, 'history_message_count', 0)),
            'context_delivery': 'additional_messages' if is_v3 else ('chat_history' if 'chat_history' in self.payload else 'query'),
            'current_question_independent': (last.get('role') == 'user' and last.get('content') == self.ctx.message
                                             if is_v3 else self.payload.get('query') == self.ctx.message),
            'conversation_id': self.conversation_id,
            'chat_id': self.chat_id,
            'outcome': self.outcome,
            'error_category': self.error_category,
            'events': dict(self.events),
            'message_events': dict(self.message_events),
            'messages_by_type': {kind: len(ids) for kind, ids in self.message_ids.items()},
            'knowledge_content_chars': sum(size for (kind, _), size in self.content_chars.items() if kind == 'knowledge'),
            'tool_names': sorted(self.tool_names),
            'error_events': self.error_events,
            'error_codes': sorted(self.error_codes),
        }

    def emit(self, phase):
        if self.enabled:
            # WARNING 确保默认 Gunicorn 日志级别也能看到；仅在显式开启时输出。
            logger.warning('coze.diagnostic %s', json.dumps({'phase': phase, **self.report()}, ensure_ascii=False))
