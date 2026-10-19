"""Published product lessons and personal review, isolated from scored quiz sessions."""
import json
import random
import uuid
from datetime import date, timedelta
from urllib.parse import urlparse

from services import feature_flags, practice_common as common, practice_service as p

UNIT_TITLES = ('认识产品', '配料与规格', '使用方法', '客户常见提问')


def require_learning():
    p.require_enabled()
    if not feature_flags.is_enabled(feature_flags.PRACTICE_LEARNING_SYSTEM):
        raise common.PracticeError('产品课程正在准备中', 403)


def _product(conn, product_id):
    product_id = common.integer(product_id, 1, 2147483647)
    row = conn.execute('SELECT id,name,category,summary,image_url FROM products WHERE id=?', (product_id,)).fetchone()
    if not row:
        raise common.PracticeError('产品不存在', 404)
    return dict(row)


def _unit(unit_no):
    return common.integer(unit_no, 1, 4)


def _canonical(question):
    return question.get('source_question_id') or question['id']


def _question_version(conn, question_id):
    row = conn.execute('SELECT updated_at FROM practice_quiz_questions WHERE id=?', (question_id,)).fetchone()
    return row['updated_at'] if row else None


def _record_answer(conn, user_id, question, correct, day):
    """Only a missed question enters the review queue; two later days correct master it."""
    question_id = _canonical(question)
    version = _question_version(conn, question_id) or question.get('updated_at', '')
    if not question.get('stage_id') and question.get('updated_at') and question['updated_at'] != version:
        return  # A completed old snapshot must not schedule a newly revised question.
    previous = conn.execute('SELECT * FROM practice_learning_mastery WHERE user_id=? AND question_id=?',
                            (user_id, question_id)).fetchone()
    if not previous and correct:
        return
    if previous and previous['question_version'] != version:
        previous = None
    if not correct:
        days, last, due, status = 0, None, str(date.fromisoformat(day) + timedelta(days=1)), 'learning'
    elif previous and previous['last_correct_day'] == day:
        days, last, due, status = previous['correct_days'], day, previous['due_day'], previous['status']
    else:
        days = min(2, (previous['correct_days'] if previous else 0) + 1)
        last = day
        status = 'mastered' if days >= 2 else 'learning'
        if days < 2:
            due = str(date.fromisoformat(day) + timedelta(days=3))
        elif previous and previous['status'] == 'mastered':
            due = previous['due_day'] if previous['due_day'] and previous['due_day'] > day else None
        else:
            due = str(date.fromisoformat(day) + timedelta(days=7))
    conn.execute('''INSERT INTO practice_learning_mastery
        (user_id,question_id,question_version,correct_days,last_correct_day,due_day,status,updated_at)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,question_id) DO UPDATE SET
        question_version=excluded.question_version,correct_days=excluded.correct_days,
        last_correct_day=excluded.last_correct_day,due_day=excluded.due_day,
        status=excluded.status,updated_at=excluded.updated_at''',
        (user_id, question_id, version, days, last, due, status, common.now().isoformat()))


def note_quiz_answer(conn, user_id, question, correct, day):
    _record_answer(conn, user_id, question, bool(correct), day)


def note_quiz_complete(conn, user_id, day):
    conn.execute("INSERT OR IGNORE INTO practice_learning_activity VALUES(?,?,'quiz')", (user_id, day))


def _activity(conn, user_id, today):
    days = {r['day'] for r in conn.execute('SELECT DISTINCT day FROM practice_learning_activity WHERE user_id=?', (user_id,))}
    # Completed quizzes predating this migration also count toward the visible calendar.
    days.update(r['day'] for r in conn.execute('''SELECT DISTINCT substr(completed_at,1,10) day FROM practice_quiz_sessions
        WHERE user_id=? AND completed=1 AND completed_at IS NOT NULL''', (user_id,)))
    cursor = date.fromisoformat(today)
    if str(cursor) not in days:
        cursor -= timedelta(days=1)
    streak = 0
    while str(cursor) in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak, [str(date.fromisoformat(today) - timedelta(days=i)) for i in range(6, -1, -1) if str(date.fromisoformat(today) - timedelta(days=i)) in days]


