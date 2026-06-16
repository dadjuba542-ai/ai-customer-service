import json
import logging
import time
import uuid
from dataclasses import dataclass

import requests

from config import Config
from models import get_agent_config, get_setting, save_chat_history

logger = logging.getLogger(__name__)

ANSWER_MESSAGE_TYPES = {'answer', 'assistant_answer'}
STREAM_STATUS_MAP = {
    'chat.created': 'connected',
    'conversation.chat.created': 'connected',
    'conversation.chat.in_progress': 'searching',
    'conversation.message.in_progress': 'generating',
    'conversation.chat.completed': 'completed',
    'done': 'completed',
}


class ChatServiceError(Exception):
    def __init__(self, message, status_code=500, retryable=False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


@dataclass
class ChatRequestContext:
    message: str
    query_type: str
    agent_id: str
    user_id: str
    team_name: str
    member_name: str
    headers: dict
    payload: dict
    request_id: str


@dataclass
class StreamState:
    request_started_at: float
    full_text: str = ''
    emitted_statuses: tuple = ()
    first_token_ms: float | None = None
    coze_message_id: str = ''
    upstream_event_count: int = 0

    def __post_init__(self):
        if not isinstance(self.emitted_statuses, set):
            self.emitted_statuses = set()


def build_chat_context(data):
    data = data or {}
    message = (data.get('message') or '').strip()
    if not message:
        raise ChatServiceError('Message is required', status_code=400, retryable=False)

    query_type = data.get('query_type', '其他')
    agent_id = data.get('agent_id', '')
    user_id = (data.get('user_id') or '').strip() or 'anonymous'
    team_name = (data.get('team_name') or '').strip()
    member_name = (data.get('member_name') or '').strip()
    api_key = get_setting('coze_api_key', Config.COZE_API_KEY)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    bot_id = ''
    if agent_id:
        agent = get_agent_config(agent_id)
        if agent and agent.get('bot_id'):
            bot_id = agent['bot_id']
    if not bot_id:
        bot_id = Config.BOT_MAPPING.get(query_type, Config.DEFAULT_BOT_ID)

    payload = {
        'bot_id': bot_id,
        'user': user_id,
        'query': message,
        'stream': False,
    }

    return ChatRequestContext(
        message=message,
        query_type=query_type,
        agent_id=agent_id,
        user_id=user_id,
        team_name=team_name,
        member_name=member_name,
        headers=headers,
        payload=payload,
        request_id=uuid.uuid4().hex[:12],
    )


def execute_sync_chat(ctx):
    started_at = time.monotonic()
    try:
        response = requests.post(
            Config.COZE_API_URL,
            headers=ctx.headers,
            json=ctx.payload,
            timeout=(5, 90),
        )
        response.raise_for_status()
        coze_response = response.json()
        bot_response, coze_message_id = _extract_sync_reply(coze_response)
        history_id = persist_chat_history(ctx, bot_response, coze_message_id)
        total_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            'chat.sync request_id=%s query_type=%s agent_id=%s total_ms=%s outcome=success',
            ctx.request_id,
            ctx.query_type,
            ctx.agent_id or '-',
            total_ms,
        )
        return {
            'message': 'Message sent successfully',
            'bot_response': bot_response,
            'history_id': history_id,
            'coze_message_id': coze_message_id,
            'request_id': ctx.request_id,
        }
    except requests.exceptions.Timeout as exc:
        total_ms = int((time.monotonic() - started_at) * 1000)
        logger.warning(
            'chat.sync request_id=%s query_type=%s agent_id=%s total_ms=%s outcome=timeout',
            ctx.request_id,
            ctx.query_type,
            ctx.agent_id or '-',
            total_ms,
        )
        raise ChatServiceError('请求超时，请稍后重试', status_code=504, retryable=True) from exc
    except requests.exceptions.RequestException as exc:
        total_ms = int((time.monotonic() - started_at) * 1000)
        logger.warning(
            'chat.sync request_id=%s query_type=%s agent_id=%s total_ms=%s outcome=network_error error=%s',
            ctx.request_id,
            ctx.query_type,
            ctx.agent_id or '-',
            total_ms,
            exc,
        )
        raise ChatServiceError(f'网络错误: {str(exc)}', status_code=502, retryable=True) from exc


