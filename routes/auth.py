import jwt
import hashlib
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from models import create_user, get_user_by_username, get_user_by_id, update_user_password_hash

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
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            current_user = get_user_by_id(data['user_id'])
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            current_user = get_user_by_id(data['user_id'])
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
            if not current_user.get('is_admin'):
                return jsonify({'error': 'Admin access required'}), 403
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400

    password_hash = hash_password(password)
    user_id = create_user(username, password_hash)

    if user_id is None:
        return jsonify({'error': 'Username already exists'}), 409

    is_admin = 1 if username == Config.ADMIN_USERNAME else 0
    token = generate_token(user_id)
    return jsonify({
        'message': 'Registration successful',
        'token': token,
        'user_id': user_id,
        'is_admin': is_admin
    }), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

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
