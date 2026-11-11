"""Question-bank MCP tools. All writes use the same validated admin services as the UI."""

import json
import csv
import io

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
    settings = data['settings']
    units = [{key: unit[key] for key in ('id', 'position', 'kind', 'title', 'level', 'question_ids')}
             for unit in data['units']]
    return {'settings': {'product_name': settings['product_name']} if settings else None,
            'units': units,
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
    data = {'stage_id': stage_id, 'csv': _course_safe_csv(args.get('csv')), 'replace': False}
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
    data = {'stage_id': stage_id, 'csv': _course_safe_csv(args.get('csv')), 'replace': False,
            'request_id': practice._request_id(args.get('request_id'))}
    if args.get('weekly_new_import', False):
        if not stage_id:
            raise practice.PracticeError('每周新题需要主题编号', 400)
        return weekly.import_new(stage_id, data)
    return practice.import_bank(data)


def _course_safe_csv(csv_text):
    """Reject proposed classifications and preserve existing approved fields on batch edits."""
    if not isinstance(csv_text, str):
        return csv_text  # The bank parser reports the malformed CSV.
    rows = list(csv.reader(io.StringIO(csv_text.lstrip('\ufeff'))))
    if not rows:
        return csv_text
    fields = {'学习目标', '难度等级', '建议单元ID'}
    removed = {i for i, name in enumerate(rows[0]) if name in fields}
    if any(any(i < len(row) and row[i].strip() for i in removed) for row in rows[1:]):
        raise practice.PracticeError('MCP批量导入不能填写课程分级；请用 practice_suggest_placement 提交待审核建议', 400)
    if not removed:
        return csv_text
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow([value for i, value in enumerate(row) if i not in removed])
    return output.getvalue()


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
    {'name': 'practice_learning_guidelines', 'description': '编写进阶题库前先调用：返回五级难度定义、7单元梯度、四选一出题规则、字段说明与审核流程。',
     'inputSchema': _schema({}), 'handler': learning_guidelines},
    {'name': 'practice_learning_outline', 'description': '在读取出题规则后调用：查看当前进阶主线的单元ID、已选题目和各级缺口。',
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
    {'name': 'practice_preview_csv', 'description': '预检 CSV 批量新增/修改，不写库；课程分级须走建议审核。每周主题新题可设 weekly_new_import=true。',
     'inputSchema': _schema({'stage_id': {'type': 'integer'}, 'csv': {'type': 'string'},
                             'weekly_new_import': {'type': 'boolean'}}, ('csv',)), 'handler': preview_csv},
    {'name': 'practice_import_csv', 'description': '按 CSV 原子批量新增/修改；须先预检。不能直接写课程分级或发布课程。',
     'inputSchema': _schema({'request_id': {'type': 'string'}, 'stage_id': {'type': 'integer'},
                             'csv': {'type': 'string'}, 'weekly_new_import': {'type': 'boolean'}},
                            ('request_id', 'csv')), 'handler': import_csv},
]

_HANDLERS = {tool['name']: tool['handler'] for tool in TOOLS}
_READ_ONLY = frozenset(('practice_bank_overview', 'practice_list_questions',
                        'practice_get_question', 'practice_learning_guidelines',
                        'practice_learning_outline', 'practice_preview_csv'))


def list_tools():
    return [{**{key: tool[key] for key in ('name', 'description', 'inputSchema')},
             'annotations': {'readOnlyHint': tool['name'] in _READ_ONLY}}
            for tool in TOOLS]


def call_tool(name, arguments):
    handler = _HANDLERS.get(name)
    if handler is None:
        raise KeyError(name)
    return json.dumps(handler(_object(arguments or {})), ensure_ascii=False, default=str)
