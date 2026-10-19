"""Shared clock, transactions, errors and request validation for learning flows."""
import re
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from models import get_db_connection
from services.chat_service import ChatServiceError

TZ = ZoneInfo('Asia/Shanghai')


def now():
    return datetime.now(TZ)


class PracticeError(ChatServiceError):
    pass


@contextmanager
def db(write=False):
    conn = get_db_connection()
    try:
        if write:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def request_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', value):
        raise PracticeError('需要有效的请求标识', 400)
    return value


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise PracticeError('题目或选项编号无效', 400)
    return value
