#!/usr/bin/env python3
"""诊断开关、摘要脱敏、对照脚本和失败路径回归；不调用真实 API。"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Config
from services.chat_service import ChatRequestContext, ChatServiceError, iter_coze_stream, execute_sync_chat
from services.coze_diagnostics import CozeDiagnostics, safe_url
from scripts.diagnose_coze import deployment_config, main, run_direct_test
from scripts.test_chat_v3 import FakeResponse, sse
from services.secret_service import encrypt_secret
import requests


def main_test():
    assert Config.COZE_DIAGNOSTICS_ENABLED is False
    ctx = ChatRequestContext('CURRENT_PRIVATE', '朋友圈帮写', 'translator', 'USER_PRIVATE', '', '',
        {'Authorization': 'Bearer TOKEN_PRIVATE'},
        {'bot_id': '7641767867948302342', 'user_id': 'USER_PRIVATE', 'stream': True,
         'additional_messages': [{'role': 'user', 'content': 'HISTORY_PRIVATE'},
             {'role': 'assistant', 'content': 'OLD_ANSWER_PRIVATE'}, {'role': 'user', 'content': 'CURRENT_PRIVATE'}]},
        'request123')
    def msg(kind, content, id):
        return {'id': id, 'conversation_id': 'conversation123', 'chat_id': 'chat123', 'role': 'assistant',
                'type': kind, 'content_type': 'text', 'content': content}
    events = sse('conversation.chat.created', {'conversation_id': 'conversation123', 'id': 'chat123'})
    events += sse('conversation.message.delta', msg('knowledge', 'KNOWLEDGE_PRIVATE', 'k1'))
    events += sse('conversation.message.completed', msg('knowledge', 'KNOWLEDGE_PRIVATE', 'k1'))
    events += sse('conversation.message.completed', msg('function_call', json.dumps({'name': 'search_knowledge', 'arguments': 'ARGUMENT_PRIVATE'}), 'f1'))
    events += sse('conversation.message.completed', msg('tool_response', 'TOOL_PRIVATE', 't1'))
    events += sse('conversation.message.completed', msg('tool_output', 'TOOL_PRIVATE', 't2'))
    events += sse('conversation.message.delta', msg('answer', '正式', 'a1'))
    events += sse('conversation.message.completed', msg('answer', '正式回答', 'a1'))
    events += sse('conversation.chat.completed', {'status': 'completed'})

    with patch('services.chat_service.find_related_cases', return_value={'items': [], 'total': 0}), \
            patch('services.chat_service.persist_chat_history', return_value=42), \
            patch('services.chat_service.requests.post', side_effect=lambda *a, **k: FakeResponse(events)), \
            patch('services.coze_diagnostics.logger.warning') as log:
        Config.COZE_DIAGNOSTICS_ENABLED = False
        baseline = list(iter_coze_stream(ctx))
        log.assert_not_called()
        Config.COZE_DIAGNOSTICS_ENABLED = True
        observed = list(iter_coze_stream(ctx))
        assert observed == baseline, 'enabling diagnostics must not change SSE or history IDs'
        assert log.call_count == 2
        result = json.loads(log.call_args.args[1])
        assert result['phase'] == 'result' and result['outcome'] == 'success'
        assert result['conversation_id'] == 'conversation123' and result['chat_id'] == 'chat123'
        assert result['history_message_count'] == 2 and result['current_question_independent'] is True
        assert result['messages_by_type']['knowledge'] == 1 and result['message_events']['knowledge'] == 2
        assert result['messages_by_type']['answer'] == 1
        assert result['messages_by_type']['tool_response'] == result['messages_by_type']['tool_output'] == 1
        assert result['knowledge_content_chars'] == len('KNOWLEDGE_PRIVATE')
        assert result['tool_names'] == ['search_knowledge']
        logged = str(log.call_args_list)
        for secret in ['TOKEN_PRIVATE', 'USER_PRIVATE', 'HISTORY_PRIVATE', 'OLD_ANSWER_PRIVATE',
                       'CURRENT_PRIVATE', 'KNOWLEDGE_PRIVATE', 'ARGUMENT_PRIVATE', 'TOOL_PRIVATE', '正式回答']:
            assert secret not in logged, secret
        assert execute_sync_chat(ctx)['bot_response'] == '正式回答'

    v2_ctx = replace(ctx, payload={'bot_id': 'bot123', 'user': 'USER_PRIVATE', 'query': ctx.message,
                                 'chat_history': [{'role': 'user', 'content': 'HISTORY_PRIVATE'}]})
    with patch('services.chat_service.find_related_cases', return_value={'items': [], 'total': 0}), \
            patch('services.chat_service.persist_chat_history', return_value=42), \
            patch('services.chat_service.requests.post', return_value=FakeResponse(json_body={
                'code': 0, 'conversation_id': 'v2-conversation', 'messages': [
                    {'type': 'knowledge', 'content': 'KNOWLEDGE_PRIVATE'}, {'type': 'answer', 'content': 'V2 正式回答'}]})), \
            patch('services.coze_diagnostics.logger.warning') as log:
        assert execute_sync_chat(v2_ctx)['bot_response'] == 'V2 正式回答'
        report = json.loads(log.call_args.args[1])
        assert report['api_version'] == 'v2' and report['history_message_count'] == 1
        assert report['conversation_id'] == 'v2-conversation' and report['messages_by_type']['knowledge'] == 1
        assert 'KNOWLEDGE_PRIVATE' not in str(log.call_args_list)

    failures = [
        (sse('conversation.chat.failed', {'code': 401, 'msg': 'ERROR_PRIVATE'}), 'error'),
        (sse('error', {'code': 4000, 'msg': 'ERROR_PRIVATE'}), 'error'),
        (sse('conversation.message.delta', msg('answer', '部分', 'a1')), 'error'),
    ]
    for upstream, outcome in failures:
        with patch('services.chat_service.find_related_cases', return_value={'items': [], 'total': 0}), \
                patch('services.chat_service.requests.post', return_value=FakeResponse(upstream)), \
                patch('services.chat_service.persist_chat_history') as save, \
                patch('services.coze_diagnostics.logger.warning') as log:
            try:
                list(iter_coze_stream(ctx))
            except ChatServiceError:
                pass
            else:
                raise AssertionError('failure should still raise')
            save.assert_not_called()
            summary = json.loads(log.call_args.args[1])
            assert summary['outcome'] == outcome and 'ERROR_PRIVATE' not in str(log.call_args_list)
    with patch('services.chat_service.find_related_cases', return_value={'items': [], 'total': 0}), \
            patch('services.chat_service.requests.post', return_value=FakeResponse(events)), \
            patch('services.coze_diagnostics.logger.warning') as log:
        stream = iter_coze_stream(ctx)
        next(stream)
        stream.close()
        assert json.loads(log.call_args.args[1])['outcome'] == 'interrupted'

    with patch('services.chat_service.find_related_cases', return_value={'items': [], 'total': 0}), \
            patch('services.chat_service.requests.post', side_effect=requests.exceptions.Timeout), \
            patch('services.coze_diagnostics.logger.warning') as log:
        try:
            list(iter_coze_stream(ctx))
        except ChatServiceError as exc:
            assert exc.status_code == 504
        else:
            raise AssertionError('timeout should still raise')
        assert json.loads(log.call_args.args[1])['outcome'] == 'timeout'

    assert safe_url('https://user:TOKEN_PRIVATE@api.example/v3/chat?token=TOKEN_PRIVATE#private') == 'https://api.example/v3/chat'
    result = run_direct_test('bot123', 'TOKEN_PRIVATE', '原始问题', post=lambda *a, **k: FakeResponse(events))
    assert result['answers'] == ['正式回答'] and result['answer_complete']
    assert result['diagnostic']['history_message_count'] == 0
    assert result['diagnostic']['publish_status'] == 'published_online'
    assert 'TOKEN_PRIVATE' not in json.dumps(result)
    result = run_direct_test('bot123', 'TOKEN_PRIVATE', '原始问题', post=lambda *a, **k: FakeResponse(sse('conversation.chat.failed', {'code': 1})))
    assert result['diagnostic']['error_events'] == 1 and not result['answer_complete']
    result = run_direct_test('bot123', 'TOKEN_PRIVATE', '原始问题', post=lambda *a, **k: FakeResponse(events[:-3]))
    assert result['diagnostic']['outcome'] == 'incomplete'

    with tempfile.TemporaryDirectory(prefix='acs-coze-diagnostics-') as tmpdir:
        Config.DATABASE_PATH = str(Path(tmpdir) / 'db.sqlite')
        Config.SECRET_KEY = 'test-secret-key-32-bytes-minimum!!'
        Config.COZE_API_KEY = 'ENVIRONMENT_PRIVATE'
        with sqlite3.connect(Config.DATABASE_PATH) as conn:
            conn.execute('CREATE TABLE agent_configs (agent_id TEXT, bot_id TEXT, type TEXT)')
            conn.execute('CREATE TABLE settings (key TEXT, value TEXT)')
            conn.execute("INSERT INTO agent_configs VALUES ('translator', 'production-bot', '朋友圈帮写')")
            conn.execute('INSERT INTO settings VALUES (?, ?)', ('coze_api_key', encrypt_secret('DATABASE_PRIVATE')))
        summary, key = deployment_config('translator')
        assert key == 'DATABASE_PRIVATE' and summary['api_key_source'] == 'database'
        assert summary['bot_id'] == 'production-bot' and summary['bot_source'] == 'database'
        before = Path(Config.DATABASE_PATH).read_bytes()
        with patch('requests.post') as post, contextlib.redirect_stdout(io.StringIO()) as stdout:
            assert main([]) == 0
            post.assert_not_called()
            assert 'PRIVATE' not in stdout.getvalue()
        assert Path(Config.DATABASE_PATH).read_bytes() == before
        with patch('requests.post', side_effect=lambda *a, **k: FakeResponse(events)) as post, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            assert main(['--live']) == 0
            payload = post.call_args.kwargs['json']
            assert payload['bot_id'] == 'production-bot' and len(payload['additional_messages']) == 1
            assert post.call_args.kwargs['headers']['Authorization'] == 'Bearer DATABASE_PRIVATE'
            assert 'DATABASE_PRIVATE' not in stdout.getvalue()
        assert Path(Config.DATABASE_PATH).read_bytes() == before
        Config.DATABASE_PATH = str(Path(tmpdir) / 'missing.sqlite')
        deployment_config('translator')
        assert not Path(Config.DATABASE_PATH).exists(), 'config-only must not create a database'
    Config.COZE_DIAGNOSTICS_ENABLED = False
    print('PASS: Coze diagnostics, redaction, unchanged answers and direct comparison script')


if __name__ == '__main__':
    main_test()
