#!/usr/bin/env python3
"""案例系统 / 人工客服系统 独立开关的回归测试。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-flags-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'

        from app import app
        from models import create_user, set_setting
        from routes.auth import hash_password
        from services import feature_flags
        from services.chat_service import find_related_cases
        from services.handoff_service import (
            HandoffError,
            assign_available,
            get_handoff_settings,
            start_handoff,
            stop_handoff_reconciler_for_tests,
        )

        client = app.test_client()
        client.environ_base["HTTP_USER_AGENT"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        admin_id = create_user('flag-admin', hash_password('very-secure-password'), is_admin=1)
        login = client.post('/api/auth/login', json={'username': 'flag-admin', 'password': 'very-secure-password'})
        assert_true(login.status_code == 200, login.get_data(as_text=True))
        auth = {'Authorization': f"Bearer {login.get_json()['token']}"}

        try:
            # 1) 默认状态：案例系统开、人工客服系统关
            assert_true(feature_flags.is_enabled('cases') is True, '案例系统默认应为开启')
            assert_true(feature_flags.is_enabled('handoff') is False, '人工客服系统默认应为关闭')
            assert_true(feature_flags.is_enabled('nope') is False, '未知开关必须按关闭处理')

            states = {item['name']: item for item in feature_flags.list_states()}
            assert_true(states['cases']['source'] == 'default', 'cases 应来自默认值')
            assert_true(states['handoff']['default'] is False, 'handoff 默认值应为关闭')

            # 2) 公开接口只暴露最小信息
            public = client.get('/api/feature-flags').get_json()['flags']
            assert_true(public['cases']['enabled'] is True, '公开接口 cases 状态不对')
            assert_true('setting_key' not in public['cases'], '公开接口不应暴露内部 key')

            # 3) 案例系统关闭：入口全被禁用
            set_setting('cases_enabled', '0')
            assert_true(feature_flags.is_enabled('cases') is False, '关闭后应读到 False')
            blocked = client.get('/api/cases')
            assert_true(blocked.status_code == 403, f'案例列表应 403，实际 {blocked.status_code}')
            assert_true(blocked.get_json()['code'] == 'feature_disabled', '缺少 feature_disabled 标识')
            assert_true(client.get('/api/cases/1').status_code == 403, '案例详情应 403')
            assert_true(client.get('/api/case-library-config').status_code == 403, '案例库配置应 403')
            assert_true(client.get('/api/admin/cases', headers=auth).status_code == 403, '后台案例列表应 403')
            assert_true(client.get('/api/admin/case-tags', headers=auth).status_code == 403, '后台案例标签应 403')

            # 调用链路：聊天不再推荐相关案例
            related = find_related_cases('便秘怎么办')
            assert_true(related['items'] == [] and related['total'] == 0, '案例关闭时不应返回相关案例')

            # 4) 案例系统关闭不影响人工客服系统（反之亦然，状态互不串）
            assert_true(feature_flags.is_enabled('handoff') is False, 'handoff 状态不应被 cases 影响')
            # 其它系统照常工作
            assert_true(client.get('/api/default-team').status_code == 200, '默认团队接口应正常')
            assert_true(client.get('/api/news').status_code == 200, '资讯接口应正常')

            # 5) 重新开启案例系统后恢复
            set_setting('cases_enabled', '1')
            assert_true(client.get('/api/cases').status_code == 200, '案例系统重开后应恢复 200')

            # 6) 人工客服系统关闭：页面、接口、定时任务全停
            assert_true(client.get('/consultant').status_code == 403, '坐席工作台页面应 403')
            assert_true(client.post('/api/handoff/start', json={'note': 'hi'}).status_code == 403, '转人工应 403')
            assert_true(client.get('/api/handoff/current').status_code == 403, '当前会话应 403')
            assert_true(client.get('/api/admin/handoff/queue', headers=auth).status_code == 403, '坐席队列应 403')
            # /config 是例外：前台靠它拿到 enabled=false 来隐藏入口
            config = client.get('/api/handoff/config')
            assert_true(config.status_code == 200, '/api/handoff/config 应始终可读')
            assert_true(config.get_json()['enabled'] is False, 'config 应返回 enabled=False')
            assert_true(assign_available() == 0, '关闭时派单定时任务应空转返回 0')
            try:
                start_handoff({'user_id': 'u1'}, note='hi')
                raise AssertionError('关闭时 start_handoff 必须抛错')
            except HandoffError as exc:
                assert_true(exc.status_code == 403, f'关闭时应返回 403，实际 {exc.status_code}')

            # 7) 开启人工客服系统：未配置 AI 智能体时拒绝
            bad = client.put('/api/admin/feature-flags', headers=auth, json={'name': 'handoff', 'enabled': True})
            assert_true(bad.status_code == 400, f'未配置智能体不应允许开启，实际 {bad.status_code}')
            set_setting('handoff_ai_agent_id', 'aura')
            ok = client.put('/api/admin/feature-flags', headers=auth, json={'name': 'handoff', 'enabled': True})
            assert_true(ok.status_code == 200, ok.get_data(as_text=True))
            assert_true(feature_flags.is_enabled('handoff') is True, '开启后状态应为 True')
            assert_true(get_handoff_settings()['enabled'] is True, '人工设置里的 enabled 应同步')
            assert_true(client.get('/api/handoff/config').get_json()['enabled'] is True, 'config 应同步为 True')
            assert_true(client.get('/consultant').status_code == 200, '开启后坐席工作台应可访问')

            # 8) 批量更新 + 关闭人工客服系统
            both = client.put('/api/admin/feature-flags', headers=auth,
                              json={'flags': {'handoff': False, 'cases': False}})
            assert_true(both.status_code == 200, both.get_data(as_text=True))
            assert_true(feature_flags.is_enabled('handoff') is False, '批量关闭 handoff 失败')
            assert_true(feature_flags.is_enabled('cases') is False, '批量关闭 cases 失败')
            assert_true(client.get('/consultant').status_code == 403, '再次关闭后工作台应 403')

            # 9) 未知开关报 404，不产生脏数据
            unknown = client.put('/api/admin/feature-flags', headers=auth, json={'name': 'ghost', 'enabled': True})
            assert_true(unknown.status_code == 404, f'未知开关应 404，实际 {unknown.status_code}')
        finally:
            stop_handoff_reconciler_for_tests()

    print('feature flags tests passed')


if __name__ == '__main__':
    main()
