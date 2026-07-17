from flask import Blueprint, jsonify, request

from config import Config
from routes.auth import identity_required
from services.security_service import rate_limit
from services.speech_service import SpeechServiceError, transcribe_audio_file
from services.tencent_realtime_speech_service import (
    TencentRealtimeSpeechError,
    create_realtime_speech_session,
    realtime_speech_ready,
)

speech_bp = Blueprint('speech', __name__)


@speech_bp.route('/config', methods=['GET'])
def speech_config():
    from models import get_setting
    enabled = get_setting('speech_enabled', '0') == '1'
    mode = get_setting('speech_mode', 'auto').strip() or 'auto'
    return jsonify({
        'enabled': enabled,
        'provider': 'tencent_asr',
        'mode': mode,
        'realtime_enabled': enabled and mode != 'batch' and realtime_speech_ready(),
        'batch_fallback_enabled': mode in ('auto', 'batch'),
        'max_duration_seconds': 60,
    })


@speech_bp.route('/realtime/session', methods=['POST'])
@identity_required
@rate_limit('speech-realtime-session', limit=Config.SPEECH_REALTIME_SESSION_LIMIT, window_seconds=600)
def create_realtime_session(identity):
    try:
        session = create_realtime_speech_session(identity['user_id'])
        session.pop('user_id', None)
        response = jsonify(session)
        response.headers['Cache-Control'] = 'no-store'
        return response
    except TencentRealtimeSpeechError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code


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
