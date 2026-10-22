#!/usr/bin/env python3
"""Isolated HTTP/MCP regression checks for remote question-bank management."""

import csv
import io
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='acs-bank-mcp-') as tmp:
        os.environ.update(DATABASE_DIR=tmp, UPLOAD_DIR=str(Path(tmp) / 'uploads'),
                          SECRET_KEY='test-bank-mcp-secret-key-at-least-32-bytes',
                          COZE_API_KEY='test-key', CRAWL_GUARD_ENABLED='false',
                          MCP_TOKEN='readonly-token-' + 'a' * 32,
                          PRACTICE_BANK_MCP_TOKEN='bank-write-token-' + 'b' * 32)
        from app import app
        from config import Config
        from models import create_product
        from services.practice_bank import RAW
        from services import practice_service as practice

        client = app.test_client()
        bank_auth = {'Authorization': 'Bearer ' + Config.PRACTICE_BANK_MCP_TOKEN}
        read_auth = {'Authorization': 'Bearer ' + Config.MCP_TOKEN}

        def call(name, arguments=None, headers=None, endpoint='/api/mcp/practice-bank'):
            response = client.post(endpoint, headers=headers or bank_auth, json={
                'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': name, 'arguments': arguments or {}},
            })
            if response.status_code != 200:
                return response.status_code, response.get_json()
            result = response.get_json()['result']
            if result.get('isError'):
                return 'error', result['content'][0]['text']
            return 'ok', json.loads(result['content'][0]['text'])

        def listing(headers, endpoint):
            response = client.post(endpoint, headers=headers, json={
                'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list',
            })
            return response.status_code, response.get_json()

        status, payload = listing(bank_auth, '/api/mcp/practice-bank')
        assert status == 200
        bank_names = {item['name'] for item in payload['result']['tools']}
        assert {'practice_bank_overview', 'practice_list_questions', 'practice_get_question',
                'practice_create_question', 'practice_update_question',
                'practice_preview_csv', 'practice_import_csv',
                'practice_list_products', 'practice_get_product_context',
                'practice_learning_guidelines', 'practice_learning_outline',
                'practice_suggest_placement'} <= bank_names
        assert 'list_leads' not in bank_names
        negotiated = client.post('/api/mcp/practice-bank', headers=bank_auth, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2026-07-28'},
        }).get_json()['result']
        assert negotiated['protocolVersion'] == '2025-06-18'
        assert negotiated['serverInfo']['name'] == 'ai-baoer-practice-bank'
        assert listing(read_auth, '/api/mcp/practice-bank')[0] == 401
        assert listing(bank_auth, '/api/mcp')[0] == 401
        readonly_names = {tool['name'] for tool in listing(read_auth, '/api/mcp')[1]['result']['tools']}
        assert 'practice_update_question' not in readonly_names
        assert client.get('/api/mcp/practice-bank', headers=bank_auth).status_code == 405
        assert client.post('/api/mcp/practice-bank', headers={**bank_auth, 'Origin': 'https://evil.example'},
                           json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).status_code == 403

        token = Config.PRACTICE_BANK_MCP_TOKEN
        Config.PRACTICE_BANK_MCP_TOKEN = ''
        assert listing(bank_auth, '/api/mcp/practice-bank')[0] == 403
        Config.PRACTICE_BANK_MCP_TOKEN = Config.MCP_TOKEN
        assert listing(bank_auth, '/api/mcp/practice-bank')[0] == 403
        Config.PRACTICE_BANK_MCP_TOKEN = token

        status, overview = call('practice_bank_overview')
        assert status == 'ok' and overview['banks'][0]['stage_id'] == 0
        assert '推荐答案' in overview['csv_columns']
        status, guide = call('practice_learning_guidelines')
        assert status == 'ok' and [item['level'] for item in guide['levels']] == [1, 2, 3, 4, 5]
        assert [item['level'] for item in guide['unit_sequence']] == [1, 2, 3, 3, 4, 4, 5]
        assert call('practice_learning_guidelines', {'unexpected': True})[0] == 'error'
        product_id = create_product('益生菌', '题库测试产品', '', '', '', '')
        assert call('practice_list_products', {'keyword': '题库测试产品'})[1]['items'][0]['id'] == product_id
        assert call('practice_get_product_context', {'product_id': product_id})[1]['facts'] == []
        status, page = call('practice_list_questions', {'stage_id': 0, 'limit': 5})
        assert status == 'ok' and len(page['items']) == 5

        request_id = uuid.uuid4().hex
        question = {'batch_no': 999, 'category': next(iter(RAW)),
                    'title': '客户询问如何比较两款产品？',
                    'options': ['先对齐规格', '只说贵的好', '直接打折', '不回答'],
                    'answer_index': 0, 'explanation': '先用相同维度比较。',
                    'method': '我们先核对规格。'}
        args = {'request_id': request_id, 'question': question}
        status, created = call('practice_create_question', args)
        assert status == 'ok' and created['enabled'] == 0
        assert call('practice_create_question', args)[1]['id'] == created['id']
        status, fetched = call('practice_get_question', {'question_id': created['id']})
        assert status == 'ok' and fetched['title'] == question['title']
        status, updated = call('practice_update_question', {
            'question_id': created['id'], 'updated_at': fetched['updated_at'],
            'changes': {'title': '客户要求比较两款产品，先说什么？'},
        })
        assert status == 'ok' and updated['title'] != fetched['title'], (status, updated)
        assert call('practice_update_question', {
            'question_id': created['id'], 'updated_at': 'stale-version',
            'changes': {'title': '不能覆盖新版'},
        })[0] == 'error'
        assert call('practice_update_question', {
            'question_id': created['id'], 'updated_at': updated['updated_at'],
            'changes': {'archived': 1},
        })[0] == 'error'
        from services import practice_path
        practice_path.initialize('独立培训产品')
        outline = call('practice_learning_outline')[1]
        assert outline['settings']['product_name'] == '独立培训产品'
        unit = outline['units'][0]
        assert call('practice_update_question', {'question_id': created['id'],
            'updated_at': updated['updated_at'], 'changes': {'difficulty_level': 1}})[0] == 'error'
        status, suggestion = call('practice_suggest_placement', {
            'question_id': created['id'], 'unit_id': unit['id'],
            'learning_objective': '认识产品信息', 'difficulty_level': unit['level']})
        assert status == 'ok' and suggestion['status'] == 'pending'
        assert call('practice_get_question', {'question_id': created['id']})[1]['difficulty_level'] is None

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(practice.CSV_COLUMNS)
        writer.writerow(['', 999, next(iter(RAW)), '客户问这款产品怎样储存？',
                         '先看产品标签', '按其他款经验说', '猜一个温度', '随便放',
                         'A', '核对具体产品说明。', '我查一下这款的储存说明。', '0', '', '', '', '', '', '', '', ''])
        csv_text = output.getvalue()
        status, preview = call('practice_preview_csv', {'stage_id': 0, 'csv': csv_text})
        assert status == 'ok' and preview['added'] == 1 and not preview['errors']
        import_args = {'request_id': uuid.uuid4().hex, 'stage_id': 0, 'csv': csv_text}
        status, imported = call('practice_import_csv', import_args)
        assert status == 'ok' and imported['added'] == 1
        assert call('practice_import_csv', import_args)[1]['ids'] == imported['ids']
        assert call('practice_import_csv', {**import_args, 'csv': csv_text + '\n'})[0] == 'error'
        invalid_csv = csv_text.replace('先看产品标签', '先看产品标签,先看产品标签', 1)
        with practice.db() as conn:
            before_invalid = conn.execute('SELECT COUNT(*) FROM practice_quiz_questions').fetchone()[0]
        assert call('practice_import_csv', {'request_id': uuid.uuid4().hex,
                                            'csv': invalid_csv})[0] == 'error'
        with practice.db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM practice_quiz_questions').fetchone()[0] == before_invalid
        assert call('practice_preview_csv', {'csv': csv_text, 'replace': True})[0] == 'error'
        with practice.db() as conn:
            before = conn.execute('SELECT COUNT(*) FROM practice_quiz_questions WHERE archived=0').fetchone()[0]
        assert call('practice_import_csv', {**import_args, 'request_id': uuid.uuid4().hex,
                                            'replace': True})[0] == 'error'
        with practice.db() as conn:
            after = conn.execute('SELECT COUNT(*) FROM practice_quiz_questions WHERE archived=0').fetchone()[0]
        assert before == after
        # The public MCP still has no write tools, even when called with a valid read token.
        assert call('practice_update_question', {}, read_auth, '/api/mcp')[0] == 'error'

        from scripts import practice_bank_mcp_bridge as bridge
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, *_):
                return b'{"jsonrpc":"2.0","id":7,"result":{"tools":[]}}'
        outgoing = io.StringIO()
        message = json.dumps({'jsonrpc': '2.0', 'id': 7, 'method': 'tools/list'}) + '\n'
        with patch.object(bridge.sys, 'stdin', io.StringIO(message)), \
             patch.object(bridge.sys, 'stdout', outgoing), \
             patch.object(bridge, 'urlopen', return_value=FakeResponse()) as opened:
            assert bridge.main() == 0
        assert json.loads(outgoing.getvalue())['result']['tools'] == []
        assert opened.call_args.args[0].get_header('Authorization') == 'Bearer ' + token

    print('test_practice_bank_mcp: all checks passed')


if __name__ == '__main__':
    main()
