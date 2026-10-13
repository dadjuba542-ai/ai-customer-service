#!/usr/bin/env python3
"""User history deletion must hide frontend data without changing backend records."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='acs-history-delete-') as tmpdir:
        os.environ.update(DATABASE_DIR=tmpdir, UPLOAD_DIR=str(Path(tmpdir) / 'uploads'),
                          SECRET_KEY='test-secret-key-32-bytes-minimum!!',
                          CRAWL_GUARD_ENABLED='false', CLEANUP_ON_STARTUP='false')
        from app import app
        from config import Config
        from models import (create_user, save_chat_history, get_db_connection, init_db,
                            get_recent_chat_turns, get_chat_history_by_ids,
                            set_chat_feedback, set_feedback_reason, cleanup_old_history)
        from routes.auth import generate_token, hash_password
        from services.ai_review_service import upsert_review_note
        from services.handoff_service import _context_from_history
        from services.chat_service import build_coze_chat_history

        client = app.test_client()
        uid = create_user('history-user', hash_password('test-password'))
        admin_id = create_user('history-admin', hash_password('test-password'), is_admin=1)
        auth = {'Authorization': f'Bearer {generate_token(uid)}'}
        admin_auth = {'Authorization': f'Bearer {generate_token(admin_id)}'}
        deleted_id = save_chat_history(uid, '产品咨询', 'deleted question', 'deleted answer',
                                      team_name='team', member_name='member', agent_id='aura')
        other_id = save_chat_history('other-user', '产品咨询', 'private question', 'private answer', agent_id='aura')
        visible_id = save_chat_history(uid, '使用答疑', 'visible question', 'visible answer', agent_id='coder')
        assert set_chat_feedback(deleted_id, uid, 0)
        assert set_feedback_reason(deleted_id, uid, 'not helpful')
        note = upsert_review_note(deleted_id, admin_id, 'retained note', 0)
        assert client.get('/api/nutritionist-notes/unread', headers=auth).get_json()['total'] == 1

        paths = ['/api/admin/dashboard/' + suffix for suffix in (
            'stats', 'trends', 'agent-usage', 'recent', 'hot-questions', 'user-stats',
            'feedback-stats', 'feedback-overview', 'feedback-by-agent', 'negative-feedback',
            'feedback-reasons', 'team-question-stats', 'qa-records', 'qa-records/export')]
        paths.append('/api/admin/ai-review')

        def backend_snapshot():
            result = {}
            for path in paths:
                response = client.get(path, headers=admin_auth)
                assert response.status_code == 200, (path, response.get_data(as_text=True))
                result[path] = response.get_data()
            return result

        before = backend_snapshot()
        response = client.post('/api/history/batch-delete', headers=auth,
                               json={'ids': [deleted_id, deleted_id, other_id]})
        assert response.status_code == 200 and response.get_json()['count'] == 1
        assert client.post('/api/history/batch-delete', headers=auth,
                           json={'ids': [deleted_id]}).get_json()['count'] == 0
        assert backend_snapshot() == before
        conn = get_db_connection()
        row = dict(conn.execute('SELECT * FROM chat_history WHERE id = ?', (deleted_id,)).fetchone())
        assert row['user_deleted_at'] and row['user_message'] == 'deleted question'
        assert row['bot_response'] == 'deleted answer' and row['feedback'] == 0
        assert conn.execute('SELECT user_deleted_at FROM chat_history WHERE id = ?', (other_id,)).fetchone()[0] is None
        assert conn.execute('SELECT content FROM nutritionist_review_notes WHERE id = ?', (note['id'],)).fetchone()[0] == 'retained note'
        conn.close()

        for path, key in [('/api/history', 'history'), ('/api/history?query_type=产品咨询', 'history')]:
            items = client.get(path, headers=auth).get_json()[key]
            assert deleted_id not in {item['id'] for item in items}
        for path in ['/api/history/sessions', '/api/history/sessions?query_type=产品咨询']:
            sessions = client.get(path, headers=auth).get_json()['sessions']
            assert deleted_id not in {item['id'] for session in sessions for item in session['items']}
        assert client.get(f'/api/history/{deleted_id}', headers=auth).status_code == 404
        assert client.get(f'/api/history/{visible_id}', headers=auth).status_code == 200
        assert get_chat_history_by_ids([deleted_id, other_id, visible_id], uid)[0]['id'] == visible_id
        for kwargs in [dict(agent_id='aura'), dict(query_type='产品咨询'), dict(shared=True)]:
            turns = get_recent_chat_turns(uid, **kwargs)
            assert all(turn['user_message'] != 'deleted question' for turn in turns)
        assert all(item['content'] not in {'deleted question', 'deleted answer'}
                   for item in build_coze_chat_history(uid, 'aura', '产品咨询', shared=True))
        rows, context = _context_from_history(uid, [deleted_id, other_id, visible_id])
        assert [row['id'] for row in rows] == [visible_id]
        assert all(item['text'] not in {'deleted question', 'deleted answer'} for item in context)
        assert not set_chat_feedback(deleted_id, uid, 1)
        assert not set_feedback_reason(deleted_id, uid, 'changed')
        assert client.post('/api/chat/feedback', headers=auth,
                           json={'history_id': deleted_id, 'feedback': 1}).status_code == 404
        assert client.post('/api/share-events', headers=auth,
                           json={'history_id': deleted_id}).status_code == 404
        assert client.get('/api/nutritionist-notes/unread', headers=auth).get_json() == {'items': [], 'total': 0}
        assert client.post(f"/api/nutritionist-notes/{note['id']}/read", headers=auth).status_code == 404
        # Backend review remains editable, but a new revision must not reappear for the user.
        upsert_review_note(deleted_id, admin_id, 'updated retained note', 1)
        assert client.get('/api/nutritionist-notes/unread', headers=auth).get_json()['total'] == 0

        fresh_id = save_chat_history(uid, '产品咨询', 'fresh question', 'fresh answer', agent_id='aura')
        assert client.get(f'/api/history/{fresh_id}', headers=auth).status_code == 200
        assert get_recent_chat_turns(uid, agent_id='aura') == [{'user_message': 'fresh question', 'bot_response': 'fresh answer'}]
        old_id = save_chat_history(uid, '产品咨询', 'old question', 'old answer', agent_id='aura')
        old_note = upsert_review_note(old_id, admin_id, 'old note', 0)
        conn = get_db_connection()
        conn.execute("UPDATE chat_history SET created_at = datetime('now', '-31 days') WHERE id = ?", (old_id,))
        conn.commit(); conn.close()
        before_cleanup = backend_snapshot()
        cleanup_old_history(30)
        cleanup_old_history(30)
        assert backend_snapshot() == before_cleanup
        assert client.get(f'/api/history/{old_id}', headers=auth).status_code == 404
        assert client.get(f'/api/history/{fresh_id}', headers=auth).status_code == 200
        conn = get_db_connection()
        assert conn.execute('SELECT content FROM nutritionist_review_notes WHERE id = ?', (old_note['id'],)).fetchone()[0] == 'old note'
        hidden_at = conn.execute('SELECT user_deleted_at FROM chat_history WHERE id = ?', (old_id,)).fetchone()[0]
        conn.close()
        assert hidden_at
        init_db()
        assert backend_snapshot() == before_cleanup
        assert client.get(f'/api/history/{deleted_id}', headers=auth).status_code == 404
        assert client.get(f'/api/history/{old_id}', headers=auth).status_code == 404
        # Exercise the same startup path when cleanup is explicitly enabled.
        Config.CLEANUP_ON_STARTUP = True
        init_db()
        assert backend_snapshot() == before_cleanup
        assert client.get('/api/nutritionist-notes/unread', headers=auth).get_json()['total'] == 0
    print('PASS: history soft deletion, backend retention, context isolation, notes, cleanup and restart')


if __name__ == '__main__':
    main()
