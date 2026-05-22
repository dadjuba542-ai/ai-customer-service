import os
import uuid
import json
from io import BytesIO
from PIL import Image
from flask import Blueprint, request, jsonify, current_app
from models import get_all_agent_configs, get_agent_config, update_agent_config, create_agent_config, delete_agent_config, get_setting, set_setting
from config import Config
from routes.auth import admin_required

admin_bp = Blueprint('admin', __name__)

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

@admin_bp.route('/agents', methods=['GET'])
@admin_required
def list_agents(current_user):
    agents = get_all_agent_configs()
    return jsonify({'agents': agents})

@admin_bp.route('/agents/<agent_id>', methods=['GET'])
@admin_required
def get_agent(current_user, agent_id):
    agent = get_agent_config(agent_id)
    if not agent:
        return jsonify({'error': 'Agent not found'}), 404
    return jsonify(agent)

@admin_bp.route('/agents/<agent_id>', methods=['PUT'])
@admin_required
def edit_agent(current_user, agent_id):
    data = request.get_json()
    update_agent_config(
        agent_id,
        data.get('name', ''),
        data.get('description', ''),
        data.get('prompt', ''),
        data.get('avatar_url', ''),
        data.get('color', '#4F46E5'),
        data.get('bot_id', ''),
        data.get('icon', 'robot'),
        data.get('chat_desc', ''),
    )
    return jsonify({'message': 'Agent updated'})

@admin_bp.route('/agents', methods=['POST'])
@admin_required
def add_agent(current_user):
    data = request.get_json()
    agent_id = data.get('agent_id', '').strip()
    if not agent_id:
        return jsonify({'error': 'agent_id is required'}), 400
    ok = create_agent_config(
        agent_id,
        data.get('name', ''),
        data.get('type', ''),
        data.get('description', ''),
        data.get('prompt', ''),
        data.get('avatar_url', ''),
        data.get('color', '#4F46E5'),
        data.get('bot_id', ''),
        data.get('icon', 'robot'),
        data.get('chat_desc', ''),
    )
    if not ok:
        return jsonify({'error': 'agent_id already exists'}), 409
    return jsonify({'message': 'Agent created'}), 201

@admin_bp.route('/agents/<agent_id>', methods=['DELETE'])
@admin_required
def remove_agent(current_user, agent_id):
    delete_agent_config(agent_id)
    return jsonify({'message': 'Agent deleted'})

@admin_bp.route('/upload', methods=['POST'])
@admin_required
def upload_file(current_user):
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No filename'}), 400

    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
    if ext not in ALLOWED_EXT:
        return jsonify({'error': 'File type not allowed'}), 400

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({'error': '文件超过 2MB，请压缩后再上传'}), 400

    image = Image.open(file)
    if image.mode in ('RGBA', 'P'):
        image = image.convert('RGB')
    max_size = 1200
    if max(image.size) > max_size:
        ratio = max_size / max(image.size)
        new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
        image = image.resize(new_size, Image.LANCZOS)
    output = BytesIO()
    image.save(output, format='JPEG', quality=85, optimize=True)
    output.seek(0)
    filename = f"{uuid.uuid4().hex}.jpg"
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), 'wb') as f:
        f.write(output.read())
    return jsonify({'url': f'/uploads/{filename}'})

@admin_bp.route('/settings/coze-api-key', methods=['GET', 'PUT'])
@admin_required
def coze_api_key(current_user):
    if request.method == 'PUT':
        data = request.get_json()
        key = data.get('api_key', '').strip()
        if not key:
            return jsonify({'error': 'API Key is required'}), 400
        set_setting('coze_api_key', key)
        return jsonify({'message': 'API Key updated'})
    current_key = get_setting('coze_api_key', '')
    masked = current_key[:8] + '****' + current_key[-4:] if len(current_key) > 12 else ''
    return jsonify({'api_key': current_key, 'masked': masked or '未设置'})

@admin_bp.route('/settings/blocked-keywords', methods=['GET', 'PUT'])
@admin_required
def blocked_keywords(current_user):
    if request.method == 'PUT':
        data = request.get_json()
        val = data.get('keywords', '').strip()
        set_setting('blocked_keywords', val)
        return jsonify({'message': '已更新'})
    raw = get_setting('blocked_keywords', '')
    default_hint = '退款,退货,投诉,假货,骗人,诈骗,虚假宣传,副作用,无效,没效果,上当,举报,315,维权,赔偿,曝光,致癌,违规,处罚,查封'
    return jsonify({'keywords': raw, 'defaultHint': default_hint})

@admin_bp.route('/settings/waiting-content', methods=['GET', 'PUT'])
@admin_required
def waiting_content(current_user):
    if request.method == 'PUT':
        data = request.get_json()
        tips = data.get('tips', '[]')
        steps = data.get('steps', '[]')
        set_setting('waiting_tips', tips)
        set_setting('waiting_steps', steps)
        return jsonify({'message': '已更新'})
    raw_tips = get_setting('waiting_tips', '[]')
    raw_steps = get_setting('waiting_steps', '[]')
    try: tips = json.loads(raw_tips)
    except: tips = []
    try: steps = json.loads(raw_steps)
    except: steps = []
    if not tips:
        tips = ["试试问我：你的产品有什么功效？","我可以帮你写朋友圈文案","关注资讯栏目获取最新动态","试试问我产品怎么使用","我还能帮你写口播文案","试试问我：你们的产品怎么使用？","我还能帮你写口播文案","快速了解产品：试试问我产品的主要成分"]
    if not steps:
        steps = ["正在理解您的问题...","正在匹配最佳智能体...","正在检索产品知识库...","正在分析问题关键点...","正在构思回答框架...","正在组织语言表达...","正在校验回答准确性...","正在润色语言风格...","正在生成完整回复...","即将完成..."]
    return jsonify({'tips': tips, 'steps': steps})
