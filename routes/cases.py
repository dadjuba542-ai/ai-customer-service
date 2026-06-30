from flask import Blueprint, jsonify, request

from models import (
    create_case_document,
    delete_case_document,
    get_all_case_documents,
    get_case_documents_page,
    get_case_document_by_id,
    search_case_documents_page,
    set_case_document_status,
    update_case_document,
)
from routes.auth import admin_required
from services.case_recognition_service import CaseRecognitionError, recognize_case_from_link

cases_bp = Blueprint('cases', __name__)


@cases_bp.route('/cases', methods=['GET'])
def list_public_cases():
    data = get_case_documents_page(
        page=request.args.get('page', 1, type=int),
        limit=request.args.get('limit', 10, type=int),
        tag_type=(request.args.get('tag_type') or '').strip(),
        tag=(request.args.get('tag') or '').strip(),
    )
    return jsonify(data)


@cases_bp.route('/cases/<int:case_id>', methods=['GET'])
def get_public_case(case_id):
    item = get_case_document_by_id(case_id, public_only=True)
    if not item:
        return jsonify({'error': 'Case not found'}), 404
    return jsonify(item)


@cases_bp.route('/cases/search', methods=['GET'])
def search_public_cases():
    data = search_case_documents_page(
        query=(request.args.get('q') or '').strip(),
        page=request.args.get('page', 1, type=int),
        limit=request.args.get('limit', 10, type=int),
    )
    return jsonify(data)


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