def _due(conn, user_id, today):
    return [dict(r) for r in conn.execute('''SELECT q.*,m.due_day,m.correct_days,m.status,m.question_version FROM practice_learning_mastery m
        JOIN practice_quiz_questions q ON q.id=m.question_id
        WHERE m.user_id=? AND m.due_day<=? AND m.status IN ('learning','mastered') AND q.archived=0
        AND m.question_version=q.updated_at
        ORDER BY m.due_day,m.updated_at,m.question_id LIMIT 3''', (user_id, today))]


def home(identity):
    require_learning()
    today = common.now().date().isoformat()
    with common.db() as conn:
        rows = conn.execute('''SELECT c.product_id,p.name,p.category,p.image_url FROM practice_learning_courses c
            JOIN products p ON p.id=c.product_id WHERE c.published=1 ORDER BY p.sort_order,p.id''').fetchall()
        courses = []
        for row in rows:
            completed = conn.execute('''SELECT COUNT(DISTINCT unit_no) FROM practice_learning_sessions
                WHERE user_id=? AND kind='unit' AND product_id=? AND completed=1''',
                (identity['user_id'], row['product_id'])).fetchone()[0]
            courses.append({**dict(row), 'completed_units': completed, 'next_unit': min(completed + 1, 4)})
        streak, activity = _activity(conn, identity['user_id'], today)
        reviewed = conn.execute('''SELECT id,completed,snapshot FROM practice_learning_sessions WHERE user_id=?
            AND kind='review' AND assigned_day=? ORDER BY created_at DESC LIMIT 1''',(identity['user_id'],today)).fetchone()
        due = [] if reviewed and reviewed['completed'] else _due(conn, identity['user_id'], today)
        if reviewed and not reviewed['completed']:
            answered = conn.execute('SELECT COUNT(*) FROM practice_learning_answers WHERE session_id=?',(reviewed['id'],)).fetchone()[0]
            due = json.loads(reviewed['snapshot'])['questions'][answered:]
        resume = conn.execute('''SELECT id,kind,product_id,unit_no FROM practice_learning_sessions
            WHERE user_id=? AND completed=0 ORDER BY created_at DESC LIMIT 1''', (identity['user_id'],)).fetchone()
    return {'enabled': True, 'courses': courses, 'due_count': len(due), 'streak': streak,
            'activity_days': activity, 'resume': dict(resume) if resume else None, 'today': today}


def course(identity, product_id):
    require_learning()
    with common.db() as conn:
        product = _product(conn, product_id)
        row = conn.execute('SELECT published FROM practice_learning_courses WHERE product_id=?', (product_id,)).fetchone()
        if not row or not row['published']:
            raise common.PracticeError('课程尚未开放', 404)
        facts = [dict(r) for r in conn.execute('''SELECT id,unit_no,title,body,source_url,version FROM practice_learning_facts
            WHERE product_id=? AND status='published' ORDER BY unit_no''', (product_id,))]
        done = {r['unit_no'] for r in conn.execute('''SELECT DISTINCT unit_no FROM practice_learning_sessions
            WHERE user_id=? AND product_id=? AND kind='unit' AND completed=1''', (identity['user_id'], product_id))}
        units = [{'unit_no': n, 'title': UNIT_TITLES[n-1], 'fact_title': next((f['title'] for f in facts if f['unit_no']==n), ''),
                  'completed': n in done, 'locked': n>1 and n-1 not in done}
                 for n in range(1, 5)]
    return {'product': product, 'units': units, 'completed_units': len(done)}


def _owned(conn, session_id, identity):
    row = conn.execute('SELECT * FROM practice_learning_sessions WHERE id=? AND user_id=?',
                       (session_id, identity['user_id'])).fetchone()
    if not row:
        raise common.PracticeError('短课不存在', 404)
    return dict(row)


def _public(conn, session):
    snapshot = json.loads(session['snapshot'])
    answers = {r['position']: dict(r) for r in conn.execute('SELECT * FROM practice_learning_answers WHERE session_id=?', (session['id'],))}
    questions = []
    for position, q in enumerate(snapshot['questions']):
        if not session['completed'] and position>session['cursor']:
            break
        item = {key:q[key] for key in ('id','title','category','options','kind')}
        if position in answers:
            item.update(answer_index=q['answer_index'], explanation=q['explanation'], method=q['method'],
                        selected_index=answers[position]['option_index'], correct=bool(answers[position]['correct']))
        questions.append(item)
    return {'id':session['id'], 'kind':session['kind'], 'product_id':session['product_id'], 'unit_no':session['unit_no'],
            'cursor':session['cursor'], 'completed':bool(session['completed']), 'correct_count':session['correct_count'],
            'answered_count':len(answers), 'total_questions':len(snapshot['questions']), 'fact':snapshot.get('fact'), 'questions':questions,
            'assigned_day':session['assigned_day']}


