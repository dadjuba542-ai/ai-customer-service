"""统一功能开关（feature flags）——案例系统 / 人工客服系统。

一个开关 = 名字 + settings 表 key + 环境变量 + 代码默认值，全部登记在下面的
``FLAGS`` 注册表里，新增开关只需要在这里加一行。

取值优先级（先命中者生效）::

    settings 表（后台「功能开关」页改过） > 环境变量 > 注册表里的 default

读取状态::

    from services import feature_flags
    if feature_flags.is_enabled('cases'):
        ...

写入状态（后台管理入口 / 脚本）::

    feature_flags.set_enabled('handoff', False)

关闭时三层拦截，缺一不可:

1. HTTP 入口：``install_request_guard(app)`` 按 FLAGS 里的 routes 前缀统一拦截，
   各 blueprint 再用 ``guard_request()`` 兜底（防路径前缀漏配）。
2. 调用链路：服务层自己判断一次（见 chat_service / handoff_service），
   避免内部调用或后台任务绕过 HTTP 层。
3. 定时任务：handoff 的派单线程在开关关闭时不启动 / 空转。
"""
import os

from flask import jsonify, request

from config import Config
from models import get_setting, set_setting

# 开关名字常量：其它模块请引用常量，不要到处写字符串字面量。
CASES_SYSTEM = 'cases'
HANDOFF_SYSTEM = 'handoff'

_TRUE_VALUES = {'1', 'true', 'yes', 'on'}
_UNSET = object()

_CASES_ROUTES = (
    '/api/cases',
    '/api/admin/cases',
    '/api/admin/case-tags',
    '/api/case-library-config',
)

_HANDOFF_ROUTES = (
    '/api/handoff',
    '/api/admin/handoff',
    '/consultant',
)

# 人工系统关闭时仍可访问：前台靠它拿到 enabled=false 来决定是否展示转人工入口。
_HANDOFF_ROUTE_EXEMPT = ('/api/handoff/config',)

