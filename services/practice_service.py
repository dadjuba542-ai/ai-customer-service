"""Server-owned decision-game snapshots, locked answers and atomic daily awards."""
import json
import csv
import io
import hashlib
import random
import re
import uuid
from datetime import datetime, timedelta

from services import feature_flags
from services import practice_common as common
from services.practice_bank import RAW, SOURCES

def now():
    return common.now()


PracticeError = common.PracticeError
db = common.db
TZ = common.TZ
_request_id = common.request_id
_integer = common.integer


def require_enabled():
    if not feature_flags.is_enabled(feature_flags.PRACTICE_SYSTEM):
        raise PracticeError('每日闯关暂未开启', 403)


def _batches(conn, stage_id=0):
    return [dict(r) for r in conn.execute('''SELECT batch_no, COUNT(*) question_count
        FROM practice_quiz_questions WHERE archived=0 AND enabled=1 AND stage_id=? GROUP BY batch_no HAVING COUNT(*)=10 ORDER BY batch_no''', (stage_id,))]


def validate_ready():
    with db() as conn:
        if not _batches(conn):
            raise PracticeError('请至少准备一组完整的10道启用题目', 400)


def _question(row):
    result = dict(row)
    for key in ('options', 'sources'):
        result[key] = json.loads(result[key])
    return result


def _snapshot(conn, batch, stage_id=0):
    questions = [_question(r) for r in conn.execute(
        'SELECT * FROM practice_quiz_questions WHERE archived=0 AND batch_no=? AND stage_id=? AND enabled=1 ORDER BY id', (batch, stage_id))]
    if len(questions) != 10:
        raise PracticeError('这组题目正在整理，请选择其他关卡', 409)
    return questions


def _random_free_questions(conn, user_id, day, stage_id, round_no):
    """Choose a repeatable preview and session snapshot for the next unscored round."""
    candidates = [question for batch in _batches(conn, stage_id)
                  for question in _snapshot(conn, batch['batch_no'], stage_id)]
    if len(candidates) < 10:
        raise PracticeError('练习题目正在准备中', 503)
    daily_ids = {q['id'] for q in json.loads(_daily(conn, day, stage_id)['snapshot'])}
    last = conn.execute('''SELECT snapshot FROM practice_quiz_sessions
        WHERE user_id=? AND assigned_day=? AND stage_id=? AND mode='free' AND entry=1 AND completed=1
        ORDER BY completed_at DESC,id DESC LIMIT 1''', (user_id, day, stage_id)).fetchone()
    last_ids = {q['id'] for q in json.loads(last['snapshot'])} if last else set()
    fresh = [q for q in candidates if q['id'] not in daily_ids and q['id'] not in last_ids]
    if len(fresh) < 10:
        fresh = [q for q in candidates if q['id'] not in daily_ids]
    pool = fresh if len(fresh) >= 10 else candidates
    seed = hashlib.sha256(f'{user_id}|{day}|{stage_id}|{round_no}'.encode()).digest()
    return random.Random(int.from_bytes(seed, 'big')).sample(pool, 10)


def _daily(conn, day, stage_id=0):
    if stage_id:
        return _stage_daily(conn, day, stage_id)
    row = conn.execute('SELECT * FROM practice_quiz_daily WHERE day=?', (day,)).fetchone()
    if row:
        return dict(row)
    batches = _batches(conn)
    if not batches:
        raise PracticeError('每日题目正在准备中', 503)
    batch = batches[datetime.fromisoformat(day).date().toordinal() % len(batches)]['batch_no']
    snapshot = json.dumps(_snapshot(conn, batch), ensure_ascii=False)
    conn.execute('INSERT INTO practice_quiz_daily VALUES(?,?,?)', (day, batch, snapshot))
    return {'day': day, 'batch_no': batch, 'snapshot': snapshot}


def daily(stage_id=0):
    require_enabled()
    with db(True) as conn:
        if stage_id:
            _require_stage_open(conn, stage_id)
        result = _daily(conn, now().date().isoformat(), stage_id)
    return {k: result[k] for k in ('day', 'batch_no')}


def catalog(identity):
    from services import practice_weekly as weekly
    require_enabled()
    day = now().date().isoformat()
    with db(True) as conn:
        conn.execute('INSERT OR IGNORE INTO practice_quiz_visits VALUES(?,?,?)',
                     (identity['user_id'], day, identity.get('team_name', '')))
        batches = _batches(conn)
        existing = conn.execute("SELECT id,completed,correct_count,points,stage_id,stage_title FROM practice_quiz_sessions WHERE user_id=? AND mode='daily' AND assigned_day=?",
                                (identity['user_id'], day)).fetchone()
        try:
            today = _daily(conn, day)
            recommendation = {k: today[k] for k in ('day', 'batch_no')}
        except PracticeError as exc:
            if exc.status_code != 503:
                raise
            recommendation = None
        stage = _active_stage(conn)
        if stage:
            stage['batches'] = _batches(conn, stage['id'])
            stage_today = _daily(conn, day, stage['id'])
            stage['daily'] = {k: stage_today[k] for k in ('day', 'batch_no')}
        entry_descriptor = weekly.entry(conn,identity)
    return {'entry':entry_descriptor, 'stage': stage, 'batches': batches, 'categories': list(RAW), 'daily': recommendation,
            'daily_session': dict(existing) if existing else None}


