"""Dependency-free service checks for the standalone seven-unit learning path."""
import sqlite3
import sys
import types
import importlib.util
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db_migrations import MIGRATIONS


conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row
conn.executescript('''
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category TEXT DEFAULT '', summary TEXT DEFAULT '', image_url TEXT DEFAULT '', sort_order INTEGER DEFAULT 0);
CREATE TABLE practice_learning_courses (product_id INTEGER PRIMARY KEY, published INTEGER, updated_at TEXT);
CREATE TABLE practice_learning_facts (id INTEGER PRIMARY KEY, product_id INTEGER, unit_no INTEGER, title TEXT, body TEXT, source_url TEXT, status TEXT, version INTEGER, updated_at TEXT);
CREATE TABLE practice_learning_unit_questions (product_id INTEGER, unit_no INTEGER, position INTEGER, question_id INTEGER, kind TEXT);
CREATE TABLE practice_quiz_questions (
 id INTEGER PRIMARY KEY, stage_id INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
 title TEXT, category TEXT DEFAULT '益生菌', product_id INTEGER, fact_id INTEGER,
 skill_code TEXT DEFAULT '', updated_at TEXT DEFAULT 'v1', source_question_id INTEGER,
 options TEXT DEFAULT '["A","B","C","D"]',answer_index INTEGER DEFAULT 0,
 explanation TEXT DEFAULT '先核对资料',method TEXT DEFAULT '我先核对资料再回答');
CREATE TABLE practice_learning_sessions (
 id TEXT PRIMARY KEY, user_id TEXT, request_id TEXT DEFAULT '',kind TEXT, product_id INTEGER, unit_no INTEGER,
 snapshot TEXT DEFAULT '{}',cursor INTEGER DEFAULT 0,completed INTEGER DEFAULT 0,correct_count INTEGER DEFAULT 0,
 assigned_day TEXT DEFAULT '2026-10-22',created_at TEXT,completed_at TEXT,
 UNIQUE(user_id,request_id));
CREATE TABLE practice_learning_answers (
 session_id TEXT,position INTEGER,option_index INTEGER,correct INTEGER,request_id TEXT,
 PRIMARY KEY(session_id,position),UNIQUE(session_id,request_id));
CREATE TABLE practice_learning_mastery (
 user_id TEXT,question_id INTEGER,question_version TEXT,correct_days INTEGER DEFAULT 0,
 last_correct_day TEXT,due_day TEXT,status TEXT DEFAULT 'learning',updated_at TEXT,
 PRIMARY KEY(user_id,question_id));
CREATE TABLE practice_learning_activity (user_id TEXT,day TEXT,kind TEXT,PRIMARY KEY(user_id,day,kind));
CREATE TABLE practice_quiz_points (session_id TEXT,user_id TEXT,points INTEGER);
''')
for sql in next(item for item in MIGRATIONS if item['name'] == 'practice_guided_path')['sqls']:
    conn.execute(sql)
for sql in next(item for item in MIGRATIONS if item['name'] == 'practice_path_publication')['sqls']:
    conn.execute(sql)
conn.commit()


class PracticeError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


@contextmanager
def database(write=False):
    try:
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise PracticeError('invalid integer')
    return value


common = types.ModuleType('services.practice_common')
common.db = database
common.integer = integer
common.PracticeError = PracticeError
common.now = lambda: datetime.fromisoformat('2026-10-22T12:00:00')
common.request_id = lambda value: value if isinstance(value,str) and len(value)>=8 else (_ for _ in ()).throw(PracticeError('invalid request id'))
learning = types.ModuleType('services.practice_learning')
learning.require_learning = lambda: None
sys.modules['services.practice_common'] = common
sys.modules['services.practice_learning'] = learning

from services import practice_path as path  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)


check(not path.home({'user_id': 'u1'})['available'], 'draft path must be hidden')
data = path.initialize('独立输入的产品')
check(len(data['units']) == 7 and data['settings']['legacy_product_id'] is None, 'independent units')
check(data['settings']['product_name'] == '独立输入的产品', 'entered product name')
check([unit['level'] for unit in data['units']] == [1, 2, 3, 3, 4, 4, 5], 'five-level progression')
guide = path.authoring_guide()
check([level['level'] for level in guide['levels']] == [1, 2, 3, 4, 5], 'five-level authoring rubric')
check(guide['unit_sequence'][-1]['level'] == 5, 'final unit uses comprehensive level')
path.save_unit(data['units'][0]['id'], {'title': '认识产品', 'question_ids': []})
check(not path.home({'user_id':'u1'})['available'], 'partial draft stays unpublished')

