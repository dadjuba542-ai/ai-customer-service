import re

from flask import Blueprint, jsonify, request

from models import create_lead_request
from routes.auth import identity_required
from services.security_service import rate_limit

leads_bp = Blueprint('leads', __name__)
PHONE_RE = re.compile(r'^1[3-9]\d{9}$')


@leads_bp.route('', methods=['POST'])
@identity_required
@rate_limit('lead-submit', limit=5, window_seconds=600)
def submit_lead(identity):
    data = request.get_json(silent=True) or {}
    customer_type = str(data.get('customer_type') or '').strip()
    product_name = str(data.get('product_name') or '').strip()
    description = str(data.get('description') or '').strip()
    phone = str(data.get('phone') or '').strip()
    wechat = str(data.get('wechat') or '').strip()
    if customer_type not in {'consumer', 'partner'}:
        return jsonify({'error': '请选择客户类型'}), 400
    if not description or len(description) > 1000:
        return jsonify({'error': '请填写需求，且不超过1000字'}), 400
    if len(product_name) > 100:
        return jsonify({'error': '产品名称过长'}), 400
    if phone and not PHONE_RE.fullmatch(phone):
        return jsonify({'error': '请输入正确的手机号'}), 400
    if wechat and len(wechat) > 80:
        return jsonify({'error': '微信号过长'}), 400
    if not phone and not wechat:
        return jsonify({'error': '手机号或微信号至少填写一项'}), 400
    result = create_lead_request(
        identity['user_id'], customer_type, product_name, description, phone, wechat,
        str(data.get('query_type') or '')[:50], str(data.get('agent_id') or '')[:80], data.get('history_id'),
    )
    return jsonify({'message': '需求已提交，我们会尽快联系您', **result}), 200 if result['duplicate'] else 201
