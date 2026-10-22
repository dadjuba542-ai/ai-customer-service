"""MCP over Streamable HTTP，按入口隔离只读与题库管理权限。

- 只读：`POST /api/mcp`，使用 `MCP_TOKEN`
- 题库管理：`POST /api/mcp/practice-bank`，使用独立的 `PRACTICE_BANK_MCP_TOKEN`
- 鉴权：`Authorization: Bearer <token>` 或请求头 `X-MCP-Token`
- 对应令牌未配置时端点关闭（403）
- 仅返回 `application/json`；不提供 GET/SSE 服务端推送（按规范返回 405）

工具实现见 `services/mcp_service.py` 和 `services/practice_bank_mcp.py`。
"""

import hmac
import logging
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

from config import Config
from services.mcp_service import dispatch
from services import practice_bank_mcp

logger = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp', __name__)


def _expected_token():
    from services.secret_service import get_secret_setting
    return (get_secret_setting('mcp_token', Config.MCP_TOKEN) or '').strip()


def _bank_token():
    token = (Config.PRACTICE_BANK_MCP_TOKEN or '').strip()
    # 配错成只读令牌时，关闭管理端点，而非让现有只读连接获得写权限。
    return token if len(token) >= 32 and token != _expected_token() else ''


def _provided_token():
    auth = request.headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return (request.headers.get('X-MCP-Token') or '').strip()


def _json_error(code, message, status):
    response = jsonify({'jsonrpc': '2.0', 'id': None, 'error': {'code': code, 'message': message}})
    response.status_code = status
    return response


def _serve(expected, toolset=None):
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

    if toolset is practice_bank_mcp:
        origin = request.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme, parsed.netloc) != (request.scheme, request.host) or parsed.path:
                return _json_error(-32005, 'Origin not allowed', 403)
        if request.content_length is not None and request.content_length > 2200000:
            return _json_error(-32006, 'Request too large', 413)

    payload = request.get_json(silent=True)
    if payload is None:
        return _json_error(-32700, 'Parse error', 400)

    if isinstance(payload, list):
        if not payload:
            return _json_error(-32600, 'Invalid Request', 400)
        responses = [resp for resp in (dispatch(message, toolset=toolset) for message in payload) if resp is not None]
        if not responses:
            return ('', 202)
        return jsonify(responses)

    response = dispatch(payload, toolset=toolset)
    if response is None:
        return ('', 202)
    return jsonify(response)


@mcp_bp.route('/mcp', methods=['POST', 'GET'])
def mcp_endpoint():
    return _serve(_expected_token())


@mcp_bp.route('/mcp/practice-bank', methods=['POST', 'GET'])
def practice_bank_endpoint():
    return _serve(_bank_token(), practice_bank_mcp)
