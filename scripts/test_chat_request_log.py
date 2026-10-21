#!/usr/bin/env python3
"""聊天请求诊断落库与 MCP 查询回归；不调用真实 Coze。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-chat-request-log-') as tmpdir:
        os.environ.update(
            DATABASE_DIR=tmpdir,
            UPLOAD_DIR=str(Path(tmpdir) / 'uploads'),
            SECRET_KEY='test-secret-key-32-bytes-minimum!!',
            COZE_API_KEY='test-coze-key',
            COZE_CHAT_API_VERSION='v3',
            MCP_TOKEN='test-mcp-token',
        )
        from app import app
        from models import get_db_connection
        from routes.auth import generate_guest_token
        from services.chat_service import ChatServiceError
        from services.chat_queue_service import ChatQueueDispatcher, claim_next_job, enqueue_job
        from services.mcp_service import dispatch

        client = app.test_client()
        auth = {'Authorization': 'Bearer ' + generate_guest_token('diag-user', '', '')}

        with patch('routes.chat.execute_sync_chat', return_value={
            'bot_response': '同步回答',
            'history_id': 11,
            'coze_message_id': 'sync-conversation',
            'conversation_id': 'sync-conversation',
            'chat_id': 'sync-chat',
            'upstream_event_count': 1,
        }):
            response = client.post('/api/chat/send', headers=auth,
                                   json={'message': 'SYNC_PRIVATE', 'agent_id': 'coder'})
            assert_true(response.status_code == 200, response.get_data(as_text=True))

        def successful_stream(ctx):
            yield {'event': 'delta', 'data': {'text': '流式', 'request_id': ctx.request_id}}
            yield {'event': 'done', 'data': {
                'full_text': '流式回答', 'history_id': 12, 'coze_message_id': 'conv-1',
                'request_id': ctx.request_id, 'conversation_id': 'conv-1', 'chat_id': 'chat-1',
                'first_token_ms': 5, 'upstream_event_count': 3,
            }}

        with patch('routes.chat.iter_coze_stream', side_effect=successful_stream):
            response = client.post('/api/chat/stream', headers=auth,
                                   json={'message': 'STREAM_PRIVATE', 'agent_id': 'coder'})
            assert_true(response.status_code == 200, response.get_data(as_text=True))
            assert_true(b'event: done' in response.data, response.data)

        def failing_stream(ctx):
            error = ChatServiceError('network error', status_code=502, retryable=True,
                                     error_category='network_error')
            error.error_code = '4000'
            error.conversation_id = 'conv-error'
            error.chat_id = 'chat-error'
            error.upstream_event_count = 2
            raise error
            yield  # pragma: no cover

        with patch('routes.chat.iter_coze_stream', side_effect=failing_stream):
            response = client.post('/api/chat/stream', headers=auth,
                                   json={'message': 'FAIL_PRIVATE', 'agent_id': 'coder'})
            assert_true(response.status_code == 200, response.get_data(as_text=True))
            assert_true(b'event: error' in response.data, response.data)

        def interrupted_stream(ctx):
            yield {'event': 'delta', 'data': {'text': '半截', 'request_id': ctx.request_id}}
            yield {'event': 'delta', 'data': {'text': '继续', 'request_id': ctx.request_id}}

        with patch('routes.chat.iter_coze_stream', side_effect=interrupted_stream):
            response = client.post('/api/chat/stream', headers=auth, buffered=False,
                                   json={'message': 'INTERRUPT_PRIVATE', 'agent_id': 'coder'})
            response.close()

        queue_ctx = SimpleNamespace(
            message='QUEUE_PRIVATE', query_type='使用答疑', agent_id='coder', channel='',
            user_id='queue-user', team_name='', member_name='', request_id='queue-request',
        )
        with patch('services.chat_queue_service.execute_sync_chat', return_value={
            'bot_response': '排队回答', 'history_id': 13, 'coze_message_id': 'queue-conv',
            'conversation_id': 'queue-conv', 'chat_id': 'queue-chat', 'upstream_event_count': 1,
        }):
            queued = enqueue_job(queue_ctx)
            job = claim_next_job()
            ChatQueueDispatcher(MagicMock(active=1))._process_job(job, 1)

        queue_fail_ctx = SimpleNamespace(
            message='QUEUE_FAIL_PRIVATE', query_type='使用答疑', agent_id='coder', channel='',
            user_id='queue-fail-user', team_name='', member_name='', request_id='queue-fail-request',
        )
        with patch('services.chat_queue_service.execute_sync_chat', side_effect=ChatServiceError(
                'queue network error', status_code=502, retryable=True,
                error_category='network_error')):
            queued = enqueue_job(queue_fail_ctx)
            job = claim_next_job()
            ChatQueueDispatcher(MagicMock(active=1))._process_job(job, 1)

        conn = get_db_connection()
        try:
            rows = [dict(row) for row in conn.execute(
                'SELECT * FROM chat_request_log ORDER BY id ASC'
            ).fetchall()]
            columns = {row['name'] for row in conn.execute(
                'PRAGMA table_info(chat_request_log)'
            ).fetchall()}
        finally:
            conn.close()

        assert_true(rows, 'chat requests should be logged')
        assert_true('user_message' not in columns and 'bot_response' not in columns,
                    'diagnostics must not store message content')
        by_endpoint = {}
        for row in rows:
            by_endpoint.setdefault(row['endpoint'], []).append(row)
        assert_true(by_endpoint['sync'][0]['outcome'] == 'success', 'sync success should be logged')
        assert_true(by_endpoint['stream'][0]['outcome'] == 'success', 'stream success should be logged')
        failures = [row for row in rows if row['outcome'] == 'error']
        assert_true(any(row['error_category'] == 'network_error' and row['error_code'] == '4000'
                        for row in failures), 'stream failure should keep error metadata')
        assert_true(any(row['conversation_id'] == 'conv-error' and row['chat_id'] == 'chat-error'
                        for row in failures), 'stream failure should keep Coze ids')
        assert_true(any(row['outcome'] == 'interrupted' for row in by_endpoint['stream']),
                    'client disconnect should be logged as interrupted')
        assert_true(any(row['endpoint'] == 'queue' and row['outcome'] == 'success'
                        for row in rows), 'queued success should be logged')
        assert_true(any(row['request_id'] == 'queue-fail-request' and row['outcome'] == 'error'
                        for row in rows), 'queued failure should be logged')
        assert_true(all(row['message_length'] > 0 for row in rows), 'message length should be recorded')
        serialized = json.dumps(rows, ensure_ascii=False)
        for secret in ('SYNC_PRIVATE', 'STREAM_PRIVATE', 'FAIL_PRIVATE',
                       'INTERRUPT_PRIVATE', 'QUEUE_PRIVATE', 'QUEUE_FAIL_PRIVATE'):
            assert_true(secret not in serialized, secret)

        def call_tool(name, arguments):
            payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': name, 'arguments': arguments}}
            response = dispatch(payload)
            return json.loads(response['result']['content'][0]['text'])

        recent = call_tool('recent_chat_failures', {'days': 7, 'limit': 20})
        assert_true(recent['count'] >= 2, recent)
        assert_true(recent['items'][0]['message_fingerprint'], recent)
        failed_request_id = next(row['request_id'] for row in rows
                                 if row['outcome'] == 'error' and row['error_category'] == 'network_error')
        detail = call_tool('chat_request_detail', {'request_id': failed_request_id})
        assert_true(detail['count'] >= 1, detail)
        assert_true('message_length' in detail['items'][0], detail)

        health = call_tool('server_health', {})
        assert_true(health['database']['ok'] is True, health)
        assert_true(health['database']['request_log_available'] is True, health)
        assert_true(health['coze']['api_key_configured'] is True, health)
        assert_true('test-coze-key' not in json.dumps(health), 'health must not expose the key')
        assert_true(health['mcp']['token_configured'] is True, health)
        assert_true('test-mcp-token' not in json.dumps(health), 'health must not expose the MCP token')

    print('PASS: chat request diagnostics, redaction, queue and MCP tools')


if __name__ == '__main__':
    main()
