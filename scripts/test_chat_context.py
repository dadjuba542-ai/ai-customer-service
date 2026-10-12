#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-chat-context-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'
        os.environ['CHAT_CONTEXT_ROUNDS'] = '6'
        os.environ['CHAT_CONTEXT_DELIVERY'] = 'query'
        os.environ['COZE_CHAT_API_VERSION'] = 'v2'

        sys.path.insert(0, str(ROOT))
        from app import app  # noqa: F401  触发 init_db / 初始化智能体
        from config import Config
        from models import get_chat_history_by_id, get_context_floor, reset_chat_context, save_chat_history
        from routes.auth import generate_guest_token
        from services.chat_service import build_chat_context, build_coze_chat_history, execute_sync_chat, iter_coze_stream
        from services.chat_queue_service import ChatQueueDispatcher, enqueue_job, claim_next_job, get_job

        first_ctx = build_chat_context({'message': '首轮问题', 'agent_id': 'aura'}, {'user_id': 'first-user'})
        assert_true(first_ctx.payload['query'] == '首轮问题', 'first input must stay unchanged')

        user_id = 'ctx-user'
        for index in range(1, 8):
            save_chat_history(
                user_id, '产品咨询', f'问题{index}', f'回答{index}', agent_id='aura',
            )
        # 同用户、不同智能体：不应混入 aura 的上下文
        save_chat_history(user_id, '使用答疑', '别的问题', '别的回答', agent_id='coder')
        # 其他用户：不应混入
        save_chat_history('other-user', '产品咨询', '他人问题', '他人回答', agent_id='aura')

        history = build_coze_chat_history(user_id, 'aura', '产品咨询')
        assert_true(len(history) == 12, f'expected 6 rounds (12 messages), got {len(history)}')
        assert_true(
            [item['role'] for item in history] == ['user', 'assistant'] * 6,
            f'roles should alternate user/assistant: {history}',
        )
        assert_true(
            all(item.get('content_type') == 'text' for item in history),
            'every history item must declare content_type=text',
        )
        # 只保留最近 6 轮：最早的“问题1”应被裁掉
        assert_true(history[0]['content'] == '问题2', f'the oldest round should be trimmed: {history[0]}')
        assert_true(history[-1]['content'] == '回答7', f'the newest reply should be last: {history[-1]}')
        assert_true(
            all('别的问题' not in item['content'] for item in history),
            'history must not leak from another agent',
        )
        assert_true(
            all('他人问题' not in item['content'] for item in history),
            'history must not leak from another user',
        )

        ctx = build_chat_context(
            {'message': '新的追问', 'agent_id': 'aura'},
            {'user_id': user_id, 'team_name': '', 'member_name': ''},
        )
        expected_query = '历史问题（按时间从早到晚）：\n1. 问题3\n2. 问题4\n3. 问题5\n4. 问题6\n5. 问题7\n6. 别的问题\n本次用户输入：\n新的追问'
        assert_true(ctx.payload['query'] == expected_query, 'query should contain only the six latest questions in order')
        assert_true(ctx.payload['query'].endswith('\n本次用户输入：\n新的追问'), 'current input must be last')
        assert_true(ctx.message == '新的追问', 'stored question must remain the original input')
        assert_true('别的问题' in ctx.payload['query'], 'agent switch should retain context')
        assert_true('问题7' in ctx.payload['query'], 'same-agent follow-up should retain context')
        assert_true('他人问题' not in ctx.payload['query'], 'shared context must remain user scoped')
        assert_true('回答' not in ctx.payload['query'] and '"role"' not in ctx.payload['query'], 'query must exclude answers and role JSON')
        assert_true('chat_history' not in ctx.payload, 'query delivery must not duplicate history')

        Config.CHAT_CONTEXT_DELIVERY = 'history'
        native_ctx = build_chat_context({'message': '原生追问', 'agent_id': 'aura'}, {'user_id': user_id})
        assert_true(native_ctx.payload['query'] == '原生追问', 'native mode keeps query unchanged')
        assert_true(len(native_ctx.payload['chat_history']) == 12, 'native mode must carry shared history')
        assert_true(native_ctx.payload['chat_history'][-1]['content'] == '别的回答', 'native mode must preserve assistant history')
        Config.CHAT_CONTEXT_DELIVERY = 'query'
        original_max_chars = Config.CHAT_CONTEXT_MESSAGE_MAX_CHARS
        Config.CHAT_CONTEXT_MESSAGE_MAX_CHARS = 2
        try:
            clipped = build_coze_chat_history(user_id, 'aura', '产品咨询', shared=True)
            assert_true(all(len(item['content']) <= 2 for item in clipped), 'shared context must respect truncation')
            clipped_ctx = build_chat_context({'message': '当前问题不截断', 'agent_id': 'aura'}, {'user_id': user_id})
            assert_true(clipped_ctx.payload['query'].endswith('6. 别的\n本次用户输入：\n当前问题不截断'), 'query should truncate only historical questions')
        finally:
            Config.CHAT_CONTEXT_MESSAGE_MAX_CHARS = original_max_chars
        assert_true(
            ctx.payload['query'].count('新的追问') == 1,
            'current message must not be duplicated into history',
        )

        # 验证真实发送路径（模拟上游，不调用付费 Coze API）。
        with patch('services.chat_service.requests.post') as post, patch('services.chat_service.find_related_cases', return_value={'items': [], 'total': 0}):
            response = MagicMock()
            response.json.return_value = {'code': 0, 'messages': [{'type': 'answer', 'content': '同步回答'}]}
            post.return_value = response
            result = execute_sync_chat(ctx)
            assert_true(post.call_args.kwargs['json']['query'] == ctx.payload['query'], 'sync must forward context')
            saved = get_chat_history_by_id(result['history_id'], user_id)
            assert_true(saved['user_message'] == '新的追问' and saved['bot_response'] == '同步回答', 'database must preserve original question and complete answer')

            response.__enter__.return_value = response
            response.iter_lines.return_value = iter([
                b'data: {"message":{"type":"answer","content":"stream reply"}}', b'', b'data: [DONE]', b'',
            ])
            events = list(iter_coze_stream(ctx))
            assert_true(events[-1]['event'] == 'done', 'stream should complete')
            assert_true(post.call_args.kwargs['json']['query'] == ctx.payload['query'], 'stream must forward context')
            assert_true(post.call_args.kwargs['json']['stream'] is True, 'stream flag should stay enabled')

            queued = enqueue_job(build_chat_context({'message': '排队追问', 'agent_id': 'coder'}, {'user_id': user_id}))
            job = claim_next_job()
            assert_true(job['job_id'] == queued['job']['job_id'], 'queued request should be claimed')
            limiter = MagicMock(active=1)
            ChatQueueDispatcher(limiter)._process_job(job, 1)
            assert_true(get_job(job['job_id'], user_id)['status'] == 'completed', 'queued request must complete')
            sent_query = post.call_args.kwargs['json']['query']
            assert_true('别的问题' in sent_query and '新的追问' in sent_query and sent_query.endswith('\n本次用户输入：\n排队追问'), 'queue must forward historical questions and current input')
            assert_true(all(answer not in sent_query for answer in ['回答', 'stream reply']), 'queue must exclude prior answers')
            limiter.release.assert_called_once()

        original_rounds = Config.CHAT_CONTEXT_ROUNDS
        Config.CHAT_CONTEXT_ROUNDS = 0
        try:
            off_ctx = build_chat_context(
                {'message': '关闭上下文', 'agent_id': 'aura'},
                {'user_id': user_id, 'team_name': '', 'member_name': ''},
            )
            assert_true('chat_history' not in off_ctx.payload, 'CHAT_CONTEXT_ROUNDS=0 should disable context')
            assert_true(off_ctx.payload['query'] == '关闭上下文', 'disabled context should keep query unchanged')
        finally:
            Config.CHAT_CONTEXT_ROUNDS = original_rounds

        # 清空即遗忘：reset 后旧历史不再带入，仅保留 reset 之后的新对话
        floor = reset_chat_context(user_id, '*')
        assert_true(floor > 0, f'reset should advance the floor, got {floor}')
        assert_true(get_context_floor(user_id, 'aura') == floor, 'floor should apply to the agent too')
        assert_true(build_chat_context({'message': '清空后追问', 'agent_id': 'coder'}, {'user_id': user_id}).payload['query'] == '清空后追问', 'global reset must forget shared context')
        assert_true(
            build_coze_chat_history(user_id, 'aura', '产品咨询') == [],
            'after reset, prior turns must be forgotten',
        )
        save_chat_history(user_id, '产品咨询', '清空后问题', '清空后回答', agent_id='aura')
        fresh = build_coze_chat_history(user_id, 'aura', '产品咨询')
        assert_true(
            [item['content'] for item in fresh] == ['清空后问题', '清空后回答'],
            f'only post-reset turns should remain: {fresh}',
        )
        fresh_ctx = build_chat_context({'message': '新追问', 'agent_id': 'coder'}, {'user_id': user_id})
        assert_true(fresh_ctx.payload['query'] == '历史问题（按时间从早到晚）：\n1. 清空后问题\n本次用户输入：\n新追问', 'post-reset query should include only the new question')

        # 接口层：POST /api/chat/context/reset 与 GET /api/chat/context/floor
        client = app.test_client()
        auth = {'Authorization': f'Bearer {generate_guest_token(user_id, "", "")}'}
        reset_res = client.post('/api/chat/context/reset', headers=auth, json={})
        assert_true(reset_res.status_code == 200, f'context reset endpoint failed: {reset_res.get_data(as_text=True)}')
        assert_true(
            build_coze_chat_history(user_id, 'aura', '产品咨询') == [],
            'endpoint reset should also clear context',
        )
        floor_res = client.get('/api/chat/context/floor?agent_id=aura', headers=auth)
        assert_true(floor_res.status_code == 200, floor_res.get_data(as_text=True))
        assert_true(floor_res.get_json()['floor_history_id'] == reset_res.get_json()['floor_history_id'], 'floor should round-trip')

        save_chat_history(user_id, '产品咨询', '单智能体清空前', '旧回答', agent_id='aura')
        save_chat_history(user_id, '使用答疑', '另一个智能体保留', '保留回答', agent_id='coder')
        reset_chat_context(user_id, 'aura')
        shared = build_coze_chat_history(user_id, 'coder', '使用答疑', shared=True)
        assert_true([item['content'] for item in shared] == ['另一个智能体保留', '保留回答'], 'shared context must respect per-agent reset')
        retained_ctx = build_chat_context({'message': '继续', 'agent_id': 'coder'}, {'user_id': user_id})
        assert_true(retained_ctx.payload['query'] == '历史问题（按时间从早到晚）：\n1. 另一个智能体保留\n本次用户输入：\n继续', 'query must respect per-agent reset and exclude retained answers')

        print('PASS: chat context smoke test')


if __name__ == '__main__':
    main()