for unit in data['units']:
    ids = []
    for index in range(3):
        qid = unit['position'] * 10 + index
        conn.execute('INSERT INTO practice_quiz_questions(id,title) VALUES(?,?)', (qid, f'题目 {qid}'))
        ids.append(qid)
    if unit['position'] == 1:
        suggestion = path.suggest({'question_id': ids[0], 'unit_id': unit['id'],
                                   'learning_objective': '识别产品信息', 'difficulty_level': 1})
        check(not conn.execute('SELECT difficulty_level FROM practice_quiz_questions WHERE id=?',
                               (ids[0],)).fetchone()[0], 'AI suggestion must not classify directly')
        path.review(suggestion['id'], True)
    if unit['position'] == 7:
        suggestion = path.suggest({'question_id': ids[0], 'unit_id': unit['id'],
                                   'learning_objective': '综合回应多个顾虑', 'difficulty_level': 5})
        path.review(suggestion['id'], True)
    for qid in ids:
        conn.execute('''UPDATE practice_quiz_questions SET learning_objective='完成知识点判断',
            difficulty_level=?,suggested_unit_id=? WHERE id=? AND difficulty_level IS NULL''',
            (unit['level'], unit['id'], qid))
    path.save_unit(unit['id'], {'title': unit['title'], 'question_ids': ids})

check(not path.home({'user_id': 'u1'})['available'], 'unpublished path must remain hidden')
path.publish()
first = path.home({'user_id': 'u1'})
check(first['available'] and first['next_unit']['position'] == 1, 'first unit is next')
check(first['completed_count'] == 0, 'initial progress')
check(first['product_name'] == '独立输入的产品', 'standalone name reaches learner')
conn.execute('UPDATE practice_quiz_questions SET suggested_unit_id=? WHERE id=11', (data['units'][1]['id'],))
try:
    path.save_unit(data['units'][0]['id'], {'title':'认识产品','question_ids':[10,11,12]})
    raise AssertionError('wrong-unit question was accepted')
except PracticeError:
    pass
conn.execute('UPDATE practice_quiz_questions SET suggested_unit_id=? WHERE id=11', (data['units'][0]['id'],))
try:
    path.suggest({'question_id': 10, 'unit_id': data['units'][2]['id'],
                  'learning_objective': '错误层级', 'difficulty_level': 1})
    raise AssertionError('mismatched level was accepted')
except PracticeError:
    pass
try:
    path.suggest({'question_id': 70, 'unit_id': data['units'][6]['id'],
                  'learning_objective': '不存在的第六级', 'difficulty_level': 6})
    raise AssertionError('level beyond five was accepted')
except PracticeError:
    pass
conn.execute('''INSERT INTO practice_learning_sessions(id,user_id,kind,path_unit_id,completed,created_at)
 VALUES('s1','u1','path',?,1,'2026-10-22')''', (first['next_unit']['id'],))
check(path.home({'user_id': 'u1'})['next_unit']['position'] == 2, 'completed unit unlocks next')
check(path.home({'user_id': 'u2'})['next_unit']['position'] == 1, 'users stay isolated')
path.save_unit(data['units'][0]['id'], {'title': '新版认识产品',
                                     'question_ids': data['units'][0]['question_ids'] or [10, 11, 12]})
check(path.home({'user_id': 'u1'})['available'], 'published path stays available while draft changes')
check(path.home({'user_id': 'u1'})['units'][0]['title'] == '认识产品', 'learner keeps published title')
check(path.admin_data()['draft_pending'], 'admin sees unpublished changes')

# Exercise the actual short-course service with local stubs for unrelated web dependencies.
flags = types.ModuleType('services.feature_flags')
flags.PRACTICE_LEARNING_SYSTEM = 'practice_learning'
flags.is_enabled = lambda _name: True
practice = types.ModuleType('services.practice_service')
practice.require_enabled = lambda: None
sys.modules['services.feature_flags'] = flags
sys.modules['services.practice_service'] = practice
spec = importlib.util.spec_from_file_location('services.practice_learning',
    Path(__file__).resolve().parents[1] / 'services' / 'practice_learning.py')