_DISABLED_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
         background:#F8FAFC; color:#0F172A; }}
  .box {{ max-width:420px; padding:32px 28px; background:#fff; border-radius:16px;
          box-shadow:0 10px 30px rgba(15,23,42,.08); text-align:center; }}
  h1 {{ font-size:18px; margin:0 0 12px; }}
  p {{ font-size:14px; line-height:1.7; color:#475569; margin:0; }}
</style></head>
<body><div class="box"><h1>{title}</h1><p>{detail}</p></div></body>
</html>"""


class FeatureFlagError(Exception):
    """开关值非法或开关不存在。"""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class FeatureFlag:
    """单个功能开关的定义与状态读取。"""

    def __init__(self, name, key, env, default, label, description,
                 routes=(), route_exempt=(), on_change=None):
        self.name = name
        self.key = key
        self.env = env
        self.default = bool(default)
        self.label = label
        self.description = description
        self.routes = tuple(routes)
        self.route_exempt = tuple(route_exempt)
        self.on_change = on_change

    # ---- 状态读取 -------------------------------------------------------
    def resolve(self):
        """返回 (enabled, source)，source 说明这个状态是哪儿来的。"""
        stored = get_setting(self.key, _UNSET)
        if stored is not _UNSET:
            return str(stored).strip().lower() in _TRUE_VALUES, 'database'
        if self.env:
            raw = os.environ.get(self.env)
            if raw is not None and str(raw).strip() != '':
                return str(raw).strip().lower() in _TRUE_VALUES, 'environment'
        return self.default, 'default'

    def is_enabled(self):
        return self.resolve()[0]

    def state(self):
        enabled, source = self.resolve()
        return {
            'name': self.name,
            'label': self.label,
            'description': self.description,
            'enabled': enabled,
            'source': source,
            'default': self.default,
            'setting_key': self.key,
            'env_var': self.env or '',
            'routes': list(self.routes),
        }

    def public_state(self):
        """给前台用的最小信息，不暴露 key / 路由等内部细节。"""
        return {
            'name': self.name,
            'label': self.label,
            'enabled': self.is_enabled(),
        }

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        set_setting(self.key, '1' if enabled else '0')
        if self.on_change:
            self.on_change(enabled)
        return enabled


def _handoff_on_change(enabled):
    """人工客服系统打开时补启动派单线程（启动时是关闭状态的话不会起）。"""
    if not enabled:
        return
    try:
        from services.handoff_service import start_handoff_reconciler
        start_handoff_reconciler()
    except Exception:  # pragma: no cover - 启动失败不能影响开关本身
        pass


def _handoff_validate(enabled):
    """沿用原有业务约束：开启人工客服必须先配好营养咨询 AI 智能体。"""
    if not enabled:
        return
    from services.handoff_service import get_handoff_settings
    if not (get_handoff_settings().get('ai_agent_id') or '').strip():
        raise FeatureFlagError(
            '启用人工客服系统前，请先在「AI 与转接设置」里选择营养咨询 AI 智能体',
            status_code=400,
        )


FLAGS = {
    CASES_SYSTEM: FeatureFlag(
        name=CASES_SYSTEM,
        key='cases_enabled',
        env='CASES_ENABLED',
        default=Config.CASES_ENABLED,
        label='案例系统',
        description='案例档案库：AI 回答的相关案例推荐、前台案例抽屉、后台案例与标签管理、链接识别入库。',
        routes=_CASES_ROUTES,
    ),
    HANDOFF_SYSTEM: FeatureFlag(
        name=HANDOFF_SYSTEM,
        key='handoff_enabled',
        env='HANDOFF_ENABLED',
        default=Config.HANDOFF_ENABLED,
        label='人工客服系统',
        description='AI 转人工营养咨询：转接/留言、坐席工作台、后台队列与坐席管理、派单定时任务。',
        routes=_HANDOFF_ROUTES,
        route_exempt=_HANDOFF_ROUTE_EXEMPT,
        on_change=_handoff_on_change,
    ),
}

_VALIDATORS = {
    HANDOFF_SYSTEM: _handoff_validate,
}


def get_flag(name):
    flag = FLAGS.get(str(name or '').strip())
    if not flag:
        raise FeatureFlagError(f'未知的功能开关: {name}', status_code=404)
    return flag


def is_enabled(name):
    """判断开关是否开启；未知开关按关闭处理，避免拼错名字反而放行。"""
    flag = FLAGS.get(str(name or '').strip())
    if not flag:
        return False
    return flag.is_enabled()


def default_enabled(name):
    return get_flag(name).default


def state_of(name):
    return get_flag(name).state()


def list_states():
    return [flag.state() for flag in FLAGS.values()]


def public_states():
    return {flag.name: flag.public_state() for flag in FLAGS.values()}


def set_enabled(name, enabled):
    flag = get_flag(name)
    validator = _VALIDATORS.get(flag.name)
    if validator:
        validator(bool(enabled))
    flag.set_enabled(enabled)
    return flag.state()


# ---- HTTP 层拦截 ---------------------------------------------------------

def _path_matches(prefixes, path):
    normalized = (path or '').rstrip('/') or '/'
    for prefix in prefixes:
        base = prefix.rstrip('/')
        if not base:
            continue
        if normalized == base or normalized.startswith(base + '/'):
            return True
    return False


def disabled_response(flag):
    """开关关闭时的统一响应：/api/ 给 JSON，页面给一个说明页。"""
    message = f'{flag.label}当前已关闭'
    if (request.path or '').startswith('/api/'):
        return jsonify({
            'error': message,
            'code': 'feature_disabled',
            'feature': flag.name,
            'enabled': False,
        }), 403
    body = _DISABLED_HTML.format(
        title=message,
        detail='该功能已由管理员关闭。如需使用，请联系管理员在后台「功能开关」中重新开启。',
    )
    return body, 403, {'Content-Type': 'text/html; charset=utf-8'}


def guard_request(name):
    """blueprint 级兜底：命中开关且未豁免就返回 403，否则返回 None。"""
    flag = get_flag(name)
    if flag.is_enabled():
        return None
    if _path_matches(flag.route_exempt, request.path):
        return None
    return disabled_response(flag)


def install_request_guard(app):
    """注册全局 before_request，按 FLAGS 登记的路径前缀拦截已关闭的系统。"""

    @app.before_request
    def _feature_flag_guard():
        if request.method == 'OPTIONS':
            return None
        path = request.path
        # 先做路径匹配再查库：普通请求（含静态资源）不产生额外查询。
        for flag in FLAGS.values():
            if not _path_matches(flag.routes, path):
                continue
            if _path_matches(flag.route_exempt, path):
                return None
            return None if flag.is_enabled() else disabled_response(flag)
        return None

    return _feature_flag_guard
