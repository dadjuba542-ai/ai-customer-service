from flask import Blueprint, jsonify
from models import get_all_agent_configs

agents_bp = Blueprint('agents', __name__)

@agents_bp.route('', methods=['GET'])
def list_agents():
    agents = get_all_agent_configs()
    return jsonify({'agents': agents})
