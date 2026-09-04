import os
import json
import html
import time
from urllib.parse import urljoin
from flask import Flask, jsonify, request, make_response, render_template, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

DEFAULT_TIPS = [
    "试试问我：你的产品有什么功效？",
    "我可以帮你写朋友圈文案，试试说：帮我写一条产品推广朋友圈",
    "关注资讯栏目，获取最新产品动态",
    "试试问我：输入'热门问题'，看看大家都在问什么",
    "我可以帮你解答产品使用中的各种疑问",
    "试试问我：你们的产品怎么使用？",
    "我还能帮你写口播文案，试试说：帮我写一段产品介绍",
    "快速了解产品：试试问我产品的主要成分",
]
DEFAULT_STEPS = [
    "正在理解您的问题...",
    "正在匹配最佳智能体...",
    "正在检索产品知识库...",
    "正在分析问题关键点...",
    "正在构思回答框架...",
    "正在组织语言表达...",
    "正在校验回答准确性...",
    "正在润色语言风格...",
    "正在生成完整回复...",
    "即将完成...",
]
DEFAULT_EXAMPLE_QUESTIONS = [
    {'text': '这个产品适合什么人？', 'agent_id': 'aura'},
    {'text': '产品应该怎么使用？', 'agent_id': 'coder'},
    {'text': '帮我推荐一个产品方案', 'agent_id': 'aura'},
    {'text': '帮我写一段客户沟通话术', 'agent_id': 'translator'},
]
from flask_cors import CORS
from config import Config
from models import init_db, get_setting, resolve_question_bindings, MAX_PRESET_EXAMPLE_QUESTIONS
from services.content_security import sanitize_media_url
from services.handoff_service import start_handoff_reconciler
from services.security_service import (
    build_rate_limited_response,
    check_request_budget,
    classify_client,
)
from routes.auth import auth_bp, token_required
from routes.chat import chat_bp
from routes.history import history_bp
from routes.news import news_bp
from routes.products import products_bp
from routes.community import community_bp
from routes.survey import survey_bp
from routes.admin import admin_bp
from routes.agents import agents_bp
from routes.dashboard import dashboard_bp
from routes.cases import cases_bp
from routes.share import share_bp
from routes.speech import speech_bp
from routes.leads import leads_bp
from routes.handoff import handoff_bp
from routes.admin_handoff import admin_handoff_bp
from routes.ai_review import ai_review_bp
from routes.nutritionist_notes import nutritionist_notes_bp

app = Flask(__name__, static_folder='static', static_url_path='')
Config.validate()
app.config.from_object(Config)
if Config.TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
if Config.CORS_ORIGINS:
    CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}})

os.makedirs(Config.UPLOAD_DIR, exist_ok=True)

init_db()
from services.secret_service import migrate_plaintext_secrets
migrate_plaintext_secrets()
start_handoff_reconciler()

_CRAWL_GUARD_LIMITS = {
    'browser': Config.CRAWL_GUARD_BROWSER_PER_MIN,
    'wechat': Config.CRAWL_GUARD_WECHAT_PER_MIN,
    'crawler': Config.CRAWL_GUARD_CRAWLER_PER_MIN,
    'script': Config.CRAWL_GUARD_SCRIPT_PER_MIN,
}

ROBOTS_TXT = """User-agent: *
Allow: /
Disallow: /admin
Disallow: /consultant
Disallow: /api/
Disallow: /uploads/
"""

