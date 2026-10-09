from flask import Blueprint, jsonify, request

from config import Config
from models import (
    create_audio_course,
    delete_audio_course,
    get_all_audio_courses,
    get_audio_course_by_id,
    get_audio_course_tags,
    get_audio_courses_page,
    get_home_audio_courses,
    search_audio_courses_page,
    set_audio_course_flag,
    set_audio_course_status,
    update_audio_course,
)
from routes.auth import admin_required
from services import feature_flags
from services.audio_service import AudioUploadError, delete_local_audio, save_uploaded_audio
from services.content_security import sanitize_audio_url

audio_courses_bp = Blueprint('audio_courses', __name__)


@audio_courses_bp.before_request
def _require_audio_courses_enabled():
    return feature_flags.guard_request(feature_flags.AUDIO_COURSES_SYSTEM)


def _sanitize_payload(payload):
    payload = payload or {}
    if 'audio_url' in payload:
        payload['audio_url'] = sanitize_audio_url(payload.get('audio_url'))
    if 'external_url' in payload:
        payload['external_url'] = sanitize_audio_url(payload.get('external_url'))
    return payload


@audio_courses_bp.route('/audio-courses', methods=['GET'])
def list_public_audio_courses():
    if (request.args.get('mode') or '').strip() == 'home':
        items = get_home_audio_courses(request.args.get('limit', 6, type=int))
        return jsonify({'items': items, 'total': len(items), 'page': 1, 'pages': 1})
    data = get_audio_courses_page(
        page=request.args.get('page', 1, type=int),
        limit=request.args.get('limit', 10, type=int),
        tag=(request.args.get('tag') or '').strip(),
    )
    return jsonify(data)


@audio_courses_bp.route('/audio-courses/search', methods=['GET'])
def search_public_audio_courses():
    data = search_audio_courses_page(
        query=(request.args.get('q') or '').strip(),
        page=request.args.get('page', 1, type=int),
        limit=request.args.get('limit', 10, type=int),
    )
    return jsonify(data)


@audio_courses_bp.route('/audio-courses/tags', methods=['GET'])
def list_audio_course_tags():
    return jsonify({'tags': get_audio_course_tags()})


@audio_courses_bp.route('/audio-courses/<int:course_id>', methods=['GET'])
def get_public_audio_course(course_id):
    item = get_audio_course_by_id(course_id, public_only=True)
    if not item:
        return jsonify({'error': 'Course not found'}), 404
    return jsonify(item)


@audio_courses_bp.route('/admin/audio-courses', methods=['GET'])
@admin_required
def admin_list_audio_courses(current_user):
    return jsonify({'courses': get_all_audio_courses(include_hidden=True)})


@audio_courses_bp.route('/admin/audio-courses/upload-audio', methods=['POST'])
@admin_required
def admin_upload_audio(current_user):
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    # 先按声明长度拦截，避免为超大请求读取 body（全局 MAX_CONTENT_LENGTH 已放宽到音频量级）
    if request.content_length and request.content_length > Config.AUDIO_MAX_UPLOAD_BYTES + 1024 * 1024:
        return jsonify({'error': '音频超过大小上限，请压缩后再上传'}), 413
    try:
        result = save_uploaded_audio(
            request.files['file'], Config.UPLOAD_DIR, Config.AUDIO_MAX_UPLOAD_BYTES
        )
    except AudioUploadError as exc:
        return jsonify({'error': exc.message}), exc.status_code
    return jsonify(result)


@audio_courses_bp.route('/admin/audio-courses', methods=['POST'])
@admin_required
def admin_create_audio_course(current_user):
    data = _sanitize_payload(request.get_json(silent=True) or {})
    try:
        course_id = create_audio_course(data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'id': course_id, 'message': '课程已创建'}), 201


@audio_courses_bp.route('/admin/audio-courses/<int:course_id>', methods=['PUT'])
@admin_required
def admin_update_audio_course(current_user, course_id):
    data = _sanitize_payload(request.get_json(silent=True) or {})
    old = get_audio_course_by_id(course_id)
    try:
        ok = update_audio_course(course_id, data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if not ok:
        return jsonify({'error': 'Course not found'}), 404
    # 换成本站新音频后清理旧文件，避免持久卷残留
    if old and 'audio_url' in data:
        old_url = (old.get('audio_url') or '').strip()
        new_url = (data.get('audio_url') or '').strip()
        if old_url and old_url != new_url:
            delete_local_audio(Config.UPLOAD_DIR, old_url)
    return jsonify({'message': '课程已更新'})


@audio_courses_bp.route('/admin/audio-courses/<int:course_id>', methods=['DELETE'])
@admin_required
def admin_delete_audio_course(current_user, course_id):
    item = get_audio_course_by_id(course_id)
    delete_audio_course(course_id)
    if item:
        delete_local_audio(Config.UPLOAD_DIR, item.get('audio_url'))
    return jsonify({'message': '课程已删除'})


@audio_courses_bp.route('/admin/audio-courses/<int:course_id>/status', methods=['PUT'])
@admin_required
def admin_set_audio_course_status(current_user, course_id):
    data = request.get_json(silent=True) or {}
    val = set_audio_course_status(course_id, data.get('status', 1))
    if val is None:
        return jsonify({'error': 'Course not found'}), 404
    return jsonify({'status': val})


@audio_courses_bp.route('/admin/audio-courses/<int:course_id>/flag', methods=['PUT'])
@admin_required
def admin_set_audio_course_flag(current_user, course_id):
    data = request.get_json(silent=True) or {}
    flag = str(data.get('flag') or '').strip()
    if flag not in ('pinned', 'show_on_home'):
        return jsonify({'error': '不支持的选项'}), 400
    try:
        val = set_audio_course_flag(course_id, flag, data.get('value', 0))
    except ValueError:
        return jsonify({'error': '不支持的选项'}), 400
    if val is None:
        return jsonify({'error': 'Course not found'}), 404
    return jsonify({flag: val})
