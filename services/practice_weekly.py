"""Weekly composition and entry analytics; ordinary chat and scoring stay isolated."""
import json
from datetime import timedelta, date
from services import practice_common as common, practice_service as p


def _weekly(conn, stage_id):
    stage = p._stage(conn, stage_id)
    if stage['kind'] != 'weekly':
        raise common.PracticeError('请选择每周主题', 400)
    return stage


def selections(conn, stage_id):
    return [{'question': p._question(r), 'is_new': bool(r['is_new'])} for r in conn.execute('''
        SELECT q.*,s.is_new FROM practice_quiz_weekly_selections s JOIN practice_quiz_questions q ON q.id=s.question_id
        WHERE s.stage_id=? AND q.stage_id=0 AND q.archived=0 ORDER BY s.position,q.id''', (stage_id,))]


def enroll(conn, stage_id, question_ids):
    _weekly(conn, stage_id)
    count = conn.execute('SELECT COUNT(*) FROM practice_quiz_weekly_selections WHERE stage_id=?',(stage_id,)).fetchone()[0]
    fresh = [qid for qid in question_ids if not conn.execute('SELECT 1 FROM practice_quiz_weekly_selections WHERE stage_id=? AND question_id=?',(stage_id,qid)).fetchone()]
    if count + len(fresh) > 30:
        raise common.PracticeError('本期已选题目加上新题超过30道，请先调整选题',400)
    for qid in fresh:
        conn.execute('INSERT INTO practice_quiz_weekly_selections VALUES(?,?,1,?)',(stage_id,qid,count))
        count += 1


def _groups(items):
    groups = [[],[],[]]
    for index, item in enumerate(i for i in items if i['is_new']):
        groups[index % 3].append(item)
    for item in (i for i in items if not i['is_new']):
        groups[min(range(3),key=lambda i:(len(groups[i]),i))].append(item)
    return groups


def _schedule(stage, groups):
    result = []
    used_titles = set()
    start = date.fromisoformat(stage['starts_on'])
    for offset in range(7):
        group_no = offset % 3
        lead = next((i['question'] for i in groups[group_no] if i['question']['title'].strip() not in used_titles),None)
        if not lead:
            raise common.PracticeError('入口问题标题过于重复，请调整选题，让七天有不同的客户问题',400)
        used_titles.add(lead['title'].strip())
        result.append({'day': str(start+timedelta(days=offset)), 'batch_no':group_no+1,
                       'lead_question_id':lead['id'], 'question_title':lead['title'],
                       'label':'初练' if offset<3 else '复练' if offset<6 else '精选复练'})
    return result


def preview(stage, items):
    new_count = sum(i['is_new'] for i in items)
    ready = len(items)==30 and 5<=new_count<=10
    schedule,error = [],None
    if ready:
        try:
            schedule=_schedule(stage,_groups(items))
        except common.PracticeError as exc:
            ready,error=False,exc.message
    return {'selected_count':len(items),'new_count':new_count,'ready':ready,'error':error,'schedule':schedule}


def builder(stage_id):
    with common.db() as conn:
        stage = _weekly(conn,stage_id)
        items = selections(conn,stage_id)
        mothers = [p._question(r) for r in conn.execute('SELECT * FROM practice_quiz_questions WHERE stage_id=0 AND archived=0 ORDER BY id DESC')]
        plan = conn.execute('SELECT * FROM practice_quiz_weekly_plans WHERE stage_id=?',(stage_id,)).fetchone()
    return {'stage':stage,'selections':[{'question_id':i['question']['id'],'is_new':i['is_new']} for i in items],
            'questions':mothers, **preview(stage,items), 'published_schedule':json.loads(plan['schedule']) if plan else []}


