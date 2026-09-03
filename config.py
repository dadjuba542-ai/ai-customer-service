import os

class Config:
    BASE_DIR = os.path.dirname(__file__)
    SECRET_KEY = os.environ.get('SECRET_KEY', '')
    COZE_API_URL = os.environ.get('COZE_API_URL', 'https://api.coze.cn/open_api/v2/chat')
    COZE_V3_CHAT_URL = os.environ.get('COZE_V3_CHAT_URL', 'https://api.coze.cn/v3/chat')
    COZE_FILE_UPLOAD_URL = os.environ.get('COZE_FILE_UPLOAD_URL', 'https://api.coze.cn/v1/files/upload')
    COZE_API_KEY = os.environ.get('COZE_API_KEY', '')
    DATABASE_DIR = os.environ.get('DATABASE_DIR', BASE_DIR)
    DATABASE_PATH = os.path.join(DATABASE_DIR, 'ai_customer_service.db')
    UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(BASE_DIR, 'static', 'uploads'))
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get('CORS_ORIGINS', '').split(',')
        if origin.strip()
    ]
    TRUST_PROXY = os.environ.get('TRUST_PROXY', 'false').lower() == 'true'
    PUBLIC_REGISTRATION_ENABLED = os.environ.get('PUBLIC_REGISTRATION_ENABLED', 'false').lower() == 'true'
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 12 * 1024 * 1024))
    CHAT_RATE_LIMIT = int(os.environ.get('CHAT_RATE_LIMIT', '12'))
    CHAT_STREAM_MAX_CONCURRENT_PER_WORKER = max(
        1,
        int(os.environ.get('CHAT_STREAM_MAX_CONCURRENT_PER_WORKER', '3')),
    )
    CHAT_QUEUE_MAX_SIZE = max(1, int(os.environ.get('CHAT_QUEUE_MAX_SIZE', '10')))
    CHAT_QUEUE_TTL_SECONDS = max(60, int(os.environ.get('CHAT_QUEUE_TTL_SECONDS', '300')))
    CHAT_QUEUE_POLL_INTERVAL_SECONDS = max(1, int(os.environ.get('CHAT_QUEUE_POLL_INTERVAL_SECONDS', '2')))
    SPEECH_RATE_LIMIT = int(os.environ.get('SPEECH_RATE_LIMIT', '20'))
    SPEECH_REALTIME_SESSION_LIMIT = int(os.environ.get('SPEECH_REALTIME_SESSION_LIMIT', '20'))
    HANDOFF_ENABLED = os.environ.get('HANDOFF_ENABLED', 'false').lower() == 'true'
    HANDOFF_AI_AGENT_ID = os.environ.get('HANDOFF_AI_AGENT_ID', '')
    HANDOFF_AVG_HANDLE_SEC = max(30, int(os.environ.get('HANDOFF_AVG_HANDLE_SEC', '180')))
    HANDOFF_QUEUE_POLL_SEC = max(2, int(os.environ.get('HANDOFF_QUEUE_POLL_SEC', '4')))
    HANDOFF_AGENT_STALE_SEC = max(30, int(os.environ.get('HANDOFF_AGENT_STALE_SEC', '90')))
    HANDOFF_CLAIM_TIMEOUT_SEC = max(30, int(os.environ.get('HANDOFF_CLAIM_TIMEOUT_SEC', '60')))
    HANDOFF_LIVE_WAIT_SEC = max(30, int(os.environ.get('HANDOFF_LIVE_WAIT_SEC', '600')))
    HANDOFF_RECONCILE_INTERVAL_SECONDS = max(2, int(os.environ.get('HANDOFF_RECONCILE_INTERVAL_SECONDS', '5')))
    # 留言模式空闲自动归档阈值（秒）：留言会话在最后一次消息后超过该时长无新消息即自动关闭
    HANDOFF_MESSAGE_IDLE_SEC = max(60, int(os.environ.get('HANDOFF_MESSAGE_IDLE_SEC', str(24 * 3600))))

    # 聊天记录保留与启动清理
    CLEANUP_ON_STARTUP = os.environ.get('CLEANUP_ON_STARTUP', 'false').lower() == 'true'
    CHAT_RETENTION_DAYS = max(1, int(os.environ.get('CHAT_RETENTION_DAYS', '30')))

    # 四大模块对应的机器人ID
    BOT_MAPPING = {
        '产品咨询': os.environ.get('BOT_PRODUCT', '7595022659508125738'),
        '使用答疑': os.environ.get('BOT_FAQ', '7595022659508125738'),
        '朋友圈帮写': os.environ.get('BOT_MOMENT', '7594631042351644715'),
        '口播文案帮写': os.environ.get('BOT_SCRIPT', '7630704938662363162'),
    }

    DEFAULT_BOT_ID = os.environ.get('BOT_PRODUCT', '7595022659508125738')

    # 仅保留旧环境兼容配置；不会再通过用户名自动提权。
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin8')

    @classmethod
    def validate(cls):
        if len(cls.SECRET_KEY) < 32:
            raise RuntimeError('SECRET_KEY is required and must contain at least 32 characters')
        if '*' in cls.CORS_ORIGINS:
            raise RuntimeError('CORS_ORIGINS cannot contain *; configure explicit trusted origins')
