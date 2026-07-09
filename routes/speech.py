from flask import Blueprint, jsonify, request

from services.speech_service import SpeechServiceError, transcribe_audio_file

speech_bp = Blueprint('speech', __name__)


@speech_bp.route('/config', methods=['GET'])
def speech_config():
    from models import get_setting
    return jsonify({'enabled': get_setting('speech_enabled', '0') == '1'})


@speech_bp.route('/transcribe', methods=['POST'])
def transcribe_speech():
    try:
        audio = request.files.get('audio')
        user_id = (request.form.get('user_id') or 'anonymous').strip() or 'anonymous'
        result = transcribe_audio_file(audio, user_id=user_id)
        return jsonify(result)
    except SpeechServiceError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code