def save_selections(stage_id,data):
    chosen = data.get('selections')
    if not isinstance(chosen,list) or len(chosen)>30:
        raise common.PracticeError('请最多选择30道题',400)
    seen = set()
    with common.db(True) as conn:
        _weekly(conn,stage_id)
        for item in chosen:
            if not isinstance(item,dict) or type(item.get('is_new')) is not bool:
                raise common.PracticeError('选题格式无效',400)
            qid = common.integer(item.get('question_id'),1,2147483647)
            if qid in seen or not conn.execute('SELECT 1 FROM practice_quiz_questions WHERE id=? AND stage_id=0 AND archived=0',(qid,)).fetchone():
                raise common.PracticeError('请从母题库选择不重复的完整题目',400)
            seen.add(qid)
        conn.execute('DELETE FROM practice_quiz_weekly_selections WHERE stage_id=?',(stage_id,))
        for position,item in enumerate(chosen):
            conn.execute('INSERT INTO practice_quiz_weekly_selections VALUES(?,?,?,?)',(stage_id,item['question_id'],int(item['is_new']),position))
        return preview(_weekly(conn,stage_id),selections(conn,stage_id))


def publish(stage_id,data):
    with common.db(True) as conn:
        stage = _weekly(conn,stage_id)
        items = selections(conn,stage_id)
        key,digest,old = p._operation(conn,data.get('request_id'),{'publish_weekly':stage_id,'items':items,'starts_on':stage['starts_on']})
        if old:
            return old
        readiness=preview(stage,items)
        if not readiness['ready']:
            raise common.PracticeError(readiness['error'] or '请选满30题，其中5–10题标为本期新题',400)
        conn.execute('UPDATE practice_quiz_questions SET archived=1,enabled=0 WHERE stage_id=?',(stage_id,))
        groups = _groups(items)
        for batch,group in enumerate(groups,1):
            for item in group:
                source = item['question']
                q = {**source,'stage_id':stage_id,'batch_no':batch,'enabled':True}
                qid = p._write_question(conn,None,q)
                conn.execute('UPDATE practice_quiz_questions SET source_question_id=?,weekly_new=? WHERE id=?',(source['id'],int(item['is_new']),qid))
                item['question'] = {**q,'id':qid}
        schedule = _schedule(stage,groups)
        conn.execute('INSERT OR REPLACE INTO practice_quiz_weekly_plans VALUES(?,?,?)',(stage_id,json.dumps(schedule,ensure_ascii=False),common.now().isoformat()))
        result = {'ok':True,'schedule':schedule}
        conn.execute('INSERT INTO practice_quiz_admin_operations VALUES(?,?,?)',(key,digest,json.dumps(result,ensure_ascii=False)))
        return result


def daily_snapshot(conn,day,stage_id):
    stage = _weekly(conn,stage_id)
    row = conn.execute('SELECT schedule FROM practice_quiz_weekly_plans WHERE stage_id=?',(stage_id,)).fetchone()
    if not row:
        raise common.PracticeError('请先组题并发布每周主题',409)
    schedule = json.loads(row['schedule'])
    offset = (date.fromisoformat(day)-date.fromisoformat(stage['starts_on'])).days
    item = schedule[offset%7]
    questions = p._snapshot(conn,item['batch_no'],stage_id)
    lead = next((q for q in questions if q['id']==item['lead_question_id']),None)
    if not lead:
        raise common.PracticeError('本期题目已调整，请重新组题发布',409)
    questions = [lead]+[q for q in questions if q['id']!=lead['id']]
    return {'day':day,'batch_no':item['batch_no'],'snapshot':json.dumps(questions,ensure_ascii=False)}


def label(stage,day):
    if stage and stage['kind']=='weekly':
        offset=(date.fromisoformat(day)-date.fromisoformat(stage['starts_on'])).days
        return '初练' if offset<3 else '复练' if offset<6 else '精选复练'
    return '今日练习'


def event(conn,identity,stage_id,day,kind):
    if kind in ('impression','click'):
        conn.execute('INSERT OR IGNORE INTO practice_quiz_visits VALUES(?,?,?)',(identity['user_id'],day,identity.get('team_name','')))
    conn.execute('INSERT OR IGNORE INTO practice_quiz_entry_events VALUES(?,?,?,?)',(identity['user_id'],stage_id,day,kind))


