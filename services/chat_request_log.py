import hashlib
import logging
import re
import time
from datetime import datetime

import requests

from config import Config
from models import get_db_connection

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 200


def _as_text(value, limit=MAX_TEXT_CHARS):
    if value is None:
        return ''
    text = value if isinstance(value, str) else str(value)
    return text[:limit]


def _fingerprint(message):
    normalized = re.sub(r'\s+', ' ', message or '').strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:24]


def _user_ref(user_id):
    seed = f'{Config.SECRET_KEY}:{user_id or ""}'.encode('utf-8')
    return hashlib.sha256(seed).hexdigest()[:24]


def _utc_now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def classify_error(exc):
    category = _as_text(getattr(exc, 'error_category', ''), 40)
    code = _as_text(getattr(exc, 'error_code', ''), 80)
    status = getattr(exc, 'status_code', None)
    message = str(exc or '')

    if not category:
        if isinstance(exc, requests.exceptions.Timeout):
            category = 'timeout'
        elif isinstance(exc, requests.exceptions.RequestException):
            category = 'network_error'
        elif status == 504:
            category = 'timeout'
        elif status == 502 and ('网络错误' in message or 'network' in message.lower()):
            category = 'network_error'
        elif status == 502:
            category = 'upstream_error'
        elif status and status >= 500:
            category = 'server_error'
        elif status and status >= 400:
            category = 'request_error'
        else:
            category = 'internal_error'
    return category, code


def record_chat_request(**fields):
    values = {
        'request_id': _as_text(fields.get('request_id'), 64),
        'endpoint': _as_text(fields.get('endpoint'), 20),
        'agent_id': _as_text(fields.get('agent_id'), 64),
        'query_type': _as_text(fields.get('query_type'), 40),
        'channel': _as_text(fields.get('channel'), 64),
        'user_ref': _as_text(fields.get('user_ref'), 64),
        'message_fingerprint': _as_text(fields.get('message_fingerprint'), 64),
        'message_length': max(0, int(fields.get('message_length') or 0)),
        'outcome': _as_text(fields.get('outcome'), 32),
        'error_category': _as_text(fields.get('error_category'), 40),
        'error_code': _as_text(fields.get('error_code'), 80),
        'http_status': fields.get('http_status'),
        'retryable': 1 if fields.get('retryable') else 0,
        'duration_ms': max(0, int(fields.get('duration_ms') or 0)),
        'first_token_ms': fields.get('first_token_ms'),
        'upstream_event_count': max(0, int(fields.get('upstream_event_count') or 0)),
        'conversation_id': _as_text(fields.get('conversation_id'), 128),
        'chat_id': _as_text(fields.get('chat_id'), 128),
        'history_id': fields.get('history_id'),
        'started_at': _as_text(fields.get('started_at'), 32) or _utc_now(),
    }
    try:
        conn = get_db_connection()
        try:
            conn.execute(
                '''INSERT INTO chat_request_log
                   (request_id, endpoint, agent_id, query_type, channel, user_ref,
                    message_fingerprint, message_length, outcome, error_category, error_code,
                    http_status, retryable, duration_ms, first_token_ms, upstream_event_count,
                    conversation_id, chat_id, history_id, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    values['request_id'], values['endpoint'], values['agent_id'],
                    values['query_type'], values['channel'], values['user_ref'],
                    values['message_fingerprint'], values['message_length'], values['outcome'],
                    values['error_category'], values['error_code'], values['http_status'],
                    values['retryable'], values['duration_ms'], values['first_token_ms'],
                    values['upstream_event_count'], values['conversation_id'], values['chat_id'],
                    values['history_id'], values['started_at'],
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning('chat.request_log write failed: %s', exc)


class ChatRequestLog:
    def __init__(self, ctx, endpoint):
        self.ctx = ctx
        self.endpoint = endpoint
        self.started_monotonic = time.monotonic()
        self.started_at = _utc_now()
        self.first_token_ms = None
        self.upstream_event_count = 0
        self.finished = False
        self.user_ref = _user_ref(getattr(ctx, 'user_id', ''))
        self.message_fingerprint = _fingerprint(getattr(ctx, 'message', ''))
        self.message_length = len(getattr(ctx, 'message', '') or '')

    def observe(self, event_name):
        self.upstream_event_count += 1
        if event_name == 'delta' and self.first_token_ms is None:
            self.first_token_ms = self.duration_ms()

    def mark_first_token(self):
        if self.first_token_ms is None:
            self.first_token_ms = self.duration_ms()

    def duration_ms(self):
        return max(0, int((time.monotonic() - self.started_monotonic) * 1000))

    def finish_success(self, data=None):
        data = data if isinstance(data, dict) else {}
        self._finish(
            outcome='success',
            http_status=200,
            first_token_ms=data.get('first_token_ms') or self.first_token_ms,
            upstream_event_count=data.get('upstream_event_count') or self.upstream_event_count,
            conversation_id=data.get('conversation_id') or '',
            chat_id=data.get('chat_id') or '',
            history_id=data.get('history_id'),
        )

    def finish_error(self, exc, http_status=None):
        category, code = classify_error(exc)
        self._finish(
            outcome='error',
            error_category=category,
            error_code=code,
            http_status=http_status or getattr(exc, 'status_code', None),
            retryable=bool(getattr(exc, 'retryable', False)),
            first_token_ms=getattr(exc, 'first_token_ms', None) or self.first_token_ms,
            upstream_event_count=getattr(exc, 'upstream_event_count', 0) or self.upstream_event_count,
            conversation_id=getattr(exc, 'conversation_id', '') or '',
            chat_id=getattr(exc, 'chat_id', '') or '',
        )

    def finish_interrupted(self):
        self._finish(
            outcome='interrupted',
            error_category='client_disconnect',
            first_token_ms=self.first_token_ms,
            upstream_event_count=self.upstream_event_count,
        )

    def _finish(self, **fields):
        if self.finished:
            return
        self.finished = True
        record_chat_request(
            request_id=getattr(self.ctx, 'request_id', ''),
            endpoint=self.endpoint,
            agent_id=getattr(self.ctx, 'agent_id', ''),
            query_type=getattr(self.ctx, 'query_type', ''),
            channel=getattr(self.ctx, 'channel', ''),
            user_ref=self.user_ref,
            message_fingerprint=self.message_fingerprint,
            message_length=self.message_length,
            duration_ms=self.duration_ms(),
            started_at=self.started_at,
            **fields,
        )
