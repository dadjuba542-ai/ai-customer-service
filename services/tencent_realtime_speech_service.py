import base64
import hashlib
import hmac
import secrets
import time
import uuid
from urllib.parse import quote, urlencode

from models import get_setting
from services.secret_service import get_secret_setting


TENCENT_REALTIME_HOST = 'asr.cloud.tencent.com'
TENCENT_REALTIME_PATH = '/asr/v2/'
DEFAULT_ENGINE_MODEL = '16k_zh'
DEFAULT_SESSION_TTL_SECONDS = 5 * 60
DEFAULT_MAX_DURATION_SECONDS = 60


class TencentRealtimeSpeechError(Exception):
    def __init__(self, message, status_code=500, retryable=False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def realtime_speech_ready():
    return all((
        get_setting('tencent_app_id', '').strip(),
        get_setting('tencent_secret_id', '').strip(),
        get_secret_setting('tencent_secret_key', '').strip(),
    ))


def create_realtime_speech_session(user_id):
    if get_setting('speech_enabled', '0') != '1':
        raise TencentRealtimeSpeechError('语音识别未开启', status_code=403)

    mode = get_setting('speech_mode', 'auto').strip() or 'auto'
    if mode == 'batch':
        raise TencentRealtimeSpeechError('实时语音识别未开启', status_code=403)

    app_id = get_setting('tencent_app_id', '').strip()
    secret_id = get_setting('tencent_secret_id', '').strip()
    secret_key = get_secret_setting('tencent_secret_key', '').strip()
    if not app_id or not secret_id or not secret_key:
        raise TencentRealtimeSpeechError('腾讯云实时语音配置不完整', status_code=503)

    engine_model = get_setting('tencent_engine_model_type', DEFAULT_ENGINE_MODEL).strip() or DEFAULT_ENGINE_MODEL
    timestamp = int(time.time())
    expires_at = timestamp + DEFAULT_SESSION_TTL_SECONDS
    voice_id = uuid.uuid4().hex
    params = {
        'convert_num_mode': 1,
        'engine_model_type': engine_model,
        'expired': expires_at,
        'filter_dirty': 0,
        'filter_modal': 0,
        'filter_punc': 0,
        'needvad': 1,
        'nonce': secrets.randbelow(2_000_000_000) + 1,
        'secretid': secret_id,
        'timestamp': timestamp,
        'voice_format': 1,
        'voice_id': voice_id,
    }
    query = urlencode(sorted(params.items()))
    sign_source = f'{TENCENT_REALTIME_HOST}{TENCENT_REALTIME_PATH}{app_id}?{query}'
    signature = base64.b64encode(
        hmac.new(secret_key.encode('utf-8'), sign_source.encode('utf-8'), hashlib.sha1).digest()
    ).decode('ascii')
    websocket_url = f'wss://{sign_source}&signature={quote(signature, safe="")}'

    return {
        'url': websocket_url,
        'voice_id': voice_id,
        'expires_at': expires_at,
        'engine_model_type': engine_model,
        'max_duration_seconds': DEFAULT_MAX_DURATION_SECONDS,
        'user_id': str(user_id or ''),
    }
