from flask import Blueprint, request, jsonify
from models import create_survey
from routes.auth import identity_required
from services.security_service import rate_limit

survey_bp = Blueprint('survey', __name__)

@survey_bp.route('', methods=['POST'])
@identity_required
@rate_limit('survey', limit=5, window_seconds=3600)
def submit_survey(identity):
    data = request.get_json(silent=True) or {}
    score = data.get('score')
    if score not in (1, 2, 3):
        return jsonify({'error': 'score must be 1, 2, or 3'}), 400
    create_survey(score)
    return jsonify({'message': 'Survey saved'})
