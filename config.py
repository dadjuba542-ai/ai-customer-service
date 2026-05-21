import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
    COZE_API_URL = os.environ.get('COZE_API_URL', 'https://api.coze.cn/open_api/v2/chat')
    COZE_API_KEY = os.environ.get('COZE_API_KEY', 'pat_B83Mnn2UsbEf8jc7R5MCGY4uaWI5Obz5xIFjjCVCG8kcJCyZcBYkTHhjDDIz0jQI')
    DATABASE_DIR = os.environ.get('DATABASE_DIR', os.path.dirname(__file__))
    DATABASE_PATH = os.path.join(DATABASE_DIR, 'ai_customer_service.db')

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
