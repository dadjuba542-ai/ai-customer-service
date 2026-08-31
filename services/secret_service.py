import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from config import Config
from models import get_setting, set_setting


logger = logging.getLogger(__name__)
ENCRYPTED_PREFIX = 'enc:v1:'
SECRET_SETTING_KEYS = ('coze_api_key', 'aliyun_access_key_secret', 'tencent_secret_key')


def _fernet():
    digest = hashlib.sha256(Config.SECRET_KEY.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value):
    value = str(value or '')
    if not value:
        return ''
    token = _fernet().encrypt(value.encode('utf-8')).decode('ascii')
    return ENCRYPTED_PREFIX + token


def decrypt_secret(value):
    value = str(value or '')
    if not value or not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX):]
    try:
        return _fernet().decrypt(token.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        logger.error('Unable to decrypt protected setting; check SECRET_KEY consistency')
        raise RuntimeError('Unable to decrypt protected setting') from exc


def get_secret_setting(key, default=''):
    raw = get_setting(key, '')
    if not raw:
        return default
    try:
        return decrypt_secret(raw)
    except RuntimeError:
        logger.exception('Failed to decrypt setting %s; falling back to default', key)
        return default


def set_secret_setting(key, value):
    set_setting(key, encrypt_secret(value))


def migrate_plaintext_secrets():
    migrated = []
    for key in SECRET_SETTING_KEYS:
        raw = get_setting(key, '')
        if raw and not raw.startswith(ENCRYPTED_PREFIX):
            set_secret_setting(key, raw)
            migrated.append(key)
    if migrated:
        logger.info('Encrypted legacy secret settings: %s', ','.join(migrated))
    return migrated