@app.before_request
def crawl_guard():
    """Per-IP budget for API calls, tiered by client type.

    Static assets are intentionally untouched so CDN caching keeps working.
    This is process-local: on multi-worker deploys keep the edge (Nginx/CDN)
    limit as the outer layer.
    """
    if not Config.CRAWL_GUARD_ENABLED or not request.path.startswith('/api/'):
        return None
    client_type = classify_client(request.headers.get('User-Agent', ''))
    limit = max(1, _CRAWL_GUARD_LIMITS.get(client_type, Config.CRAWL_GUARD_SCRIPT_PER_MIN))
    subject = request.remote_addr or 'unknown'
    allowed, retry_after = check_request_budget(f'crawl-guard:{subject}', limit, 60)
    if allowed:
        return None
    if client_type in ('crawler', 'script'):
        app.logger.warning(
            'crawl guard: client_type=%s ip=%s path=%s limit=%s',
            client_type, subject, request.path, limit,
        )
    if Config.CRAWL_GUARD_ENFORCE:
        return build_rate_limited_response(retry_after)
    return None


@app.route('/robots.txt')
def robots_txt():
    response = make_response(ROBOTS_TXT)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response


app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(chat_bp, url_prefix='/api/chat')
app.register_blueprint(history_bp, url_prefix='/api/history')
app.register_blueprint(news_bp, url_prefix='/api/news')
app.register_blueprint(products_bp, url_prefix='/api/products')
app.register_blueprint(community_bp, url_prefix='/api/community')
app.register_blueprint(survey_bp, url_prefix='/api/survey')
app.register_blueprint(admin_bp, url_prefix='/api/admin')
app.register_blueprint(agents_bp, url_prefix='/api/agents')
app.register_blueprint(dashboard_bp, url_prefix='/api/admin/dashboard')
app.register_blueprint(cases_bp, url_prefix='/api')
app.register_blueprint(share_bp, url_prefix='/api')
app.register_blueprint(speech_bp, url_prefix='/api/speech')
app.register_blueprint(leads_bp, url_prefix='/api/leads')
app.register_blueprint(handoff_bp, url_prefix='/api/handoff')
app.register_blueprint(admin_handoff_bp, url_prefix='/api/admin/handoff')
app.register_blueprint(ai_review_bp, url_prefix='/api/admin/ai-review')
app.register_blueprint(nutritionist_notes_bp, url_prefix='/api/nutritionist-notes')


@app.after_request
def add_cache_headers(response):
    path = request.path.lower()
    if path.endswith('.html') or path in ('/', '/admin'):
        response.headers['Cache-Control'] = 'no-cache'
    elif path.startswith('/uploads/'):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif path.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico')):
        response.headers['Cache-Control'] = 'public, max-age=604800'
    elif path.endswith(('.css', '.js')):
        response.headers['Cache-Control'] = 'public, max-age=86400'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), geolocation=(), microphone=(self)'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://html2canvas.hertzen.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; connect-src 'self' wss://asr.cloud.tencent.com; "
        "media-src 'self' blob:; worker-src 'self' blob:"
    )
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # 后台与数据接口不进搜索引擎索引；首页保持可索引，微信分享卡片依赖其 og 标签。
    if path.startswith(('/admin', '/consultant', '/api/')):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive, nosnippet'
    return response



_INDEX_PAGE_CACHE = {}
_INDEX_PAGE_CACHE_TTL = 5
_INDEX_PAGE_CACHE_MAX = 8

