"""Question-bank MCP tools. All writes use the same validated admin services as the UI."""

import json

from config import Config
from services import practice_service as practice
from services import practice_weekly as weekly
from services import practice_path as path

SERVER_INFO = {'name': 'ai-baoer-practice-bank', 'version': Config.APP_VERSION}
_EDITABLE = frozenset(('batch_no', 'category', 'title', 'options', 'answer_index',
                       'explanation', 'method', 'sources', 'enabled', 'product_id',
                       'skill_code', 'fact_id'))


def learning_outline(args):
    _object(args)
    data = path.admin_data()
    return {'settings': data['settings'], 'units': data['units'],
            'unclassified_count': data['unclassified_count'], 'level_gaps': data['level_gaps'],
            'levels': data['levels']}


def learning_guidelines(args):
    _allow(_object(args), ())
    return path.authoring_guide()


def suggest_placement(args):
    args = _object(args)
    _allow(args, ('question_id', 'unit_id', 'learning_objective', 'difficulty_level', 'rationale'))
    return path.suggest(args)


def _object(value, label='参数'):
    if not isinstance(value, dict):
        raise practice.PracticeError(f'{label}须为 JSON 对象', 400)
    return value


def _integer(value, label, minimum=0, maximum=2147483647):
    if type(value) is not int or not minimum <= value <= maximum:
        raise practice.PracticeError(f'{label}无效', 400)
    return value


def _stage_id(args):
    return _integer(args.get('stage_id', 0), '题库编号')


def _allow(args, fields):
    unknown = set(args) - set(fields)
    if unknown:
        raise practice.PracticeError('不支持的参数：' + ', '.join(sorted(unknown)), 400)


def _question(conn, question_id):
    row = conn.execute('SELECT * FROM practice_quiz_questions WHERE id=? AND archived=0',
                       (question_id,)).fetchone()
    if not row:
        raise practice.PracticeError('题目不存在', 404)
    result = practice._question(row)
    result['enabled'] = bool(result['enabled'])
    return result


def overview(args):
    _object(args)
    with practice.db() as conn:
        stages = practice._stage_summaries(conn)
        banks = []
        for stage_id, title in [(0, '母题库'), *((s['id'], s['title']) for s in stages)]:
            rows = conn.execute('''SELECT batch_no,COUNT(*) AS total,
                SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled
                FROM practice_quiz_questions WHERE stage_id=? AND archived=0
                GROUP BY batch_no ORDER BY batch_no''', (stage_id,)).fetchall()
            banks.append({'stage_id': stage_id, 'title': title,
                          'batches': [dict(row) for row in rows]})
    return {'categories': list(practice.RAW), 'skill_codes': list(practice.SKILL_CODES),
            'source_keys': list(practice.SOURCES), 'csv_columns': practice.CSV_COLUMNS,
            'stages': stages, 'banks': banks}


def list_questions(args):
    args = _object(args)
    stage_id = args.get('stage_id')
    if stage_id is not None:
        stage_id = _integer(stage_id, '题库编号')
    batch_no = args.get('batch_no')
    if batch_no is not None:
        batch_no = _integer(batch_no, '关卡编号', 1, 10000)
    enabled = args.get('enabled')
    if enabled is not None and type(enabled) is not bool:
        raise practice.PracticeError('启用筛选无效', 400)
    keyword = args.get('keyword', '')
    if not isinstance(keyword, str) or len(keyword) > 100:
        raise practice.PracticeError('关键词不能超过100字', 400)
    limit = _integer(args.get('limit', 20), '每页条数', 1, 50)
    offset = _integer(args.get('offset', 0), '起始位置', 0, 100000)
    clauses, values = ['archived=0'], []
    if stage_id is not None:
        clauses.append('stage_id=?'); values.append(stage_id)
    if batch_no is not None:
        clauses.append('batch_no=?'); values.append(batch_no)
    if enabled is not None:
        clauses.append('enabled=?'); values.append(int(enabled))
    if keyword.strip():
        clauses.append('(title LIKE ? OR category LIKE ? OR explanation LIKE ?)')
        term = '%' + keyword.strip() + '%'
        values.extend((term, term, term))
    where = ' AND '.join(clauses)
    with practice.db() as conn:
        total = conn.execute('SELECT COUNT(*) FROM practice_quiz_questions WHERE ' + where, values).fetchone()[0]
        rows = conn.execute('''SELECT id,stage_id,batch_no,category,title,enabled,updated_at,
            product_id,skill_code,fact_id FROM practice_quiz_questions WHERE ''' + where +
            ' ORDER BY stage_id,batch_no,id LIMIT ? OFFSET ?', (*values, limit, offset)).fetchall()
    return {'total': total, 'offset': offset, 'limit': limit,
            'items': [dict(row) | {'enabled': bool(row['enabled'])} for row in rows]}


