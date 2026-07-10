from flask import Blueprint, jsonify, request

from config import Config
from routes.auth import identity_required
from services.security_service import rate_limit
from services.speech_service import SpeechServiceError, transcribe_audio_file

speech_bp = Blueprint('speech', __name__)


@speech_bp.route('/config', methods=['GET'])
def speech_config():
    from models import get_setting
    return jsonify({'enabled': get_setting('speech_enabled', '0') == '1'})


@speech_bp.route('/transcribe', methods=['POST'])
@identity_required
@rate_limit('speech', limit=Config.SPEECH_RATE_LIMIT, window_seconds=600)
def transcribe_speech(identity):
    try:
        audio = request.files.get('audio')
        result = transcribe_audio_file(audio, user_id=identity['user_id'])
        return jsonify(result)
    except SpeechServiceError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code
