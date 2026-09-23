"""MCP over Streamable HTTP（只读，Bearer token 鉴权）。

- 端点：`POST /api/mcp`（JSON-RPC 2.0）
- 鉴权：`Authorization: Bearer <MCP_TOKEN>` 或请求头 `X-MCP-Token`
- 未配置 `MCP_TOKEN` 时端点整体关闭（403），不会默认暴露
- 仅返回 `application/json`；不提供 GET/SSE 服务端推送（按规范返回 405）

工具实现见 `services/mcp_service.py`。
"""

import hmac
import logging

from flask import Blueprint, jsonify, request

from config import Config
from services.mcp_service import dispatch

logger = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp', __name__)


def _expected_token():
    from services.secret_service import get_secret_setting
    return (get_secret_setting('mcp_token', Config.MCP_TOKEN) or '').strip()


def _provided_token():
    auth = request.headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return (request.headers.get('X-MCP-Token') or '').strip()


def _json_error(code, message, status):
    response = jsonify({'jsonrpc': '2.0', 'id': None, 'error': {'code': code, 'message': message}})
    response.status_code = status
    return response


@mcp_bp.route('/mcp', methods=['POST', 'GET'])
def mcp_endpoint():
    expected = _expected_token()
    if not expected:
        return _json_error(-32003, 'MCP endpoint disabled', 403)
    provided = _provided_token()
    if not provided or not hmac.compare_digest(provided, expected):
        logger.warning('mcp: unauthorized request ip=%s', request.remote_addr)
        response = _json_error(-32001, 'Unauthorized', 401)
        response.headers['WWW-Authenticate'] = 'Bearer'
        return response

    if request.method == 'GET':
        return _json_error(-32004, 'SSE stream not supported', 405)

    payload = request.get_json(silent=True)
    if payload is None:
        return _json_error(-32700, 'Parse error', 400)

    if isinstance(payload, list):
        if not payload:
            return _json_error(-32600, 'Invalid Request', 400)
        responses = [resp for resp in (dispatch(message) for message in payload) if resp is not None]
        if not responses:
            return ('', 202)
        return jsonify(responses)

    response = dispatch(payload)
    if response is None:
        return ('', 202)
    return jsonify(response)