def get_question(args):
    args = _object(args)
    question_id = _integer(args.get('question_id'), '题目编号', 1)
    with practice.db() as conn:
        return _question(conn, question_id)


def list_products(args):
    args = _object(args)
    keyword = args.get('keyword', '')
    if not isinstance(keyword, str) or len(keyword) > 100:
        raise practice.PracticeError('产品关键词不能超过100字', 400)
    term = '%' + keyword.strip() + '%'
    with practice.db() as conn:
        rows = conn.execute('''SELECT p.id,p.name,p.category,p.summary,
            COUNT(f.id) AS fact_count,COALESCE(c.published,0) AS course_published
            FROM products p LEFT JOIN practice_learning_facts f ON f.product_id=p.id
            LEFT JOIN practice_learning_courses c ON c.product_id=p.id
            WHERE p.name LIKE ? OR p.category LIKE ?
            GROUP BY p.id ORDER BY p.sort_order,p.id LIMIT 100''', (term, term)).fetchall()
    return {'items': [dict(row) | {'course_published': bool(row['course_published'])}
                      for row in rows]}


def get_product_context(args):
    args = _object(args)
    product_id = _integer(args.get('product_id'), '产品编号', 1)
    with practice.db() as conn:
        product = conn.execute('SELECT id,name,category,summary FROM products WHERE id=?',
                               (product_id,)).fetchone()
        if not product:
            raise practice.PracticeError('产品不存在', 404)
        facts = conn.execute('''SELECT id,unit_no,title,body,source_url,status,version,updated_at
            FROM practice_learning_facts WHERE product_id=? ORDER BY unit_no''',
            (product_id,)).fetchall()
    return {'product': dict(product), 'facts': [dict(row) for row in facts]}


def create_question(args):
    args = _object(args)
    request_id = practice._request_id(args.get('request_id'))
    question = _object(args.get('question'), '题目')
    unknown = set(question) - _EDITABLE - {'stage_id'}
    if unknown:
        raise practice.PracticeError('不支持的题目字段：' + ', '.join(sorted(unknown)), 400)
    payload = {**question, 'enabled': question.get('enabled', False), 'request_id': request_id}
    result = practice.add_question(payload)
    with practice.db() as conn:
        return _question(conn, result['id'])


def update_question(args):
    args = _object(args)
    question_id = _integer(args.get('question_id'), '题目编号', 1)
    version = args.get('updated_at')
    if not isinstance(version, str) or not version:
        raise practice.PracticeError('请提供从 get_question 取得的 updated_at', 400)
    changes = _object(args.get('changes'), '修改内容')
    if not changes or set(changes) - _EDITABLE:
        raise practice.PracticeError('修改内容为空或包含不可修改字段', 400)
    with practice.db() as conn:
        current = _question(conn, question_id)
    practice.save_question(question_id, {**current, **changes, 'updated_at': version})
    with practice.db() as conn:
        return _question(conn, question_id)


def preview_csv(args):
    args = _object(args)
    _allow(args, ('stage_id', 'csv', 'weekly_new_import'))
    stage_id = _stage_id(args)
    if type(args.get('weekly_new_import', False)) is not bool:
        raise practice.PracticeError('每周新题标识无效', 400)
    data = {'stage_id': stage_id, 'csv': args.get('csv'), 'replace': False}
    if args.get('weekly_new_import', False):
        if not stage_id:
            raise practice.PracticeError('每周新题需要主题编号', 400)
        return weekly.preview_new(stage_id, data)
    return practice.preview_import(data)


def import_csv(args):
    args = _object(args)
    _allow(args, ('request_id', 'stage_id', 'csv', 'weekly_new_import'))
    stage_id = _stage_id(args)
    if type(args.get('weekly_new_import', False)) is not bool:
        raise practice.PracticeError('每周新题标识无效', 400)
    data = {'stage_id': stage_id, 'csv': args.get('csv'), 'replace': False,
            'request_id': practice._request_id(args.get('request_id'))}
    if args.get('weekly_new_import', False):
        if not stage_id:
            raise practice.PracticeError('每周新题需要主题编号', 400)
        return weekly.import_new(stage_id, data)
    return practice.import_bank(data)


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'additionalProperties': False}


