"""音频课程文件上传：流式落盘到持久化目录，可选自动识别时长，并提供本地文件清理工具。"""
import os
import shutil
import subprocess
import uuid

ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'm4a', 'aac', 'wav', 'ogg', 'mp4'}
AUDIO_SUBDIR = 'audio'
_URL_PREFIX = f'/uploads/{AUDIO_SUBDIR}/'


class AudioUploadError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def is_allowed_audio_filename(filename):
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_AUDIO_EXTENSIONS


def save_uploaded_audio(file_storage, upload_dir, max_bytes):
    """校验并保存上传的音频，返回 {url, duration_seconds, size}。

    用 ``file_storage.save`` 流式写入，避免把整个音频读进内存；落盘后再按
    实际字节数校验，超限即删除并报错。
    """
    if not file_storage or not (file_storage.filename or '').strip():
        raise AudioUploadError('请选择音频文件')
    if not is_allowed_audio_filename(file_storage.filename):
        raise AudioUploadError('仅支持 mp3/m4a/aac/wav/ogg/mp4 音频')

    ext = file_storage.filename.rsplit('.', 1)[1].lower()
    target_dir = os.path.join(upload_dir, AUDIO_SUBDIR)
    os.makedirs(target_dir, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.{ext}'
    path = os.path.join(target_dir, filename)
    file_storage.save(path)
    size = os.path.getsize(path)
    if size == 0:
        _remove_quietly(path)
        raise AudioUploadError('音频内容为空')
    if size > max_bytes:
        _remove_quietly(path)
        raise AudioUploadError(f'音频超过 {max_bytes // (1024 * 1024)}MB，请压缩后再上传')

    return {
        'url': f'{_URL_PREFIX}{filename}',
        'duration_seconds': _probe_duration(path),
        'size': size,
    }


def local_audio_path(upload_dir, audio_url):
    """把本站音频 URL 映射为磁盘路径；非本站或含路径穿越时返回空字符串。"""
    url = str(audio_url or '').strip()
    if not url.startswith(_URL_PREFIX):
        return ''
    name = url[len(_URL_PREFIX):]
    if not name or '/' in name or '\\' in name or '..' in name:
        return ''
    return os.path.join(upload_dir, AUDIO_SUBDIR, name)


def delete_local_audio(upload_dir, audio_url):
    """删除本站音频文件；调用方负责先确认该文件不再被引用。"""
    path = local_audio_path(upload_dir, audio_url)
    if not path or not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _probe_duration(path):
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return 0
    try:
        result = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
        seconds = float((result.stdout or b'').decode('utf-8', 'ignore').strip() or 0)
        return max(0, int(round(seconds)))
    except (subprocess.SubprocessError, ValueError):
        return 0


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass
