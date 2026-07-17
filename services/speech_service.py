import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tempfile
import uuid

import requests

from models import get_setting
from services.secret_service import get_secret_setting


MAX_AUDIO_BYTES = 10 * 1024 * 1024
ALLOWED_MIMES = {
    'audio/webm',
    'audio/mp4',
    'audio/mpeg',
    'audio/m4a',
    'audio/wav',
    'audio/x-wav',
    'audio/ogg',
}
TENCENT_ASR_URL = os.environ.get('TENCENT_ASR_URL', 'https://asr.tencentcloudapi.com')
TENCENT_REGION = os.environ.get('TENCENT_ASR_REGION', 'ap-guangzhou')


class SpeechServiceError(Exception):
    def __init__(self, message, status_code=500, retryable=False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def transcribe_audio_file(file_storage, user_id='anonymous'):
    if get_setting('speech_enabled', '0') != '1':
        raise SpeechServiceError('语音识别未开启', status_code=403)

    audio_bytes, filename, mimetype = _read_and_validate_audio(file_storage)
    wav_bytes = _convert_audio_to_wav(audio_bytes, filename)
    text = _transcribe_with_tencent(wav_bytes)

    if not text:
        raise SpeechServiceError('没有识别到文字，请靠近麦克风再试', status_code=502, retryable=True)
    return {'text': text.strip(), 'provider': 'tencent_asr'}


def _transcribe_with_tencent(wav_bytes):
    secret_id = get_setting('tencent_secret_id', '').strip()
    secret_key = get_secret_setting('tencent_secret_key', '').strip()
    if not secret_id or not secret_key:
        raise SpeechServiceError('未配置腾讯云语音识别 SecretId 和 SecretKey', status_code=400)

    payload = {
        'ProjectId': 0,
        'SubServiceType': 2,
        'EngSerViceType': '16k_zh',
        'SourceType': 1,
        'VoiceFormat': 'wav',
        'Data': base64.b64encode(wav_bytes).decode('ascii'),
        'DataLen': len(wav_bytes),
        'FilterDirty': 0,
        'FilterPunc': 0,
        'ConvertNumMode': 1,
    }
    response = _tencent_api_request('SentenceRecognition', payload, secret_id, secret_key)
    result = response.get('Result', '') if isinstance(response, dict) else ''
    if not result:
        raise SpeechServiceError('没有识别到文字，请靠近麦克风再试', status_code=502, retryable=True)
    return str(result).strip()


def _tencent_api_request(action, payload, secret_id, secret_key):
    host = 'asr.tencentcloudapi.com'
    service = 'asr'
    version = '2019-06-14'
    timestamp = int(__import__('time').time())
    date = __import__('datetime').datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    content_type = 'application/json; charset=utf-8'
    signed_headers = 'content-type;host'
    canonical_headers = f'content-type:{content_type}\nhost:{host}\n'
    hashed_payload = hashlib.sha256(body.encode('utf-8')).hexdigest()
    canonical_request = f'POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}'
    credential_scope = f'{date}/{service}/tc3_request'
    string_to_sign = '\n'.join([
        'TC3-HMAC-SHA256', str(timestamp), credential_scope,
        hashlib.sha256(canonical_request.encode('utf-8')).hexdigest(),
    ])
    secret_date = hmac.new(('TC3' + secret_key).encode(), date.encode(), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, service.encode(), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b'tc3_request', hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = (
        f'TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, '
        f'SignedHeaders={signed_headers}, Signature={signature}'
    )
    try:
        response = requests.post(
            TENCENT_ASR_URL,
            headers={
                'Authorization': authorization,
                'Content-Type': content_type,
                'Host': host,
                'X-TC-Action': action,
                'X-TC-Version': version,
                'X-TC-Region': TENCENT_REGION,
                'X-TC-Timestamp': str(timestamp),
            },
            data=body.encode('utf-8'),
            timeout=(5, 45),
        )
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.Timeout as exc:
        raise SpeechServiceError('腾讯云语音识别超时，请稍后重试', status_code=504, retryable=True) from exc
    except requests.exceptions.RequestException as exc:
        raise SpeechServiceError('腾讯云语音识别失败，请重试', status_code=502, retryable=True) from exc
    except ValueError as exc:
        raise SpeechServiceError('腾讯云语音识别返回异常，请重试', status_code=502, retryable=True) from exc
    error = ((result.get('Response') or {}).get('Error') or {}) if isinstance(result, dict) else {}
    if error:
        raise SpeechServiceError('腾讯云语音识别失败，请检查 SecretId、SecretKey 和权限', status_code=502, retryable=True)
    return result.get('Response') or {}


def _read_and_validate_audio(file_storage):
    if not file_storage:
        raise SpeechServiceError('请上传音频文件', status_code=400)

    mimetype = (file_storage.mimetype or '').split(';')[0].strip().lower()
    if mimetype not in ALLOWED_MIMES:
        raise SpeechServiceError('语音转换失败，请稍后重试', status_code=400)

    audio_bytes = file_storage.read()
    if not audio_bytes:
        raise SpeechServiceError('音频内容为空', status_code=400)
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise SpeechServiceError('音频太大，请控制在 10MB 以内', status_code=400)

    ext = _extension_for_mime(mimetype)
    raw_name = (file_storage.filename or '').strip()
    filename = raw_name if raw_name else f'voice-{uuid.uuid4().hex[:10]}.{ext}'
    if '.' not in filename:
        filename = f'{filename}.{ext}'
    return audio_bytes, filename, mimetype


def _extension_for_mime(mimetype):
    mapping = {
        'audio/webm': 'webm',
        'audio/mp4': 'mp4',
        'audio/mpeg': 'mp3',
        'audio/m4a': 'm4a',
        'audio/wav': 'wav',
        'audio/x-wav': 'wav',
        'audio/ogg': 'ogg',
    }
    return mapping.get(mimetype, 'webm')


def _convert_audio_to_wav(audio_bytes, filename):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SpeechServiceError('服务器未安装音频转换工具', status_code=500, retryable=False)

    suffix = os.path.splitext(filename or '')[1] or '.audio'
    input_path = ''
    output_path = ''
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as input_file:
            input_file.write(audio_bytes)
            input_path = input_file.name
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as output_file:
            output_path = output_file.name
        subprocess.run(
            [ffmpeg, '-y', '-i', input_path, '-ac', '1', '-ar', '16000', '-f', 'wav', output_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        )
        with open(output_path, 'rb') as output_file:
            wav_bytes = output_file.read()
        if not wav_bytes:
            raise SpeechServiceError('语音转换失败，请稍后重试', status_code=502, retryable=True)
        return wav_bytes
    except subprocess.TimeoutExpired as exc:
        raise SpeechServiceError('语音转换超时，请稍后重试', status_code=504, retryable=True) from exc
    except subprocess.CalledProcessError as exc:
        raise SpeechServiceError('语音转换失败，请稍后重试', status_code=502, retryable=True) from exc
    finally:
        for path in (input_path, output_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
