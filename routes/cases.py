from flask import Blueprint, jsonify, request

from models import (
    create_case_document,
    create_case_tag,
    delete_case_document,
    get_all_case_documents,
    get_case_documents_page,
    get_case_document_by_id,
    get_case_tags,
    search_case_documents_page,
    set_case_document_status,
    set_case_tag_status,
    update_case_document,
    update_case_tag,
)
from routes.auth import admin_required
from services import feature_flags
from services.content_security import redact_customer_profile
from services.case_recognition_service import (
    CaseRecognitionError,
    recognize_case_from_link,
    recognize_cases_from_rows,
)

cases_bp = Blueprint('cases', __name__)


@cases_bp.before_request
def _require_cases_enabled():
    """兜底拦截：即便全局路径前缀没覆盖到，案例系统的任何接口都不放行。"""
    return feature_flags.guard_request(feature_flags.CASES_SYSTEM)


def _redact_case_payload(payload):
    """Strip identifying details before a case leaves the public API.

    Admin routes return raw rows on purpose; this only guards the anonymous
    list / detail / search endpoints.
    """
    if not payload:
        return payload
    items = [payload]
    if isinstance(payload, dict) and isinstance(payload.get('items'), list):
        items = payload['items']
    for item in items:
        if isinstance(item, dict) and 'customer_profile' in item:
            item['customer_profile'] = redact_customer_profile(item['customer_profile'])
    return payload


@cases_bp.route('/cases', methods=['GET'])
def list_public_cases():
    data = get_case_documents_page(
        page=request.args.get('page', 1, type=int),
        limit=request.args.get('limit', 10, type=int),
        tag_type=(request.args.get('tag_type') or '').strip(),
        tag=(request.args.get('tag') or '').strip(),
    )
    return jsonify(_redact_case_payload(data))


@cases_bp.route('/cases/<int:case_id>', methods=['GET'])
def get_public_case(case_id):
    item = get_case_document_by_id(case_id, public_only=True)
    if not item:
        return jsonify({'error': 'Case not found'}), 404
    return jsonify(_redact_case_payload(item))


@cases_bp.route('/cases/search', methods=['GET'])
def search_public_cases():
    data = search_case_documents_page(
        query=(request.args.get('q') or '').strip(),
        page=request.args.get('page', 1, type=int),
        limit=request.args.get('limit', 10, type=int),
    )
    return jsonify(_redact_case_payload(data))


@cases_bp.route('/admin/cases', methods=['GET'])
@admin_required
def admin_list_cases(current_user):
    return jsonify({'cases': get_all_case_documents(include_hidden=True)})


@cases_bp.route('/admin/cases/recognize-link', methods=['POST'])
@admin_required
def admin_recognize_case_link(current_user):
    data = request.get_json(silent=True) or {}
    try:
        result = recognize_case_from_link(data.get('url', ''))
    except CaseRecognitionError as exc:
        return jsonify({'error': exc.message}), exc.status_code
    return jsonify(result)


@cases_bp.route('/admin/cases/recognize-batch', methods=['POST'])
@admin_required
def admin_recognize_cases_batch(current_user):
    data = request.get_json(silent=True) or {}
    raw_rows = data.get('rows')
    if raw_rows is None:
        raw_rows = [line for line in str(data.get('text') or '').splitlines()]
    if not isinstance(raw_rows, list):
        return jsonify({'error': 'rows 格式不正确'}), 400

    rows = []
    for row in raw_rows:
        if isinstance(row, (list, tuple)):
            rows.append(' '.join(str(cell) for cell in row if str(cell or '').strip()))
        else:
            rows.append(str(row or ''))
    try:
        result = recognize_cases_from_rows(rows)
    except CaseRecognitionError as exc:
        return jsonify({'error': exc.message}), exc.status_code
    return jsonify(result)


@cases_bp.route('/admin/cases', methods=['POST'])
@admin_required
def admin_create_case(current_user):
    data = request.get_json(silent=True) or {}
    try:
        case_id = create_case_document(data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'id': case_id, 'message': '案例已创建'}), 201


@cases_bp.route('/admin/cases/<int:case_id>', methods=['PUT'])
@admin_required
def admin_update_case(current_user, case_id):
    data = request.get_json(silent=True) or {}
    try:
        ok = update_case_document(case_id, data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if not ok:
        return jsonify({'error': 'Case not found'}), 404
    return jsonify({'message': '案例已更新'})


@cases_bp.route('/admin/cases/<int:case_id>', methods=['DELETE'])
@admin_required
def admin_delete_case(current_user, case_id):
    delete_case_document(case_id)
    return jsonify({'message': '案例已删除'})


@cases_bp.route('/admin/cases/<int:case_id>/status', methods=['PUT'])
@admin_required
def admin_set_case_status(current_user, case_id):
    data = request.get_json(silent=True) or {}
    val = set_case_document_status(case_id, data.get('status', 1))
    if val is None:
        return jsonify({'error': 'Case not found'}), 404
    return jsonify({'status': val})


@cases_bp.route('/admin/case-tags', methods=['GET'])
@admin_required
def admin_list_case_tags(current_user):
    try:
        tags = get_case_tags((request.args.get('type') or '').strip())
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'tags': tags})


@cases_bp.route('/admin/case-tags', methods=['POST'])
@admin_required
def admin_create_case_tag(current_user):
    data = request.get_json(silent=True) or {}
    try:
        tag_id = create_case_tag(data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'id': tag_id, 'message': '标签已创建'}), 201


@cases_bp.route('/admin/case-tags/<int:tag_id>', methods=['PUT'])
@admin_required
def admin_update_case_tag(current_user, tag_id):
    data = request.get_json(silent=True) or {}
    try:
        ok = update_case_tag(tag_id, data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if not ok:
        return jsonify({'error': 'Tag not found'}), 404
    return jsonify({'message': '标签已更新'})


@cases_bp.route('/admin/case-tags/<int:tag_id>/status', methods=['PUT'])
@admin_required
def admin_set_case_tag_status(current_user, tag_id):
    data = request.get_json(silent=True) or {}
    val = set_case_tag_status(tag_id, data.get('status', 1))
    if val is None:
        return jsonify({'error': 'Tag not found'}), 404
    return jsonify({'status': val})
