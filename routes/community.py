from flask import Blueprint, request, jsonify
from models import create_question, update_question, get_questions, get_question_detail, get_question_replies, create_reply, delete_question, delete_reply, set_reply_status, like_reply, toggle_question_status, get_question_categories, check_content
from routes.auth import admin_required, get_optional_identity, identity_required
from services.security_service import rate_limit

community_bp = Blueprint('community', __name__)

@community_bp.route('/questions', methods=['GET'])
def list_questions():
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category')
    data = get_questions(page=page, limit=10, category=category, status=1)
    return jsonify(data)

@community_bp.route('/questions/<int:qid>', methods=['GET'])
def get_question(qid):
    identity = get_optional_identity()
    viewer_id = identity['user_id'] if identity else ''
    item = get_question_detail(qid, viewer_id=viewer_id)
    if not item:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(item)

@community_bp.route('/questions/<int:qid>/replies', methods=['POST'])
@identity_required
@rate_limit('community-reply', limit=10, window_seconds=600)
def add_reply(identity, qid):
    data = request.get_json(silent=True) or {}
    nickname = '匿名用户'
    content = (data.get('content') or '').strip()
    viewer_id = identity['user_id']
    if not content:
        return jsonify({'error': '回复不能为空'}), 400
    status = 0 if not check_content(content) else 1
    if not status:
        return jsonify({'error': '内容包含限制词汇', 'blocked': True}), 400
    id = create_reply(qid, nickname, content, 0, viewer_id)
    return jsonify({'id': id, 'status': 0, 'message': '评论已提交，精选后公开展示'}), 201

@community_bp.route('/categories')
def list_categories():
    cats = get_question_categories()
    return jsonify({'categories': cats})

@community_bp.route('/replies/<int:rid>/like', methods=['POST'])
@identity_required
@rate_limit('community-like', limit=60, window_seconds=3600)
def like_reply_route(identity, rid):
    count = like_reply(rid)
    if count is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'like_count': count})

# ===== Admin CRUD =====
@community_bp.route('/admin/questions', methods=['GET'])
@admin_required
def admin_list(current_user):
    page = request.args.get('page', 1, type=int)
    data = get_questions(page=page, limit=50, status=None)
    for item in data.get('items', []):
        item['replies'] = get_question_replies(item['id'], status=None)
    return jsonify(data)

@community_bp.route('/admin/questions', methods=['POST'])
@admin_required
def admin_create(current_user):
    data = request.get_json()
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    category = (data.get('category') or '').strip()
    if not title:
        return jsonify({'error': '问题不能为空'}), 400
    id = create_question('', title, content, category, 1)
    return jsonify({'id': id, 'message': '创建成功'}), 201

@community_bp.route('/admin/questions/<int:qid>', methods=['PUT'])
@admin_required
def admin_update(current_user, qid):
    data = request.get_json()
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    category = (data.get('category') or '').strip()
    status = data.get('status', 1)
    if not title:
        return jsonify({'error': '问题不能为空'}), 400
    update_question(qid, title, content, category, status)
    return jsonify({'message': '已更新'})

@community_bp.route('/admin/questions/<int:qid>', methods=['DELETE'])
@admin_required
def admin_delete(current_user, qid):
    delete_question(qid)
    return jsonify({'message': '已删除'})

@community_bp.route('/admin/questions/<int:qid>/status', methods=['PUT'])
@admin_required
def admin_toggle_status(current_user, qid):
    val = toggle_question_status(qid)
    return jsonify({'status': val})

@community_bp.route('/admin/replies/<int:rid>', methods=['DELETE'])
@admin_required
def admin_delete_reply(current_user, rid):
    delete_reply(rid)
    return jsonify({'message': '已删除'})

@community_bp.route('/admin/replies/<int:rid>/status', methods=['PUT'])
@admin_required
def admin_set_reply_status(current_user, rid):
    data = request.get_json(silent=True) or {}
    status = data.get('status', 1)
    val = set_reply_status(rid, status)
    if val is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'status': val})
