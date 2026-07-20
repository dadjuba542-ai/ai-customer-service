import os
import json
from flask import Blueprint, request, jsonify, current_app
from models import get_all_agent_configs, get_agent_config, update_agent_config, create_agent_config, delete_agent_config, get_setting, set_setting, list_lead_requests, update_lead_request, get_news_page
from config import Config
from routes.auth import admin_required
from services.image_service import is_allowed_image_filename, process_uploaded_image
from services.secret_service import get_secret_setting, set_secret_setting
from services.handoff_service import HandoffError, get_handoff_settings, update_handoff_settings

admin_bp = Blueprint('admin', __name__)
LEAD_STATUSES = {'pending', 'contacted', 'completed'}

MAX_UPLOAD_SIZE = 8 * 1024 * 1024


@admin_bp.route('/settings/handoff', methods=['GET', 'PUT'])
@admin_required
def handoff_settings(current_user):
    if request.method == 'GET':
        return jsonify(get_handoff_settings())
    try:
        return jsonify({'settings': update_handoff_settings(request.get_json(silent=True) or {})})
    except HandoffError as exc:
        return jsonify({'error': exc.message}), exc.status_code
    except (TypeError, ValueError):
        return jsonify({'error': '配置格式不正确'}), 400


@admin_bp.route('/leads', methods=['GET'])
@admin_required
def admin_leads(current_user):
    status = request.args.get('status', '').strip()
    customer_type = request.args.get('customer_type', '').strip()
    if status and status not in LEAD_STATUSES:
        return jsonify({'error': '无效的状态'}), 400
    return jsonify(list_lead_requests(status, customer_type, request.args.get('page', 1, type=int), request.args.get('limit', 30, type=int)))


@admin_bp.route('/leads/<int:lead_id>', methods=['PUT'])
@admin_required
def edit_lead(lead_id, current_user):
    data = request.get_json(silent=True) or {}
    status = str(data.get('status') or '').strip()
    note = str(data.get('admin_note') or '').strip()
    if len(note) > 1000:
        return jsonify({'error': '备注不能超过1000字'}), 400
    if not update_lead_request(lead_id, status, note):
        return jsonify({'error': '需求不存在或状态无效'}), 400
    return jsonify({'message': '需求已更新'})

