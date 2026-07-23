from flask import Blueprint, jsonify, request

from routes.auth import identity_required
from services.ai_review_service import AiReviewError, list_unread_notes, mark_note_read


nutritionist_notes_bp = Blueprint('nutritionist_notes', __name__)


@nutritionist_notes_bp.route('/unread', methods=['GET'])
@identity_required
def unread(identity):
    try:
        return jsonify(list_unread_notes(identity['user_id'], request.args.get('limit', 20)))
    except AiReviewError as exc:
        return jsonify({'error': exc.message}), exc.status_code


@nutritionist_notes_bp.route('/<int:note_id>/read', methods=['POST'])
@identity_required
def read(identity, note_id):
    try:
        mark_note_read(identity['user_id'], note_id)
        return jsonify({'message': 'ok'})
    except AiReviewError as exc:
        return jsonify({'error': exc.message}), exc.status_code
