#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    from services.security_service import ConcurrentRequestLimiter

    limiter = ConcurrentRequestLimiter(3)
    assert_true([limiter.try_acquire() for _ in range(3)] == [1, 2, 3], 'three slots should be available')
    assert_true(limiter.try_acquire() is None, 'the fourth slot should be rejected without blocking')
    assert_true(limiter.release() == 2, 'release should decrement the active count')
    assert_true(limiter.try_acquire() == 3, 'a released slot should be reusable')
    while limiter.active:
        limiter.release()

    with tempfile.TemporaryDirectory(prefix='acs-chat-capacity-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'
        os.environ['CHAT_STREAM_MAX_CONCURRENT_PER_WORKER'] = '1'

        from app import app
        from models import set_setting
        from routes import chat as chat_routes
        from services.chat_service import ChatServiceError

        set_setting('default_team_names', '["测试团队"]')
        client = app.test_client()
        client.environ_base["HTTP_USER_AGENT"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        session = client.post('/api/auth/session', json={'team_name': '测试团队', 'member_name': '测试用户'})
        assert_true(session.status_code == 200, session.get_data(as_text=True))
        headers = {'Authorization': f"Bearer {session.get_json()['token']}"}
        payload = {'message': '并发保护测试', 'query_type': '产品咨询'}

        original_limiter = chat_routes._stream_limiter
        chat_routes._stream_limiter = ConcurrentRequestLimiter(1)
        try:
            assert_true(chat_routes._stream_limiter.try_acquire() == 1, 'test should occupy the only stream slot')
            queued = client.post('/api/chat/stream', headers=headers, json=payload)
            assert_true(queued.status_code == 202, queued.get_data(as_text=True))
            queued_data = queued.get_json()
            assert_true(queued_data.get('status') == 'queued', queued_data)
            assert_true(queued_data.get('job_id'), queued_data)
            cancelled = client.post(
                f"/api/chat/jobs/{queued_data['job_id']}/cancel",
                headers=headers,
            )
            assert_true(cancelled.status_code == 200, cancelled.get_data(as_text=True))
            chat_routes._stream_limiter.release()

            def successful_stream(ctx):
                yield {
                    'event': 'done',
                    'data': {
                        'full_text': '测试回答',
                        'history_id': 1,
                        'coze_message_id': '',
                        'request_id': ctx.request_id,
                        'related_cases': [],
                        'related_cases_total': 0,
                    },
                }

            with patch('routes.chat.iter_coze_stream', side_effect=successful_stream):
                completed = client.post('/api/chat/stream', headers=headers, json=payload)
                assert_true(completed.status_code == 200, completed.get_data(as_text=True))
                assert_true(b'event: done' in completed.data, completed.data)
            assert_true(chat_routes._stream_limiter.active == 0, 'normal completion should release the slot')

            def failing_stream(_ctx):
                raise ChatServiceError('模拟上游失败', status_code=502, retryable=True)
                yield  # pragma: no cover - keeps this function a generator

            with patch('routes.chat.iter_coze_stream', side_effect=failing_stream):
                failed = client.post('/api/chat/stream', headers=headers, json=payload)
                assert_true(failed.status_code == 200, failed.get_data(as_text=True))
                assert_true(b'event: error' in failed.data, failed.data)
            assert_true(chat_routes._stream_limiter.active == 0, 'upstream failure should release the slot')

            def interrupted_stream(ctx):
                yield {'event': 'status', 'data': {'status': 'connected', 'request_id': ctx.request_id}}
                yield {'event': 'delta', 'data': {'text': 'partial', 'request_id': ctx.request_id}}

            with patch('routes.chat.iter_coze_stream', side_effect=interrupted_stream):
                interrupted = client.post('/api/chat/stream', headers=headers, json=payload, buffered=False)
                assert_true(chat_routes._stream_limiter.active == 1, 'open response should retain the stream slot')
                interrupted.close()
            assert_true(chat_routes._stream_limiter.active == 0, 'closing the client response should release the slot')
        finally:
            while chat_routes._stream_limiter.active:
                chat_routes._stream_limiter.release()
            chat_routes._stream_limiter = original_limiter

    print('PASS: chat stream capacity limiter')


if __name__ == '__main__':
    main()