def iter_coze_stream(ctx):
    stream_payload = dict(ctx.payload)
    stream_payload['stream'] = True
    state = StreamState(request_started_at=time.monotonic())
    connect_started_at = time.monotonic()

    try:
        with requests.post(
            Config.COZE_API_URL,
            headers=ctx.headers,
            json=stream_payload,
            stream=True,
            timeout=(5, 30),
        ) as response:
            response.raise_for_status()
            connect_ms = int((time.monotonic() - connect_started_at) * 1000)
            logger.info(
                'chat.stream request_id=%s query_type=%s agent_id=%s coze_connect_ms=%s outcome=connected',
                ctx.request_id,
                ctx.query_type,
                ctx.agent_id or '-',
                connect_ms,
            )
            yield {'event': 'status', 'data': {'status': 'connected', 'request_id': ctx.request_id}}

            for upstream_event, raw_data in _iter_sse_events(response):
                state.upstream_event_count += 1
                if raw_data == '[DONE]':
                    break
                payload = _safe_json_loads(raw_data)
                if payload is None:
                    continue

                normalized_event = _normalize_event_name(upstream_event, payload)
                if normalized_event:
                    mapped = STREAM_STATUS_MAP.get(normalized_event)
                    if mapped and mapped not in state.emitted_statuses and mapped != 'completed':
                        state.emitted_statuses.add(mapped)
                        yield {'event': 'status', 'data': {'status': mapped, 'request_id': ctx.request_id}}

                message_text = _extract_stream_text(normalized_event, payload, state.full_text)
                if message_text:
                    if state.first_token_ms is None:
                        state.first_token_ms = int((time.monotonic() - state.request_started_at) * 1000)
                        if 'generating' not in state.emitted_statuses:
                            state.emitted_statuses.add('generating')
                            yield {'event': 'status', 'data': {'status': 'generating', 'request_id': ctx.request_id}}
                    state.full_text += message_text
                    yield {'event': 'delta', 'data': {'text': message_text, 'request_id': ctx.request_id}}

                coze_message_id = _extract_coze_message_id(payload)
                if coze_message_id and not state.coze_message_id:
                    state.coze_message_id = coze_message_id

            if not state.full_text:
                raise ChatServiceError('抱歉，我现在无法回答您的问题。', status_code=502, retryable=False)

            yield {'event': 'status', 'data': {'status': 'saving', 'request_id': ctx.request_id}}
            save_started_at = time.monotonic()
            history_id = persist_chat_history(ctx, state.full_text, state.coze_message_id)
            save_history_ms = int((time.monotonic() - save_started_at) * 1000)
            total_ms = int((time.monotonic() - state.request_started_at) * 1000)
            logger.info(
                'chat.stream request_id=%s query_type=%s agent_id=%s first_token_ms=%s save_history_ms=%s total_ms=%s upstream_events=%s outcome=success',
                ctx.request_id,
                ctx.query_type,
                ctx.agent_id or '-',
                state.first_token_ms or -1,
                save_history_ms,
                total_ms,
                state.upstream_event_count,
            )
            yield {
                'event': 'done',
                'data': {
                    'full_text': state.full_text,
                    'history_id': history_id,
                    'coze_message_id': state.coze_message_id,
                    'request_id': ctx.request_id,
                },
            }
    except requests.exceptions.Timeout as exc:
        total_ms = int((time.monotonic() - state.request_started_at) * 1000)
        logger.warning(
            'chat.stream request_id=%s query_type=%s agent_id=%s total_ms=%s outcome=timeout',
            ctx.request_id,
            ctx.query_type,
            ctx.agent_id or '-',
            total_ms,
        )
        raise ChatServiceError('请求超时，请稍后重试', status_code=504, retryable=True) from exc
    except requests.exceptions.RequestException as exc:
        total_ms = int((time.monotonic() - state.request_started_at) * 1000)
        logger.warning(
            'chat.stream request_id=%s query_type=%s agent_id=%s total_ms=%s outcome=network_error error=%s',
            ctx.request_id,
            ctx.query_type,
            ctx.agent_id or '-',
            total_ms,
            exc,
        )
        raise ChatServiceError(f'网络错误: {str(exc)}', status_code=502, retryable=True) from exc