def _snapshot_question(row, kind):
    q = dict(row)
    if isinstance(q.get('options'), str):
        q['options'] = json.loads(q['options'])
    indexes = list(range(4))
    random.SystemRandom().shuffle(indexes)
    q['options'] = [q['options'][i] for i in indexes]
    q['answer_index'] = indexes.index(q['answer_index'])
    q['kind'] = kind
    return q


def create_session(identity, data):
    require_learning()
    request_id = common.request_id(data.get('request_id'))
    kind = data.get('kind')
    if kind not in ('unit', 'review'):
        raise common.PracticeError('短课类型无效', 400)
    day, stamp = common.now().date().isoformat(), common.now().isoformat()
    with common.db(True) as conn:
        previous = conn.execute('SELECT * FROM practice_learning_sessions WHERE user_id=? AND request_id=?',
                                (identity['user_id'], request_id)).fetchone()
        if previous:
            if previous['kind']!=kind or (kind=='unit' and (previous['product_id']!=data.get('product_id') or previous['unit_no']!=data.get('unit_no'))):
                raise common.PracticeError('请求标识已用于其他短课', 409)
            return _public(conn, dict(previous))
        if kind=='unit':
            product_id, unit_no = common.integer(data.get('product_id'),1,2147483647), _unit(data.get('unit_no'))
            _product(conn, product_id)
            course_row=conn.execute('SELECT published FROM practice_learning_courses WHERE product_id=?',(product_id,)).fetchone()
            if not course_row or not course_row['published']:
                raise common.PracticeError('课程尚未开放',404)
            if unit_no>1 and not conn.execute('''SELECT 1 FROM practice_learning_sessions WHERE user_id=? AND product_id=?
                AND unit_no=? AND kind='unit' AND completed=1''',(identity['user_id'],product_id,unit_no-1)).fetchone():
                raise common.PracticeError('请先完成上一单元',409)
            existing=conn.execute('''SELECT * FROM practice_learning_sessions WHERE user_id=? AND kind='unit'
                AND product_id=? AND unit_no=? AND completed=0 ORDER BY created_at DESC LIMIT 1''',
                (identity['user_id'],product_id,unit_no)).fetchone()
            if existing:
                return _public(conn,dict(existing))
            fact=conn.execute('''SELECT * FROM practice_learning_facts WHERE product_id=? AND unit_no=? AND status='published' ''',
                              (product_id,unit_no)).fetchone()
            selected=conn.execute('''SELECT q.*,l.kind FROM practice_learning_unit_questions l
                JOIN practice_quiz_questions q ON q.id=l.question_id WHERE l.product_id=? AND l.unit_no=?
                ORDER BY l.position''',(product_id,unit_no)).fetchall()
            if not fact or len(selected)!=3:
                raise common.PracticeError('课程内容尚未准备完整',409)
            snapshot={'fact':{k:fact[k] for k in ('id','title','body','source_url','version')},
                      'questions':[_snapshot_question(row,row['kind']) for row in selected]}
        else:
            product_id,unit_no=None,None
            existing=conn.execute('''SELECT * FROM practice_learning_sessions WHERE user_id=? AND kind='review'
                AND assigned_day=? ORDER BY created_at DESC LIMIT 1''',(identity['user_id'],day)).fetchone()
            if existing:
                return _public(conn,dict(existing))
            due=_due(conn,identity['user_id'],day)
            if not due:
                raise common.PracticeError('今天没有待复习的题',409)
            selected=[]
            for row in due:
                item=dict(row)
                item['options']=json.loads(item['options'])
                item['sources']=[]
                selected.append(_snapshot_question(item,'review'))
            snapshot={'fact':None,'questions':selected}
        session_id=uuid.uuid4().hex
        conn.execute('''INSERT INTO practice_learning_sessions
            (id,user_id,request_id,kind,product_id,unit_no,snapshot,assigned_day,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)''',(session_id,identity['user_id'],request_id,kind,product_id,unit_no,
                                           json.dumps(snapshot,ensure_ascii=False),day,stamp))
        return _public(conn,_owned(conn,session_id,identity))


