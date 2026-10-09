#!/usr/bin/env python3
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-chat-context-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'
        os.environ['CHAT_CONTEXT_ROUNDS'] = '6'

        sys.path.insert(0, str(ROOT))
        from app import app  # noqa: F401  触发 init_db / 初始化智能体
        from config import Config
        from models import get_context_floor, reset_chat_context, save_chat_history
        from routes.auth import generate_guest_token
        from services.chat_service import build_chat_context, build_coze_chat_history

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
        assert_true(ctx.payload['query'] == '新的追问', 'current message should stay in query')
        assert_true(len(ctx.payload.get('chat_history', [])) == 12, 'context should be attached to payload')
        assert_true(
            all(item['content'] != '新的追问' for item in ctx.payload['chat_history']),
            'current message must not be duplicated into chat_history',
        )

        original_rounds = Config.CHAT_CONTEXT_ROUNDS
        Config.CHAT_CONTEXT_ROUNDS = 0
        try:
            off_ctx = build_chat_context(
                {'message': '关闭上下文', 'agent_id': 'aura'},
                {'user_id': user_id, 'team_name': '', 'member_name': ''},
            )
            assert_true('chat_history' not in off_ctx.payload, 'CHAT_CONTEXT_ROUNDS=0 should disable context')
        finally:
            Config.CHAT_CONTEXT_ROUNDS = original_rounds

        # 清空即遗忘：reset 后旧历史不再带入，仅保留 reset 之后的新对话
        floor = reset_chat_context(user_id, '*')
        assert_true(floor > 0, f'reset should advance the floor, got {floor}')
        assert_true(get_context_floor(user_id, 'aura') == floor, 'floor should apply to the agent too')
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

        print('PASS: chat context smoke test')


if __name__ == '__main__':
    main()
