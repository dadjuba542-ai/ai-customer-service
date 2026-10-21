import os

class Config:
    BASE_DIR = os.path.dirname(__file__)
    APP_VERSION = (os.environ.get('APP_VERSION')
                   or os.environ.get('RAILWAY_GIT_COMMIT_SHA')
                   or os.environ.get('ZEABUR_GIT_COMMIT_SHA')
                   or 'dev')
    SECRET_KEY = os.environ.get('SECRET_KEY', '')
    COZE_API_URL = os.environ.get('COZE_API_URL', 'https://api.coze.cn/open_api/v2/chat')
    COZE_V3_CHAT_URL = os.environ.get('COZE_V3_CHAT_URL', 'https://api.coze.cn/v3/chat')
    COZE_CHAT_API_VERSION = os.environ.get('COZE_CHAT_API_VERSION', 'v3').strip().lower()
    COZE_DIAGNOSTICS_ENABLED = os.environ.get('COZE_DIAGNOSTICS_ENABLED', 'false').lower() == 'true'
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
    # 全局请求体上限需容纳音频上传（图片接口仍单独限制 8MB）
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 52 * 1024 * 1024))
    AUDIO_MAX_UPLOAD_BYTES = max(1, int(os.environ.get('AUDIO_MAX_UPLOAD_BYTES', 50 * 1024 * 1024)))
    CHAT_RATE_LIMIT = int(os.environ.get('CHAT_RATE_LIMIT', '12'))
    # 单次聊天（含空召回改写/重查）的总时限，必须小于 nginx/gunicorn 超时。
    CHAT_TOTAL_TIMEOUT_SECONDS = max(30, int(os.environ.get('CHAT_TOTAL_TIMEOUT_SECONDS', '150')))
    # 等待上游时向前端发送 SSE 心跳的间隔，避免反代按读空闲超时断流。
    CHAT_STREAM_HEARTBEAT_SECONDS = max(1, int(os.environ.get('CHAT_STREAM_HEARTBEAT_SECONDS', '15')))
    # 空召回时，首次 Coze 调用超过该秒数则跳过改写重查，直接返回补充信息提示。
    CHAT_REWRITE_MAX_INITIAL_SECONDS = max(0, int(os.environ.get('CHAT_REWRITE_MAX_INITIAL_SECONDS', '30')))
    CHAT_STREAM_MAX_CONCURRENT_PER_WORKER = max(
        1,
        int(os.environ.get('CHAT_STREAM_MAX_CONCURRENT_PER_WORKER', '3')),
    )
    CHAT_QUEUE_MAX_SIZE = max(1, int(os.environ.get('CHAT_QUEUE_MAX_SIZE', '10')))
    CHAT_QUEUE_TTL_SECONDS = max(60, int(os.environ.get('CHAT_QUEUE_TTL_SECONDS', '300')))
    CHAT_QUEUE_POLL_INTERVAL_SECONDS = max(1, int(os.environ.get('CHAT_QUEUE_POLL_INTERVAL_SECONDS', '2')))
    # 随每次提问带回 Coze 的多轮上下文轮数（1 轮 = 1 问 1 答）；0 表示关闭
    CHAT_CONTEXT_ROUNDS = max(0, int(os.environ.get('CHAT_CONTEXT_ROUNDS', '6')))
    # 单条历史消息截断上限，避免上下文过大
    CHAT_CONTEXT_MESSAGE_MAX_CHARS = max(0, int(os.environ.get('CHAT_CONTEXT_MESSAGE_MAX_CHARS', '2000')))
    # 仅 V2 回退使用：query 拼历史问题，history 使用原生历史字段；V3 始终使用原生消息。
    CHAT_CONTEXT_DELIVERY = os.environ.get('CHAT_CONTEXT_DELIVERY', 'query').strip().lower()
    SPEECH_RATE_LIMIT = int(os.environ.get('SPEECH_RATE_LIMIT', '20'))
    # 只读 MCP 端点（/api/mcp）的 Bearer token；留空则端点关闭
    MCP_TOKEN = os.environ.get('MCP_TOKEN', '')
    SPEECH_REALTIME_SESSION_LIMIT = int(os.environ.get('SPEECH_REALTIME_SESSION_LIMIT', '20'))
    # 功能开关默认值（运行时状态以 settings 表为准，详见 services/feature_flags.py）
    CASES_ENABLED = os.environ.get('CASES_ENABLED', 'true').lower() == 'true'
    AUDIO_COURSES_ENABLED = os.environ.get('AUDIO_COURSES_ENABLED', 'false').lower() == 'true'
    HANDOFF_ENABLED = os.environ.get('HANDOFF_ENABLED', 'false').lower() == 'true'
    PRACTICE_ENABLED = os.environ.get('PRACTICE_ENABLED', 'false').lower() == 'true'
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

    # 反爬：按客户端类型分级限流（仅作用于 /api/ 路径，静态资源不受影响）
    CRAWL_GUARD_ENABLED = os.environ.get('CRAWL_GUARD_ENABLED', 'true').lower() == 'true'
    CRAWL_GUARD_BROWSER_PER_MIN = int(os.environ.get('CRAWL_GUARD_BROWSER_PER_MIN', '180'))
    CRAWL_GUARD_WECHAT_PER_MIN = int(os.environ.get('CRAWL_GUARD_WECHAT_PER_MIN', '180'))
    CRAWL_GUARD_CRAWLER_PER_MIN = int(os.environ.get('CRAWL_GUARD_CRAWLER_PER_MIN', '20'))
    CRAWL_GUARD_SCRIPT_PER_MIN = int(os.environ.get('CRAWL_GUARD_SCRIPT_PER_MIN', '30'))
    # 被限流时是否直接拒绝。false = 仅记录日志观察，不改响应（灰度用）
    CRAWL_GUARD_ENFORCE = os.environ.get('CRAWL_GUARD_ENFORCE', 'true').lower() == 'true'

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
        if cls.COZE_CHAT_API_VERSION not in {'v2', 'v3'}:
            raise RuntimeError('COZE_CHAT_API_VERSION must be v2 or v3')
        if cls.CHAT_CONTEXT_DELIVERY not in {'query', 'history'}:
            raise RuntimeError('CHAT_CONTEXT_DELIVERY must be query or history')
        if cls.CHAT_TOTAL_TIMEOUT_SECONDS <= cls.CHAT_STREAM_HEARTBEAT_SECONDS:
            raise RuntimeError('CHAT_TOTAL_TIMEOUT_SECONDS must be greater than CHAT_STREAM_HEARTBEAT_SECONDS')
        if len(cls.SECRET_KEY) < 32:
            raise RuntimeError('SECRET_KEY is required and must contain at least 32 characters')
        if '*' in cls.CORS_ORIGINS:
            raise RuntimeError('CORS_ORIGINS cannot contain *; configure explicit trusted origins')