def entry(conn,identity):
    day = common.now().date().isoformat()
    stage = p._active_stage(conn)
    existing = conn.execute("SELECT * FROM practice_quiz_sessions WHERE user_id=? AND mode='daily' AND assigned_day=?",(identity['user_id'],day)).fetchone()
    if not existing or existing['completed']:
        unfinished = conn.execute("SELECT * FROM practice_quiz_sessions WHERE user_id=? AND assigned_day=? AND entry=1 AND completed=0 ORDER BY created_at DESC,id DESC LIMIT 1",(identity['user_id'],day)).fetchone()
        if unfinished:
            existing=unfinished
    if existing and not existing['completed']:
        s = dict(existing)
        q = json.loads(s['snapshot'])[s['cursor']]
        answered_count = conn.execute('SELECT COUNT(*) FROM practice_quiz_answers WHERE session_id=?',(s['id'],)).fetchone()[0]
        return {'day':day,'stage_id':s['stage_id'],'stage_title':s['stage_title'],'question_title':q['title'],'question_id':q['id'],
                'session_id':s['id'],'mode':s['mode'],'label':'继续练习','action':'resume','answered_count':answered_count,
                'kind':stage['kind'] if stage and stage['id']==s['stage_id'] else 'seasonal'}
    stage_id = stage['id'] if stage else 0
    try:
        today = p._daily(conn,day,stage_id)
    except common.PracticeError as exc:
        if exc.status_code != 503:
            raise
        return None
    mode = 'free' if existing else 'daily'
    replay_round = None
    if mode == 'free':
        replay_round = conn.execute('''SELECT COUNT(*) FROM practice_quiz_sessions
            WHERE user_id=? AND assigned_day=? AND mode='free' AND entry=1 AND completed=1''',
            (identity['user_id'], day)).fetchone()[0]
        q = p._random_free_questions(conn, identity['user_id'], day, stage_id, replay_round)[0]
    else:
        q = json.loads(today['snapshot'])[0]
    return {'day':day,'stage_id':stage_id,'stage_title':stage['title'] if stage else '今日客户问题','kind':stage['kind'] if stage else 'regular',
            'question_title':q['title'],'question_id':q['id'],'session_id':None,'mode':mode,
            'label':label(stage,day),'action':'start','batch_no':replay_round+1 if mode=='free' else today['batch_no'],
            'replay_round':replay_round,'answered_count':0}


def get_entry(identity):
    p.require_enabled()
    with common.db(True) as conn:
        result = entry(conn,identity)
    return {'entry':result}


def record_impression(identity,data):
    p.require_enabled()
    stage_id = common.integer(data.get('stage_id'),0,2147483647)
    day = data.get('day')
    with common.db(True) as conn:
        current = entry(conn,identity)
        if current and current['stage_id']==stage_id and current['day']==day:
            event(conn,identity,stage_id,day,'impression')
    return {'ok':True}


def metrics(conn):
    rows = conn.execute('''SELECT stage_id,event,COUNT(DISTINCT user_id) users FROM practice_quiz_entry_events GROUP BY stage_id,event''').fetchall()
    result = {}
    for r in rows:
        result.setdefault(r['stage_id'],{'stage_id':r['stage_id'],'impression':0,'click':0,'first_answer':0,'complete':0})[r['event']]=r['users']
    return list(result.values())


def promotion_preview(stage_id):
    with common.db(True) as conn:
        stage = p._stage(conn,stage_id)
        rows = conn.execute('SELECT schedule FROM practice_quiz_weekly_plans WHERE stage_id=?',(stage_id,)).fetchone()
        if stage['kind']=='weekly' and rows:
            schedule = json.loads(rows['schedule'])
            for item in schedule:
                cached=conn.execute('SELECT snapshot FROM practice_quiz_stage_daily WHERE day=? AND stage_id=?',(item['day'],stage_id)).fetchone()
                lead=conn.execute('SELECT title FROM practice_quiz_questions WHERE id=?',(item['lead_question_id'],)).fetchone()
                item['question_title']=json.loads(cached['snapshot'])[0]['title'] if cached else lead['title'] if lead else item['question_title']
                if cached:
                    item['batch_no']=conn.execute('SELECT batch_no FROM practice_quiz_stage_daily WHERE day=? AND stage_id=?',(item['day'],stage_id)).fetchone()[0]
        elif stage['kind']=='weekly':
            schedule = preview(stage,selections(conn,stage_id))['schedule']
        else:
            schedule=[]
            if p._batches(conn,stage_id):
                day=common.now().date().isoformat()
                q=json.loads(p._daily(conn,day,stage_id)['snapshot'])[0]
                schedule=[{'day':day,'batch_no':q['batch_no'],'question_title':q['title'],'label':'今日练习'}]
    return {'stage':stage,'schedule':schedule,'draft':stage['kind']=='weekly' and not bool(rows)}


