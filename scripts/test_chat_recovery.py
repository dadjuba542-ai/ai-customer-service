#!/usr/bin/env python3
"""空召回恢复端到端回归；模拟 Coze，不调用远端服务。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import requests
from test_chat_v3 import FakeResponse, sse


def reply(text, message_id='answer'):
    return FakeResponse(sse('conversation.message.delta', {
        'id': message_id, 'role': 'assistant', 'type': 'answer',
        'content_type': 'text', 'content': text,
    }) + sse('conversation.chat.completed', {'id': 'chat-1', 'status': 'completed'}))


def main():
    with tempfile.TemporaryDirectory(prefix='acs-recovery-') as tmp:
        os.environ.update(DATABASE_DIR=tmp, UPLOAD_DIR=str(Path(tmp) / 'uploads'),
                          SECRET_KEY='test-secret-key-32-bytes-minimum!!',
                          COZE_API_KEY='test-key', COZE_CHAT_API_VERSION='v3')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import app
        from models import set_setting, get_db_connection, save_chat_history
        from services.chat_service import (build_chat_context, iter_coze_stream,
                                           execute_sync_chat, KNOWLEDGE_EMPTY_REPLY)

        set_setting('coze_rewrite_bot_id', '123456')
        original = '这个怎么吃？'
        rewritten = '测试产品的服用方法是什么？'
        save_chat_history(user_id='prior', query_type='产品咨询', user_message='测试产品', bot_response='产品资料')

        def run(user, responses, sync=False):
            ctx = build_chat_context({'message': original, 'agent_id': 'aura'}, {'user_id': user})
            with patch('services.chat_service.requests.post', side_effect=responses) as post:
                result = execute_sync_chat(ctx) if sync else list(iter_coze_stream(ctx))
            conn = get_db_connection()
            rows = conn.execute('SELECT * FROM chat_history WHERE user_id = ?', (user,)).fetchall()
            conn.close()
            assert len(rows) == 1, (user, len(rows))
            assert rows[0]['user_message'] == original
            return result, post, rows[0]['bot_response']

        events, post, saved = run('success', [reply(KNOWLEDGE_EMPTY_REPLY), reply(rewritten), reply('有效回答', 'retry-answer')])
        assert saved == '有效回答'
        assert [e['event'] for e in events].count('done') == 1
        assert [e['data']['text'] for e in events if e['event'] == 'replace'] == ['正在换个问法查找资料…', '有效回答']
        assert post.call_count == 3
        payloads = [c.kwargs['json'] for c in post.call_args_list]
        assert payloads[0]['bot_id'] == payloads[2]['bot_id']
        assert payloads[1]['bot_id'] == '123456'
        assert payloads[1]['auto_save_history'] is False
        assert json.loads(payloads[1]['additional_messages'][-1]['content'])['original_question'] == original
        assert payloads[2]['additional_messages'][-1]['content'] == rewritten
        assert KNOWLEDGE_EMPTY_REPLY not in str(payloads[2]['additional_messages'])

        _, post, saved = run('normal', [reply('普通回答')])
        assert post.call_count == 1 and saved == '普通回答'
        _, post, saved = run('near', [reply(KNOWLEDGE_EMPTY_REPLY + '其他内容')])
        assert post.call_count == 1
        _, post, saved = run('unchanged', [reply(KNOWLEDGE_EMPTY_REPLY), reply(original)])
        assert post.call_count == 2 and saved == KNOWLEDGE_EMPTY_REPLY
        _, post, saved = run('still-empty', [reply(KNOWLEDGE_EMPTY_REPLY), reply(rewritten), reply(KNOWLEDGE_EMPTY_REPLY)])
        assert post.call_count == 3 and saved == KNOWLEDGE_EMPTY_REPLY
        for name, responses in [
            ('rewrite-failed', [reply(KNOWLEDGE_EMPTY_REPLY), requests.exceptions.Timeout()]),
            ('retry-failed', [reply(KNOWLEDGE_EMPTY_REPLY), reply(rewritten), requests.exceptions.Timeout()]),
            ('blank', [reply(KNOWLEDGE_EMPTY_REPLY), reply('   ')]),
            ('too-long', [reply(KNOWLEDGE_EMPTY_REPLY), reply('字' * 4001)]),
            ('retry-blank', [reply(KNOWLEDGE_EMPTY_REPLY), reply(rewritten), reply('   ')]),
            ('retry-partial', [reply(KNOWLEDGE_EMPTY_REPLY), reply(rewritten),
                               FakeResponse(sse('conversation.message.delta', {
                                   'role': 'assistant', 'type': 'answer', 'content_type': 'text',
                                   'content': '不完整回答',
                               }))]),
        ]:
            _, _, saved = run(name, responses)
            assert saved == KNOWLEDGE_EMPTY_REPLY
        _, post, saved = run('trimmed', [reply(' \n' + KNOWLEDGE_EMPTY_REPLY + '\n'), reply(rewritten), reply('恢复')])
        assert post.call_count == 3 and saved == '恢复'
        result, _, saved = run('sync', [reply(KNOWLEDGE_EMPTY_REPLY), reply(rewritten), reply('同步恢复回答')], sync=True)
        assert result['bot_response'] == saved == '同步恢复回答'

        # 首次调用的旧上下文原样保留，重查不注入第一轮兜底。
        ctx = build_chat_context({'message': original}, {'user_id': 'prior'})
        with patch('services.chat_service.requests.post', side_effect=[reply(KNOWLEDGE_EMPTY_REPLY), reply(rewritten), reply('恢复')]) as post:
            list(iter_coze_stream(ctx))
        first, second, third = [c.kwargs['json'] for c in post.call_args_list]
        assert first['additional_messages'][:-1] == third['additional_messages'][:-1]
        assert json.loads(second['additional_messages'][0]['content'])['recent_dialogue']

        set_setting('coze_rewrite_bot_id', '')
        _, post, saved = run('disabled', [reply(KNOWLEDGE_EMPTY_REPLY)])
        assert post.call_count == 1 and saved == KNOWLEDGE_EMPTY_REPLY

        client = app.test_client()
        assert client.get('/api/admin/settings/coze-rewrite').status_code == 401
        from routes.admin import coze_rewrite_settings
        with app.test_request_context(method='PUT', json={'bot_id': 'invalid'}):
            assert coze_rewrite_settings.__wrapped__({})[1] == 400
        with app.test_request_context(method='PUT', json={'bot_id': '123456'}):
            assert coze_rewrite_settings.__wrapped__({}).status_code == 200
        with app.test_request_context(method='GET'):
            assert coze_rewrite_settings.__wrapped__({}).get_json()['bot_id'] == '123456'
        with patch('config.Config.COZE_CHAT_API_VERSION', 'v2'):
            _, post, saved = run('v2', [FakeResponse(json_body={
                'code': 0, 'messages': [{'type': 'answer', 'content': KNOWLEDGE_EMPTY_REPLY}],
            })], sync=True)
            assert post.call_count == 1 and saved == KNOWLEDGE_EMPTY_REPLY
    print('PASS: exact fallback, bounded recovery, history, sync, failure restoration and admin config')


if __name__ == '__main__':
    main()
