import jwt
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, request, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from models import create_user, get_setting, get_user_by_username, get_user_by_id, update_user_password_hash
from services.security_service import rate_limit

auth_bp = Blueprint('auth', __name__)

def hash_password(password):
    return generate_password_hash(password)

def verify_password(password, password_hash):
    if not password_hash:
        return False
    # Backward compatibility for old sha256 records.
    if len(password_hash) == 64 and all(c in '0123456789abcdef' for c in password_hash.lower()):
        return hashlib.sha256(password.encode()).hexdigest() == password_hash
    return check_password_hash(password_hash, password)

def generate_token(user_id):
    now = datetime.now(timezone.utc)
    payload = {
        'sub': user_id,
        'user_id': user_id,
        'token_type': 'user',
        'iat': now,
        'exp': now + timedelta(days=7),
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def generate_guest_token(user_id, team_name, member_name):
    now = datetime.now(timezone.utc)
    payload = {
        'sub': user_id,
        'user_id': user_id,
        'token_type': 'guest',
        'team_name': team_name,
        'member_name': member_name,
        'iat': now,
        'exp': now + timedelta(days=7),
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')


def _decode_request_token():
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    token = header[7:].strip()
    if not token:
        return None
    return jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])


def _identity_from_payload(payload, *, allow_guest=True, require_user=False):
    token_type = payload.get('token_type') or 'user'
    user_id = payload.get('sub') or payload.get('user_id')
    if not user_id:
        return None
    if token_type == 'guest':
        if require_user or not allow_guest:
            return None
        return {
            'user_id': user_id,
            'token_type': 'guest',
            'team_name': payload.get('team_name', ''),
            'member_name': payload.get('member_name', ''),
        }
    user = get_user_by_id(user_id)
    if not user:
        return None
    return {
        'user_id': user_id,
        'token_type': 'user',
        'team_name': '',
        'member_name': user.get('username', ''),
        'user': user,
    }


def get_optional_identity():
    try:
        payload = _decode_request_token()
        return _identity_from_payload(payload) if payload else None
    except jwt.InvalidTokenError:
        return None


def identity_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            payload = _decode_request_token()
            identity = _identity_from_payload(payload) if payload else None
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        if not identity:
            return jsonify({'error': 'Valid session token is required'}), 401
        g.request_identity = identity
        return f(identity, *args, **kwargs)
    return decorated

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            payload = _decode_request_token()
            identity = _identity_from_payload(payload, allow_guest=False, require_user=True) if payload else None
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        if not identity:
            return jsonify({'error': 'User token is required'}), 401
        current_user = identity['user']
        g.request_identity = identity
        return f(current_user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            payload = _decode_request_token()
            identity = _identity_from_payload(payload, allow_guest=False, require_user=True) if payload else None
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        if not identity:
            return jsonify({'error': 'User token is required'}), 401
        current_user = identity['user']
        if not current_user.get('is_admin'):
            return jsonify({'error': 'Admin access required'}), 403
        g.request_identity = identity
        return f(current_user, *args, **kwargs)
    return decorated

@auth_bp.route('/register', methods=['POST'])
@rate_limit('auth-register', limit=5, window_seconds=600)
def register():
    if not Config.PUBLIC_REGISTRATION_ENABLED:
        return jsonify({'error': 'Public registration is disabled'}), 403
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    if len(username) > 50 or not re.fullmatch(r'[A-Za-z0-9_.\-\u4e00-\u9fff]+', username):
        return jsonify({'error': 'Username format is invalid'}), 400
    if not 10 <= len(password) <= 128:
        return jsonify({'error': 'Password must contain 10 to 128 characters'}), 400

    password_hash = hash_password(password)
    user_id = create_user(username, password_hash, is_admin=0)

    if user_id is None:
        return jsonify({'error': 'Username already exists'}), 409

    token = generate_token(user_id)
    return jsonify({
        'message': 'Registration successful',
        'token': token,
        'user_id': user_id,
        'is_admin': 0
    }), 201

@auth_bp.route('/login', methods=['POST'])
@rate_limit('auth-login', limit=10, window_seconds=600)
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400

    user = get_user_by_username(username)
    if not user or not verify_password(password, user['password_hash']):
        return jsonify({'error': 'Invalid username or password'}), 401

    # Upgrade legacy sha256 password hash after successful login.
    current_hash = user.get('password_hash') or ''
    if len(current_hash) == 64 and all(c in '0123456789abcdef' for c in current_hash.lower()):
        update_user_password_hash(user['user_id'], hash_password(password))

    token = generate_token(user['user_id'])
    return jsonify({
        'message': 'Login successful',
        'token': token,
        'user_id': user['user_id'],
        'is_admin': user.get('is_admin', 0)
    })


@auth_bp.route('/session', methods=['POST'])
@rate_limit('session', limit=10, window_seconds=60)
def create_guest_session():
    import json

    data = request.get_json(silent=True) or {}
    team_name = (data.get('team_name') or '').strip()
    member_name = (data.get('member_name') or '').strip()
    if not 1 <= len(member_name) <= 20:
        return jsonify({'error': '姓名长度必须为 1 到 20 个字符'}), 400

    try:
        configured_teams = json.loads(get_setting('default_team_names', '[]'))
    except (TypeError, ValueError):
        configured_teams = []
    teams = [str(item).strip() for item in configured_teams if str(item).strip()]
    if not teams:
        legacy_team = get_setting('default_team_name', '').strip()
        teams = [legacy_team] if legacy_team else []
    if not teams:
        return jsonify({'error': '系统尚未配置团队'}), 503
    if team_name not in teams:
        return jsonify({'error': '请选择管理员配置的团队'}), 403

    existing_token = request.headers.get('Authorization', '')
    try:
        existing_payload = _decode_request_token()
    except jwt.InvalidTokenError:
        existing_payload = None
    if (
        existing_payload
        and existing_payload.get('token_type') == 'guest'
        and existing_payload.get('team_name') == team_name
        and existing_payload.get('member_name') == member_name
    ):
        token = existing_token[7:].strip()
    else:
        token = generate_guest_token(uuid.uuid4().hex, team_name, member_name)
    return jsonify({'token': token, 'expires_in': 7 * 24 * 60 * 60})
