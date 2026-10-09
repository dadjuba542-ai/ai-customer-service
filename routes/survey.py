from flask import Blueprint, request, jsonify
from models import create_survey, create_research_survey
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


MAX_RESEARCH_ANSWERS = 30
MAX_ANSWER_LENGTH = 500
MAX_CONTACT_LENGTH = 60


def _clean_research_answers(answers):
    if not isinstance(answers, dict) or not answers:
        return None
    cleaned = {}
    for key, value in list(answers.items())[:MAX_RESEARCH_ANSWERS]:
        if not isinstance(key, str) or not key or len(key) > 40:
            continue
        if isinstance(value, list):
            cleaned[key] = [str(item)[:100] for item in value[:20]]
        elif isinstance(value, bool):
            continue
        elif isinstance(value, (int, float, str)):
            cleaned[key] = value if not isinstance(value, str) else value.strip()[:MAX_ANSWER_LENGTH]
        else:
            continue
    return cleaned or None


@survey_bp.route('/research', methods=['POST'])
@identity_required
@rate_limit('research-survey', limit=5, window_seconds=86400)
def submit_research_survey(identity):
    data = request.get_json(silent=True) or {}
    answers = _clean_research_answers(data.get('answers'))
    if not answers:
        return jsonify({'error': 'answers required'}), 400
    contact = str(data.get('contact') or '').strip()[:MAX_CONTACT_LENGTH]
    create_research_survey(
        user_id=identity.get('user_id', ''),
        user_type=identity.get('token_type', ''),
        answers=answers,
        contact=contact,
    )
    return jsonify({'message': 'Survey saved'})
