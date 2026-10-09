#!/usr/bin/env python3
"""后台「问答记录」（按周期查看问答）回归测试。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-qa-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'
        os.environ['CRAWL_GUARD_ENABLED'] = 'false'

        from app import app
        from models import create_user, save_chat_history
        from routes.auth import hash_password

        client = app.test_client()
        create_user('qa-admin', hash_password('very-secure-password'), is_admin=1)
        login = client.post('/api/auth/login', json={
            'username': 'qa-admin', 'password': 'very-secure-password',
        })
        assert_true(login.status_code == 200, login.get_data(as_text=True))
        auth = {'Authorization': f"Bearer {login.get_json()['token']}"}

        # 未登录拒绝
        assert_true(client.get('/api/admin/dashboard/qa-records').status_code == 401,
                    '未登录应 401')

        save_chat_history(user_id='u1', query_type='产品咨询', user_message='便秘用什么产品',
                          bot_response='可以试试一排净润肠养生，注意不能口服。', agent_id='aura')
        save_chat_history(user_id='u1', query_type='使用答疑', user_message='产品怎么用',
                          bot_response='按包装推荐量使用即可。', agent_id='coder')

        listing = client.get('/api/admin/dashboard/qa-records', headers=auth).get_json()
        assert_true(listing['total'] == 2, '总数应为 2')
        assert_true(listing['items'][0].get('agent_name'), '应带智能体名称')
        assert_true(listing['pages'] == 1, '默认每页 20 条，应为 1 页')

        assert_true(
            client.get('/api/admin/dashboard/qa-records?keyword=便秘', headers=auth)
            .get_json()['total'] == 1, '关键词筛选失败')
        assert_true(
            client.get('/api/admin/dashboard/qa-records?query_type=使用答疑', headers=auth)
            .get_json()['total'] == 1, '类型筛选失败')
        assert_true(
            client.get('/api/admin/dashboard/qa-records?start_date=2099-01-01', headers=auth)
            .get_json()['total'] == 0, '未来日期应无数据')

        paged = client.get('/api/admin/dashboard/qa-records?limit=1&page=1', headers=auth).get_json()
        assert_true(len(paged['items']) == 1 and paged['pages'] == 2, '分页不正确')

        export = client.get('/api/admin/dashboard/qa-records/export', headers=auth)
        assert_true(export.status_code == 200, '导出应 200')
        body = export.get_data(as_text=True)
        assert_true('时间' in body and '回答' in body, '缺少 CSV 表头')
        assert_true('便秘用什么产品' in body, '导出缺少数据行')
        assert_true(export.headers.get('Content-Type', '').startswith('text/csv'), '导出类型不对')

    print('test_qa_records: all checks passed')


if __name__ == '__main__':
    main()
