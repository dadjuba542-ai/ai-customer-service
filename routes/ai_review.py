from flask import Blueprint, jsonify, request

from routes.auth import admin_required
from services.ai_review_service import (
    AiReviewError, list_ai_reviews, upsert_review_note, withdraw_review_note,
)
from services.security_service import rate_limit


ai_review_bp = Blueprint('ai_review', __name__)


def _error(exc):
    return jsonify({'error': exc.message}), exc.status_code


@ai_review_bp.route('', methods=['GET'])
@admin_required
def list_reviews(current_user):
    try:
        return jsonify(list_ai_reviews(request.args))
    except AiReviewError as exc:
        return _error(exc)


@ai_review_bp.route('/<int:history_id>/note', methods=['PUT'])
@admin_required
@rate_limit('ai-review-note', limit=60, window_seconds=60)
def save_note(current_user, history_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({'note': upsert_review_note(
            history_id, current_user['user_id'], data.get('content'), data.get('expected_revision', 0)
        )})
    except AiReviewError as exc:
        return _error(exc)


@ai_review_bp.route('/<int:history_id>/note', methods=['DELETE'])
@admin_required
@rate_limit('ai-review-note', limit=60, window_seconds=60)
def delete_note(current_user, history_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({'note': withdraw_review_note(
            history_id, current_user['user_id'], data.get('expected_revision')
        )})
    except AiReviewError as exc:
        return _error(exc)
