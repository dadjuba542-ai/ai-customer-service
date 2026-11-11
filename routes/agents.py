from flask import Blueprint, jsonify
from models import get_all_agent_configs

agents_bp = Blueprint('agents', __name__)

@agents_bp.route('', methods=['GET'])
def list_agents():
    agents = get_all_agent_configs()
    public_fields = ('agent_id', 'name', 'type', 'description', 'prompt',
                     'avatar_url', 'color', 'icon', 'chat_desc')
    return jsonify({'agents': [{key: agent.get(key, '') for key in public_fields}
                              for agent in agents]})
