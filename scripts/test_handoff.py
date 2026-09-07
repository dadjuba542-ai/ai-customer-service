#!/usr/bin/env python3
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jwt


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-handoff-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'

        from app import app
        from models import create_user, get_db_connection, save_chat_history, set_setting
        from routes.auth import hash_password
        from services.chat_service import build_chat_context

        client = app.test_client()
        client.environ_base["HTTP_USER_AGENT"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        admin_id = create_user('nutritionist', hash_password('very-secure-password'), is_admin=1)
        assert_true(admin_id, 'admin creation failed')
        login = client.post('/api/auth/login', json={'username': 'nutritionist', 'password': 'very-secure-password'})
        assert_true(login.status_code == 200, login.get_data(as_text=True))
        admin_token = login.get_json()['token']
        admin_headers = {'Authorization': f'Bearer {admin_token}'}

        set_setting('default_team_names', '["营养一组"]')
        set_setting('handoff_enabled', '1')
        set_setting('handoff_ai_agent_id', 'aura')

        unregistered = client.post('/api/admin/handoff/agent/status', headers=admin_headers, json={'online': True})
        assert_true(unregistered.status_code == 403, '未添加坐席不应允许自动开通上线')

        add_agent = client.post('/api/admin/handoff/agents', headers=admin_headers, json={
            'username': 'nutritionist', 'display_name': '营养师小王', 'max_concurrent': 1,
        })
        assert_true(add_agent.status_code == 201, add_agent.get_data(as_text=True))
        assert_true(add_agent.get_json()['agent']['max_concurrent'] == 1, add_agent.get_json())
        duplicate_agent = client.post('/api/admin/handoff/agents', headers=admin_headers, json={'username': 'nutritionist'})
        assert_true(duplicate_agent.status_code == 409, '重复添加坐席应返回409')
        bad_agent = client.post('/api/admin/handoff/agents', headers=admin_headers, json={'username': '不存在的用户'})
        assert_true(bad_agent.status_code == 404, '不存在的用户名应返回404')

        status = client.post('/api/admin/handoff/agent/status', headers=admin_headers, json={'online': True, 'max_concurrent': 1})
        assert_true(status.status_code == 200, status.get_data(as_text=True))
        assert_true(status.get_json()['agent']['online'] == 1, 'agent should be online')

        def guest(name):
            response = client.post('/api/auth/session', json={'team_name': '营养一组', 'member_name': name})
            assert_true(response.status_code == 200, response.get_data(as_text=True))
            token = response.get_json()['token']
            claims = jwt.decode(token, os.environ['SECRET_KEY'], algorithms=['HS256'])
            return token, claims['user_id']

        guest1_token, guest1_id = guest('用户甲')
        guest2_token, guest2_id = guest('用户乙')
        guest3_token, guest3_id = guest('用户丙')
        guest4_token, guest4_id = guest('用户丁')
        guest5_token, guest5_id = guest('用户戊')
        guest1_headers = {'Authorization': f'Bearer {guest1_token}'}
        guest2_headers = {'Authorization': f'Bearer {guest2_token}'}
        guest3_headers = {'Authorization': f'Bearer {guest3_token}'}
        guest4_headers = {'Authorization': f'Bearer {guest4_token}'}
        guest5_headers = {'Authorization': f'Bearer {guest5_token}'}

        empty_start = client.post('/api/handoff/start', headers=guest1_headers, json={'query_type': '营养咨询'})
        assert_true(empty_start.status_code == 400, '空留言不应创建转人工会话')

        history_id = save_chat_history(guest1_id, '营养咨询', '最近胃口不好', '可以先观察饮食情况', agent_id='aura')
        start1 = client.post('/api/handoff/start', headers=guest1_headers, json={
            'history_ids': [history_id], 'query_type': '营养咨询', 'note': '希望真人再帮我看看',
        })
        assert_true(start1.status_code == 201, start1.get_data(as_text=True))
        session1 = start1.get_json()['session']
        assert_true(session1['status'] == 'assigned', session1)
        initial_messages = client.get(
            f"/api/handoff/messages/{session1['session_id']}", headers=guest1_headers,
        ).get_json()['messages']
        assert_true(
            any(item['sender_role'] == 'user' and item['content'] == '希望真人再帮我看看' for item in initial_messages),
            '转接前最后一个有效问题应立即出现在客服消息流',
        )

        start2 = client.post('/api/handoff/start', headers=guest2_headers, json={'query_type': '营养咨询', 'note': '第二位用户的问题'})
        assert_true(start2.status_code == 201, start2.get_data(as_text=True))
        session2 = start2.get_json()['session']
        assert_true(session2['status'] == 'queued', session2)
        assert_true(session2['queue_position'] == 1, session2)

        duplicate = client.post('/api/handoff/start', headers=guest2_headers, json={'note': '重复点击'})
        assert_true(duplicate.status_code == 201, duplicate.get_data(as_text=True))
        assert_true(duplicate.get_json()['session']['session_id'] == session2['session_id'], 'start must be idempotent')

        forbidden = client.get(f"/api/handoff/session/{session1['session_id']}", headers=guest2_headers)
        assert_true(forbidden.status_code == 404, 'users must not read another user session')

        claim1 = client.post(f"/api/admin/handoff/{session1['session_id']}/claim", headers=admin_headers)
        assert_true(claim1.status_code == 200, claim1.get_data(as_text=True))
        assert_true(claim1.get_json()['session']['status'] == 'active', claim1.get_json())
        assert_true(claim1.get_json()['session']['ai_context'][0]['text'] == '最近胃口不好', 'AI context missing')

        user_message = client.post('/api/handoff/message', headers=guest1_headers, json={
            'session_id': session1['session_id'], 'content': '我已经持续三天了',
        })
        assert_true(user_message.status_code == 201, user_message.get_data(as_text=True))
        reply = client.post(f"/api/admin/handoff/{session1['session_id']}/reply", headers=admin_headers, json={'content': '请先告诉我每天的饮食情况'})
        assert_true(reply.status_code == 201, reply.get_data(as_text=True))
        active_remove = client.delete(f'/api/admin/handoff/agents/{admin_id}', headers=admin_headers)
        assert_true(active_remove.status_code == 409, '有进行中会话的坐席不应被移除')
        messages = client.get(f"/api/handoff/messages/{session1['session_id']}", headers=guest1_headers)
        roles = [item['sender_role'] for item in messages.get_json()['messages']]
        assert_true('user' in roles and 'agent' in roles and 'system' in roles, roles)

        ai_blocked = client.post('/api/chat/send', headers=guest1_headers, json={
            'message': '不应该再由AI回复', 'channel': 'nutrition_consultation', 'agent_id': 'creative',
        })
        assert_true(ai_blocked.status_code == 409, ai_blocked.get_data(as_text=True))

        close1 = client.post(f"/api/admin/handoff/{session1['session_id']}/close", headers=admin_headers, json={'reason': 'done'})
        assert_true(close1.status_code == 200, close1.get_data(as_text=True))

        archive = client.get('/api/admin/handoff/archive?page=1&limit=20', headers=admin_headers)
        assert_true(archive.status_code == 200, archive.get_data(as_text=True))
        archive_data = archive.get_json()
        assert_true(archive_data['pagination']['total'] == 1, archive_data)
        assert_true(archive_data['items'][0]['session_id'] == session1['session_id'], archive_data)
        assert_true(archive_data['items'][0]['last_question'] == '我已经持续三天了', archive_data)
        assert_true(archive_data['items'][0]['last_reply'] == '请先告诉我每天的饮食情况', archive_data)

        archive_filtered = client.get(
            '/api/admin/handoff/archive?keyword=%E9%A5%AE%E9%A3%9F&team=%E8%90%A5%E5%85%BB%E4%B8%80%E7%BB%84&service_mode=live',
            headers=admin_headers,
        )
        assert_true(archive_filtered.status_code == 200, archive_filtered.get_data(as_text=True))
        assert_true(archive_filtered.get_json()['pagination']['total'] == 1, archive_filtered.get_json())

        archive_detail = client.get(
            f"/api/admin/handoff/archive/{session1['session_id']}", headers=admin_headers,
        )
        assert_true(archive_detail.status_code == 200, archive_detail.get_data(as_text=True))
        archive_session = archive_detail.get_json()['session']
        assert_true(archive_session['status'] == 'closed', archive_session)
        assert_true(any(item['sender_role'] == 'agent' for item in archive_session['messages']), archive_session)
        assert_true(archive_session['ai_context'][0]['text'] == '最近胃口不好', archive_session)

        history = client.get(
            f'/api/admin/handoff/users/{guest1_id}/history?limit=20', headers=admin_headers,
        )
        assert_true(history.status_code == 200, history.get_data(as_text=True))
        assert_true(history.get_json()['items'][0]['session_id'] == session1['session_id'], history.get_json())
        excluded_history = client.get(
            f'/api/admin/handoff/users/{guest1_id}/history?exclude_session_id={session1["session_id"]}',
            headers=admin_headers,
        )
        assert_true(excluded_history.get_json()['pagination']['total'] == 0, excluded_history.get_json())
        assert_true(
            client.get(f"/api/admin/handoff/archive/{session2['session_id']}", headers=admin_headers).status_code == 404,
            'open session must not be readable through archive detail',
        )
        assert_true(client.get('/api/admin/handoff/archive').status_code == 401, 'archive requires admin auth')

        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO handoff_messages (session_id, sender_role, sender_id, content)
               VALUES (?, 'user', ?, '=1+1')''',
            (session1['session_id'], guest1_id),
        )
        conn.commit()
        conn.close()
        export_one = client.post(
            '/api/admin/handoff/export', headers=admin_headers,
            json={'session_ids': [session1['session_id']]},
        )
        assert_true(export_one.status_code == 200, export_one.get_data(as_text=True))
        assert_true(export_one.data.startswith(b'\xef\xbb\xbf'), 'CSV should include UTF-8 BOM')
        assert_true(export_one.headers.get('X-Export-Row-Count') == '1', export_one.headers)
        assert_true('attachment; filename=' in export_one.headers.get('Content-Disposition', ''), export_one.headers)
        export_text = export_one.data.decode('utf-8-sig')
        assert_true('我已经持续三天了' in export_text and '请先告诉我每天的饮食情况' in export_text, export_text)
        assert_true("'=1+1" in export_text, 'CSV formula injection should be neutralized')
        assert_true('转人工前 AI 对话' not in export_text and '最近胃口不好' not in export_text, 'AI context must not be exported')

        export_filtered = client.post(
            '/api/admin/handoff/export', headers=admin_headers,
            json={'filters': {'keyword': '饮食', 'team': '营养一组', 'service_mode': 'live'}},
        )
        assert_true(export_filtered.status_code == 200, export_filtered.get_data(as_text=True))
        assert_true(export_filtered.headers.get('X-Export-Row-Count') == '1', export_filtered.headers)
        conn = get_db_connection()
        audit_rows = conn.execute(
            'SELECT export_scope, row_count FROM handoff_export_logs ORDER BY id ASC'
        ).fetchall()
        conn.close()
        assert_true([row['export_scope'] for row in audit_rows] == ['single', 'filtered'], audit_rows)
        assert_true(all(row['row_count'] == 1 for row in audit_rows), audit_rows)

        current2 = client.get('/api/handoff/current', headers=guest2_headers).get_json()['session']
        assert_true(current2['status'] == 'assigned', current2)

        close2 = client.post(f"/api/admin/handoff/{session2['session_id']}/close", headers=admin_headers, json={'reason': 'done'})
        assert_true(close2.status_code == 200, close2.get_data(as_text=True))

        start3 = client.post('/api/handoff/start', headers=guest3_headers, json={
            'query_type': '营养咨询', 'note': '这条问题需要稍后留言回复',
        })
        session3 = start3.get_json()['session']
        deferred3 = client.post('/api/handoff/defer', headers=guest3_headers, json={'session_id': session3['session_id']})
        assert_true(deferred3.status_code == 200, deferred3.get_data(as_text=True))
        assert_true(deferred3.get_json()['session']['service_mode'] == 'message', deferred3.get_json())
        from services.handoff_service import has_open_handoff_session
        assert_true(not has_open_handoff_session(guest3_id), '留言模式不应阻塞 AI 通道')
        claim3 = client.post(f"/api/admin/handoff/{session3['session_id']}/claim", headers=admin_headers)
        assert_true(claim3.status_code == 200, claim3.get_data(as_text=True))
        reply3 = client.post(f"/api/admin/handoff/{session3['session_id']}/reply", headers=admin_headers, json={
            'content': '这是营养师稍后的留言回复',
        })
        assert_true(reply3.status_code == 201, reply3.get_data(as_text=True))
        assert_true(not reply3.get_json()['message']['auto_closed'], '留言回复后不应立即关闭')
        current3 = client.get('/api/handoff/current', headers=guest3_headers).get_json()['session']
        assert_true(current3 is not None and current3['status'] == 'active', current3)
        assert_true(current3['service_mode'] == 'message', current3)
        follow3 = client.post('/api/handoff/message', headers=guest3_headers, json={
            'session_id': session3['session_id'], 'content': '请问需要注意哪些饮食禁忌？',
        })
        assert_true(follow3.status_code == 201, follow3.get_data(as_text=True))
        reply3b = client.post(f"/api/admin/handoff/{session3['session_id']}/reply", headers=admin_headers, json={'content': '避免辛辣刺激'})
        assert_true(reply3b.status_code == 201, reply3b.get_data(as_text=True))
        assert_true(not reply3b.get_json()['message']['auto_closed'], '多轮留言中不应关闭')
        from services.handoff_service import _reconcile_locked
        conn = get_db_connection()
        conn.execute(
            "UPDATE handoff_sessions SET last_message_at = datetime('now', '-25 hour') WHERE session_id = ?",
            (session3['session_id'],),
        )
        _reconcile_locked(conn)
        conn.commit()
        conn.close()
        archived3 = client.get(f"/api/handoff/session/{session3['session_id']}", headers=guest3_headers).get_json()['session']
        assert_true(archived3['status'] == 'closed' and archived3['close_reason'] == 'message_idle', archived3)
        assert_true(client.get('/api/handoff/current', headers=guest3_headers).get_json()['session'] is None, '留言 24h 空闲后应自动归档')
        recent3 = client.get('/api/handoff/recent?limit=20', headers=guest3_headers)
        assert_true(recent3.status_code == 200, recent3.get_data(as_text=True))
        recent3_session = next(item for item in recent3.get_json()['sessions'] if item['session_id'] == session3['session_id'])
        assert_true(recent3_session['unread_count'] == 1, recent3_session)
        restored3 = client.get(f"/api/handoff/session/{session3['session_id']}", headers=guest3_headers)
        assert_true(restored3.status_code == 200, restored3.get_data(as_text=True))
        restored3_messages = restored3.get_json()['session']
        assert_true(restored3_messages['unread_count'] == 1, restored3_messages)
        visible3 = client.get(f"/api/handoff/messages/{session3['session_id']}", headers=guest3_headers)
        assert_true(any(item['sender_role'] == 'agent' and item['content'] == '避免辛辣刺激' for item in visible3.get_json()['messages']), visible3.get_json())
        recent3_read = client.get('/api/handoff/recent?limit=20', headers=guest3_headers).get_json()
        recent3_read_session = next(item for item in recent3_read['sessions'] if item['session_id'] == session3['session_id'])
        assert_true(recent3_read_session['unread_count'] == 0, recent3_read_session)

        start4 = client.post('/api/handoff/start', headers=guest4_headers, json={
            'query_type': '营养咨询', 'note': '测试等待超时自动留言',
        })
        session4 = start4.get_json()['session']
        from services.handoff_service import _reconcile_locked
        conn = get_db_connection()
        conn.execute(
            "UPDATE handoff_sessions SET live_deadline_at = datetime('now', '-1 second') WHERE session_id = ?",
            (session4['session_id'],),
        )
        _reconcile_locked(conn)
        conn.commit()
        conn.close()
        timed_out4 = client.get(f"/api/handoff/session/{session4['session_id']}", headers=guest4_headers).get_json()['session']
        assert_true(timed_out4['service_mode'] == 'message', timed_out4)
        claim4 = client.post(f"/api/admin/handoff/{session4['session_id']}/claim", headers=admin_headers)
        assert_true(claim4.status_code == 200, claim4.get_data(as_text=True))
        reply4 = client.post(f"/api/admin/handoff/{session4['session_id']}/reply", headers=admin_headers, json={'content': '超时留言回复'})
        assert_true(reply4.status_code == 201, reply4.get_data(as_text=True))
        assert_true(not reply4.get_json()['message']['auto_closed'], '超时转留言后回复不应立即关闭')
        close4 = client.post(f"/api/admin/handoff/{session4['session_id']}/close", headers=admin_headers, json={'reason': 'done'})
        assert_true(close4.status_code == 200, close4.get_data(as_text=True))

        offline = client.post('/api/admin/handoff/agent/status', headers=admin_headers, json={'online': False, 'max_concurrent': 3})
        assert_true(offline.status_code == 200, offline.get_data(as_text=True))

        removed_agent = client.delete(f'/api/admin/handoff/agents/{admin_id}', headers=admin_headers)
        assert_true(removed_agent.status_code == 200, removed_agent.get_data(as_text=True))
        blocked_after_remove = client.post('/api/admin/handoff/agent/status', headers=admin_headers, json={'online': True})
        assert_true(blocked_after_remove.status_code == 403, '移除坐席后不应允许上线')
        re_add_agent = client.post('/api/admin/handoff/agents', headers=admin_headers, json={
            'username': 'nutritionist', 'display_name': '营养师小王', 'max_concurrent': 3,
        })
        assert_true(re_add_agent.status_code == 201, re_add_agent.get_data(as_text=True))

        qr_empty = client.get('/api/admin/handoff/quick-replies', headers=admin_headers)
        assert_true(qr_empty.status_code == 200 and qr_empty.get_json()['quick_replies'] == [], qr_empty.get_data(as_text=True))
        qr_create = client.post('/api/admin/handoff/quick-replies', headers=admin_headers, json={
            'title': '确认收货地址', 'content': '您好，麻烦确认一下您的收货地址和联系方式。', 'sort_order': 1, 'enabled': True,
        })
        assert_true(qr_create.status_code == 201, qr_create.get_data(as_text=True))
        qr_id = qr_create.get_json()['quick_reply']['id']
        qr_create2 = client.post('/api/admin/handoff/quick-replies', headers=admin_headers, json={
            'title': '饮食禁忌提醒', 'content': '请避免辛辣、生冷及高糖食物。', 'sort_order': 2, 'enabled': False,
        })
        assert_true(qr_create2.status_code == 201, qr_create2.get_data(as_text=True))
        qr_id2 = qr_create2.get_json()['quick_reply']['id']
        qr_bad = client.post('/api/admin/handoff/quick-replies', headers=admin_headers, json={'title': '', 'content': 'x'})
        assert_true(qr_bad.status_code == 400, '空标题应返回400')
        qr_all = client.get('/api/admin/handoff/quick-replies', headers=admin_headers)
        assert_true(qr_all.get_json()['quick_replies'][0]['id'] == qr_id, qr_all.get_json())
        qr_enabled = client.get('/api/admin/handoff/quick-replies?enabled=1', headers=admin_headers)
        enabled_ids = [item['id'] for item in qr_enabled.get_json()['quick_replies']]
        assert_true(qr_id in enabled_ids and qr_id2 not in enabled_ids, enabled_ids)
        qr_update = client.put(f'/api/admin/handoff/quick-replies/{qr_id}', headers=admin_headers, json={
            'content': '您好，请确认收货地址和联系电话。', 'sort_order': 3,
        })
        assert_true(qr_update.status_code == 200, qr_update.get_data(as_text=True))
        assert_true(qr_update.get_json()['quick_reply']['sort_order'] == 3, qr_update.get_json())
        qr_toggle = client.put(f'/api/admin/handoff/quick-replies/{qr_id2}', headers=admin_headers, json={'enabled': True})
        assert_true(qr_toggle.status_code == 200 and qr_toggle.get_json()['quick_reply']['enabled'] == 1, qr_toggle.get_json())
        qr_delete = client.delete(f'/api/admin/handoff/quick-replies/{qr_id}', headers=admin_headers)
        assert_true(qr_delete.status_code == 200, qr_delete.get_data(as_text=True))
        qr_missing = client.delete(f'/api/admin/handoff/quick-replies/{qr_id}', headers=admin_headers)
        assert_true(qr_missing.status_code == 404, '删除不存在话术应返回404')
        qr_remaining = client.get('/api/admin/handoff/quick-replies', headers=admin_headers).get_json()['quick_replies']
        assert_true(len(qr_remaining) == 1 and qr_remaining[0]['id'] == qr_id2, qr_remaining)

        offline_start = client.post('/api/handoff/start', headers=guest5_headers, json={
            'query_type': '营养咨询', 'note': '营养师离线时直接留言', 'service_mode': 'message',
        })
        assert_true(offline_start.status_code == 201, offline_start.get_data(as_text=True))
        offline_session = offline_start.get_json()['session']
        assert_true(offline_session['service_mode'] == 'message', offline_session)
        assert_true(offline_session['status'] == 'queued', offline_session)
        assert_true(not has_open_handoff_session(guest5_id), '离线留言不应进入在线排队状态')

        status = client.post('/api/admin/handoff/agent/status', headers=admin_headers, json={'online': True, 'max_concurrent': 3})
        assert_true(status.status_code == 200, status.get_data(as_text=True))
        offline_claim = client.post(f"/api/admin/handoff/{offline_session['session_id']}/claim", headers=admin_headers)
        assert_true(offline_claim.status_code == 200, offline_claim.get_data(as_text=True))
        offline_reply = client.post(f"/api/admin/handoff/{offline_session['session_id']}/reply", headers=admin_headers, json={'content': '离线留言回复'})
        assert_true(offline_reply.status_code == 201, offline_reply.get_data(as_text=True))
        assert_true(not offline_reply.get_json()['message']['auto_closed'], '离线留言回复不应立即关闭')
        close_offline = client.post(f"/api/admin/handoff/{offline_session['session_id']}/close", headers=admin_headers, json={'reason': 'done'})
        assert_true(close_offline.status_code == 200, close_offline.get_data(as_text=True))

        # 人工账号体系：管理员创建非管理员人工账号，用其登录工作台接待
        seat_add = client.post('/api/admin/handoff/agents', headers=admin_headers, json={
            'username': 'nutritionist02', 'display_name': '营养师小李', 'max_concurrent': 2,
            'password': 'seat-password-123',
        })
        assert_true(seat_add.status_code == 201, seat_add.get_data(as_text=True))
        no_pwd = client.post('/api/admin/handoff/agents', headers=admin_headers, json={'username': 'nutritionist03'})
        assert_true(no_pwd.status_code == 404, no_pwd.get_data(as_text=True))
        weak_pwd = client.post('/api/admin/handoff/agents', headers=admin_headers, json={'username': 'nutritionist03', 'password': 'short'})
        assert_true(weak_pwd.status_code == 400, weak_pwd.get_data(as_text=True))
        seat_login = client.post('/api/auth/login', json={'username': 'nutritionist02', 'password': 'seat-password-123'})
        assert_true(seat_login.status_code == 200, seat_login.get_data(as_text=True))
        seat_data = seat_login.get_json()
        assert_true(seat_data['is_admin'] == 0 and seat_data['is_agent'], seat_data)
        seat_headers = {'Authorization': f"Bearer {seat_data['token']}"}
        seat_profile = client.get('/api/user/profile', headers=seat_headers).get_json()
        assert_true(seat_profile['is_agent'] and not seat_profile['is_admin'], seat_profile)
        seat_online = client.post('/api/admin/handoff/agent/status', headers=seat_headers, json={'online': True})
        assert_true(seat_online.status_code == 200, seat_online.get_data(as_text=True))
        assert_true(client.get('/api/admin/handoff/agent/me', headers=seat_headers).status_code == 200, 'seat must access agent/me')
        assert_true(client.get('/api/admin/handoff/quick-replies?enabled=1', headers=seat_headers).status_code == 200, 'seat must load quick replies')
        assert_true(client.get('/api/admin/handoff/agents', headers=seat_headers).status_code == 403, 'seat must not manage agent list')
        assert_true(client.post('/api/admin/handoff/quick-replies', headers=seat_headers, json={'title': 'x', 'content': 'y'}).status_code == 403, 'seat must not create quick replies')
        assert_true(client.get('/api/admin/handoff/agent/me').status_code == 401, 'anonymous must be rejected on agent api')
        seat_offline = client.post('/api/admin/handoff/agent/status', headers=seat_headers, json={'online': False})
        assert_true(seat_offline.status_code == 200, seat_offline.get_data(as_text=True))

        from services.handoff_service import start_handoff
        identities = [
            {'user_id': f'concurrent-user-{index}', 'team_name': '营养一组', 'member_name': f'并发用户{index}'}
            for index in range(5)
        ]
        with ThreadPoolExecutor(max_workers=5) as pool:
            concurrent_sessions = list(pool.map(lambda identity: start_handoff(identity, query_type='营养咨询', note='并发测试问题'), identities))
        statuses = [item['status'] for item in concurrent_sessions]
        assert_true(statuses.count('assigned') == 3 and statuses.count('queued') == 2, statuses)
        assert_true(len({item['session_id'] for item in concurrent_sessions}) == 5, 'concurrent sessions must be unique')

        forged_context = build_chat_context({
            'message': '测试指定智能体', 'channel': 'nutrition_consultation', 'agent_id': 'creative',
        }, {'user_id': guest3_id, 'team_name': '营养一组', 'member_name': '用户丙'})
        assert_true(forged_context.agent_id == 'aura', 'nutrition AI must be forced by server setting')

        notifications = client.get('/api/admin/handoff/notifications', headers=admin_headers)
        assert_true(notifications.status_code == 200, notifications.get_data(as_text=True))
        assert_true('cursor' in notifications.get_json(), 'notification cursor missing')

        page = client.get('/consultant')
        assert_true(page.status_code == 200 and '营养师工作台' in page.get_data(as_text=True), 'consultant page missing')

        print('PASS: handoff end-to-end smoke test')


if __name__ == '__main__':
    main()
