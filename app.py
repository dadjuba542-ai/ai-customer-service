import os
import json
from flask import Flask, jsonify, send_from_directory, render_template

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
from flask_cors import CORS
from config import Config
from models import init_db
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.history import history_bp
from routes.news import news_bp
from routes.products import products_bp
from routes.community import community_bp
from routes.survey import survey_bp
from routes.admin import admin_bp
from routes.agents import agents_bp
from routes.dashboard import dashboard_bp

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)
app.config.from_object(Config)

os.makedirs(os.path.join(app.root_path, 'static', 'uploads'), exist_ok=True)

init_db()

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

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/waiting-content')
def waiting_content():
    from models import get_setting
    import json
    raw_tips = get_setting('waiting_tips', '[]')
    raw_steps = get_setting('waiting_steps', '[]')
    try: tips = json.loads(raw_tips)
    except: tips = []
    try: steps = json.loads(raw_steps)
    except: steps = []
    if not tips: tips = DEFAULT_TIPS
    if not steps: steps = DEFAULT_STEPS
    return jsonify({'tips': tips, 'steps': steps})

@app.route('/api/user/profile')
def user_profile():
    from routes.auth import token_required
    from flask import request

    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'error': 'Token is missing'}), 401

    try:
        import jwt
        if token.startswith('Bearer '):
            token = token[7:]
        data = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        from models import get_user_by_id
        user = get_user_by_id(data['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 401
        return jsonify({
            'user_id': user['user_id'],
            'username': user['username'],
            'is_admin': user.get('is_admin', 0),
            'created_at': user['created_at']
        })
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Token has expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5001)
