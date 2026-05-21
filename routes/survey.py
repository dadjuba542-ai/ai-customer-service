from flask import Blueprint, request, jsonify
from models import create_survey
from routes.auth import admin_required

survey_bp = Blueprint('survey', __name__)

@survey_bp.route('', methods=['POST'])
def submit_survey():
    data = request.get_json()
    score = data.get('score')
    if score not in (1, 2, 3):
        return jsonify({'error': 'score must be 1, 2, or 3'}), 400
    create_survey(score)
    return jsonify({'message': 'Survey saved'})
