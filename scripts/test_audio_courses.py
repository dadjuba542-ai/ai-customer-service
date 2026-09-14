#!/usr/bin/env python3
"""音频课程模块回归测试：建表 / 检索 / CRUD / 鉴权 / 上传 / 开关。"""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='acs-audio-') as tmpdir:
        os.environ['DATABASE_DIR'] = tmpdir
        os.environ['UPLOAD_DIR'] = str(Path(tmpdir) / 'uploads')
        os.environ['SECRET_KEY'] = 'test-secret-key-32-bytes-minimum!!'
        os.environ['COZE_API_KEY'] = 'test-coze-key'

        from app import app
        from config import Config
        from models import create_user, get_db_connection, set_setting
        from routes.auth import hash_password
        from services import feature_flags

        client = app.test_client()
        client.environ_base['HTTP_USER_AGENT'] = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        )

        # 表结构
        conn = get_db_connection()
        course_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audio_courses'"
        ).fetchone()
        fts_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audio_courses_fts'"
        ).fetchone()
        conn.close()
        assert_true(course_table is not None, 'audio_courses 表缺失')
        assert_true(fts_table is not None, 'audio_courses_fts 表缺失')

        create_user('audio-admin', hash_password('very-secure-password'), is_admin=1)
        login = client.post('/api/auth/login', json={
            'username': 'audio-admin', 'password': 'very-secure-password',
        })
        assert_true(login.status_code == 200, login.get_data(as_text=True))
        auth = {'Authorization': f"Bearer {login.get_json()['token']}"}

        # 默认关闭：公开与后台接口都应 403
        assert_true(feature_flags.is_enabled('audio_courses') is False, '默认应为关闭')
        assert_true(client.get('/api/audio-courses').status_code == 403, '关闭时公开列表应 403')
        assert_true(client.get('/api/admin/audio-courses', headers=auth).status_code == 403, '关闭时后台列表应 403')

        # 开启开关
        set_setting('audio_courses_enabled', '1')
        assert_true(feature_flags.is_enabled('audio_courses') is True, '开启后应读到 True')

        # 鉴权：无 token 不能访问后台写接口
        assert_true(client.get('/api/admin/audio-courses').status_code == 401, '后台列表应要求鉴权')

        # 危险 URL 在写入时被清洗
        created = client.post('/api/admin/audio-courses', headers=auth, json={
            'title': '便秘怎么调理',
            'series': '五期课程',
            'episode': 1,
            'duration_seconds': 125,
            'audio_url': 'javascript:alert(1)',
            'external_url': 'https://example.com/course',
            'tags': '便秘,肠道',
            'summary': '讲便秘的日常调理',
            'content': '益生菌和膳食纤维的搭配思路',
            'status': 1,
        })
        assert_true(created.status_code == 201, created.get_data(as_text=True))
        course_id = created.get_json()['id']

        admin_list = client.get('/api/admin/audio-courses', headers=auth).get_json()['courses']
        assert_true(len(admin_list) == 1, '后台列表应返回 1 条')
        assert_true(admin_list[0]['audio_url'] == '', 'javascript: 音频地址应被清洗为空')
        assert_true(admin_list[0]['external_url'] == 'https://example.com/course', '外链应保留')

        # 使用合法音频地址
        client.put(f'/api/admin/audio-courses/{course_id}', headers=auth, json={
            'title': '便秘怎么调理',
            'audio_url': '/uploads/audio/demo.mp3',
            'tags': '便秘,肠道',
            'summary': '讲便秘的日常调理',
            'content': '益生菌和膳食纤维的搭配思路',
        })

        # 标签命中
        tag_hits = client.get('/api/audio-courses/search', query_string={'q': '便秘'}).get_json()
        assert_true(tag_hits['total'] >= 1, '标签检索应命中')
        # 正文 / 全文命中
        text_hits = client.get('/api/audio-courses/search', query_string={'q': '益生菌'}).get_json()
        assert_true(text_hits['total'] >= 1, '正文检索应命中')
        # 标签筛选
        tag_filter = client.get('/api/audio-courses', query_string={'tag': '便秘'}).get_json()
        assert_true(tag_filter['total'] >= 1, '标签筛选应命中')
        # 公开详情
        detail = client.get(f'/api/audio-courses/{course_id}')
        assert_true(detail.status_code == 200, '公开详情应 200')
        assert_true(detail.get_json()['title'] == '便秘怎么调理', '详情标题不对')

        # 公开列表/搜索为精简投影：不含文字稿与音频地址
        public_item = client.get('/api/audio-courses').get_json()['items'][0]
        assert_true('content' not in public_item, '公开列表不应返回文字稿')
        assert_true('audio_url' not in public_item, '公开列表不应返回音频地址')
        assert_true('content' in detail.get_json(), '详情应返回完整字段')

        # PUT 合并：只传标题时保留其它字段
        client.put(f'/api/admin/audio-courses/{course_id}', headers=auth,
                   json={'title': '便秘怎么调理（改）'})
        after_merge = client.get(f'/api/audio-courses/{course_id}').get_json()
        assert_true(after_merge['title'] == '便秘怎么调理（改）', '标题应更新')
        assert_true(after_merge['audio_url'] == '/uploads/audio/demo.mp3', '未传字段应保留')
        client.put(f'/api/admin/audio-courses/{course_id}', headers=auth,
                   json={'title': '便秘怎么调理'})

        # 严格 URL 清洗：含引号 / 伪协议一律清空
        client.put(f'/api/admin/audio-courses/{course_id}', headers=auth,
                   json={'external_url': 'https://ex.com/"><script>focus()</script>'})
        strict = client.get('/api/admin/audio-courses', headers=auth).get_json()['courses'][0]
        assert_true(strict['external_url'] == '', '含引号的地址应被清空')
        client.put(f'/api/admin/audio-courses/{course_id}', headers=auth,
                   json={'external_url': 'https://example.com/course'})

        # 隐藏后公开不可见
        client.put(f'/api/admin/audio-courses/{course_id}/status', headers=auth, json={'status': 0})
        assert_true(client.get(f'/api/audio-courses/{course_id}').status_code == 404, '隐藏后详情应 404')
        assert_true(
            client.get('/api/audio-courses/search', query_string={'q': '便秘'}).get_json()['total'] == 0,
            '隐藏后不应出现在检索结果',
        )
        client.put(f'/api/admin/audio-courses/{course_id}/status', headers=auth, json={'status': 1})

        # 上传：扩展名 / 体积校验
        bad_ext = client.post(
            '/api/admin/audio-courses/upload-audio', headers=auth,
            data={'file': (io.BytesIO(b'hello'), 'note.txt')},
            content_type='multipart/form-data',
        )
        assert_true(bad_ext.status_code == 400, '非音频扩展名应拒绝')

        original_limit = Config.AUDIO_MAX_UPLOAD_BYTES
        try:
            Config.AUDIO_MAX_UPLOAD_BYTES = 4
            too_big = client.post(
                '/api/admin/audio-courses/upload-audio', headers=auth,
                data={'file': (io.BytesIO(b'0123456789'), 'a.mp3')},
                content_type='multipart/form-data',
            )
            assert_true(too_big.status_code == 400, '超体积音频应拒绝')
        finally:
            Config.AUDIO_MAX_UPLOAD_BYTES = original_limit

        upload = client.post(
            '/api/admin/audio-courses/upload-audio', headers=auth,
            data={'file': (io.BytesIO(b'ID3fakeaudio'), 'demo.mp3')},
            content_type='multipart/form-data',
        )
        assert_true(upload.status_code == 200, upload.get_data(as_text=True))
        assert_true(upload.get_json()['url'].startswith('/uploads/audio/'), '上传返回值缺少音频地址')

        # 文件清理：换音频删旧文件，删课程删文件
        upload_dir = os.environ['UPLOAD_DIR']
        first_url = upload.get_json()['url']
        first_path = os.path.join(upload_dir, 'audio', first_url.rsplit('/', 1)[-1])
        assert_true(os.path.isfile(first_path), '上传文件应存在')

        upload2 = client.post(
            '/api/admin/audio-courses/upload-audio', headers=auth,
            data={'file': (io.BytesIO(b'ID3fakeaudio2'), 'demo2.mp3')},
            content_type='multipart/form-data',
        )
        second_url = upload2.get_json()['url']
        second_path = os.path.join(upload_dir, 'audio', second_url.rsplit('/', 1)[-1])

        cleanup_id = client.post('/api/admin/audio-courses', headers=auth, json={
            'title': '清理测试',
            'audio_url': first_url,
        }).get_json()['id']
        client.put(f'/api/admin/audio-courses/{cleanup_id}', headers=auth,
                   json={'audio_url': second_url})
        assert_true(not os.path.exists(first_path), '换音频后旧文件应删除')
        assert_true(os.path.isfile(second_path), '新音频文件应保留')
        client.delete(f'/api/admin/audio-courses/{cleanup_id}', headers=auth)
        assert_true(not os.path.exists(second_path), '删除课程后音频文件应删除')

        # 置顶 + 首页展示
        second = client.post('/api/admin/audio-courses', headers=auth, json={
            'title': '腹胀专题',
            'audio_url': '/uploads/audio/b.mp3',
            'show_on_home': 1,
        })
        assert_true(second.status_code == 201, second.get_data(as_text=True))
        second_id = second.get_json()['id']

        pin_res = client.put(f'/api/admin/audio-courses/{course_id}/flag', headers=auth,
                             json={'flag': 'pinned', 'value': 1})
        assert_true(pin_res.status_code == 200, pin_res.get_data(as_text=True))
        client.put(f'/api/admin/audio-courses/{course_id}/flag', headers=auth,
                   json={'flag': 'show_on_home', 'value': 1})

        home = client.get('/api/audio-courses', query_string={'mode': 'home'}).get_json()
        home_ids = [item['id'] for item in home['items']]
        assert_true(course_id in home_ids and second_id in home_ids, '首页应包含勾选课程')
        assert_true(home_ids[0] == course_id, '置顶课程应排在首页最前')

        bad_flag = client.put(f'/api/admin/audio-courses/{course_id}/flag', headers=auth,
                              json={'flag': 'ghost', 'value': 1})
        assert_true(bad_flag.status_code == 400, '未知选项应 400')

        third = client.post('/api/admin/audio-courses', headers=auth,
                            json={'title': '未上首页', 'audio_url': '/uploads/audio/c.mp3'})
        third_id = third.get_json()['id']
        home_after = [
            item['id']
            for item in client.get('/api/audio-courses', query_string={'mode': 'home'}).get_json()['items']
        ]
        assert_true(third_id not in home_after, '未勾选首页的课程不应出现')

        # 删除
        for cid in (course_id, second_id, third_id):
            client.delete(f'/api/admin/audio-courses/{cid}', headers=auth)
        assert_true(
            client.get('/api/admin/audio-courses', headers=auth).get_json()['courses'] == [],
            '删除后列表应为空',
        )

        # 关闭开关后再次拦截
        set_setting('audio_courses_enabled', '0')
        assert_true(client.get('/api/audio-courses').status_code == 403, '再次关闭后应 403')

    print('audio courses tests passed')


if __name__ == '__main__':
    main()