def get_session(identity, session_id):
    require_learning()
    with common.db() as conn:
        return _public(conn,_owned(conn,session_id,identity))


def perform(identity,session_id,action,data):
    require_learning()
    if action not in ('answer','next'):
        raise common.PracticeError('操作不存在',404)
    request_id=common.request_id(data.get('request_id'))
    with common.db(True) as conn:
        s=_owned(conn,session_id,identity)
        questions=json.loads(s['snapshot'])['questions']
        if s['completed']:
            return _public(conn,s)
        if action=='answer':
            previous=conn.execute('SELECT * FROM practice_learning_answers WHERE session_id=? AND request_id=?',(session_id,request_id)).fetchone()
            if previous:
                if (questions[previous['position']]['id']!=data.get('question_id') or previous['option_index']!=data.get('option_index')):
                    raise common.PracticeError('此请求标识已用于其他答案',409)
                return _public(conn,s)
        position=s['cursor']
        q=questions[position]
        if data.get('question_id')!=q['id']:
            if action=='next' and any(i<position and old['id']==data.get('question_id') for i,old in enumerate(questions)):
                return _public(conn,s)
            raise common.PracticeError('请按当前题目作答',409)
        answer=conn.execute('SELECT * FROM practice_learning_answers WHERE session_id=? AND position=?',(session_id,position)).fetchone()
        if action=='answer':
            option=common.integer(data.get('option_index'),0,3)
            if answer:
                if answer['option_index']!=option:
                    raise common.PracticeError('首次选择已保存',409)
                return _public(conn,s)
            correct=int(option==q['answer_index'])
            conn.execute('INSERT INTO practice_learning_answers VALUES(?,?,?,?,?)',(session_id,position,option,correct,request_id))
            _record_answer(conn,identity['user_id'],q,correct,common.now().date().isoformat())
            conn.execute('UPDATE practice_learning_sessions SET correct_count=correct_count+? WHERE id=?',(correct,session_id))
            if position==len(questions)-1:
                conn.execute('UPDATE practice_learning_sessions SET completed=1,completed_at=? WHERE id=?',(common.now().isoformat(),session_id))
                if s['kind']=='unit':
                    conn.execute("INSERT OR IGNORE INTO practice_learning_activity VALUES(?,?,'unit')",(identity['user_id'],common.now().date().isoformat()))
        else:
            if not answer:
                raise common.PracticeError('请先完成这道题',409)
            conn.execute('UPDATE practice_learning_sessions SET cursor=cursor+1 WHERE id=?',(session_id,))
        return _public(conn,_owned(conn,session_id,identity))


def admin_data():
    with common.db() as conn:
        products=[dict(r) for r in conn.execute('''SELECT p.id,p.name,p.category,c.published FROM products p
            LEFT JOIN practice_learning_courses c ON c.product_id=p.id ORDER BY p.sort_order,p.id''')]
        facts=[dict(r) for r in conn.execute('SELECT * FROM practice_learning_facts ORDER BY product_id,unit_no')]
        assignments=[dict(r) for r in conn.execute('SELECT * FROM practice_learning_unit_questions ORDER BY product_id,unit_no,position')]
        questions=[dict(r) for r in conn.execute('''SELECT id,title,category,product_id,skill_code,fact_id,updated_at
            FROM practice_quiz_questions WHERE stage_id=0 AND archived=0 ORDER BY id''')]
    return {'products':products,'facts':facts,'assignments':assignments,'questions':questions,'unit_titles':UNIT_TITLES}


