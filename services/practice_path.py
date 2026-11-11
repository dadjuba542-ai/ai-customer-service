"""Reviewed seven-unit learning path with a stable learner-facing publication."""
import json

from services import practice_common as common, practice_learning as learning

LEVELS = {1: '识别事实', 2: '理解判断', 3: '场景应用', 4: '组织回答', 5: '综合应对'}
SEED = (
    ('product', 1, '认识产品', 1),
    ('product', 2, '配料与规格', 2),
    ('skill', None, '判断客户需求', 3),
    ('product', 3, '使用方法', 3),
    ('skill', None, '准确回答与核实', 4),
    ('product', 4, '客户常见提问', 4),
    ('skill', None, '处理异议与后续跟进', 5),
)


def authoring_guide():
    """Machine-readable rubric for local assistants drafting reviewed bank questions."""
    return {
        'version': '2026-10-22-five-levels',
        'purpose': '围绕一款培训产品，将产品知识与客户问答编成由浅入深的7单元学习主线。',
        'levels': [
            {'level': 1, 'name': LEVELS[1], 'learner_action': '识别一个明确的产品事实。',
             'question_pattern': '问一个名称、用途或基础定义，在解析中说明依据。',
             'example': '这款产品属于哪一类？'},
            {'level': 2, 'name': LEVELS[2], 'learner_action': '理解两项资料的含义或差别。',
             'question_pattern': '给出标签、配料或规格信息，判断哪种解读准确。',
             'example': '客户比较两种规格时，哪一项资料应先对齐？'},
            {'level': 3, 'name': LEVELS[3], 'learner_action': '根据客户情境判断需要问什么、查什么。',
             'question_pattern': '提供一句具体客户提问，选择最合适的澄清问题或使用依据。',
             'example': '客户问自己适不适合，第一步应了解哪项需求？'},
            {'level': 4, 'name': LEVELS[4], 'learner_action': '把已知资料组织成清楚、可执行的回答。',
             'question_pattern': '要求选择既回答问题又说明依据或下一步的回复。',
             'example': '客户追问使用方法时，哪句回复最完整？'},
            {'level': 5, 'name': LEVELS[5], 'learner_action': '综合处理多个顾虑并安排后续沟通。',
             'question_pattern': '同时给出价格、适用性或信任顾虑，选择回应顺序与后续动作。',
             'example': '客户既担心不适合又觉得贵，怎样接话并推进核实？'},
        ],
        'unit_sequence': [
            {'position': position, 'kind': kind, 'title': title, 'level': level,
             'questions_required': 3}
            for position, (kind, _product_unit_no, title, level) in enumerate(SEED, 1)
        ],
        'question_rules': [
            '每题只考一个学习目标，题干有具体情境或明确的知识点。',
            '提供四个互不重复、长度与语气尽量相近的选项；推荐答案须在题目解析中说明依据。',
            '错误选项应对应常见误解或沟通失误，不能靠荒谬选项凑数。',
            '解析写明推荐答案的依据及关键判断；参考回复写成伙伴实际可说的一句话。',
            '产品知识直接写入独立的产品题目、解析与参考回复；资料未覆盖的细节可考“先核实再回复”。',
            'batch_no 是每日10题题组编号，不代表学习难度；主线按 difficulty_level 和单元归属编排。',
        ],
        'authoring_fields': {
            'title': '客户场景或知识问题，不直接暴露正确选项',
            'options': '四个不同的决策或回复，按 A/B/C/D 顺序传入',
            'answer_index': '从0开始：0=A、1=B、2=C、3=D',
            'explanation': '解释为什么该选项正确，以及最易混淆的判断点',
            'method': '一条具体、自然的参考回复',
            'learning_objective': '学完本题能够识别、判断或回答什么',
            'difficulty_level': '1到5，对应本工具的五级梯度',
            'unit_id': '从 practice_learning_outline 取得目标单元ID',
        },
        'workflow': [
            '先调用 practice_learning_guidelines，再调用 practice_learning_outline 读取当前单元和题目缺口。',
            '产品题目由负责人单独输入或审核，不从产品板块推测事实，也不要求另写知识卡。',
            '查重后用 practice_create_question 在 stage_id=0 的母题库创建停用新题。',
            '用 practice_suggest_placement 提交学习目标、难度和单元ID，等待后台审核。',
            '负责人审核、选满每单元3题，并在后台发布后，学员才会看到主线。',
        ],
    }


