import io
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from urllib.parse import urlencode

import requests

from config import Config
from models import get_setting


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
TRANSCRIBE_PROMPT = '请把这段音频转写成简体中文文字，只返回转写结果，不要解释。'
ALIYUN_TOKEN_URL = os.environ.get('ALIYUN_NLS_TOKEN_URL', 'https://nls-meta.cn-shanghai.aliyuncs.com/pop/2018-05-18/tokens')
ALIYUN_ASR_URL = os.environ.get('ALIYUN_NLS_ASR_URL', 'https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/asr')
SUPPORTED_PROVIDERS = {'aliyun_asr', 'coze'}


class SpeechServiceError(Exception):
    def __init__(self, message, status_code=500, retryable=False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def transcribe_audio_file(file_storage, user_id='anonymous'):
    if get_setting('speech_enabled', '0') != '1':
        raise SpeechServiceError('语音识别未开启', status_code=403)

    provider = get_setting('speech_provider', 'aliyun_asr').strip() or 'aliyun_asr'
    if provider not in SUPPORTED_PROVIDERS:
        provider = 'aliyun_asr'

    audio_bytes, filename, mimetype = _read_and_validate_audio(file_storage)
    wav_bytes = _convert_audio_to_wav(audio_bytes, filename)

    if provider == 'coze':
        text = _transcribe_with_coze(wav_bytes, user_id)
    else:
        text = _transcribe_with_aliyun(wav_bytes)

    if not text:
        raise SpeechServiceError('没有识别到文字，请靠近麦克风再试', status_code=502, retryable=True)
    return {'text': text.strip(), 'provider': provider}


def _transcribe_with_aliyun(wav_bytes):
    app_key = get_setting('aliyun_nls_app_key', '').strip()
    access_key_id = get_setting('aliyun_access_key_id', '').strip()
    access_key_secret = get_setting('aliyun_access_key_secret', '').strip()
    if not app_key or not access_key_id or not access_key_secret:
        raise SpeechServiceError('未配置语音识别服务', status_code=400)

    token = _get_aliyun_nls_token(access_key_id, access_key_secret)
    params = {
        'appkey': app_key,
        'format': 'wav',
        'sample_rate': 16000,
        'enable_punctuation_prediction': 'true',
        'enable_inverse_text_normalization': 'true',
    }
    try:
        response = requests.post(
            f'{ALIYUN_ASR_URL}?{urlencode(params)}',
            headers={
                'X-NLS-Token': token,
                'Content-Type': 'application/octet-stream',
            },
            data=wav_bytes,
            timeout=(5, 30),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.Timeout as exc:
        raise SpeechServiceError('语音识别超时，请稍后重试', status_code=504, retryable=True) from exc
    except requests.exceptions.RequestException as exc:
        raise SpeechServiceError('语音识别失败，请重试', status_code=502, retryable=True) from exc
    except ValueError as exc:
        raise SpeechServiceError('语音识别返回异常，请重试', status_code=502, retryable=True) from exc

    if payload.get('status') not in (20000000, '20000000', None):
        message = payload.get('message') or payload.get('status_text') or '语音识别失败，请重试'
        raise SpeechServiceError(_friendly_aliyun_error(message), status_code=502, retryable=True)

    text = (payload.get('result') or payload.get('text') or '').strip()
    if not text:
        raise SpeechServiceError('没有识别到文字，请靠近麦克风再试', status_code=502, retryable=True)
    return text


def _get_aliyun_nls_token(access_key_id, access_key_secret):
    try:
        response = requests.post(
            ALIYUN_TOKEN_URL,
            json={'AccessKeyId': access_key_id, 'AccessKeySecret': access_key_secret},
            timeout=(5, 20),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.Timeout as exc:
        raise SpeechServiceError('语音识别鉴权超时，请稍后重试', status_code=504, retryable=True) from exc
    except requests.exceptions.RequestException as exc:
        raise SpeechServiceError('语音识别鉴权失败，请检查阿里云配置', status_code=502, retryable=True) from exc
    except ValueError as exc:
        raise SpeechServiceError('语音识别鉴权返回异常', status_code=502, retryable=True) from exc

    token = _find_first_key(payload, ('Id', 'token', 'id'))
    if not token:
        raise SpeechServiceError('语音识别鉴权失败，请检查阿里云配置', status_code=502, retryable=True)
    return str(token)


def _transcribe_with_coze(wav_bytes, user_id):
    bot_id = get_setting('speech_coze_bot_id', '').strip()
    if not bot_id:
        raise SpeechServiceError('未配置语音识别 Bot ID', status_code=400)

    api_key = get_setting('coze_api_key', Config.COZE_API_KEY)
    if not api_key:
        raise SpeechServiceError('未配置 Coze API Key', status_code=400)

    file_id = _upload_audio_to_coze(wav_bytes, 'voice.wav', 'audio/wav', api_key)
    return _ask_coze_to_transcribe(file_id, 'wav', bot_id, api_key, user_id)


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


def _upload_audio_to_coze(audio_bytes, filename, mimetype, api_key):
    try:
        response = requests.post(
            Config.COZE_FILE_UPLOAD_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (filename, io.BytesIO(audio_bytes), mimetype)},
            timeout=(5, 60),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.Timeout as exc:
        raise SpeechServiceError('音频上传超时，请稍后重试', status_code=504, retryable=True) from exc
    except requests.exceptions.RequestException as exc:
        raise SpeechServiceError(f'音频上传失败: {exc}', status_code=502, retryable=True) from exc
    except ValueError as exc:
        raise SpeechServiceError('音频上传返回异常', status_code=502, retryable=True) from exc

    if payload.get('code') not in (None, 0):
        raise SpeechServiceError(payload.get('msg') or 'Coze 文件上传失败', status_code=502, retryable=True)

    file_id = _find_first_key(payload, ('file_id', 'id'))
    if not file_id:
        raise SpeechServiceError('Coze 文件上传未返回 file_id', status_code=502, retryable=True)
    return str(file_id)


def _ask_coze_to_transcribe(file_id, audio_file_type, bot_id, api_key, user_id):
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    content = json.dumps([
        {'type': 'text', 'text': TRANSCRIBE_PROMPT},
        {'type': 'audio', 'file_id': file_id, 'audio_file_type': audio_file_type},
    ], ensure_ascii=False)
    payload = {
        'bot_id': bot_id,
        'user_id': user_id or 'anonymous',
        'stream': True,
        'additional_messages': [{
            'role': 'user',
            'content': content,
            'content_type': 'object_string',
        }],
    }
    try:
        with requests.post(
            Config.COZE_V3_CHAT_URL,
            headers=headers,
            json=payload,
            stream=True,
            timeout=(5, 45),
        ) as response:
            response.raise_for_status()
            return _extract_text_from_coze_stream(response)
    except requests.exceptions.Timeout as exc:
        raise SpeechServiceError('语音识别请求超时，请稍后重试', status_code=504, retryable=True) from exc
    except requests.exceptions.RequestException as exc:
        raise SpeechServiceError(f'语音识别请求失败: {exc}', status_code=502, retryable=True) from exc


def _extract_text_from_coze_stream(response):
    full_text = ''
    last_error = ''
    for event_name, raw_data in _iter_sse_events(response):
        if raw_data == '[DONE]':
            break
        payload = _safe_json_loads(raw_data)
        if not payload:
            continue
        if payload.get('code') not in (None, 0):
            raise SpeechServiceError(_friendly_coze_error(payload.get('msg')), status_code=502, retryable=True)
        normalized_event = _normalize_event_name(event_name, payload)
        if 'error' in normalized_event:
            last_error = _friendly_coze_error(payload.get('msg') or payload.get('message') or payload.get('error'))
            continue
        delta = _extract_stream_text(normalized_event, payload, full_text)
        if delta:
            full_text += delta
    if full_text.strip():
        return full_text.strip()
    if last_error:
        raise SpeechServiceError(last_error, status_code=502, retryable=True)
    raise SpeechServiceError('未识别到文字，请重试', status_code=502, retryable=True)


def _iter_sse_events(response):
    event_name = ''
    data_lines = []
    response.encoding = 'utf-8'
    for raw_line in response.iter_lines(decode_unicode=False):
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode('utf-8', errors='replace').rstrip('\r')
        else:
            line = str(raw_line).rstrip('\r')
        if not line:
            if event_name or data_lines:
                yield event_name, '\n'.join(data_lines)
            event_name = ''
            data_lines = []
            continue
        if line.startswith(':'):
            continue
        if line.startswith('event:'):
            event_name = line[6:].strip()
            continue
        if line.startswith('data:'):
            data_lines.append(line[5:].strip())
    if event_name or data_lines:
        yield event_name, '\n'.join(data_lines)


def _safe_json_loads(raw_data):
    try:
        return json.loads(raw_data)
    except (TypeError, ValueError):
        return None


def _normalize_event_name(upstream_event, payload):
    for candidate in (
        upstream_event,
        payload.get('event'),
        payload.get('type'),
        payload.get('name'),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return ''


def _extract_stream_text(normalized_event, payload, current_text):
    message = payload.get('message')
    if isinstance(message, dict):
        msg_type = message.get('type')
        if msg_type and msg_type not in ('answer', 'assistant_answer'):
            return ''
        return _normalize_delta_text(_extract_text_content(message.get('content'), message.get('content_type')), current_text)

    if normalized_event and 'delta' in normalized_event:
        for key in ('content', 'text', 'delta'):
            normalized = _normalize_delta_text(_extract_text_content(payload.get(key)), current_text)
            if normalized:
                return normalized

    data = payload.get('data')
    if isinstance(data, dict):
        msg_type = data.get('type')
        if msg_type and msg_type not in ('answer', 'assistant_answer'):
            return ''
        for key in ('content', 'text', 'delta'):
            normalized = _normalize_delta_text(_extract_text_content(data.get(key), data.get('content_type')), current_text)
            if normalized:
                return normalized

    return ''


def _normalize_delta_text(text, current_text):
    if not isinstance(text, str) or not text:
        return ''
    if current_text and text.startswith(current_text):
        return text[len(current_text):]
    if current_text.endswith(text):
        return ''
    return text


def _friendly_coze_error(message):
    text = str(message or '').strip()
    lowered = text.lower()
    if 'auto_save_history' in lowered and 'stream' in lowered:
        return '语音识别参数不兼容，请刷新页面后重试'
    if 'audio_file_type' in lowered:
        return '语音转换失败，请稍后重试'
    if text:
        return text
    return 'Coze 语音识别失败'


def _friendly_aliyun_error(message):
    text = str(message or '').strip()
    lowered = text.lower()
    if 'token' in lowered or 'forbidden' in lowered or 'unauthorized' in lowered:
        return '语音识别鉴权失败，请检查阿里云配置'
    if 'timeout' in lowered:
        return '语音识别超时，请稍后重试'
    if text:
        return text
    return '语音识别失败，请重试'


def _extract_text_content(content, content_type=None):
    if not content:
        return ''
    if isinstance(content, str) and content_type == 'object_string':
        try:
            items = json.loads(content)
            if isinstance(items, list):
                return ''.join(str(x.get('text') or '') for x in items if isinstance(x, dict)).strip()
        except ValueError:
            return content.strip()
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return ''.join(str(x.get('text') or '') for x in content if isinstance(x, dict)).strip()
    if isinstance(content, dict):
        return str(content.get('text') or '').strip()
    return ''


def _find_first_key(value, keys):
    if isinstance(value, dict):
        for key in keys:
            if value.get(key):
                return value.get(key)
        for child in value.values():
            found = _find_first_key(child, keys)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_first_key(child, keys)
            if found:
                return found
    return None
