#!/usr/bin/env python3
"""Dependency-free stdio bridge from a local MCP client to the remote bank MCP."""

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = 'https://aibao.jzzbaizhushou.com/api/mcp/practice-bank'


def _settings():
    url = os.environ.get('PRACTICE_BANK_MCP_URL', DEFAULT_URL).strip()
    parts = urlsplit(url)
    local = parts.hostname in ('localhost', '127.0.0.1', '::1')
    if (parts.scheme != 'https' and not (local and parts.scheme == 'http')) or not parts.hostname:
        raise ValueError('题库 MCP 地址必须使用 HTTPS；本机回环地址可使用 HTTP')
    token = os.environ.get('PRACTICE_BANK_MCP_TOKEN', '').strip()
    if not token:
        token_path = Path(os.environ.get('PRACTICE_BANK_MCP_TOKEN_FILE', ROOT / '.mcp_bank_token'))
        token = token_path.read_text(encoding='utf-8').strip()
    if len(token) < 32:
        raise ValueError('题库 MCP 令牌至少需要32位')
    return url, token


def _send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def _error(request_id, message):
    return {'jsonrpc': '2.0', 'id': request_id,
            'error': {'code': -32000, 'message': message}}


def main():
    try:
        url, token = _settings()
    except (OSError, ValueError) as exc:
        sys.stderr.write('[practice-bank-mcp] 无法启动：%s\n' % exc)
        return 1
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError('JSON-RPC 消息须为对象')
        except ValueError as exc:
            _send(_error(None, str(exc)))
            continue
        request_id = payload.get('id')
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type': 'application/json',
                                   'Accept': 'application/json, text/event-stream',
                                   'Authorization': 'Bearer ' + token}, method='POST')
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read(4_000_001)
                if not data:
                    continue  # 通知没有响应
                if len(data) > 4_000_000:
                    raise ValueError('服务端响应过大')
                _send(json.loads(data))
        except HTTPError as exc:
            # Do not echo response bodies or credentials to a model-facing error.
            if request_id is not None:
                _send(_error(request_id, '题库服务返回 HTTP %s' % exc.code))
        except (URLError, OSError, ValueError) as exc:
            if request_id is not None:
                _send(_error(request_id, '题库服务连接失败：%s' % type(exc).__name__))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