def _unit_done(conn, user_id, unit):
    return bool(conn.execute('''SELECT 1 FROM practice_learning_sessions WHERE user_id=?
        AND kind='path' AND path_unit_id=? AND completed=1 LIMIT 1''',
        (user_id, unit['id'])).fetchone())


def _units(conn):
    return [dict(row) for row in conn.execute('SELECT * FROM practice_learning_path_units ORDER BY position')]


def _ready(conn, units, require_placement=True):
    if len(units) != len(SEED):
        return False
    for unit in units:
        rows = conn.execute('''SELECT q.id,q.difficulty_level,q.learning_objective,q.suggested_unit_id FROM practice_learning_path_questions l
            JOIN practice_quiz_questions q ON q.id=l.question_id AND q.stage_id=0 AND q.archived=0
            WHERE l.unit_id=? ORDER BY l.position''', (unit['id'],)).fetchall()
        if len(rows) != 3 or any(r['difficulty_level'] != unit['level'] or not r['learning_objective'] or
                                 (require_placement and r['suggested_unit_id'] != unit['id']) for r in rows):
            return False
    return True


def _draft_snapshot(conn, units, require_placement=True):
    settings = conn.execute('SELECT product_name FROM practice_learning_path_settings WHERE id=1').fetchone()
    if not settings or not _ready(conn, units, require_placement):
        return None
    result = []
    for unit in units:
        questions = [dict(row) for row in conn.execute('''SELECT q.* FROM practice_learning_path_questions l
            JOIN practice_quiz_questions q ON q.id=l.question_id
            WHERE l.unit_id=? ORDER BY l.position''', (unit['id'],))]
        result.append({'id': unit['id'], 'position': unit['position'], 'kind': unit['kind'],
                       'product_id': unit['product_id'], 'product_unit_no': unit['product_unit_no'],
                       'title': unit['title'], 'level': unit['level'], 'questions': questions})
    return {'product_name': settings['product_name'], 'units': result}


def _publication(conn):
    row = conn.execute('SELECT snapshot FROM practice_learning_path_publication WHERE id=1').fetchone()
    if row:
        return json.loads(row['snapshot'])
    # Existing installations may have published the path before this table existed.
    settings = conn.execute('SELECT published FROM practice_learning_path_settings WHERE id=1').fetchone()
    return _draft_snapshot(conn, _units(conn), require_placement=False) if settings and settings['published'] else None


def _preserve_publication(conn):
    """Capture an older live publication before its first draft edit after migration."""
    if conn.execute('SELECT 1 FROM practice_learning_path_publication WHERE id=1').fetchone():
        return
    snapshot = _publication(conn)
    if snapshot:
        conn.execute('''INSERT INTO practice_learning_path_publication(id,snapshot,published_at)
            VALUES(1,?,?)''', (json.dumps(snapshot, ensure_ascii=False), common.now().isoformat()))


def home(identity):
    learning.require_learning()
    with common.db() as conn:
        published = _publication(conn)
        if not published:
            return {'available': False, 'units': [], 'next_unit': None, 'completed_count': 0}
        result = []
        first_pending = None
        for unit in published['units']:
            done = _unit_done(conn, identity['user_id'], unit)
            row = {k: unit[k] for k in ('id', 'position', 'kind', 'product_id', 'product_unit_no', 'title', 'level')}
            row['level_label'] = LEVELS[unit['level']]
            row['completed'] = done
            row['subtitle'] = '产品知识 · 3题即时解析' if unit['kind'] == 'product' else '沟通方法 · 3题即时解析'
            if not done and first_pending is None:
                first_pending = row
            result.append(row)
        resume = None
        if first_pending:
            resume = conn.execute('''SELECT id FROM practice_learning_sessions WHERE user_id=?
                AND kind='path' AND path_unit_id=? AND completed=0 ORDER BY created_at DESC LIMIT 1''',
                (identity['user_id'], first_pending['id'])).fetchone()
        return {'available': True, 'units': result, 'next_unit': first_pending,
                'resume_id': resume['id'] if resume else None,
                'completed_count': sum(unit['completed'] for unit in result),
                'product_name': published['product_name']}


def initialize(product_name):
    if not isinstance(product_name, str) or not product_name.strip() or len(product_name) > 100:
        raise common.PracticeError('请填写不超过100字的培训产品名称', 400)
    product_name = product_name.strip()
    with common.db(True) as conn:
        if conn.execute('SELECT 1 FROM practice_learning_path_settings WHERE id=1').fetchone():
            raise common.PracticeError('主线已建立，请在编排区继续编辑', 409)
        stamp = common.now().isoformat()
        conn.execute('INSERT INTO practice_learning_path_settings VALUES(1,?,NULL,0,?)', (product_name, stamp))
        for position, (kind, product_unit_no, title, level) in enumerate(SEED, 1):
            conn.execute('''INSERT INTO practice_learning_path_units
                (position,kind,product_id,product_unit_no,title,body,level,updated_at)
                VALUES(?,?,?,?,?,?,?,?)''', (position, kind, None,
                                            product_unit_no, title, '', level, stamp))
    return admin_data()