TOOLS = [
    {'name': 'practice_bank_overview', 'description': '查看母题库、阶段/每周主题、关卡题量、可用分类与能力标签。',
     'inputSchema': _schema({}), 'handler': overview},
    {'name': 'practice_list_questions', 'description': '分页搜索题目摘要；省略 stage_id 搜索全部题库，stage_id=0 只搜母题库。',
     'inputSchema': _schema({'stage_id': {'type': 'integer'}, 'batch_no': {'type': 'integer'},
                             'enabled': {'type': 'boolean'}, 'keyword': {'type': 'string'},
                             'limit': {'type': 'integer'}, 'offset': {'type': 'integer'}}),
     'handler': list_questions},
    {'name': 'practice_get_question', 'description': '获取题目完整编辑内容、推荐答案和更新版本。',
     'inputSchema': _schema({'question_id': {'type': 'integer'}}, ('question_id',)),
     'handler': get_question},
    {'name': 'practice_list_products', 'description': '查找可关联题目的产品编号及已维护事实卡数量。',
     'inputSchema': _schema({'keyword': {'type': 'string'}}), 'handler': list_products},
    {'name': 'practice_get_product_context', 'description': '查看产品摘要与培训事实卡正文、来源、审核状态，供编写产品题时核对依据。',
     'inputSchema': _schema({'product_id': {'type': 'integer'}}, ('product_id',)),
     'handler': get_product_context},
    {'name': 'practice_learning_guidelines', 'description': '编写进阶题库前先调用：返回五级难度定义、7单元梯度、四选一出题规则、字段说明与审核流程。',
     'inputSchema': _schema({}), 'handler': learning_guidelines},
    {'name': 'practice_learning_outline', 'description': '在读取出题规则后调用：查看当前进阶主线的单元ID、独立录入的知识卡、题目安排和各级缺口。',
     'inputSchema': _schema({}), 'handler': learning_outline},
    {'name': 'practice_suggest_placement', 'description': '按五级出题规则提交学习目标、难度1–5与建议单元；难度须匹配单元，进入后台审核队列。',
     'inputSchema': _schema({'question_id': {'type': 'integer'}, 'unit_id': {'type': 'integer'},
                             'learning_objective': {'type': 'string'}, 'difficulty_level': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                             'rationale': {'type': 'string'}},
                            ('question_id', 'unit_id', 'learning_objective', 'difficulty_level')),
     'handler': suggest_placement},
    {'name': 'practice_create_question', 'description': '先读取 practice_learning_guidelines 与 practice_learning_outline，再创建一道符合目标单元难度的四选一题；默认停用，分级另提审核建议。request_id 防重。',
     'inputSchema': _schema({'request_id': {'type': 'string', 'description': '8–100位唯一请求标识'},
                             'question': _schema({
                                 'stage_id': {'type': 'integer', 'description': '默认0母题库'},
                                 'batch_no': {'type': 'integer'}, 'category': {'type': 'string'},
                                 'title': {'type': 'string'}, 'options': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 4, 'maxItems': 4},
                                 'answer_index': {'type': 'integer', 'description': '0=A，1=B，2=C，3=D'},
                                 'explanation': {'type': 'string'}, 'method': {'type': 'string'},
                                 'enabled': {'type': 'boolean'}, 'sources': {'type': 'array', 'items': {'type': 'string'}},
                                 'product_id': {'type': 'integer'}, 'skill_code': {'type': 'string'}, 'fact_id': {'type': 'integer'},
                             }, ('batch_no', 'category', 'title', 'options', 'answer_index', 'explanation', 'method'))},
                            ('request_id', 'question')), 'handler': create_question},
    {'name': 'practice_update_question', 'description': '按 updated_at 版本局部修改题目；须先 get_question，版本冲突时重新读取。',
     'inputSchema': _schema({'question_id': {'type': 'integer'}, 'updated_at': {'type': 'string'},
                             'changes': {'type': 'object', 'description': '可修改题干、选项、答案、解析、参考回答、启用状态等；不能改题库归属'}},
                            ('question_id', 'updated_at', 'changes')), 'handler': update_question},
    {'name': 'practice_preview_csv', 'description': '预检 CSV 批量新增/修改，不写库。每周主题新题可设 weekly_new_import=true。',
     'inputSchema': _schema({'stage_id': {'type': 'integer'}, 'csv': {'type': 'string'},
                             'weekly_new_import': {'type': 'boolean'}}, ('csv',)), 'handler': preview_csv},
    {'name': 'practice_import_csv', 'description': '按 CSV 原子批量新增/修改；须先预检。合并导入，不提供整库替换。',
     'inputSchema': _schema({'request_id': {'type': 'string'}, 'stage_id': {'type': 'integer'},
                             'csv': {'type': 'string'}, 'weekly_new_import': {'type': 'boolean'}},
                            ('request_id', 'csv')), 'handler': import_csv},
]

_HANDLERS = {tool['name']: tool['handler'] for tool in TOOLS}
_READ_ONLY = frozenset(('practice_bank_overview', 'practice_list_questions',
                        'practice_get_question', 'practice_list_products', 'practice_learning_guidelines',
                        'practice_learning_outline',
                        'practice_get_product_context', 'practice_preview_csv'))


def list_tools():
    return [{**{key: tool[key] for key in ('name', 'description', 'inputSchema')},
             'annotations': {'readOnlyHint': tool['name'] in _READ_ONLY}}
            for tool in TOOLS]


def call_tool(name, arguments):
    handler = _HANDLERS.get(name)
    if handler is None:
        raise KeyError(name)
    return json.dumps(handler(_object(arguments or {})), ensure_ascii=False, default=str)
