#!/usr/bin/env python3
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-chat-queue-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'
        os.environ['CHAT_QUEUE_MAX_SIZE'] = '10'
        os.environ['CHAT_QUEUE_TTL_SECONDS'] = '300'
        os.environ['CHAT_QUEUE_POLL_INTERVAL_SECONDS'] = '30'

        import sys
        sys.path.insert(0, str(ROOT))
        from app import app
        from services.chat_queue_service import (
            cancel_job,
            claim_next_job,
            complete_job,
            enqueue_job,
            get_job,
        )

        contexts = [SimpleNamespace(
            message=f'问题 {index}',
            query_type='产品咨询',
            agent_id='aura',
            channel='',
            user_id=f'user-{index}',
            team_name='测试团队',
            member_name=f'用户 {index}',
            request_id=f'request-{index}',
        ) for index in range(11)]

        jobs = []
        for ctx in contexts[:10]:
            result = enqueue_job(ctx)
            assert_true(not result.get('full'), 'the first ten jobs should fit in the queue')
            assert_true(result['position'] == len(jobs) + 1, 'jobs should be FIFO')
            jobs.append(result['job']['job_id'])

        full = enqueue_job(contexts[10])
        assert_true(full.get('full') is True, 'the eleventh queued job should be rejected')

        first = claim_next_job(worker_pid=123)
        assert_true(first['job_id'] == jobs[0], 'the oldest queued job should be claimed first')
        assert_true(first['status'] == 'running', 'claimed job should become running')
        assert_true(get_job(jobs[0], contexts[0].user_id)['status'] == 'running', 'owner can read running status')

        complete_job(jobs[0], {
            'bot_response': '测试回答',
            'history_id': 11,
            'related_cases': [],
            'related_cases_total': 0,
        })
        completed = get_job(jobs[0], contexts[0].user_id)
        assert_true(completed['status'] == 'completed', 'completed job should be readable')
        assert_true(completed['bot_response'] == '测试回答', 'completed result should be returned')

        cancelled = cancel_job(jobs[1], contexts[1].user_id)
        assert_true(cancelled['status'] == 'cancelled', 'queued job should be cancellable')
        assert_true(get_job(jobs[1], contexts[1].user_id)['status'] == 'cancelled', 'cancelled status should persist')

        for index in range(2, 10):
            cancel_job(jobs[index], contexts[index].user_id)
        dispatch_job = enqueue_job(contexts[10])
        assert_true(dispatch_job.get('job'), 'a slot should be available after cancellations')

        from services.chat_queue_service import ChatQueueDispatcher
        from services.security_service import ConcurrentRequestLimiter
        dispatcher = ChatQueueDispatcher(ConcurrentRequestLimiter(1))
        with patch('services.chat_queue_service.execute_sync_chat', return_value={
            'bot_response': '后台回答',
            'history_id': 12,
            'related_cases': [],
            'related_cases_total': 0,
        }):
            dispatcher._dispatch_available()
            with dispatcher._jobs_lock:
                running = list(dispatcher._jobs)
            for thread in running:
                thread.join(timeout=3)
        dispatched = get_job(dispatch_job['job']['job_id'], contexts[10].user_id)
        assert_true(dispatched['status'] == 'completed', 'dispatcher should complete a queued job')
        dispatcher.stop_for_tests()

        app.test_client()  # Keep the import path covered without making an external request.
    print('PASS: chat queue smoke test')


if __name__ == '__main__':
    main()
