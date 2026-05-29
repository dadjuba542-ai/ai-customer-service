import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', '')
    COZE_API_URL = os.environ.get('COZE_API_URL', 'https://api.coze.cn/open_api/v2/chat')
    COZE_API_KEY = os.environ.get('COZE_API_KEY', '')
    DATABASE_DIR = os.environ.get('DATABASE_DIR', os.path.dirname(__file__))
    DATABASE_PATH = os.path.join(DATABASE_DIR, 'ai_customer_service.db')
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*')
    STRICT_SECURITY = os.environ.get('STRICT_SECURITY', 'false').lower() == 'true'
    HIDE_ADMIN_API_KEY = os.environ.get('HIDE_ADMIN_API_KEY', 'false').lower() == 'true'

    # 四大模块对应的机器人ID
    BOT_MAPPING = {
        '产品咨询': os.environ.get('BOT_PRODUCT', '7595022659508125738'),
        '使用答疑': os.environ.get('BOT_FAQ', '7595022659508125738'),
        '朋友圈帮写': os.environ.get('BOT_MOMENT', '7594631042351644715'),
        '口播文案帮写': os.environ.get('BOT_SCRIPT', '7630704938662363162'),
    }

    DEFAULT_BOT_ID = os.environ.get('BOT_PRODUCT', '7595022659508125738')

    # 管理员账号：用该用户名注册的用户自动成为管理员
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin8')

    @classmethod
    def validate(cls):
        if cls.STRICT_SECURITY and not cls.SECRET_KEY:
            raise RuntimeError('SECRET_KEY is required and cannot be empty')
