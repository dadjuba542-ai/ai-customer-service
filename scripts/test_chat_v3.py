#!/usr/bin/env python3
"""V3 原生上下文、SSE 和网页调用路径回归；不调用真实 Coze。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests


def sse(event, data):
    return [f'event: {event}'.encode(), ('data: ' + json.dumps(data, ensure_ascii=False)).encode(), b'']


class FakeResponse:
    def __init__(self, events=(), json_body=None):
        self.events = events
        self.json_body = json_body
        self.headers = {'Content-Type': 'application/json' if json_body is not None else 'text/event-stream'}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_lines(self, **kwargs):
        return iter(self.events)

    def json(self):
        return self.json_body


def main():
    with tempfile.TemporaryDirectory(prefix='acs-chat-v3-') as tmpdir:
        os.environ.update(DATABASE_DIR=tmpdir, UPLOAD_DIR=str(Path(tmpdir) / 'uploads'),
                          SECRET_KEY='test-secret-key-32-bytes-minimum!!', COZE_API_KEY='test-key',
                          COZE_CHAT_API_VERSION='v3', CHAT_CONTEXT_ROUNDS='6', CHAT_CONTEXT_DELIVERY='query')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import app
        from config import Config
        from models import save_chat_history, reset_chat_context, get_chat_history_by_id, get_db_connection
        from routes.auth import generate_guest_token
        from services.chat_service import build_chat_context, execute_sync_chat, iter_coze_stream, ChatServiceError
        from services.chat_queue_service import enqueue_job, claim_next_job, ChatQueueDispatcher, get_job

        identity = {'user_id': 'v3-user'}
        def context(message='修改刚才的回答', agent='aura', user='v3-user'):
            return build_chat_context({'message': message, 'agent_id': agent}, {'user_id': user})

        first = context()
        assert first.payload['additional_messages'] == [
            {'role': 'user', 'type': 'question', 'content': '修改刚才的回答', 'content_type': 'text'}]
        for index in range(1, 8):
            save_chat_history(identity['user_id'], '产品咨询', f'问题{index}', f'回答{index}', agent_id='aura')
        save_chat_history(identity['user_id'], '使用答疑', '切换前问题', '切换前回答', agent_id='coder')
        save_chat_history('other-user', '产品咨询', '不应泄漏', '私人回答', agent_id='aura')
        ctx = context()
        messages = ctx.payload['additional_messages']
        assert len(messages) == 13
        assert [m['role'] for m in messages] == ['user', 'assistant'] * 6 + ['user']
        assert messages[0]['content'] == '问题3' and messages[-2]['content'] == '切换前回答'
        assert all(m['type'] == ('question' if m['role'] == 'user' else 'answer') for m in messages)
        assert not any(m['content'] == '不应泄漏' for m in messages)
        assert all(key not in ctx.payload for key in ['query', 'user', 'chat_history', 'conversation_id'])
        assert ctx.payload['user_id'] == identity['user_id'] and ctx.message == messages[-1]['content']

        Config.CHAT_CONTEXT_MESSAGE_MAX_CHARS = 2
        clipped = context()
        assert all(len(m['content']) <= 2 for m in clipped.payload['additional_messages'][:-1])
        assert clipped.payload['additional_messages'][-1]['content'] == ctx.message
        Config.CHAT_CONTEXT_MESSAGE_MAX_CHARS = 2000
        Config.CHAT_CONTEXT_ROUNDS = 0
        assert len(context().payload['additional_messages']) == 1
        Config.CHAT_CONTEXT_ROUNDS = 100
        for index in range(55):
            save_chat_history('long-user', '产品咨询', f'长历史{index}', f'长回答{index}', agent_id='aura')
        assert len(context(user='long-user').payload['additional_messages']) == 99
        Config.CHAT_CONTEXT_ROUNDS = 6

        def message(text, message_id='answer1', kind='answer'):
            return {'id': message_id, 'role': 'assistant', 'type': kind, 'content_type': 'text',
                    'content': text, 'conversation_id': 'conversation123'}

        events = sse('conversation.chat.created', {'id': 'chat123', 'conversation_id': 'conversation123'})
        for kind in ['knowledge', 'function_call', 'tool_output', 'verbose', 'follow_up']:
            events += sse('conversation.message.delta', message('不应展示', kind, kind))
        events += sse('conversation.message.delta', message('哈'))
        events += sse('conversation.message.delta', message('哈'))
        events += sse('conversation.message.completed', message('哈哈，完整'))
        events += sse('conversation.message.completed', message('第二段', 'answer2'))
        events += sse('conversation.chat.completed', {'status': 'completed', 'last_error': {'code': 0}})
        expected = '哈哈，完整第二段'
        related = {'items': [], 'total': 0}
        with patch('services.chat_service.find_related_cases', return_value=related), \
                patch('services.chat_service.requests.post', side_effect=lambda *a, **k: FakeResponse(events)) as post:
            result = execute_sync_chat(ctx)
            assert result['bot_response'] == expected
            saved = get_chat_history_by_id(result['history_id'], identity['user_id'])
            assert saved['user_message'] == ctx.message and saved['bot_response'] == expected
            assert result['coze_message_id'] == 'conversation123'
            assert post.call_args.args[0] == Config.COZE_V3_CHAT_URL
            assert post.call_args.kwargs['json'] == ctx.payload and post.call_args.kwargs['stream'] is True
            streamed = list(iter_coze_stream(ctx))
            assert streamed[-1]['data']['full_text'] == expected
            assert ''.join(e['data']['text'] for e in streamed if e['event'] == 'delta') == expected

            queue_ctx = context('排队追问', 'coder')
            queued = enqueue_job(queue_ctx)
            job = claim_next_job()
            limiter = MagicMock(active=1)
            ChatQueueDispatcher(limiter)._process_job(job, 1)
            assert get_job(queued['job']['job_id'], identity['user_id'])['bot_response'] == expected
            sent = post.call_args.kwargs['json']['additional_messages']
            assert sent[-1]['content'] == '排队追问' and any(m['role'] == 'assistant' for m in sent[:-1])
            limiter.release.assert_called_once()

            client = app.test_client()
            auth = {'Authorization': 'Bearer ' + generate_guest_token('api-v3-user', '', '')}
            sync_res = client.post('/api/chat/send', headers=auth, json={'message': '网页同步', 'agent_id': 'aura'})
            assert sync_res.status_code == 200 and sync_res.get_json()['bot_response'] == expected
            stream_res = client.post('/api/chat/stream', headers=auth, json={'message': '网页流式', 'agent_id': 'aura'})
            assert stream_res.status_code == 200 and b'event: done' in stream_res.data

        with get_db_connection() as conn:
            count_before = conn.execute('SELECT COUNT(*) FROM chat_history').fetchone()[0]
        failures = [
            FakeResponse(json_body={'code': 4101, 'msg': 'invalid token'}),
            FakeResponse(sse('error', {'code': 4000, 'msg': 'bad request'})),
            FakeResponse(sse('conversation.chat.failed', {'last_error': {'code': 1, 'msg': 'failed'}})),
            FakeResponse(sse('conversation.chat.requires_action', {'status': 'requires_action'})),
            FakeResponse(sse('conversation.message.delta', message('未完成回答'))),
            FakeResponse(sse('conversation.chat.completed', {'status': 'completed'})),
            FakeResponse(sse('conversation.message.delta', message('错误')) +
                         sse('conversation.message.completed', message('内容不一致'))),
        ]
        for response in failures:
            with patch('services.chat_service.find_related_cases', return_value=related), \
                    patch('services.chat_service.requests.post', return_value=response):
                try:
                    execute_sync_chat(ctx)
                except ChatServiceError:
                    pass
                else:
                    raise AssertionError('invalid/failed/incomplete response must raise')
        with patch('services.chat_service.find_related_cases', return_value=related), \
                patch('services.chat_service.requests.post', side_effect=requests.exceptions.Timeout):
            try:
                execute_sync_chat(ctx)
            except ChatServiceError as exc:
                assert exc.status_code == 504 and exc.retryable
            else:
                raise AssertionError('timeout must raise')
        with get_db_connection() as conn:
            assert conn.execute('SELECT COUNT(*) FROM chat_history').fetchone()[0] == count_before

        reset_chat_context(identity['user_id'], '*')
        assert len(context().payload['additional_messages']) == 1
        save_chat_history(identity['user_id'], '产品咨询', '清空前', '旧回答', agent_id='aura')
        reset_chat_context(identity['user_id'], 'aura')
        save_chat_history(identity['user_id'], '使用答疑', '保留问题', '保留回答', agent_id='coder')
        assert [m['content'] for m in context().payload['additional_messages']] == ['保留问题', '保留回答', '修改刚才的回答']
        print('PASS: Coze V3 context, sync/stream/queue, API responses and failure handling')


if __name__ == '__main__':
    main()