@admin_bp.route('/home-bulletins', methods=['GET'])
@admin_required
def admin_home_bulletins(current_user):
    page = get_news_page(1, request.args.get('limit', 50, type=int), category='首页滚动')
    return jsonify({'news': page['items']})

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
    if get_setting('handoff_ai_agent_id', '').strip() == agent_id:
        return jsonify({'error': '该智能体正在用于营养咨询，请先切换转人工设置'}), 409
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

    if not is_allowed_image_filename(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_SIZE:
        return jsonify({'error': '文件超过 8MB，请先压缩后再上传'}), 400

    upload_dir = Config.UPLOAD_DIR
    try:
        result = process_uploaded_image(file, upload_dir)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({
        'url': result.url,
        'thumb_url': result.thumb_url,
        'width': result.width,
        'height': result.height,
        'size': result.size,
        'thumb_size': result.thumb_size,
    })

@admin_bp.route('/settings/coze-api-key', methods=['GET', 'PUT'])
@admin_required
def coze_api_key(current_user):
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        key = data.get('api_key', '').strip()
        if not key:
            return jsonify({'error': 'API Key is required'}), 400
        set_secret_setting('coze_api_key', key)
        return jsonify({'message': 'API Key updated'})
    current_key = get_secret_setting('coze_api_key', Config.COZE_API_KEY)
    masked = current_key[:8] + '****' + current_key[-4:] if len(current_key) > 12 else ''
    return jsonify({'masked': masked or '未设置', 'configured': bool(current_key)})

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


@admin_bp.route('/settings/example-questions', methods=['GET', 'PUT'])
@admin_required
def example_questions(current_user):
    default_questions = ['这个产品适合什么人？', '产品应该怎么使用？', '帮我推荐一个产品方案', '帮我写一段客户沟通话术']
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        questions = data.get('questions') or []
        if not isinstance(questions, list):
            return jsonify({'error': '问题格式不正确'}), 400
        questions = [str(item).strip() for item in questions if str(item).strip()][:6]
        if not questions:
            return jsonify({'error': '至少保留一条示例问题'}), 400
        if any(len(item) > 80 for item in questions):
            return jsonify({'error': '单条问题不能超过80字'}), 400
        set_setting('example_questions', json.dumps(questions, ensure_ascii=False))
        return jsonify({'message': '示例问题已更新', 'questions': questions})
    raw = get_setting('example_questions', '[]')
    try:
        questions = json.loads(raw)
    except (TypeError, ValueError):
        questions = []
    return jsonify({'questions': questions if isinstance(questions, list) and questions else default_questions})


@admin_bp.route('/settings/speech', methods=['GET', 'PUT'])
@admin_required
def speech_settings(current_user):
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get('enabled'))
        mode = (data.get('mode') or 'auto').strip() or 'auto'
        if mode not in ('auto', 'realtime', 'batch'):
            mode = 'auto'
        tencent_app_id = str(data.get('tencent_app_id') or '').strip()
        tencent_secret_id = (data.get('tencent_secret_id') or '').strip()
        tencent_secret_key = (data.get('tencent_secret_key') or '').strip()
        existing_tencent_secret = get_secret_setting('tencent_secret_key', '').strip()
        if enabled and (not tencent_secret_id or not (tencent_secret_key or existing_tencent_secret)):
            return jsonify({'error': '开启语音识别前请填写腾讯云 SecretId 和 SecretKey'}), 400
        if enabled and mode != 'batch' and not tencent_app_id:
            return jsonify({'error': '开启实时语音识别前请填写腾讯云 AppID'}), 400
        if tencent_app_id and not tencent_app_id.isdigit():
            return jsonify({'error': '腾讯云 AppID 应为纯数字'}), 400

        set_setting('speech_enabled', '1' if enabled else '0')
        set_setting('speech_provider', 'tencent_asr')
        set_setting('speech_mode', mode)
        set_setting('tencent_app_id', tencent_app_id)
        set_setting('tencent_secret_id', tencent_secret_id)
        if tencent_secret_key:
            set_secret_setting('tencent_secret_key', tencent_secret_key)
        return jsonify({
            'message': '已更新',
            'enabled': enabled,
            'provider': 'tencent_asr',
            'mode': mode,
            'tencent_app_id': tencent_app_id,
            'tencent_secret_id': tencent_secret_id,
            'tencent_secret_key_masked': _mask_secret(get_secret_setting('tencent_secret_key', '')),
        })
    return jsonify({
        'enabled': get_setting('speech_enabled', '0') == '1',
        'provider': 'tencent_asr',
        'mode': get_setting('speech_mode', 'auto') or 'auto',
        'tencent_app_id': get_setting('tencent_app_id', ''),
        'tencent_secret_id': get_setting('tencent_secret_id', ''),
        'tencent_secret_key_masked': _mask_secret(get_secret_setting('tencent_secret_key', '')),
    })


def _mask_secret(value):
    value = (value or '').strip()
    if not value:
        return ''
    if len(value) <= 8:
        return '****'
    return value[:4] + '****' + value[-4:]


@admin_bp.route('/settings/case-library-url', methods=['GET', 'PUT'])
@admin_required
def case_library_url(current_user):
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        url = (data.get('case_library_url') or '').strip()
        if url and not (url.startswith('http://') or url.startswith('https://')):
            return jsonify({'error': '请输入 http:// 或 https:// 开头的 H5 链接'}), 400
        set_setting('case_library_url', url)
        return jsonify({'message': '已更新', 'case_library_url': url})
    return jsonify({'case_library_url': get_setting('case_library_url', '')})

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

@admin_bp.route('/settings/default-team', methods=['GET', 'PUT'])
@admin_required
def default_team(current_user):
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        raw = data.get('team_names')
        if isinstance(raw, list):
            teams = [str(x).strip() for x in raw if str(x).strip()]
        else:
            text = str(raw or data.get('team_name') or '')
            teams = [t.strip() for t in text.split(',') if t.strip()]
        set_setting('default_team_names', json.dumps(teams, ensure_ascii=False))
        # Keep legacy key for compatibility.
        set_setting('default_team_name', teams[0] if teams else '')
        return jsonify({'message': '默认团队名单已更新', 'team_names': teams})
    raw = get_setting('default_team_names', '[]')
    try:
        teams = json.loads(raw)
        if not isinstance(teams, list):
            teams = []
    except:
        teams = []
    if not teams:
        single = get_setting('default_team_name', '').strip()
        if single:
            teams = [single]
    return jsonify({'team_names': teams})