actual_learning = importlib.util.module_from_spec(spec)
sys.modules['services.practice_learning'] = actual_learning
spec.loader.exec_module(actual_learning)
path.learning = actual_learning
path.publish()
lesson = actual_learning.create_session({'user_id':'u2'},
    {'request_id':'startpath001','kind':'path','path_unit_id':data['units'][0]['id']})
check(lesson['kind']=='path' and lesson['path_kind']=='product', 'standalone product lesson')
check('answer_index' not in lesson['questions'][0], 'answer stays hidden before selection')
try:
    actual_learning.get_session({'user_id':'u1'},lesson['id'])
    raise AssertionError('another user read the lesson')
except PracticeError:
    pass
try:
    actual_learning.create_session({'user_id':'u2'},
        {'request_id':'skipunit0001','kind':'path','path_unit_id':data['units'][1]['id']})
    raise AssertionError('unfinished prerequisite was bypassed')
except PracticeError:
    pass
check(actual_learning.create_session({'user_id':'u2'},
    {'request_id':'startpath001','kind':'path','path_unit_id':data['units'][0]['id']})['id']==lesson['id'],
    'create retry is idempotent')
old_question=lesson['questions'][0]['title']
path.save_unit(data['units'][0]['id'], {'title':'再改一次',
                                       'question_ids':[10,11,12]})
check(path.home({'user_id':'u2'})['resume_id'] == lesson['id'], 'unfinished lesson remains resumable after draft edit')
check(lesson['fact'] is None, 'new path lessons do not require a knowledge card')
check(actual_learning.get_session({'user_id':'u2'},lesson['id'])['questions'][0]['title']==old_question,
      'started lesson keeps its question snapshot')
for position in range(3):
    snapshot=json.loads(conn.execute('SELECT snapshot FROM practice_learning_sessions WHERE id=?',
                                     (lesson['id'],)).fetchone()['snapshot'])
    item=snapshot['questions'][position]
    request={'request_id':f'answerpath{position}','question_id':item['id'],
             'option_index':item['answer_index'] if position else (item['answer_index']+1)%4}
    lesson=actual_learning.perform({'user_id':'u2'},lesson['id'],'answer',request)
    check(actual_learning.perform({'user_id':'u2'},lesson['id'],'answer',request)['answered_count']==position+1,
          'answer retry is idempotent')
    if not lesson['completed']:
        lesson=actual_learning.perform({'user_id':'u2'},lesson['id'],'next',
            {'request_id':f'nextpath{position}','question_id':item['id']})
check(lesson['completed'] and lesson['correct_count']==2, 'three answers complete the lesson')
check(conn.execute('SELECT COUNT(*) FROM practice_learning_mastery WHERE user_id=?',('u2',)).fetchone()[0]==1,
      'missed path question enters review queue')
conn.execute("UPDATE practice_quiz_questions SET title='新版本题目',updated_at='v2' WHERE id=10")
still_published = actual_learning.create_session({'user_id':'u3'},
    {'request_id':'publishedold01','kind':'path','path_unit_id':data['units'][0]['id']})
check(still_published['questions'][0]['title'] == old_question,
      'new learners use the published question snapshot until approval')
path.publish()
check(path.home({'user_id':'u2'})['units'][0]['title'] == '再改一次', 'publication switches after approval')
second=actual_learning.create_session({'user_id':'u2'},
    {'request_id':'secondunit01','kind':'path','path_unit_id':data['units'][1]['id']})
check(second['path_unit_id']==data['units'][1]['id'], 'completion unlocks next unit')
check(conn.execute('SELECT COUNT(*) FROM practice_quiz_points').fetchone()[0]==0,
      'path sessions never award leaderboard points')

try:
    actual_learning.create_session({'user_id':'u3'},
        {'request_id':'productunit01','kind':'unit','product_id':101,'unit_no':1})
    raise AssertionError('legacy four-unit course was still available')
except PracticeError:
    pass
conn.execute('DELETE FROM practice_learning_path_publication')
conn.execute('UPDATE practice_quiz_questions SET suggested_unit_id=NULL WHERE id=11')
check(path.home({'user_id':'u4'})['available'], 'legacy published path is readable after migration')
path._preserve_publication(conn)
check(conn.execute('SELECT COUNT(*) FROM practice_learning_path_publication').fetchone()[0] == 1,
      'legacy publication is captured before an edit')
print('test_practice_path: all checks passed')
