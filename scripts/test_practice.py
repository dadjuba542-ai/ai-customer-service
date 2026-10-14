#!/usr/bin/env python3
"""Isolated SQLite/API regression tests for the ten-question decision game."""
import json
import csv
import io
import os
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix='acs-quiz-test-')
os.environ.update(DATABASE_DIR=TMP.name, UPLOAD_DIR=str(Path(TMP.name)/'uploads'),
                  SECRET_KEY='test-practice-secret-key-at-least-32-characters', COZE_API_KEY='test-key',
                  HANDOFF_ENABLED='false', CRAWL_GUARD_ENABLED='false', PRACTICE_ENABLED='false')
from app import app
from models import create_user, init_db, set_setting
from routes.auth import generate_guest_token, generate_token, hash_password
from services import practice_service as p, feature_flags, practice_weekly as w
from services.practice_bank import seed_bank
from services.security_service import reset_rate_limits_for_tests

A = {'user_id': 'quiz-user-a', 'team_name': '一团队', 'member_name': '小王'}
B = {'user_id': 'quiz-user-b', 'team_name': '二团队', 'member_name': '小李'}
STAMP = datetime(2026, 10, 14, 10, tzinfo=p.TZ)

def rid():
    return uuid.uuid4().hex

class PracticeTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(p, 'now', return_value=STAMP)
        self.mock_clock = self.clock.start()
        reset_rate_limits_for_tests()
        with p.db(True) as conn:
            for table in ('entry_requests', 'entry_events', 'weekly_selections', 'weekly_plans', 'admin_operations', 'stage_daily', 'stages', 'visits', 'points', 'answers', 'sessions', 'daily', 'questions'):
                conn.execute('DELETE FROM practice_quiz_' + table)
            seed_bank(conn)
        set_setting('practice_enabled', '1')

    def tearDown(self):
        self.clock.stop()

    def start(self, who=A, mode='daily', batch=1, key=None):
        return p.create_session(who, {'request_id': key or rid(), 'mode': mode, 'batch_no': batch})

    def answer_payload(self, s, correct=True):
        with p.db() as conn:
            questions = json.loads(conn.execute('SELECT snapshot FROM practice_quiz_sessions WHERE id=?', (s['id'],)).fetchone()[0])
        q = questions[s['cursor']]
        return {'request_id': rid(), 'question_id': q['id'], 'option_index': (q['answer_index'] + (0 if correct else 1)) % 4}

    def answer(self, s, who=A, correct=True):
        return p.perform(s['id'], who, 'answer', self.answer_payload(s, correct))

    def next(self, s, who=A):
        return p.perform(s['id'], who, 'next', {'request_id': rid(), 'question_id': s['questions'][s['cursor']]['id']})

    def finish(self, s=None, who=A, correct=10):
        s = s or self.start(who)
        while not s['completed']:
            s = self.answer(s, who, s['cursor'] < correct)
            if not s['completed']:
                s = self.next(s, who)
        return s

    def test_seed_and_repeat_migration(self):
        data = p.admin_data()
        self.assertEqual(len(data['questions']), 100)
        self.assertEqual(len(data['batches']), 10)
        self.assertEqual(len({q['title'] for q in data['questions']}), 100)
        for category in data['categories']:
            self.assertEqual(sum(q['category'] == category for q in data['questions']), 25)
        q = data['questions'][0]
        p.save_question(q['id'], dict(q, title='修改后保留', enabled=True))
        init_db()
        self.assertEqual(p.admin_data()['questions'][0]['title'], '修改后保留')

    def test_no_answer_leak_before_selection(self):
        s = self.start()
        self.assertEqual(len(s['questions']), 1)
        self.assertNotIn('snapshot', s)
        self.assertNotIn('answer_index', s['questions'][0])
        self.assertNotIn('explanation', s['questions'][0])
        self.assertNotIn('snapshot', p.daily())
        s = self.answer(s)
        self.assertIn('method', s['questions'][0])
        self.assertEqual(len(s['questions']), 1)

    def test_daily_fixed_and_snapshot_preserved(self):
        today = p.daily()
        s = self.start()
        qid = s['questions'][0]['id']
        q = next(q for q in p.admin_data()['questions'] if q['id'] == qid)
        p.save_question(qid, dict(q, title='后来改的题目', enabled=True))
        self.assertNotEqual(p.get_session(s['id'], A)['questions'][0]['title'], '后来改的题目')
        self.assertNotEqual(self.start(B)['questions'][0]['title'], '后来改的题目')
        self.assertEqual(p.daily(), today)
        self.mock_clock.return_value = STAMP + timedelta(days=1)
        self.assertNotEqual(p.daily()['batch_no'], today['batch_no'])

    def test_daily_reward_and_replay(self):
        s = self.finish(correct=7)
        self.assertEqual(s['points'], 70)
        self.assertEqual(s['correct_count'], 7)
        self.assertEqual(self.start()['id'], s['id'])
        replay = self.finish(self.start(mode='free', batch=s['batch_no']))
        self.assertEqual(replay['points'], 0)
        self.assertEqual(p.scores(A)['today_points'], 70)
        self.assertEqual(len(s['questions']), 10)

    def test_zero_score_has_no_rank(self):
        s = self.finish(correct=0)
        self.assertEqual(s['points'], 0)
        self.assertIsNone(p.scores(A)['my_rank'])
        self.assertEqual(p.scores(A)['my_honor'], '')

    def test_incomplete_awards_nothing(self):
        s = self.answer(self.start())
        self.assertEqual(s['points'], 0)
        self.assertEqual(p.scores(A)['today_points'], 0)
        self.assertFalse(s['completed'])

    def test_duplicate_create_and_request_conflict(self):
        key = rid()
        s = self.start(mode='free', key=key)
        self.assertEqual(s, self.start(mode='free', key=key))
        with self.assertRaises(p.PracticeError):
            self.start(mode='free', batch=2, key=key)

    def test_answer_is_locked_and_next_is_idempotent(self):
        s = self.start()
        payload = self.answer_payload(s)
        s = p.perform(s['id'], A, 'answer', payload)
        self.assertEqual(s, p.perform(s['id'], A, 'answer', payload))
        with self.assertRaises(p.PracticeError):
            p.perform(s['id'], A, 'answer', dict(payload, option_index=(payload['option_index']+1)%4))
        advanced = self.next(s)
        self.assertEqual(advanced['cursor'], 1)
        self.assertEqual(self.next(s)['cursor'], 1)
        with self.assertRaises(p.PracticeError):
            self.next(advanced)
        # Reusing an answer request ID for another question cannot create a new answer.
        with self.assertRaises(p.PracticeError):
            p.perform(s['id'], A, 'answer', dict(self.answer_payload(advanced), request_id=payload['request_id']))

    def test_concurrent_last_answer_and_daily_create(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            starts = list(pool.map(lambda _: self.start(), range(6)))
        self.assertEqual(len({s['id'] for s in starts}), 1)
        s = starts[0]
        for _ in range(9):
            s = self.next(self.answer(s))
        payload = self.answer_payload(s)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: p.perform(s['id'], A, 'answer', payload), range(8)))
        self.assertTrue(all(r['points'] == 100 for r in results))
        with p.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM practice_quiz_points').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM practice_quiz_answers').fetchone()[0], 10)

    def test_concurrent_conflicting_choices(self):
        s = self.start()
        payload = self.answer_payload(s)
        def submit(index):
            try:
                return p.perform(s['id'], A, 'answer', dict(payload, request_id=rid(), option_index=index))
            except p.PracticeError as exc:
                return exc.status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(sum(r == 409 for r in results), 3)

    def test_failure_rolls_back_final_answer_then_retry(self):
        s = self.start()
        for _ in range(9):
            s = self.next(self.answer(s))
        payload = self.answer_payload(s)
        with patch.object(p, 'now', side_effect=RuntimeError('simulated interruption')):
            with self.assertRaises(RuntimeError):
                p.perform(s['id'], A, 'answer', payload)
        restored = p.get_session(s['id'], A)
        self.assertEqual(restored['answered_count'], 9)
        result = p.perform(s['id'], A, 'answer', payload)
        self.assertEqual(result['points'], 100)

    def test_cross_day_and_beijing_boundary(self):
        self.mock_clock.return_value = datetime(2026,10,14,23,59,tzinfo=p.TZ)
        s = self.start()
        self.mock_clock.return_value += timedelta(minutes=2)
        old = self.finish(s)
        self.assertEqual(old['points'], 0)
        self.assertIn('跨日', old['point_reason'])
        self.assertEqual(self.finish()['points'], 100)
        self.assertEqual(p.scores(A)['today_points'], 100)

    def test_weekly_titles_ties_and_team_isolation(self):
        monday = STAMP - timedelta(days=STAMP.weekday())
        self.mock_clock.return_value = monday - timedelta(days=1)  # previous Sunday
        same = dict(A, user_id='same-name-other-id')
        third = dict(A, user_id='third-user', member_name='小陈')
        fourth = dict(A, user_id='fourth-user', member_name='小张')
        self.finish(who=A)
        self.finish(who=same)
        self.finish(who=third, correct=9)
        self.finish(who=fourth, correct=8)
        self.finish(who=B)
        self.mock_clock.return_value = monday
        self.assertEqual(p.scores(A)['my_honor'], '周冠军')
        self.assertEqual(p.scores(same)['my_honor'], '周冠军')
        self.assertEqual(p.scores(third)['my_honor'], '沟通达人')
        self.assertEqual(p.scores(fourth)['my_honor'], '学习之星')
        self.assertEqual(p.scores(A)['week_points'], 0)
        for who in (A, same, third):
            self.finish(who=who, correct=9 if who == third else 10)
        scores = p.scores(A)
        self.assertEqual([r['rank'] for r in scores['items']], [1, 1, 3])
        self.assertNotIn(B['member_name'], str(scores['items']))
        self.assertTrue(all('user_id' not in r for r in scores['items']))
        self.mock_clock.return_value = monday + timedelta(days=14)
        self.assertEqual(p.scores(A)['my_honor'], '')

    def test_private_records_and_session_isolation(self):
        s = self.start()
        self.answer(s)
        with self.assertRaises(p.PracticeError) as ctx:
            p.get_session(s['id'], B)
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(p.PracticeError):
            p.perform(s['id'], B, 'answer', self.answer_payload(s))
        self.assertEqual(p.records(B)['total'], 0)
        self.assertEqual(self.start(mode='free')['answered_count'], 0)

    def test_disabled_batch_and_feature(self):
        with p.db(True) as conn:
            conn.execute('UPDATE practice_quiz_questions SET enabled=0 WHERE batch_no=1')
        self.assertEqual(len(p.catalog(A)['batches']), 9)
        with self.assertRaises(p.PracticeError):
            self.start(mode='free', batch=1)
        with p.db(True) as conn:
            conn.execute('UPDATE practice_quiz_questions SET enabled=0')
        with self.assertRaises(p.PracticeError):
            p.validate_ready()
        set_setting('practice_enabled', '0')
        with self.assertRaises(p.PracticeError):
            p.catalog(A)
        self.assertEqual(len(p.admin_data()['questions']), 100)

    def test_admin_validation_and_retention_metrics(self):
        q = p.admin_data()['questions'][0]
        for change in ({'options': ['a']*4}, {'answer_index': True}, {'enabled': 1}, {'sources': [{}]}, {'title': ''}):
            with self.assertRaises(p.PracticeError):
                p.save_question(q['id'], {**q, 'enabled': True, **change})
        p.catalog(A)
        self.finish()
        self.mock_clock.return_value += timedelta(days=1)
        p.catalog(A)
        self.start()
        metrics = p.admin_data()['summary'][0]
        self.assertEqual(metrics['visitors'], 1)
        self.assertEqual(metrics['participants'], 1)
        self.assertEqual(metrics['completed'], 1)
        self.assertEqual(metrics['next_day_returns'], 1)
        self.assertEqual(metrics['seven_day_returns'], 1)

    def csv_rows(self):
        return list(csv.DictReader(io.StringIO(p.export_bank().lstrip('\ufeff'))))

    def csv_text(self, rows):
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=p.CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def test_bulk_add_unlimited_bank_and_idempotency(self):
        rows = self.csv_rows()[:10]
        for index, row in enumerate(rows):
            row.update(id='', 关卡='11', 客户场景='新场景'+str(index), 版本='')
        text = self.csv_text(rows)
        self.assertEqual(p.preview_import({'csv':text})['added'], 10)
        request = {'request_id':rid(), 'csv':text}
        first = p.import_bank(request)
        self.assertEqual(first['added'], 10)
        self.assertEqual(p.import_bank(request), first)
        self.assertEqual(len(p.admin_data()['questions']), 110)
        self.assertEqual(len(p.catalog(A)['batches']), 11)
        new = self.start(mode='free', batch=11)
        self.assertGreater(new['questions'][0]['id'], 100)
        self.assertEqual(self.finish(new)['correct_count'], 10)

    def test_csv_round_trip_and_existing_snapshot(self):
        session = self.start(mode='free')
        rows = self.csv_rows()[:1]
        rows[0]['客户场景'] = '逗号,引号"与\n多行场景'
        rows[0]['A'] = '=一个文本选项'
        result = p.import_bank({'request_id':rid(), 'csv':self.csv_text(rows)})
        self.assertEqual(result['updated'], 1)
        exported = self.csv_rows()[0]
        self.assertEqual(exported['客户场景'], rows[0]['客户场景'])
        self.assertTrue(exported['A'].startswith("'="))
        self.assertEqual(p.preview_import({'csv':self.csv_text([exported])})['errors'], [])
        self.assertNotEqual(p.get_session(session['id'], A)['questions'][0]['title'], rows[0]['客户场景'])

    def test_bulk_invalid_row_and_stale_version_are_atomic(self):
        rows = self.csv_rows()[:2]
        rows[0]['客户场景'] = '不应写入'
        rows[1]['推荐答案'] = 'Z'
        text = self.csv_text(rows)
        self.assertTrue(p.preview_import({'csv':text})['errors'])
        with self.assertRaises(p.PracticeError):
            p.import_bank({'csv':text, 'request_id':rid()})
        self.assertNotEqual(p.admin_data()['questions'][0]['title'], '不应写入')
        rows = self.csv_rows()[:1]
        q = p.admin_data()['questions'][0]
        p.save_question(q['id'], {**q,'enabled':True,'title':'较新的编辑'})
        self.assertTrue(p.preview_import({'csv':self.csv_text(rows)})['errors'])
        with self.assertRaises(p.PracticeError):
            p.save_question(q['id'], {**q,'enabled':True})
        self.assertEqual(p.admin_data()['questions'][0]['title'], '较新的编辑')

    def test_draft_create_retry_and_capacity(self):
        q = p.admin_data()['questions'][0]
        data = {**q, 'batch_no':11, 'enabled':False, 'request_id':rid()}
        first = p.add_question(data)
        self.assertEqual(first, p.add_question(data))
        self.assertNotIn(11, [b['batch_no'] for b in p.catalog(A)['batches']])
        with self.assertRaises(p.PracticeError):
            p.add_question({**data,'request_id':rid(),'batch_no':1,'enabled':True})
        with self.assertRaises(p.PracticeError):
            p.add_question({**data,'title':'请求内容变化'})

    def stage(self, title='三伏天', count=50, start='2026-10-14', end='2026-10-20'):
        data = {'title':title,'description':'阶段练习','starts_on':start,'ends_on':end,'enabled':False,'request_id':rid()}
        stage_id = p.save_stage(data)['id']
        if count:
            rows = self.csv_rows()[:count]
            for i,row in enumerate(rows):
                row.update(id='', 关卡=str(i//10+1), 分类=title, 版本='')
            p.import_bank({'csv':self.csv_text(rows),'stage_id':stage_id,'request_id':rid()})
            p.save_stage({**data,'enabled':True},stage_id)
        return stage_id

    def test_stage_schedule_isolation_and_shared_points(self):
        sid = self.stage()
        catalog = p.catalog(A)
        self.assertEqual(catalog['stage']['id'],sid)
        self.assertEqual(catalog['stage']['question_count'],50)
        self.assertEqual(len(catalog['stage']['batches']),5)
        self.assertEqual(len(catalog['batches']),10)
        self.assertEqual(len(p.admin_data()['questions']),100)
        session = p.create_session(A,{'mode':'daily','stage_id':sid,'request_id':rid()})
        self.assertEqual(session['stage_title'],'三伏天')
        self.assertEqual(self.finish(session)['points'],100)
        self.assertEqual(self.start()['id'],session['id'])
        free = p.create_session(A,{'mode':'free','stage_id':sid,'batch_no':1,'request_id':rid()})
        self.assertEqual(self.finish(free)['points'],0)
        self.assertEqual(p.scores(A)['today_points'],100)
        self.mock_clock.return_value = STAMP-timedelta(days=1)
        self.assertIsNone(p.promotion()['stage'])
        self.mock_clock.return_value = STAMP+timedelta(days=6,hours=13,minutes=59)
        self.assertIsNotNone(p.promotion()['stage'])
        self.mock_clock.return_value += timedelta(minutes=2)
        self.assertIsNone(p.promotion()['stage'])
        with self.assertRaises(p.PracticeError):
            p.create_session(B,{'mode':'free','stage_id':sid,'batch_no':1,'request_id':rid()})
        self.assertEqual(p.get_session(session['id'],A)['stage_title'],'三伏天')

    def test_stage_replace_snapshot_and_switch(self):
        sid = self.stage(count=10)
        s = p.create_session(A,{'mode':'daily','stage_id':sid,'request_id':rid()})
        original = s['questions'][0]['title']
        rows = self.csv_rows()[:10]
        for i,row in enumerate(rows):
            row.update(id='',版本='',客户场景='替换题目'+str(i))
        text = self.csv_text(rows)
        self.assertTrue(p.preview_import({'csv':text,'stage_id':sid})['errors'])
        self.assertEqual(p.preview_import({'csv':text,'stage_id':sid,'replace':True})['errors'],[])
        req = {'csv':text,'stage_id':sid,'replace':True,'request_id':rid()}
        p.import_bank(req)
        p.import_bank(req)
        self.assertEqual(len(p.admin_data(sid)['questions']),10)
        self.assertEqual(p.get_session(s['id'],A)['questions'][0]['title'],original)
        other = p.create_session(B,{'mode':'daily','stage_id':sid,'request_id':rid()})
        self.assertEqual(other['questions'][0]['title'],original) # fixed today's topic
        free = p.create_session(B,{'mode':'free','stage_id':sid,'batch_no':1,'request_id':rid()})
        self.assertTrue(free['questions'][0]['title'].startswith('替换题目'))
        replacement = self.stage(title='新阶段',count=10)
        self.assertEqual(p.promotion()['stage']['id'],replacement)
        self.assertEqual(next(s for s in p.admin_data()['stages'] if s['id']==sid)['enabled'],0)
        self.assertEqual(p.get_session(s['id'],A)['stage_title'],'三伏天')

    def test_stage_and_regular_concurrent_daily_share_one_session(self):
        sid = self.stage(count=10)
        def start_stage(stage_id):
            return p.create_session(A,{'mode':'daily','stage_id':stage_id,'request_id':rid()})
        with ThreadPoolExecutor(max_workers=6) as pool:
            sessions = list(pool.map(start_stage,[0,sid,0,sid,0,sid]))
        self.assertEqual(len({s['id'] for s in sessions}),1)
        self.finish(sessions[0])
        self.assertEqual(p.scores(A)['today_points'],100)

    def test_stage_validation_and_cross_bank_import(self):
        sid = self.stage(count=0)
        with self.assertRaises(p.PracticeError):
            p.save_stage({'title':'测试','description':'','starts_on':'2026-10-20','ends_on':'2026-10-10','enabled':False},sid)
        with self.assertRaises(p.PracticeError):
            p.save_stage({'title':'测试','description':'','starts_on':'2026-10-14','ends_on':'2026-10-20','enabled':True},sid)
        self.assertTrue(p.preview_import({'csv':p.export_bank(),'stage_id':sid})['errors'])
        with self.assertRaises(p.PracticeError):
            p.import_bank({'csv':p.export_bank(),'replace':True,'request_id':rid()})
        self.assertIsNone(p.catalog(A)['stage'])

    def weekly_theme(self, enable=True):
        data={'title':'价格异议沟通周','description':'每周练习','starts_on':'2026-10-12','ends_on':'2026-10-18','enabled':False,'kind':'weekly','request_id':rid()}
        sid=p.save_stage(data)['id']
        originals=p.admin_data()['questions'][:25]
        for q in originals[:5]:
            p.add_question({**q,'title':'本期新题：'+q['title'],'stage_id':sid,'enabled':False,'request_id':rid()})
        selections=w.builder(sid)['selections']+[{'question_id':q['id'],'is_new':False} for q in originals]
        w.save_selections(sid,{'selections':selections})
        result=w.publish(sid,{'request_id':rid()})
        if enable:p.save_stage({**data,'enabled':True},sid)
        return sid,result

    def test_weekly_generation_and_seven_distinct_entry_questions(self):
        sid,result=self.weekly_theme()
        self.assertEqual(len(p.admin_data(sid)['questions']),30)
        self.assertEqual(len(p.admin_data()['questions']),105)
        self.assertEqual(len(result['schedule']),7)
        self.assertEqual(len({s['lead_question_id'] for s in result['schedule']}),7)
        self.assertEqual([s['batch_no'] for s in result['schedule']],[1,2,3,1,2,3,1])
        self.assertEqual([s['label'] for s in result['schedule']],['初练']*3+['复练']*3+['精选复练'])
        titles=[]
        for offset in range(7):
            self.mock_clock.return_value=STAMP.replace(day=12)+timedelta(days=offset)
            e=w.get_entry(B)['entry'];titles.append(e['question_title'])
            session=p.create_session(B,{'entry':True,'request_id':rid(),'entry_day':e['day'],'entry_stage_id':sid,'entry_question_id':e['question_id']})
            self.assertEqual(session['questions'][0]['title'],e['question_title'])
            self.assertNotIn('answer_index',e)
            self.assertNotIn('options',e)
            self.finish(session,who=B)
        self.assertEqual(len(set(titles)),7)
        self.assertTrue(all(t.startswith('本期新题') for t in titles[:5]))

    def test_weekly_new_csv_and_auto_enrollment(self):
        data={'title':'新题周','starts_on':'2026-10-12','ends_on':'2026-10-18','enabled':False,'kind':'weekly','request_id':rid()}
        sid=p.save_stage(data)['id']
        rows=self.csv_rows()[:5]
        for row in rows:row.update(id='',版本='',启用='1')
        text=self.csv_text(rows)
        self.assertEqual(w.preview_new(sid,{'csv':text})['errors'],[])
        request={'csv':text,'request_id':rid()}
        result=w.import_new(sid,request)
        self.assertEqual(w.import_new(sid,request),result)
        self.assertEqual(w.builder(sid)['new_count'],5)
        self.assertEqual(w.builder(sid)['selected_count'],5)
        self.assertEqual(len(p.admin_data()['questions']),105)
        self.assertEqual(len(p.admin_data(sid)['draft_questions']),5)

    def test_weekly_snapshot_and_publish_retry(self):
        sid,_=self.weekly_theme()
        source=w.builder(sid)['questions'][0]
        s=p.create_session(A,{'entry':True,'request_id':rid()})
        before=p.get_session(s['id'],A)
        p.save_question(source['id'],{**source,'title':'母题后来修改','enabled':False})
        self.assertFalse(any(q['title']=='母题后来修改' for q in p.admin_data(sid)['questions']))
        request={'request_id':rid()}
        w.publish(sid,request)
        w.publish(sid,request)
        self.assertEqual(len(p.admin_data(sid)['questions']),30)
        self.assertEqual(p.get_session(s['id'],A)['questions'],before['questions'])

    def test_entry_resume_free_replay_and_atomic_metrics(self):
        sid,_=self.weekly_theme()
        e=w.get_entry(A)['entry']
        self.assertEqual(p.admin_data()['entry_metrics'],[])
        w.record_impression(A,e);w.record_impression(A,e)
        key=rid();s=p.create_session(A,{'entry':True,'request_id':key})
        self.assertEqual(p.create_session(A,{'entry':True,'request_id':key})['id'],s['id'])
        s=self.answer(s)
        self.assertEqual(w.get_entry(A)['entry']['action'],'resume')
        self.assertEqual(p.create_session(A,{'entry':True,'request_id':rid()})['id'],s['id'])
        s=self.next(s)
        restored=p.create_session(A,{'entry':True,'request_id':rid()})
        self.assertEqual(restored['cursor'],1)
        completed=self.finish(s)
        self.assertEqual(completed['points'],100)
        self.assertEqual(w.get_entry(A)['entry']['mode'],'free')
        replay=p.create_session(A,{'entry':True,'request_id':rid()})
        self.assertEqual(replay['mode'],'free')
        self.assertEqual(p.create_session(A,{'entry':True,'request_id':rid()})['id'],replay['id'])
        self.assertEqual(self.finish(replay)['points'],0)
        metric=next(m for m in p.admin_data()['entry_metrics'] if m['stage_id']==sid)
        self.assertEqual([metric[k] for k in ('impression','click','first_answer','complete')],[1,1,1,1])
        self.assertEqual(p.scores(A)['today_points'],100)
        self.assertEqual(p.admin_data()['summary'][0]['visitors'],1)

    def test_entry_context_changes_and_closed_theme_fallback(self):
        sid,_=self.weekly_theme()
        e=w.get_entry(A)['entry']
        with self.assertRaises(p.PracticeError):
            p.create_session(A,{'entry':True,'request_id':rid(),'entry_day':'2026-10-13','entry_stage_id':sid,'entry_question_id':e['question_id']})
        self.mock_clock.return_value=STAMP+timedelta(days=5)
        self.assertEqual(w.get_entry(A)['entry']['stage_id'],0)
        self.assertEqual(w.get_entry(A)['entry']['mode'],'daily')
        self.assertEqual(p.create_session(A,{'entry':True,'request_id':rid()})['stage_id'],0)

    def test_weekly_dates_and_selection_validation(self):
        data={'title':'测试周','starts_on':'2026-10-12','ends_on':'2026-10-20','kind':'weekly','enabled':False,'request_id':rid()}
        with self.assertRaises(p.PracticeError):p.save_stage(data)
        sid=p.save_stage({**data,'ends_on':'2026-10-18'})['id']
        with self.assertRaises(p.PracticeError):w.publish(sid,{'request_id':rid()})
        with self.assertRaises(p.PracticeError):w.save_selections(sid,{'selections':[{'question_id':1,'is_new':False}]*2})
        self.assertEqual(w.builder(sid)['selected_count'],0)

    def test_http_auth_spoofing_and_admin(self):
        client = app.test_client()
        client.environ_base['HTTP_USER_AGENT'] = 'Mozilla/5.0'
        with app.app_context():
            token = generate_guest_token(A['user_id'], A['team_name'], A['member_name'])
        auth = {'Authorization': 'Bearer ' + token}
        self.assertEqual(client.get('/api/practice/catalog').status_code, 401)
        self.assertEqual(client.get('/api/practice/entry').status_code, 401)
        entry_response=client.get('/api/practice/entry',headers=auth)
        self.assertEqual(entry_response.status_code,200)
        self.assertNotIn('answer_index',entry_response.get_json()['entry'])
        self.assertNotIn('options',entry_response.get_json()['entry'])
        self.assertEqual(client.get('/api/admin/practice/stages/1/weekly',headers=auth).status_code,401)
        self.assertEqual(client.post('/api/admin/practice/stages/1/weekly/publish',headers=auth,json={'request_id':rid()}).status_code,401)
        response = client.post('/api/practice/sessions', headers=auth, json={
            'mode': 'daily', 'request_id': rid(), 'user_id': B['user_id'], 'team_name': B['team_name'], 'points': 100})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        s = response.get_json()
        with p.db() as conn:
            row = conn.execute('SELECT user_id,team_name,points FROM practice_quiz_sessions WHERE id=?', (s['id'],)).fetchone()
        self.assertEqual(tuple(row), (A['user_id'], A['team_name'], 0))
        self.assertEqual(client.get('/api/admin/practice', headers=auth).status_code, 401)
        self.assertEqual(client.get('/api/admin/practice/export', headers=auth).status_code, 401)
        self.assertEqual(client.post('/api/admin/practice/import', headers=auth, json={'csv':'x','request_id':rid()}).status_code, 401)
        self.assertEqual(client.post('/api/practice/sessions', headers=auth, json=[]).status_code, 400)
        user = create_user('quiz-admin-' + rid(), hash_password('password-123'), is_admin=1)
        with app.app_context():
            admin_auth = {'Authorization': 'Bearer ' + generate_token(user)}
        set_setting('practice_enabled', '0')
        self.assertEqual(client.get('/api/practice/catalog', headers=auth).status_code, 403)
        self.assertEqual(client.get('/api/admin/practice', headers=admin_auth).status_code, 200)
        enable = client.put('/api/admin/feature-flags', headers=admin_auth, json={'name': 'practice', 'enabled': True})
        self.assertEqual(enable.status_code, 200, enable.get_data(as_text=True))
        q = p.admin_data()['questions'][0]
        self.assertEqual(client.put('/api/admin/practice/questions/1', headers=admin_auth, json=dict(q, enabled=True)).status_code, 200)

if __name__ == '__main__':
    unittest.main(verbosity=2)