def shift_plan(conn,stage_id,starts_on):
    row=conn.execute('SELECT schedule FROM practice_quiz_weekly_plans WHERE stage_id=?',(stage_id,)).fetchone()
    if row:
        schedule=json.loads(row['schedule'])
        for offset,item in enumerate(schedule):
            item['day']=str(date.fromisoformat(starts_on)+timedelta(days=offset))
        conn.execute('UPDATE practice_quiz_weekly_plans SET schedule=? WHERE stage_id=?',(json.dumps(schedule,ensure_ascii=False),stage_id))


def import_new(stage_id,data):
    with common.db(True) as conn:
        _weekly(conn,stage_id)
        key,digest,old=p._operation(conn,data.get('request_id'),{'weekly_new':stage_id,'csv':data.get('csv')})
        if old:
            return old
        changes,errors=read_new(conn,stage_id,data)
        if errors:
            raise common.PracticeError(f"第{errors[0]['row']}行：{errors[0]['message']}；未写入任何题目",400)
        ids=[]
        for q in changes:
            last=conn.execute('SELECT COALESCE(MAX(batch_no),0) FROM practice_quiz_questions WHERE stage_id=0 AND archived=0').fetchone()[0]
            count=conn.execute('SELECT COUNT(*) FROM practice_quiz_questions WHERE stage_id=0 AND archived=0 AND batch_no=?',(last,)).fetchone()[0]
            q['batch_no']=last if last and count<10 else last+1
            ids.append(p._write_question(conn,None,q))
        enroll(conn,stage_id,ids)
        result={'added':len(ids),'updated':0,'ids':ids}
        conn.execute('INSERT INTO practice_quiz_admin_operations VALUES(?,?,?)',(key,digest,json.dumps(result)))
        return result


def read_new(conn,stage_id,data):
    _weekly(conn,stage_id)
    # New-question CSVs use mother categories and keep source questions inactive until organized.
    import csv,io
    text=data.get('csv')
    if not isinstance(text,str) or len(text.encode('utf-8'))>2000000:
        raise common.PracticeError('请上传不超过2MB的CSV题库',400)
    try:
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')),strict=True)
        rows=list(reader)
        if len(rows)>1000:
            raise common.PracticeError('每次最多导入1000道题',400)
        output=io.StringIO(newline='')
        fields=list(reader.fieldnames or [])
        for field in ('关卡','启用'):
            if field not in fields:fields.append(field)
        writer=csv.DictWriter(output,fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if row.get('id','').strip():
                raise common.PracticeError('本期新题导入请留空id；已有题请在选题区勾选',400)
            row['关卡']=row.get('关卡') or '1'
            row['启用']='0'
            writer.writerow(row)
    except (csv.Error,ValueError,AttributeError) as exc:
        raise common.PracticeError('CSV格式错误，请使用下载的模板',400) from exc
    changes,errors=p._read_import(conn,output.getvalue(),0)
    count=conn.execute('SELECT COUNT(*) FROM practice_quiz_weekly_selections WHERE stage_id=?',(stage_id,)).fetchone()[0]
    if count+len(changes)>30:
        errors.append({'row':0,'message':'本期选题加上新题超过30道'})
    return changes,errors


def preview_new(stage_id,data):
    with common.db() as conn:
        changes,errors=read_new(conn,stage_id,data)
    return {'added':len(changes),'updated':0,'items':changes[:10],'total':len(changes),'errors':errors}
