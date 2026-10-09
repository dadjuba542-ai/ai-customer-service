#!/usr/bin/env python3
"""本地只读 MCP server（stdio 传输）。

用途：让 opencode / Claude Desktop 等 MCP host 在本机直接查询本站数据，
用于运营分析、客服质检、文案/案例创作辅助。

- 纯标准库实现（JSON-RPC 2.0，换行分隔），零依赖，本机 python3 即可运行。
- 只读，直连本地 SQLite（DATABASE_DIR / DATABASE_PATH 与主程序一致）。
- 工具实现与线上 HTTP 版共用 `services/mcp_service.py`。

线上（部署到服务器）请走 `routes/mcp.py` 暴露的 `/api/mcp`，用 token 鉴权，
再把 `opencode.json` 切成 `"type": "remote"`。详见 `docs/MCP_INTEGRATION.md`。
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.mcp_service import dispatch  # noqa: E402


def _send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    sys.stderr.write('[mcp] started pid=%s python=%s\n' % (os.getpid(), sys.version.split()[0]))
    sys.stderr.flush()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            sys.stderr.write('[mcp] skip non-JSON line: %r\n' % line[:200])
            sys.stderr.flush()
            continue
        try:
            response = dispatch(message)
        except Exception as exc:  # 保证循环不因单条消息崩溃
            sys.stderr.write('[mcp] dispatch error: %s\n' % exc)
            sys.stderr.flush()
            if isinstance(message, dict) and message.get('id') is not None:
                _send({'jsonrpc': '2.0', 'id': message.get('id'),
                       'error': {'code': -32603, 'message': 'Internal error: %s' % exc}})
            continue
        if response is not None:
            _send(response)


if __name__ == '__main__':
    main()