def admin_data():
    with common.db() as conn:
        settings = conn.execute('SELECT * FROM practice_learning_path_settings WHERE id=1').fetchone()
        units = _units(conn)
        for unit in units:
            unit['question_ids'] = [r['question_id'] for r in conn.execute('''SELECT question_id
                FROM practice_learning_path_questions WHERE unit_id=? ORDER BY position''', (unit['id'],))]
        questions = [dict(r) for r in conn.execute('''SELECT id,title,category,product_id,fact_id,skill_code,
            learning_objective,difficulty_level,suggested_unit_id,explanation,method FROM practice_quiz_questions
            WHERE stage_id=0 AND archived=0 ORDER BY id DESC''')]
        owners = {r['question_id']: r['unit_id'] for r in conn.execute('SELECT question_id,unit_id FROM practice_learning_path_questions')}
        for question in questions:
            question['assigned_unit_id'] = owners.get(question['id'])
        unit_levels = {unit['id']: unit['level'] for unit in units}
        level_gaps = {level: {'remaining_slots': sum(max(0, 3-len(unit['question_ids'])) for unit in units if unit['level']==level),
                              'available_questions': sum(q['difficulty_level']==level and q['learning_objective'] and
                                                         unit_levels.get(q['suggested_unit_id'])==level and q['id'] not in owners
                                                         for q in questions)}
                      for level in LEVELS}
        suggestions = [dict(r) for r in conn.execute('''SELECT s.*,q.title question_title,u.title unit_title
            FROM practice_learning_path_suggestions s
            JOIN practice_quiz_questions q ON q.id=s.question_id
            JOIN practice_learning_path_units u ON u.id=s.unit_id
            WHERE s.status='pending' ORDER BY s.created_at,s.id''')]
        ready = _ready(conn, units)
        published = _publication(conn)
        draft = _draft_snapshot(conn, units) if ready else None
    return {'settings': dict(settings) if settings else None, 'units': units,
            'questions': questions, 'suggestions': suggestions, 'ready': ready,
            'has_publication': bool(published), 'draft_pending': bool(published and draft != published),
            'levels': LEVELS, 'level_gaps': level_gaps,
            'unclassified_count': sum(not q['difficulty_level'] for q in questions)}


def save_unit(unit_id, data):
    unit_id = common.integer(unit_id, 1, 2147483647)
    title, ids = data.get('title'), data.get('question_ids')
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise common.PracticeError('请填写不超过100字的单元标题', 400)
    if not isinstance(ids, list) or len(ids) > 3 or len(set(map(str, ids))) != len(ids):
        raise common.PracticeError('每单元最多选择3道不同的母题', 400)
    ids = [common.integer(qid, 1, 2147483647) for qid in ids]
    with common.db(True) as conn:
        _preserve_publication(conn)
        unit = conn.execute('SELECT * FROM practice_learning_path_units WHERE id=?', (unit_id,)).fetchone()
        if not unit:
            raise common.PracticeError('学习单元不存在', 404)
        for qid in ids:
            q = conn.execute('''SELECT difficulty_level,learning_objective,suggested_unit_id FROM practice_quiz_questions
                WHERE id=? AND stage_id=0 AND archived=0''', (qid,)).fetchone()
            if not q or q['difficulty_level'] != unit['level'] or not q['learning_objective'] or q['suggested_unit_id'] != unit_id:
                raise common.PracticeError('请选择已审核学习目标、难度及本单元归属的题目', 400)
            owner = conn.execute('SELECT unit_id FROM practice_learning_path_questions WHERE question_id=?', (qid,)).fetchone()
            if owner and owner['unit_id'] != unit_id:
                raise common.PracticeError('题目已用于主线其他单元', 400)
        conn.execute('UPDATE practice_learning_path_units SET title=?,body=?,updated_at=? WHERE id=?',
                     (title.strip(), '', common.now().isoformat(), unit_id))
        conn.execute('DELETE FROM practice_learning_path_questions WHERE unit_id=?', (unit_id,))
        for position, qid in enumerate(ids):
            conn.execute('INSERT INTO practice_learning_path_questions VALUES(?,?,?)', (unit_id, position, qid))
        conn.execute('UPDATE practice_learning_path_settings SET updated_at=? WHERE id=1',
                     (common.now().isoformat(),))
    return {'ok': True}


