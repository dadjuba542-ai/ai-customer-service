#!/usr/bin/env python3
"""聊天总超时、SSE 心跳和慢空召回跳过改写回归；不调用真实 Coze。"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-chat-timeout-') as tmpdir:
        os.environ.update(
            DATABASE_DIR=tmpdir,
            UPLOAD_DIR=str(Path(tmpdir) / 'uploads'),
            SECRET_KEY='test-secret-key-32-bytes-minimum!!',
            COZE_API_KEY='test-coze-key',
            COZE_CHAT_API_VERSION='v3',
        )
        from app import app
        from config import Config
        from models import set_setting
        from services.chat_service import (
            ChatServiceError,
            KNOWLEDGE_EMPTY_REPLY,
            build_chat_context,
            iter_coze_stream,
        )
        from test_chat_v3 import FakeResponse, sse

        ctx = build_chat_context({'message': '超时测试', 'agent_id': 'coder'}, {'user_id': 'timeout-user'})
        original = (
            Config.CHAT_STREAM_HEARTBEAT_SECONDS,
            Config.CHAT_TOTAL_TIMEOUT_SECONDS,
            Config.CHAT_REWRITE_MAX_INITIAL_SECONDS,
        )
        try:
            Config.CHAT_STREAM_HEARTBEAT_SECONDS = 0.01
            Config.CHAT_TOTAL_TIMEOUT_SECONDS = 2

            def slow_done(_ctx, read_timeout=30, cancel_event=None):
                time.sleep(0.05)
                yield {'event': 'done', 'data': {'full_text': '慢回答', 'history_id': 1,
                                                 'coze_message_id': 'conv-slow', 'request_id': _ctx.request_id}}

            with patch('services.chat_service._iter_coze_stream_impl', side_effect=slow_done):
                events = list(iter_coze_stream(ctx))
            assert_true(any(event['event'] == 'status' and event['data'].get('status') == 'waiting'
                            for event in events), 'slow upstream should emit heartbeat status')
            assert_true(events[-1]['event'] == 'done', 'heartbeat must not change the final done event')

            Config.CHAT_TOTAL_TIMEOUT_SECONDS = 0.05

            def too_slow(_ctx, read_timeout=30, cancel_event=None):
                time.sleep(0.2)
                yield {'event': 'done', 'data': {'full_text': '不应到达', 'history_id': 2}}

            with patch('services.chat_service._iter_coze_stream_impl', side_effect=too_slow):
                try:
                    list(iter_coze_stream(ctx))
                except ChatServiceError as exc:
                    assert_true(exc.status_code == 504 and exc.error_category == 'timeout',
                                'total timeout should raise a retryable timeout error')
                    assert_true('超时' in exc.message, exc.message)
                else:
                    raise AssertionError('total timeout should be enforced')

            Config.CHAT_TOTAL_TIMEOUT_SECONDS = 5
            Config.CHAT_REWRITE_MAX_INITIAL_SECONDS = 0.0001
            set_setting('coze_rewrite_bot_id', '123456')
            empty = FakeResponse(sse('conversation.message.delta', {
                'id': 'answer', 'role': 'assistant', 'type': 'answer',
                'content_type': 'text', 'content': KNOWLEDGE_EMPTY_REPLY,
            }) + sse('conversation.chat.completed', {'id': 'chat-1', 'status': 'completed'}))
            with patch('services.chat_service.requests.post', side_effect=[empty]) as post:
                events = list(iter_coze_stream(ctx))
            assert_true(post.call_count == 1, 'slow empty recall should skip rewrite')
            assert_true(not any(event['event'] == 'replace' for event in events),
                        'skipped rewrite should not send replace frames')
            assert_true(events[-1]['event'] == 'done'
                        and KNOWLEDGE_EMPTY_REPLY in events[-1]['data']['full_text'],
                        'skipped rewrite should return the knowledge-empty prompt')
        finally:
            (Config.CHAT_STREAM_HEARTBEAT_SECONDS,
             Config.CHAT_TOTAL_TIMEOUT_SECONDS,
             Config.CHAT_REWRITE_MAX_INITIAL_SECONDS) = original

        app.test_client()
    print('PASS: chat heartbeat, total timeout and slow empty-recall handling')


if __name__ == '__main__':
    main()
