import requests
from flask import Blueprint, request, jsonify
from config import Config
from models import save_chat_history, get_setting, get_agent_config

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/send', methods=['POST'])
def send_to_coze():
    data = request.get_json()
    message = data.get('message')
    query_type = data.get('query_type', '其他')
    agent_id = data.get('agent_id', '')

    if not message:
        return jsonify({'error': 'Message is required'}), 400

    user_id = 'anonymous'
    api_key = get_setting('coze_api_key', Config.COZE_API_KEY)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    # 优先使用智能体自身的 bot_id，否则按 query_type 查映射
    bot_id = ''
    if agent_id:
        agent = get_agent_config(agent_id)
        if agent and agent.get('bot_id'):
            bot_id = agent['bot_id']
    if not bot_id:
        bot_id = Config.BOT_MAPPING.get(query_type, Config.DEFAULT_BOT_ID)
    payload = {
        "bot_id": bot_id,
        "user": user_id,
        "query": message,
        "stream": False
    }

    try:
        # 使用分离的超时设置：连接10秒，读取30秒
        response = requests.post(
            Config.COZE_API_URL, 
            headers=headers, 
            json=payload, 
            timeout=(10, 90)  # (connect timeout, read timeout)
        )
        response.raise_for_status()
        coze_response = response.json()

        if coze_response.get('code') == 0:
            messages = coze_response.get('messages', [])
            bot_response = ''
            for msg in messages:
                if msg.get('type') == 'answer':
                    bot_response = msg.get('content', '')
                    break
            if not bot_response:
                bot_response = '抱歉，我现在无法回答您的问题。'
            coze_message_id = coze_response.get('conversation_id', '')
        else:
            bot_response = f"Coze API错误: {coze_response.get('msg', '未知错误')}"
            coze_message_id = None

        history_id = save_chat_history(
            user_id=user_id,
            query_type=query_type,
            user_message=message,
            bot_response=bot_response,
            coze_message_id=coze_message_id
        )

        return jsonify({
            'message': 'Message sent successfully',
            'bot_response': bot_response,
            'history_id': history_id,
            'coze_message_id': coze_message_id
        })
    except requests.exceptions.Timeout:
        return jsonify({'error': '请求超时，请稍后重试'}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'网络错误: {str(e)}'}), 502

@chat_bp.route('/feedback', methods=['POST'])
def submit_feedback():
    data = request.get_json()
    history_id = data.get('history_id')
    feedback = data.get('feedback')
    reason = (data.get('reason') or '').strip()

    if not history_id or feedback not in (0, 1):
        return jsonify({'error': 'history_id and feedback(0/1) are required'}), 400

    from models import set_chat_feedback, set_feedback_reason
    set_chat_feedback(history_id, feedback)
    if feedback == 0 and reason:
        set_feedback_reason(history_id, reason)
    return jsonify({'message': 'Feedback saved'})
