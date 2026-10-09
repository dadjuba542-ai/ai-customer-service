#!/usr/bin/env python3
"""只读 MCP 端点（/api/mcp）的回归测试。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-mcp-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'
        os.environ['MCP_TOKEN'] = 'test-mcp-token'
        os.environ['CRAWL_GUARD_ENABLED'] = 'false'

        from app import app
        from config import Config
        from services.mcp_service import mask_phone, mask_wechat

        client = app.test_client()
        auth = {'Authorization': 'Bearer test-mcp-token'}

        # 1) 鉴权：无 token / 错 token 均 401
        no_token = client.post('/api/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        assert_true(no_token.status_code == 401, '缺少 token 必须 401')
        bad = client.post('/api/mcp', headers={'Authorization': 'Bearer nope'},
                          json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        assert_true(bad.status_code == 401, '错误 token 必须 401')

        # 2) 未配置 token 时端点整体关闭
        original = Config.MCP_TOKEN
        Config.MCP_TOKEN = ''
        disabled = client.post('/api/mcp', headers=auth,
                               json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        Config.MCP_TOKEN = original
        assert_true(disabled.status_code == 403, '未配置 token 必须 403')

        # 3) initialize
        init = client.post('/api/mcp', headers=auth, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18'},
        })
        assert_true(init.status_code == 200, init.get_data(as_text=True))
        init_result = init.get_json()['result']
        assert_true(init_result['serverInfo']['name'] == 'ai-customer-service', 'serverInfo 不对')
        assert_true(init_result['protocolVersion'] == '2025-06-18', '应回显客户端协议版本')

        # 4) tools/list
        listing = client.post('/api/mcp', headers=auth,
                              json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}).get_json()
        names = [tool['name'] for tool in listing['result']['tools']]
        for expected in ('chat_stats', 'top_user_questions', 'search_products', 'get_product',
                         'list_leads', 'list_agents'):
            assert_true(expected in names, '缺少工具 %s' % expected)
        assert_true(all('handler' not in tool for tool in listing['result']['tools']),
                    '不能把 handler 暴露出去')

        # 5) tools/call
        call = client.post('/api/mcp', headers=auth, json={
            'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
            'params': {'name': 'list_agents', 'arguments': {}},
        }).get_json()
        import json as _json
        text = call['result']['content'][0]['text']
        payload = _json.loads(text)
        for item in payload['items']:
            assert_true('bot_id' not in item and 'prompt' not in item,
                        'list_agents 不应返回 prompt/bot_id')

        # 6) 未知工具返回 isError，而非 500
        unknown = client.post('/api/mcp', headers=auth, json={
            'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
            'params': {'name': 'nope', 'arguments': {}},
        }).get_json()
        assert_true(unknown['result'].get('isError') is True, '未知工具应 isError')

        # 7) 通知无 id -> 202 空响应
        note = client.post('/api/mcp', headers=auth,
                           json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        assert_true(note.status_code == 202, '通知应返回 202')

        # 8) GET 不提供 SSE
        get_resp = client.get('/api/mcp', headers=auth)
        assert_true(get_resp.status_code == 405, 'GET 应返回 405')

        # 9) 脱敏
        assert_true(mask_phone('13812345678') == '138****78', '手机号脱敏不对')
        assert_true('8' not in mask_phone('13812345678')[3:-2], '手机号中间位必须打码')
        assert_true(mask_wechat('wxid_abc') == 'w***c', '微信脱敏不对')

    print('test_mcp: all checks passed')


if __name__ == '__main__':
    main()