@app.route('/')
@app.route('/index.html')
def index():
    cache_key = request.host
    now = time.monotonic()
    cached = _INDEX_PAGE_CACHE.get(cache_key)
    if cached and now - cached[0] < _INDEX_PAGE_CACHE_TTL:
        document = cached[1]
    else:
        with open(os.path.join(Config.BASE_DIR, 'static', 'index.html'), encoding='utf-8') as file_obj:
            document = file_obj.read()

        title = (get_setting('share_title', 'AI宝儿智能体') or 'AI宝儿智能体').strip()[:80]
        description = (get_setting('share_description', '产品咨询、使用答疑与健康问题解答') or '').strip()[:200]
        image_url = sanitize_media_url(get_setting('share_image_url', '/avatar-optimized.png')) or '/avatar-optimized.png'
        absolute_image_url = urljoin(request.url_root, image_url.lstrip('/'))
        absolute_page_url = request.base_url

        replacements = {
            '<title>AI宝儿智能体</title>': f'<title>{html.escape(title)}</title>',
            '<meta name="description" content="产品咨询、使用答疑与健康问题解答">': f'<meta name="description" content="{html.escape(description, quote=True)}">',
            '<meta property="og:site_name" content="AI宝儿智能体">': f'<meta property="og:site_name" content="{html.escape(title, quote=True)}">',
            '<meta property="og:title" content="AI宝儿智能体">': f'<meta property="og:title" content="{html.escape(title, quote=True)}">',
            '<meta property="og:description" content="产品咨询、使用答疑与健康问题解答">': f'<meta property="og:description" content="{html.escape(description, quote=True)}">',
            '<meta property="og:image" content="/avatar-optimized.png">': f'<meta property="og:image" content="{html.escape(absolute_image_url, quote=True)}">',
            '<meta property="og:url" content="/">': f'<meta property="og:url" content="{html.escape(absolute_page_url, quote=True)}">',
            '<meta name="twitter:title" content="AI宝儿智能体">': f'<meta name="twitter:title" content="{html.escape(title, quote=True)}">',
            '<meta name="twitter:description" content="产品咨询、使用答疑与健康问题解答">': f'<meta name="twitter:description" content="{html.escape(description, quote=True)}">',
            '<meta name="twitter:image" content="/avatar-optimized.png">': f'<meta name="twitter:image" content="{html.escape(absolute_image_url, quote=True)}">',
        }
        for old, new_value in replacements.items():
            document = document.replace(old, new_value)

        if len(_INDEX_PAGE_CACHE) >= _INDEX_PAGE_CACHE_MAX:
            _INDEX_PAGE_CACHE.pop(next(iter(_INDEX_PAGE_CACHE)))
        _INDEX_PAGE_CACHE[cache_key] = (now, document)

    response = make_response(document)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response


@app.route('/admin')
def admin_page():
    return render_template('admin.html')


@app.route('/consultant')
def consultant_page():
    return render_template('consultant.html')


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(Config.UPLOAD_DIR, filename)

@app.route('/api/waiting-content')
def waiting_content():
    raw_tips = get_setting('waiting_tips', '[]')
    raw_steps = get_setting('waiting_steps', '[]')
    try: tips = json.loads(raw_tips)
    except (TypeError, ValueError): tips = []
    try: steps = json.loads(raw_steps)
    except (TypeError, ValueError): steps = []
    if not tips: tips = DEFAULT_TIPS
    if not steps: steps = DEFAULT_STEPS
    return jsonify({'tips': tips, 'steps': steps})

@app.route('/api/example-questions')
def example_questions():
    raw = get_setting('example_questions', '[]')
    questions = resolve_question_bindings(raw, limit=MAX_PRESET_EXAMPLE_QUESTIONS)
    if not questions:
        questions = resolve_question_bindings(DEFAULT_EXAMPLE_QUESTIONS, limit=MAX_PRESET_EXAMPLE_QUESTIONS)
    return jsonify({'questions': questions})

@app.route('/api/default-team')
def default_team():
    raw = get_setting('default_team_names', '[]')
    try:
        teams = json.loads(raw)
        if not isinstance(teams, list):
            teams = []
    except (TypeError, ValueError):
        teams = []
    if not teams:
        single = get_setting('default_team_name', '').strip()
        if single:
            teams = [single]
    return jsonify({'team_names': teams})

@app.route('/api/case-library-config')
def case_library_config():
    return jsonify({'case_library_url': get_setting('case_library_url', '')})

@app.route('/api/user/profile')
@token_required
def user_profile(current_user):
    return jsonify({
        'user_id': current_user['user_id'],
        'username': current_user['username'],
        'is_admin': current_user.get('is_admin', 0),
        'created_at': current_user['created_at']
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5001)
