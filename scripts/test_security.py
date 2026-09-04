#!/usr/bin/env python3
import os
import tempfile
from pathlib import Path
import sys

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-security-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ.pop('PUBLIC_REGISTRATION_ENABLED', None)

        from app import app
        from models import save_chat_history, set_setting

        client = app.test_client()
        client.environ_base["HTTP_USER_AGENT"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        assert_true(
            client.post('/api/auth/register', json={'username': 'public', 'password': 'longpassword'}).status_code == 403,
            'public registration should be disabled by default',
        )
        assert_true(client.post('/api/chat/send', json={'message': 'hello'}).status_code == 401, 'chat must require a session')

        set_setting('default_team_names', '["一团队"]')
        response = client.post('/api/auth/session', json={
            'user_id': 'victim-choice',
            'team_name': '一团队',
            'member_name': '张三',
        })
        assert_true(response.status_code == 200, response.get_data(as_text=True))
        token = response.get_json()['token']
        claims = jwt.decode(token, os.environ['SECRET_KEY'], algorithms=['HS256'])
        assert_true(claims['user_id'] != 'victim-choice', 'guest IDs must be server-generated')

        own_id = save_chat_history(claims['user_id'], '产品咨询', 'own', 'reply')
        other_id = save_chat_history('someone-else', '产品咨询', 'other', 'reply')
        auth = {'Authorization': f'Bearer {token}'}
        deleted = client.post('/api/history/batch-delete', headers=auth, json={'ids': [own_id, other_id]})
        assert_true(deleted.status_code == 200, deleted.get_data(as_text=True))
        assert_true(deleted.get_json()['count'] == 1, deleted.get_json())

        print('PASS: security smoke test')


if __name__ == '__main__':
    main()