def publish():
    with common.db(True) as conn:
        units = _units(conn)
        settings = conn.execute('SELECT * FROM practice_learning_path_settings WHERE id=1').fetchone()
        if not settings or len(units) < 7:
            raise common.PracticeError('请先建立学习主线', 409)
        snapshot = _draft_snapshot(conn, units)
        if not snapshot:
            raise common.PracticeError('请完善每个单元的3道已审核归属题目', 400)
        conn.execute('''INSERT INTO practice_learning_path_publication(id,snapshot,published_at)
            VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET snapshot=excluded.snapshot,published_at=excluded.published_at''',
            (json.dumps(snapshot, ensure_ascii=False), common.now().isoformat()))
        conn.execute('UPDATE practice_learning_path_settings SET published=1,updated_at=? WHERE id=1',
                     (common.now().isoformat(),))
    return {'ok': True}


def suggest(data):
    qid = common.integer(data.get('question_id'), 1, 2147483647)
    unit_id = common.integer(data.get('unit_id'), 1, 2147483647)
    level = common.integer(data.get('difficulty_level'), 1, 5)
    objective, rationale = data.get('learning_objective'), data.get('rationale', '')
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 200:
        raise common.PracticeError('学习目标须为1到200字', 400)
    if not isinstance(rationale, str) or len(rationale) > 500:
        raise common.PracticeError('建议理由不能超过500字', 400)
    with common.db(True) as conn:
        question = conn.execute('SELECT updated_at FROM practice_quiz_questions WHERE id=? AND stage_id=0 AND archived=0', (qid,)).fetchone()
        if not question:
            raise common.PracticeError('母题不存在', 404)
        unit = conn.execute('SELECT level FROM practice_learning_path_units WHERE id=?', (unit_id,)).fetchone()
        if not unit:
            raise common.PracticeError('单元不存在', 404)
        if unit['level'] != level:
            raise common.PracticeError('建议难度须与目标单元一致', 400)
        existing = conn.execute("SELECT id FROM practice_learning_path_suggestions WHERE question_id=? AND unit_id=? AND status='pending'", (qid, unit_id)).fetchone()
        if existing:
            conn.execute('''UPDATE practice_learning_path_suggestions SET question_version=?,learning_objective=?,difficulty_level=?,rationale=?
                WHERE id=?''', (question['updated_at'], objective.strip(), level, rationale.strip(), existing['id']))
            suggestion_id = existing['id']
        else:
            suggestion_id = conn.execute('''INSERT INTO practice_learning_path_suggestions
                (question_id,unit_id,question_version,learning_objective,difficulty_level,rationale,created_at)
                VALUES(?,?,?,?,?,?,?)''', (qid, unit_id, question['updated_at'], objective.strip(), level, rationale.strip(), common.now().isoformat())).lastrowid
    return {'id': suggestion_id, 'status': 'pending'}


def review(suggestion_id, accepted):
    suggestion_id = common.integer(suggestion_id, 1, 2147483647)
    if type(accepted) is not bool:
        raise common.PracticeError('审核结果无效', 400)
    with common.db(True) as conn:
        row = conn.execute("SELECT * FROM practice_learning_path_suggestions WHERE id=? AND status='pending'", (suggestion_id,)).fetchone()
        if not row:
            raise common.PracticeError('建议已处理或不存在', 404)
        if accepted:
            question = conn.execute('SELECT updated_at FROM practice_quiz_questions WHERE id=? AND stage_id=0 AND archived=0',
                                    (row['question_id'],)).fetchone()
            if not question or question['updated_at'] != row['question_version']:
                raise common.PracticeError('题目已修改，请让AI重新提交分级建议', 409)
            _preserve_publication(conn)
            conn.execute('''UPDATE practice_quiz_questions SET learning_objective=?,difficulty_level=?,suggested_unit_id=?
                WHERE id=? AND stage_id=0 AND archived=0''',
                (row['learning_objective'], row['difficulty_level'], row['unit_id'], row['question_id']))
        conn.execute('''UPDATE practice_learning_path_suggestions SET status=?,reviewed_at=? WHERE id=?''',
                     ('accepted' if accepted else 'rejected', common.now().isoformat(), suggestion_id))
    return {'ok': True, 'accepted': accepted}
