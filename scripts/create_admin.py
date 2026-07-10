#!/usr/bin/env python3
"""Create the first administrator without exposing an admin registration endpoint."""

import argparse
import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config
from models import create_user, init_db
from routes.auth import hash_password


def main():
    parser = argparse.ArgumentParser(description='Create an AI宝儿 administrator')
    parser.add_argument('username')
    args = parser.parse_args()

    username = args.username.strip()
    if not re.fullmatch(r'[A-Za-z0-9_.\-\u4e00-\u9fff]{1,50}', username):
        parser.error('username format is invalid')

    password = getpass.getpass('Password (10-128 characters): ')
    if not 10 <= len(password) <= 128:
        parser.error('password must contain 10 to 128 characters')

    Config.validate()
    init_db()
    user_id = create_user(username, hash_password(password), is_admin=1)
    if not user_id:
        parser.error('username already exists')
    print(f'created administrator: {args.username}')


if __name__ == '__main__':
    main()
