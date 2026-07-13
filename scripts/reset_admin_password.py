#!/usr/bin/env python3
"""Reset an existing administrator password without storing plaintext in Git."""

import argparse
import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config
from models import get_user_by_username, init_db, update_user_password_hash
from routes.auth import hash_password


def main():
    parser = argparse.ArgumentParser(description='Reset an AI宝儿 administrator password')
    parser.add_argument('username')
    args = parser.parse_args()

    username = args.username.strip()
    if not re.fullmatch(r'[A-Za-z0-9_.\-\u4e00-\u9fff]{1,50}', username):
        parser.error('username format is invalid')

    password = getpass.getpass('New password (10-128 characters): ')
    if not 10 <= len(password) <= 128:
        parser.error('password must contain 10 to 128 characters')

    Config.validate()
    init_db()
    user = get_user_by_username(username)
    if not user:
        parser.error('administrator does not exist; use create_admin.py first')
    if not user.get('is_admin'):
        parser.error('the user is not an administrator')

    update_user_password_hash(user['user_id'], hash_password(password))
    print(f'password reset for administrator: {username}')


if __name__ == '__main__':
    main()