def _owned(conn, session_id, identity):
    row = conn.execute('SELECT * FROM practice_quiz_sessions WHERE id=? AND user_id=?',
                       (session_id, identity['user_id'])).fetchone()
    if not row:
        raise PracticeError('练习不存在', 404)
    return dict(row)


def _public(conn, session):
    result = {k: session[k] for k in ('id', 'mode', 'assigned_day', 'batch_no', 'cursor', 'completed',
                                    'correct_count', 'points', 'point_reason', 'created_at', 'completed_at', 'stage_id', 'stage_title', 'entry')}
    answers = {r['question_id']: dict(r) for r in conn.execute(
        'SELECT * FROM practice_quiz_answers WHERE session_id=?', (session['id'],))}
    result['answered_count'] = len(answers)
    questions = json.loads(session['snapshot'])
    result['questions'] = []
    for index, question in enumerate(questions):
        if not session['completed'] and index > session['cursor']:
            break
        public = {k: question[k] for k in ('id', 'category', 'title', 'options')}
        answer = answers.get(question['id'])
        if answer:
            public.update({k: question[k] for k in ('answer_index', 'explanation', 'method')})
            public.update(selected_index=answer['option_index'], correct=bool(answer['correct']))
        result['questions'].append(public)
    return result


def create_session(identity, data):
    from services import practice_weekly as weekly
    require_enabled()
    request_id = _request_id(data.get('request_id'))
    via_entry = data.get('entry', False)
    if type(via_entry) is not bool:
        raise PracticeError('入口标识无效', 400)
    stage_id = _integer(data.get('stage_id', 0), 0, 2147483647)
    mode = data.get('mode', 'daily' if via_entry else None)
    if mode not in ('daily', 'free'):
        raise PracticeError('请选择每日闯关或自由练习', 400)
    batch = _integer(data.get('batch_no'), 1, 10000) if mode == 'free' else None
    stamp = now()
    day = stamp.date().isoformat()
    with db(True) as conn:
        if via_entry:
            alias = conn.execute('SELECT session_id FROM practice_quiz_entry_requests WHERE user_id=? AND request_id=?',(identity['user_id'],request_id)).fetchone()
            if alias:
                return _public(conn,_owned(conn,alias['session_id'],identity))
        previous = conn.execute('SELECT * FROM practice_quiz_sessions WHERE user_id=? AND create_request_id=?',
                                (identity['user_id'], request_id)).fetchone()
        if previous:
            if via_entry and previous['entry']:
                return _public(conn, dict(previous))
            if previous['mode'] != mode or previous['stage_id'] != stage_id or (batch and previous['batch_no'] != batch):
                raise PracticeError('此请求标识已用于另一项练习', 409)
            return _public(conn, dict(previous))
        if via_entry:
            descriptor = weekly.entry(conn, identity)
            if not descriptor:
                raise PracticeError('题目正在准备中', 503)
            if data.get('entry_day') and (data['entry_day']!=descriptor['day'] or data.get('entry_stage_id')!=descriptor['stage_id'] or data.get('entry_question_id')!=descriptor['question_id']):
                raise PracticeError('今日入口已更新，请从新的问题进入',409)
            stage_id, mode = descriptor['stage_id'], descriptor['mode']
            weekly.event(conn, identity, stage_id, day, 'click')
            if descriptor['session_id']:
                s = _owned(conn, descriptor['session_id'], identity)
                if not s['entry']:
                    answered = conn.execute('SELECT 1 FROM practice_quiz_answers WHERE session_id=? AND position=?', (s['id'], s['cursor'])).fetchone()
                    conn.execute('UPDATE practice_quiz_sessions SET entry=1,entry_cursor=? WHERE id=?', (s['cursor']+int(bool(answered)),s['id']))
                conn.execute('INSERT INTO practice_quiz_entry_requests VALUES(?,?,?)',(identity['user_id'],request_id,s['id']))
                return _public(conn, _owned(conn,s['id'],identity))
            batch = descriptor['batch_no']
        if mode == 'daily':
            previous = conn.execute("SELECT * FROM practice_quiz_sessions WHERE user_id=? AND assigned_day=? AND mode='daily'",
                                    (identity['user_id'], day)).fetchone()
            if previous:
                return _public(conn, dict(previous))
            if stage_id:
                _require_stage_open(conn, stage_id)
            today = _daily(conn, day, stage_id)
            batch = today['batch_no']
            questions = json.loads(today['snapshot'])
        else:
            if stage_id:
                _require_stage_open(conn, stage_id)
            questions = (_random_free_questions(conn, identity['user_id'], day, stage_id, descriptor['replay_round'])
                         if via_entry else _snapshot(conn, batch, stage_id))
        # Shuffle options once per session; preserve the permutation on every retry/refresh.
        for q in questions:
            indexes = list(range(4))
            random.SystemRandom().shuffle(indexes)
            q['options'] = [q['options'][i] for i in indexes]
            q['answer_index'] = indexes.index(q['answer_index'])
        session_id = uuid.uuid4().hex
        conn.execute('''INSERT INTO practice_quiz_sessions
            (id,user_id,team_name,member_name,create_request_id,mode,assigned_day,batch_no,snapshot,created_at,stage_id,stage_title,entry)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (session_id, identity['user_id'], identity.get('team_name', ''),
            identity.get('member_name', ''), request_id, mode, day, batch,
            json.dumps(questions, ensure_ascii=False), stamp.isoformat(), stage_id,
            _stage(conn, stage_id)['title'] if stage_id else '', int(via_entry)))
        if via_entry:
            conn.execute('INSERT INTO practice_quiz_entry_requests VALUES(?,?,?)',(identity['user_id'],request_id,session_id))
        return _public(conn, _owned(conn, session_id, identity))


def get_session(session_id, identity):
    require_enabled()
    with db() as conn:
        return _public(conn, _owned(conn, session_id, identity))


def perform(session_id, identity, action, data):
    from services import practice_weekly as weekly
    require_enabled()
    if action not in ('answer', 'next'):
        raise PracticeError('操作不存在', 404)
    request_id = _request_id(data.get('request_id'))
    question_id = _integer(data.get('question_id'), 1, 2147483647)
    option = _integer(data.get('option_index'), 0, 3) if action == 'answer' else None
    # SQLite's writer transaction serializes workers and makes the last answer + award atomic.
    with db(True) as conn:
        session = _owned(conn, session_id, identity)
        questions = json.loads(session['snapshot'])
        current = questions[session['cursor']]
        answer = conn.execute('SELECT * FROM practice_quiz_answers WHERE session_id=? AND question_id=?',
                              (session_id, question_id)).fetchone()
        if action == 'answer':
            previous = conn.execute('SELECT * FROM practice_quiz_answers WHERE session_id=? AND request_id=?',
                                    (session_id, request_id)).fetchone()
            if previous and (previous['question_id'] != question_id or previous['option_index'] != option):
                raise PracticeError('此请求标识已用于其他答案', 409)
            if answer:
                if answer['option_index'] != option:
                    raise PracticeError('首次选择已保存，可在自由练习中重练', 409)
                return _public(conn, session)
            if session['completed'] or current['id'] != question_id:
                raise PracticeError('请按当前题目作答', 409)
            correct = int(option == current['answer_index'])
            conn.execute('INSERT INTO practice_quiz_answers VALUES(?,?,?,?,?,?)',
                         (session_id, question_id, session['cursor'], option, correct, request_id))
            from services import practice_learning
            practice_learning.note_quiz_answer(conn, identity['user_id'], current, correct, now().date().isoformat())
            if session['entry'] and session['cursor'] == session['entry_cursor']:
                weekly.event(conn, identity, session['stage_id'], session['assigned_day'], 'first_answer')
            conn.execute('UPDATE practice_quiz_sessions SET correct_count=correct_count+? WHERE id=?', (correct, session_id))
            if session['cursor'] == 9:
                if session['entry']:
                    weekly.event(conn, identity, session['stage_id'], session['assigned_day'], 'complete')
                stamp = now()
                points, reason = 0, '自由练习已保存'
                if session['mode'] == 'daily':
                    if session['assigned_day'] == stamp.date().isoformat():
                        points = (session['correct_count'] + correct) * 10
                        reason = '今日积分已入账'
                        conn.execute('INSERT INTO practice_quiz_points VALUES(?,?,?,?,?,?)',
                                     (session_id, session['user_id'], session['team_name'], session['member_name'],
                                      session['assigned_day'], points))
                    else:
                        reason = '跨日完成，成绩已保存；可继续挑战今天的每日局'
                conn.execute('UPDATE practice_quiz_sessions SET completed=1,points=?,point_reason=?,completed_at=? WHERE id=?',
                             (points, reason, stamp.isoformat(), session_id))
                practice_learning.note_quiz_complete(conn, identity['user_id'], stamp.date().isoformat())
        else:
            if not answer:
                raise PracticeError('请先选择答案并阅读解析', 409)
            if current['id'] == question_id and not session['completed']:
                conn.execute('UPDATE practice_quiz_sessions SET cursor=cursor+1 WHERE id=?', (session_id,))
            # A replay for an already passed question returns state and never skips a question.
        return _public(conn, _owned(conn, session_id, identity))


def records(identity, page=1):
    require_enabled()
    page = max(1, min(page or 1, 100000))
    with db() as conn:
        total = conn.execute('SELECT COUNT(*) FROM practice_quiz_sessions WHERE user_id=?', (identity['user_id'],)).fetchone()[0]
        rows = conn.execute('''SELECT id,mode,batch_no,completed,cursor,correct_count,points,created_at,stage_id,stage_title,entry FROM practice_quiz_sessions
            WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET ?''', (identity['user_id'], (page-1)*20))
        return {'items': [dict(r) for r in rows], 'total': total, 'page': page}


def _ranking(conn, team, start, end):
    rows = conn.execute('''SELECT user_id,SUM(points) points FROM practice_quiz_points
        WHERE team_name=? AND day>=? AND day<=? GROUP BY user_id HAVING SUM(points)>0
        ORDER BY points DESC,user_id''', (team, start, end)).fetchall()
    result, previous, rank = [], None, 0
    for index, row in enumerate(rows):
        if row['points'] != previous:
            rank = index + 1
        previous = row['points']
        name = conn.execute('''SELECT member_name FROM practice_quiz_points WHERE team_name=? AND user_id=?
            AND day>=? AND day<=? ORDER BY day DESC LIMIT 1''', (team, row['user_id'], start, end)).fetchone()[0]
        result.append({'user_id': row['user_id'], 'name': name, 'points': row['points'], 'rank': rank})
    return result


def _honor(rank):
    return '周冠军' if rank == 1 else '沟通达人' if rank <= 3 else '学习之星' if rank <= 10 else ''


def scores(identity):
    require_enabled()
    today = now().date()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    team = identity.get('team_name', '')
    with db() as conn:
        previous = _ranking(conn, team, str(start-timedelta(days=7)), str(start-timedelta(days=1)))
        honors = {r['user_id']: _honor(r['rank']) for r in previous}
        rows = _ranking(conn, team, str(start), str(end))
        today_points = conn.execute('SELECT COALESCE(SUM(points),0) FROM practice_quiz_points WHERE user_id=? AND day=?',
                                    (identity['user_id'], str(today))).fetchone()[0]
    mine = next((r for r in rows if r['user_id'] == identity['user_id']), None)
    # Include all ties at the cutoff, while reporting the caller's rank even below the display limit.
    items = [dict(name=r['name'], points=r['points'], rank=r['rank'],
                  honor=honors.get(r['user_id'], ''), is_me=r['user_id'] == identity['user_id']) for r in rows if r['rank'] <= 100]
    return {'items': items, 'week_start': str(start), 'week_end': str(end), 'today_points': today_points,
            'week_points': mine['points'] if mine else 0, 'my_rank': mine['rank'] if mine else None,
            'my_honor': honors.get(identity['user_id'], ''), 'team_name': team}


def admin_data(stage_id=0):
    from services import practice_weekly as weekly
    with db() as conn:
        if stage_id:
            _stage(conn, stage_id)
        questions = [_question(r) for r in conn.execute('SELECT * FROM practice_quiz_questions WHERE stage_id=? AND archived=0 ORDER BY batch_no,id', (stage_id,))]
        stages = _stage_summaries(conn)
        draft_questions = [i['question'] for i in weekly.selections(conn, stage_id)] if stage_id and _stage(conn,stage_id)['kind']=='weekly' else []
        entry_metrics = weekly.metrics(conn)
        sessions = [dict(r) for r in conn.execute('SELECT user_id,team_name,assigned_day,completed FROM practice_quiz_sessions')]
        visits = [dict(r) for r in conn.execute('SELECT * FROM practice_quiz_visits')]
        batches = _batches(conn, stage_id)
    summary = []
    for team in sorted({s['team_name'] for s in sessions + visits}):
        group = [s for s in sessions if s['team_name'] == team]
        visitor_ids = {v['user_id'] for v in visits if v['team_name'] == team}
        days = {}
        for s in group:
            days.setdefault(s['user_id'], set()).add(datetime.fromisoformat(s['assigned_day']).date())
        visits_by_user = {}
        for visit in visits:
            if visit['team_name'] == team:
                visits_by_user.setdefault(visit['user_id'], set()).add(datetime.fromisoformat(visit['day']).date())
        next_day = sum(any(d+timedelta(days=1) in visits_by_user.get(user, set()) for d in dates)
                       for user, dates in days.items())
        seven_day = sum(any(d+timedelta(days=n) in dates for d in dates for n in range(1, 8)) for dates in days.values())
        summary.append(dict(team_name=team, visitors=len(visitor_ids), participants=len(days), started=len(group),
                            completed=sum(s['completed'] for s in group), next_day_returns=next_day, seven_day_returns=seven_day))
    return {'draft_questions': draft_questions, 'entry_metrics':entry_metrics, 'today': now().date().isoformat(), 'stages': stages, 'stage_id': stage_id, 'questions': questions, 'batches': batches, 'categories': list(dict.fromkeys([*RAW, *[q['category'] for q in questions]])), 'sources': SOURCES, 'summary': summary,
            'enabled': feature_flags.is_enabled(feature_flags.PRACTICE_SYSTEM)}


CSV_COLUMNS = ['id', '关卡', '分类', '客户场景', 'A', 'B', 'C', 'D', '推荐答案', '解析', '参考回复', '启用', '参考资料', '版本', '产品ID', '能力标签', '事实卡ID']
SKILL_CODES = ('needs', 'product', 'claims', 'price', 'usage', 'followup')


def _validate_question(data):
    if not isinstance(data, dict):
        raise PracticeError('题目格式无效', 400)
    values = {}
    labels = {'title': '客户场景', 'explanation': '解析', 'method': '参考回复'}
    for key, maximum in (('title', 500), ('explanation', 2000), ('method', 1000)):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise PracticeError(f'{labels[key]}不能为空且不能超过{maximum}字', 400)
        values[key] = value.strip()
    options = data.get('options')
    if (not isinstance(options, list) or len(options) != 4 or
        any(not isinstance(o, str) or not o.strip() or len(o) > 500 for o in options) or
        len({o.strip() for o in options}) != 4):
        raise PracticeError('请填写四个不同的选项，每项不超过500字', 400)
    stage_id = _integer(data.get('stage_id', 0), 0, 2147483647)
    category = data.get('category')
    sources = data.get('sources', [])
    if (not isinstance(category, str) or not category.strip() or len(category)>40 or (not stage_id and category not in RAW) or not isinstance(sources, list) or
        any(not isinstance(s, str) or s not in SOURCES for s in sources)):
        raise PracticeError('分类或参考资料无效', 400)
    if type(data.get('enabled')) is not bool:
        raise PracticeError('启用状态无效', 400)
    values.update(stage_id=stage_id, category=category.strip(), options=[o.strip() for o in options], sources=sources,
                  enabled=data['enabled'], answer_index=_integer(data.get('answer_index'), 0, 3),
                  batch_no=_integer(data.get('batch_no'), 1, 10000))
    product_id = data.get('product_id')
    fact_id = data.get('fact_id')
    skill_code = data.get('skill_code', '')
    if product_id is not None:
        product_id = _integer(product_id, 1, 2147483647)
    if fact_id is not None:
        fact_id = _integer(fact_id, 1, 2147483647)
    if fact_id is not None and product_id is None:
        raise PracticeError('关联事实卡时请先选择产品', 400)
    if skill_code not in ('', *SKILL_CODES):
        raise PracticeError('能力标签无效', 400)
    values.update(product_id=product_id, fact_id=fact_id, skill_code=skill_code)
    return values


def _check_capacity(questions):
    counts = {}
    for q in questions:
        if q['enabled']:
            key = (q.get('stage_id', 0), q['batch_no'])
            counts[key] = counts.get(key, 0) + 1
    if any(count > 10 for count in counts.values()):
        raise PracticeError('每关最多启用10道题，请将新增题放入新关卡或先停用替换题', 400)


def _write_question(conn, question_id, q):
    fields = (q['stage_id'], q['batch_no'], q['category'], q['title'], json.dumps(q['options'], ensure_ascii=False), q['answer_index'],
              q['explanation'], q['method'], json.dumps(q['sources']), int(q['enabled']), now().isoformat(),
              q.get('product_id'), q.get('skill_code', ''), q.get('fact_id'))
    if question_id is None:
        return conn.execute('''INSERT INTO practice_quiz_questions
            (stage_id,batch_no,category,title,options,answer_index,explanation,method,sources,enabled,updated_at,product_id,skill_code,fact_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', fields).lastrowid
    conn.execute('''UPDATE practice_quiz_questions SET archived=0,stage_id=?,batch_no=?,category=?,title=?,options=?,answer_index=?,
        explanation=?,method=?,sources=?,enabled=?,updated_at=?,product_id=?,skill_code=?,fact_id=? WHERE id=?''', fields + (question_id,))
    return question_id


def save_question(question_id, data):
    with db(True) as conn:
        existing = conn.execute('SELECT * FROM practice_quiz_questions WHERE id=? AND archived=0', (question_id,)).fetchone()
        if not existing:
            raise PracticeError('题目不存在', 404)
        if data.get('updated_at') and data['updated_at'] != existing['updated_at']:
            raise PracticeError('这道题已被更新，请重新打开后修改', 409)
        if data.get('stage_id', existing['stage_id']) != existing['stage_id']:
            target = data.get('stage_id')
            if target and _stage(conn,target)['kind']=='weekly' and existing['stage_id']==0 and conn.execute('SELECT 1 FROM practice_quiz_weekly_selections WHERE stage_id=? AND question_id=?',(target,question_id)).fetchone():
                data = {**data,'stage_id':0}
            else:
                raise PracticeError('题目不属于当前题库', 409)
        if existing['stage_id'] and _stage(conn,existing['stage_id'])['kind']=='weekly' and data.get('batch_no',existing['batch_no'])!=existing['batch_no']:
            raise PracticeError('本期分组由七天安排确定，请在组题区重新生成题包',400)
        q = _validate_question({'batch_no': existing['batch_no'], 'stage_id': existing['stage_id'],
                                'product_id': existing['product_id'], 'skill_code': existing['skill_code'], 'fact_id': existing['fact_id'], **data})
        if q['product_id'] and not conn.execute('SELECT 1 FROM products WHERE id=?',(q['product_id'],)).fetchone():
            raise PracticeError('关联产品不存在', 400)
        if q['fact_id'] and not conn.execute('SELECT 1 FROM practice_learning_facts WHERE id=? AND product_id=?',(q['fact_id'],q['product_id'])).fetchone():
            raise PracticeError('关联事实卡不存在', 400)
        others = [dict(r) for r in conn.execute('SELECT stage_id,batch_no,enabled FROM practice_quiz_questions WHERE id<>?', (question_id,))]
        _check_capacity(others + [q])
        _write_question(conn, question_id, q)
        if q['stage_id']==0:
            affected={existing['product_id'],q['product_id']}
            affected.update(r['product_id'] for r in conn.execute('SELECT product_id FROM practice_learning_unit_questions WHERE question_id=?',(question_id,)))
            for product_id in affected-{None}:
                conn.execute('UPDATE practice_learning_courses SET published=0,updated_at=? WHERE product_id=?',
                             (now().isoformat(),product_id))


def _operation(conn, request_id, payload):
    request_id = _request_id(request_id)
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    row = conn.execute('SELECT * FROM practice_quiz_admin_operations WHERE request_id=?', (request_id,)).fetchone()
    if row and row['digest'] != digest:
        raise PracticeError('此请求标识已用于其他内容', 409)
    return request_id, digest, json.loads(row['result']) if row else None


def add_question(data):
    payload = {k:v for k,v in data.items() if k != 'request_id'}
    with db(True) as conn:
        key, digest, previous = _operation(conn, data.get('request_id'), payload)
        if previous:
            return previous
        weekly_target = payload.get('stage_id',0)
        weekly_target = weekly_target if weekly_target and _stage(conn,weekly_target)['kind']=='weekly' else 0
        if weekly_target:
            batch_row=conn.execute('SELECT COALESCE(MAX(batch_no),0) FROM practice_quiz_questions WHERE stage_id=0 AND archived=0').fetchone()[0]
            last_count=conn.execute('SELECT COUNT(*) FROM practice_quiz_questions WHERE stage_id=0 AND archived=0 AND batch_no=?',(batch_row,)).fetchone()[0]
            payload={**payload,'stage_id':0,'enabled':False,'batch_no':batch_row if batch_row and last_count<10 else batch_row+1}
        q = _validate_question(payload)
        if q['product_id'] and not conn.execute('SELECT 1 FROM products WHERE id=?',(q['product_id'],)).fetchone():
            raise PracticeError('关联产品不存在', 400)
        if q['fact_id'] and not conn.execute('SELECT 1 FROM practice_learning_facts WHERE id=? AND product_id=?',(q['fact_id'],q['product_id'])).fetchone():
            raise PracticeError('关联事实卡不存在', 400)
        if q['stage_id']:
            _stage(conn, q['stage_id'])
        _check_capacity([dict(r) for r in conn.execute('SELECT stage_id,batch_no,enabled FROM practice_quiz_questions')] + [q])
        result = {'id': _write_question(conn, None, q)}
        if weekly_target:
            from services import practice_weekly as weekly
            weekly.enroll(conn, weekly_target, [result['id']])
        conn.execute('INSERT INTO practice_quiz_admin_operations VALUES(?,?,?)', (key, digest, json.dumps(result)))
        return result


def export_bank(stage_id=0):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    with db() as conn:
        if stage_id:
            _stage(conn, stage_id)
        for row in conn.execute('SELECT * FROM practice_quiz_questions WHERE stage_id=? AND archived=0 ORDER BY batch_no,id', (stage_id,)):
            q = _question(row)
            values = [q['id'], q['batch_no'], q['category'], q['title'], *q['options'], 'ABCD'[q['answer_index']],
                      q['explanation'], q['method'], '1' if q['enabled'] else '0', ';'.join(q['sources']), q['updated_at'],
                      q.get('product_id') or '', q.get('skill_code') or '', q.get('fact_id') or '']
            writer.writerow(["'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in values])
    return '\ufeff' + output.getvalue()


def _read_import(conn, text, stage_id=0, replace=False):
    if stage_id:
        _stage(conn, stage_id)
    if not isinstance(text, str) or len(text.encode('utf-8')) > 2000000:
        raise PracticeError('请上传不超过2MB的CSV题库', 400)
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
    required = set(CSV_COLUMNS[1:11])
    try:
        fields = reader.fieldnames
    except csv.Error as exc:
        raise PracticeError('CSV表头格式错误，请使用下载的模板', 400) from exc
    if not fields or not required.issubset(fields) or len(fields) != len(set(fields)):
        raise PracticeError('CSV表头不完整，请先下载模板', 400)
    changes, errors, seen = [], [], set()
    try:
        for line, row in enumerate(reader, 2):
            if line > 1001:
                raise PracticeError('每次最多导入1000道题', 400)
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError('列数与表头不一致')
                row = {k: v[1:] if v.startswith("'") and v[1:].startswith(('=', '+', '-', '@', '\t', '\r')) else v for k,v in row.items()}
                question_id = int(row['id']) if row.get('id', '').strip() else None
                if question_id is not None:
                    if question_id in seen:
                        raise ValueError('同一id在文件中出现多次')
                    seen.add(question_id)
                    existing = conn.execute('SELECT updated_at,product_id,skill_code,fact_id FROM practice_quiz_questions WHERE id=? AND stage_id=? AND archived=0', (question_id, stage_id)).fetchone()
                    if not existing:
                        raise ValueError('id不存在；新增题请留空id')
                    if not row.get('版本') or row['版本'] != existing['updated_at']:
                        raise ValueError('版本已变化，请重新导出这道题再修改')
                answer = row['推荐答案'].strip().upper()
                enabled = row.get('启用', '0').strip()
                if answer not in ('A', 'B', 'C', 'D') or enabled not in ('0', '1'):
                    raise ValueError('推荐答案填A/B/C/D，启用填0/1')
                q = _validate_question(dict(stage_id=stage_id, batch_no=int(row['关卡']), category=row['分类'].strip(), title=row['客户场景'],
                    options=[row[k] for k in 'ABCD'], answer_index='ABCD'.index(answer), explanation=row['解析'],
                    method=row['参考回复'], enabled=enabled == '1', sources=[s for s in row.get('参考资料', '').split(';') if s],
                    product_id=(int(row['产品ID']) if row.get('产品ID','').strip() else existing['product_id'] if question_id and '产品ID' not in row else None),
                    skill_code=(row['能力标签'].strip() if '能力标签' in row else existing['skill_code'] if question_id else ''),
                    fact_id=(int(row['事实卡ID']) if row.get('事实卡ID','').strip() else existing['fact_id'] if question_id and '事实卡ID' not in row else None)))
                if q['product_id'] and not conn.execute('SELECT 1 FROM products WHERE id=?',(q['product_id'],)).fetchone():
                    raise ValueError('关联产品不存在')
                if q['fact_id'] and not conn.execute('SELECT 1 FROM practice_learning_facts WHERE id=? AND product_id=?',(q['fact_id'],q['product_id'])).fetchone():
                    raise ValueError('关联事实卡不存在')
                changes.append({'id': question_id, **q})
            except (ValueError, PracticeError) as exc:
                errors.append({'row': line, 'message': exc.message if isinstance(exc, PracticeError) else str(exc)})
    except csv.Error as exc:
        errors.append({'row': reader.line_num, 'message': f'CSV格式错误：{exc}'})
    if not changes and not errors:
        errors.append({'row': 2, 'message': '文件中没有题目'})
    if not errors:
        existing = [dict(r) for r in conn.execute('SELECT id,stage_id,batch_no,enabled FROM practice_quiz_questions') if r['id'] not in seen and not (replace and r['stage_id']==stage_id)]
        try:
            _check_capacity(existing + changes)
        except PracticeError as exc:
            errors.append({'row': 0, 'message': exc.message})
    return changes, errors


def preview_import(data):
    with db() as conn:
        changes, errors = _read_import(conn, data.get('csv'), data.get('stage_id', 0), _replace_mode(data))
    return {'added': sum(q['id'] is None for q in changes), 'updated': sum(q['id'] is not None for q in changes),
            'errors': errors, 'items': changes[:10], 'total': len(changes)}


def import_bank(data):
    with db(True) as conn:
        if _replace_mode(data) and _stage(conn,data['stage_id'])['kind']=='weekly':
            raise PracticeError('每周主题请从组题区生成题包；本期修正可导出后按id更新',400)
        key, digest, previous = _operation(conn, data.get('request_id'), {'csv': data.get('csv'), 'stage_id': data.get('stage_id', 0), 'replace': _replace_mode(data)})
        if previous:
            return previous
        changes, errors = _read_import(conn, data.get('csv'), data.get('stage_id', 0), _replace_mode(data))
        if errors:
            first = errors[0]
            raise PracticeError(f"第{first['row']}行：{first['message']}；未写入任何题目", 400)
        if _replace_mode(data):
            conn.execute('UPDATE practice_quiz_questions SET archived=1,enabled=0 WHERE stage_id=?', (data['stage_id'],))
        ids = [_write_question(conn, q['id'], q) for q in changes]
        affected = set()
        if _replace_mode(data):
            affected.update(r['product_id'] for r in conn.execute('''SELECT DISTINCT l.product_id FROM practice_learning_unit_questions l
                JOIN practice_quiz_questions q ON q.id=l.question_id WHERE q.archived=1 AND q.stage_id=?''', (data['stage_id'],)))
        affected.update(q['product_id'] for q in changes if q['stage_id']==0 and q['product_id'] and q['fact_id'])
        if ids:
            affected.update(r['product_id'] for r in conn.execute('''SELECT DISTINCT product_id FROM practice_learning_unit_questions
                WHERE question_id IN (%s)''' % ','.join('?' for _ in ids), ids))
        for product_id in affected:
            conn.execute('UPDATE practice_learning_courses SET published=0,updated_at=? WHERE product_id=?', (now().isoformat(),product_id))
        result = {'added': sum(q['id'] is None for q in changes), 'updated': sum(q['id'] is not None for q in changes), 'ids': ids}
        conn.execute('INSERT INTO practice_quiz_admin_operations VALUES(?,?,?)', (key, digest, json.dumps(result)))
        return result


def _stage(conn, stage_id):
    stage_id = _integer(stage_id, 1, 2147483647)
    row = conn.execute('SELECT * FROM practice_quiz_stages WHERE id=?', (stage_id,)).fetchone()
    if not row:
        raise PracticeError('阶段题库不存在', 404)
    return dict(row)


def _stage_summaries(conn):
    result = []
    day = now().date().isoformat()
    for row in conn.execute('SELECT * FROM practice_quiz_stages ORDER BY id DESC'):
        stage = dict(row)
        stage['question_count'] = conn.execute('SELECT COUNT(*) FROM practice_quiz_questions WHERE stage_id=? AND enabled=1', (stage['id'],)).fetchone()[0]
        stage['batch_count'] = len(_batches(conn, stage['id']))
        ready = stage['batch_count'] > 0
        if stage['kind']=='weekly':
            ready = stage['batch_count']==3 and stage['question_count']==30 and bool(conn.execute('SELECT 1 FROM practice_quiz_weekly_plans WHERE stage_id=?',(stage['id'],)).fetchone())
        stage['status'] = ('未开启' if not stage['enabled'] else '待开放' if day < stage['starts_on'] else
                           '已结束' if day > stage['ends_on'] else '开放中' if ready else '题目待完善')
        result.append(stage)
    return result


def _active_stage(conn):
    return next((s for s in _stage_summaries(conn) if s['status'] == '开放中'), None)


def _require_stage_open(conn, stage_id):
    stage = _stage(conn, stage_id)
    day = now().date().isoformat()
    if not stage['enabled'] or not stage['starts_on'] <= day <= stage['ends_on']:
        raise PracticeError('此阶段题库当前未开放，可在个人记录中查看已开始的练习', 403)
    if not _batches(conn, stage_id) or (stage['kind']=='weekly' and not any(s['id']==stage_id and s['status']=='开放中' for s in _stage_summaries(conn))):
        raise PracticeError('阶段题目正在准备中', 409)
    return stage


def _stage_daily(conn, day, stage_id):
    row = conn.execute('SELECT * FROM practice_quiz_stage_daily WHERE day=? AND stage_id=?', (day, stage_id)).fetchone()
    if row:
        return dict(row)
    batches = _batches(conn, stage_id)
    if not batches:
        raise PracticeError('阶段题目正在准备中', 503)
    if _stage(conn,stage_id)['kind']=='weekly':
        from services import practice_weekly as weekly
        prepared = weekly.daily_snapshot(conn,day,stage_id)
        batch, snapshot = prepared['batch_no'],prepared['snapshot']
    else:
        batch = batches[datetime.fromisoformat(day).date().toordinal() % len(batches)]['batch_no']
        questions = _snapshot(conn,batch,stage_id)
        lead = datetime.fromisoformat(day).date().toordinal()//len(batches)%10
        questions = [questions[lead]]+questions[:lead]+questions[lead+1:]
        snapshot = json.dumps(questions, ensure_ascii=False)
    conn.execute('INSERT INTO practice_quiz_stage_daily VALUES(?,?,?,?)', (day, stage_id, batch, snapshot))
    return {'day': day, 'batch_no': batch, 'snapshot': snapshot}


def promotion():
    require_enabled()
    with db() as conn:
        stage = _active_stage(conn)
    return {'stage': {k:stage[k] for k in ('id','title','description','starts_on','ends_on','question_count','batch_count')} if stage else None}


def save_stage(data, stage_id=None):
    is_new = stage_id is None
    kind = data.get('kind', None)
    values = {}
    for key, maximum in (('title', 60), ('description', 300)):
        value = data.get(key, '')
        if not isinstance(value, str) or len(value)>maximum or (key=='title' and not value.strip()):
            raise PracticeError('请填写阶段名称（60字以内）和简介（300字以内）', 400)
        values[key] = value.strip()
    for key in ('starts_on','ends_on'):
        value = data.get(key)
        try:
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError()
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise PracticeError('请填写有效的开放起止日期', 400) from exc
        values[key] = value
    if values['ends_on'] < values['starts_on'] or type(data.get('enabled')) is not bool:
        raise PracticeError('结束日期须不早于开始日期，启用状态需有效', 400)
    with db(True) as conn:
        previous = None
        if stage_id:
            existing = _stage(conn, stage_id)
            if data.get('updated_at') and data['updated_at'] != existing['updated_at']:
                raise PracticeError('阶段设置已变化，请刷新后编辑', 409)
        else:
            key, digest, previous = _operation(conn, data.get('request_id'), {'stage': data})
            if previous:
                return previous
        kind = kind or (existing['kind'] if stage_id else 'seasonal')
        if kind not in ('weekly','seasonal'):
            raise PracticeError('主题类型无效',400)
        if kind=='weekly' and (datetime.fromisoformat(values['ends_on'])-datetime.fromisoformat(values['starts_on'])).days!=6:
            raise PracticeError('每周主题的开放时间应为连续7天',400)
        if data['enabled']:
            if kind=='weekly' and not values['starts_on'] <= now().date().isoformat() <= values['ends_on']:
                raise PracticeError('每周主题请在开始日期当天或开放期间开启',400)
            if not stage_id or not _batches(conn, stage_id):
                raise PracticeError('先上传题目，至少准备一组完整的10道启用题后再开启', 400)
            if kind=='weekly' and not (len(_batches(conn,stage_id))==3 and conn.execute('SELECT 1 FROM practice_quiz_weekly_plans WHERE stage_id=?',(stage_id,)).fetchone()):
                raise PracticeError('请先选题并发布30题主题包',400)
            conn.execute('UPDATE practice_quiz_stages SET enabled=0,updated_at=? WHERE id<>? AND enabled=1', (now().isoformat(), stage_id))
        fields = (values['title'], values['description'], values['starts_on'], values['ends_on'], int(data['enabled']), now().isoformat())
        if stage_id:
            conn.execute('UPDATE practice_quiz_stages SET title=?,description=?,starts_on=?,ends_on=?,enabled=?,updated_at=? WHERE id=?', fields+(stage_id,))
        else:
            stage_id = conn.execute('INSERT INTO practice_quiz_stages(title,description,starts_on,ends_on,enabled,updated_at) VALUES(?,?,?,?,?,?)',fields).lastrowid
        conn.execute('UPDATE practice_quiz_stages SET kind=? WHERE id=?',(kind,stage_id))
        if kind=='weekly':
            from services import practice_weekly as weekly
            weekly.shift_plan(conn,stage_id,values['starts_on'])
        result = {'id':stage_id}
        if is_new:
            conn.execute('INSERT INTO practice_quiz_admin_operations VALUES(?,?,?)', (key,digest,json.dumps(result)))
        return result


def _replace_mode(data):
    value = data.get('replace', False)
    if type(value) is not bool or (value and not data.get('stage_id')):
        raise PracticeError('只有阶段题库可使用整库替换', 400)
    return value