def persist_chat_history(ctx, bot_response, coze_message_id):
    return save_chat_history(
        user_id=ctx.user_id,
        query_type=ctx.query_type,
        user_message=ctx.message,
        bot_response=bot_response,
        coze_message_id=coze_message_id,
        team_name=ctx.team_name,
        member_name=ctx.member_name,
    )


def _extract_sync_reply(coze_response):
    if coze_response.get('code') == 0:
        messages = coze_response.get('messages', [])
        bot_response = ''
        for msg in messages:
            if msg.get('type') == 'answer':
                bot_response = msg.get('content', '')
                break
        if not bot_response:
            bot_response = '抱歉，我现在无法回答您的问题。'
        return bot_response, coze_response.get('conversation_id', '')
    return f"Coze API错误: {coze_response.get('msg', '未知错误')}", ''


def _iter_sse_events(response):
    event_name = ''
    data_lines = []
    response.encoding = 'utf-8'
    for raw_line in response.iter_lines(decode_unicode=False):
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode('utf-8', errors='replace').rstrip('\r')
        else:
            line = str(raw_line).rstrip('\r')
        if not line:
            if event_name or data_lines:
                yield event_name, '\n'.join(data_lines)
            event_name = ''
            data_lines = []
            continue
        if line.startswith(':'):
            continue
        if line.startswith('event:'):
            event_name = line[6:].strip()
            continue
        if line.startswith('data:'):
            data_lines.append(line[5:].strip())
    if event_name or data_lines:
        yield event_name, '\n'.join(data_lines)


def _safe_json_loads(raw_data):
    try:
        return json.loads(raw_data)
    except (TypeError, ValueError):
        return None


def _normalize_event_name(upstream_event, payload):
    for candidate in (
        upstream_event,
        payload.get('event'),
        payload.get('type'),
        payload.get('name'),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return ''


def _extract_stream_text(normalized_event, payload, current_text):
    message = payload.get('message')
    if isinstance(message, dict):
        msg_type = message.get('type')
        if msg_type and msg_type not in ANSWER_MESSAGE_TYPES:
            return ''
        text = message.get('content')
        return _normalize_delta_text(text, current_text)

    if normalized_event and 'delta' in normalized_event:
        for key in ('content', 'text', 'delta'):
            text = payload.get(key)
            normalized = _normalize_delta_text(text, current_text)
            if normalized:
                return normalized

    data = payload.get('data')
    if isinstance(data, dict):
        msg_type = data.get('type')
        if msg_type and msg_type not in ANSWER_MESSAGE_TYPES:
            return ''
        for key in ('content', 'text', 'delta'):
            normalized = _normalize_delta_text(data.get(key), current_text)
            if normalized:
                return normalized

    return ''


def _normalize_delta_text(text, current_text):
    if not isinstance(text, str) or not text:
        return ''
    if current_text and text.startswith(current_text):
        return text[len(current_text):]
    if current_text.endswith(text):
        return ''
    return text


def _extract_coze_message_id(payload):
    for candidate in (
        payload.get('conversation_id'),
        payload.get('chat_id'),
        payload.get('id'),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    chat = payload.get('chat')
    if isinstance(chat, dict):
        for key in ('id', 'chat_id', 'conversation_id'):
            value = chat.get(key)
            if isinstance(value, str) and value:
                return value
    return ''
