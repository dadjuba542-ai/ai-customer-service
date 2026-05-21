from flask import Blueprint, request, jsonify
from models import create_question, update_question, get_questions, get_question_detail, create_reply, delete_question, delete_reply, toggle_question_status, get_question_categories, check_content
from routes.auth import admin_required

community_bp = Blueprint('community', __name__)

@community_bp.route('/questions', methods=['GET'])
def list_questions():
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category')
    data = get_questions(page=page, limit=10, category=category, status=1)
    return jsonify(data)

@community_bp.route('/questions/<int:qid>', methods=['GET'])
def get_question(qid):
    item = get_question_detail(qid)
    if not item:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(item)

@community_bp.route('/questions/<int:qid>/replies', methods=['POST'])
def add_reply(qid):
    data = request.get_json()
    nickname = (data.get('nickname') or '').strip()
    content = (data.get('content') or '').strip()
    if not nickname or not content:
        return jsonify({'error': '昵称和回复不能为空'}), 400
    status = 0 if not check_content(content) else 1
    if not status:
        return jsonify({'error': '内容包含限制词汇', 'blocked': True}), 400
    id = create_reply(qid, nickname, content, status)
    return jsonify({'id': id, 'message': '回复成功'}), 201

@community_bp.route('/categories')
def list_categories():
    cats = get_question_categories()
    return jsonify({'categories': cats})

# ===== Admin CRUD =====
@community_bp.route('/admin/questions', methods=['GET'])
@admin_required
def admin_list(current_user):
    page = request.args.get('page', 1, type=int)
    data = get_questions(page=page, limit=50, status=None)
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