def save_fact(product_id,unit_no,data):
    product_id,unit_no=common.integer(product_id,1,2147483647),_unit(unit_no)
    title,body,source=data.get('title'),data.get('body'),data.get('source_url','')
    if not isinstance(title,str) or not title.strip() or len(title)>100 or not isinstance(body,str) or not body.strip() or len(body)>800:
        raise common.PracticeError('请填写知识点标题与不超过800字的正文',400)
    if not isinstance(source,str) or len(source)>1000 or source and (urlparse(source).scheme not in ('http','https') or not urlparse(source).netloc):
        raise common.PracticeError('来源链接无效',400)
    with common.db(True) as conn:
        _product(conn,product_id)
        old=conn.execute('SELECT * FROM practice_learning_facts WHERE product_id=? AND unit_no=?',(product_id,unit_no)).fetchone()
        stamp=common.now().isoformat()
        if old:
            conn.execute('''UPDATE practice_learning_facts SET title=?,body=?,source_url=?,status='draft',
                version=version+1,updated_at=? WHERE id=?''',(title.strip(),body.strip(),source.strip(),stamp,old['id']))
            fact_id=old['id']
        else:
            fact_id=conn.execute('''INSERT INTO practice_learning_facts
                (product_id,unit_no,title,body,source_url,updated_at) VALUES(?,?,?,?,?,?)''',
                (product_id,unit_no,title.strip(),body.strip(),source.strip(),stamp)).lastrowid
        conn.execute('''INSERT INTO practice_learning_courses VALUES(?,0,?) ON CONFLICT(product_id)
            DO UPDATE SET published=0,updated_at=excluded.updated_at''',(product_id,stamp))
        related=[dict(r) for r in conn.execute('SELECT id,title FROM practice_quiz_questions WHERE fact_id=? AND archived=0',(fact_id,))]
    return {'id':fact_id,'related_questions':related,'needs_review':bool(related)}


def assign_unit(product_id,unit_no,data):
    product_id,unit_no=common.integer(product_id,1,2147483647),_unit(unit_no)
    ids=data.get('question_ids')
    if not isinstance(ids,list) or len(ids)!=3 or len(set(map(str,ids)))!=3:
        raise common.PracticeError('每单元请选择3道不同题目',400)
    ids=[common.integer(i,1,2147483647) for i in ids]
    with common.db(True) as conn:
        _product(conn,product_id)
        fact=conn.execute('SELECT id FROM practice_learning_facts WHERE product_id=? AND unit_no=?',(product_id,unit_no)).fetchone()
        if not fact:
            raise common.PracticeError('请先填写本单元事实卡',409)
        for qid in ids:
            row=conn.execute('''SELECT product_id,fact_id FROM practice_quiz_questions
                WHERE id=? AND stage_id=0 AND archived=0''',(qid,)).fetchone()
            if not row or row['product_id']!=product_id or row['fact_id']!=fact['id']:
                raise common.PracticeError('请选择关联本产品、本单元事实卡的母题',400)
        conn.execute('DELETE FROM practice_learning_unit_questions WHERE product_id=? AND unit_no=?',(product_id,unit_no))
        for position,qid in enumerate(ids):
            conn.execute('INSERT INTO practice_learning_unit_questions VALUES(?,?,?,?,?)',
                         (product_id,unit_no,position,qid,'knowledge' if position<2 else 'application'))
        conn.execute('UPDATE practice_learning_courses SET published=0,updated_at=? WHERE product_id=?',(common.now().isoformat(),product_id))
    return {'ok':True}


def publish(product_id):
    product_id=common.integer(product_id,1,2147483647)
    with common.db(True) as conn:
        _product(conn,product_id)
        for unit_no in range(1,5):
            fact=conn.execute('SELECT id,source_url FROM practice_learning_facts WHERE product_id=? AND unit_no=?',(product_id,unit_no)).fetchone()
            rows=conn.execute('''SELECT l.position,l.kind,q.id,q.product_id,q.fact_id FROM practice_learning_unit_questions l
                JOIN practice_quiz_questions q ON q.id=l.question_id AND q.archived=0 AND q.stage_id=0
                WHERE l.product_id=? AND l.unit_no=? ORDER BY l.position''',(product_id,unit_no)).fetchall()
            if not fact or not fact['source_url'] or len(rows)!=3 or [r['kind'] for r in rows]!=['knowledge','knowledge','application'] or any(r['product_id']!=product_id or r['fact_id']!=fact['id'] for r in rows):
                raise common.PracticeError(f'第{unit_no}单元需要带素材来源的事实卡、2道理解题和1道应用题',400)
        conn.execute("UPDATE practice_learning_facts SET status='published' WHERE product_id=?",(product_id,))
        stamp=common.now().isoformat()
        conn.execute('''INSERT INTO practice_learning_courses VALUES(?,1,?) ON CONFLICT(product_id)
            DO UPDATE SET published=1,updated_at=excluded.updated_at''',(product_id,stamp))
    return {'ok':True}
