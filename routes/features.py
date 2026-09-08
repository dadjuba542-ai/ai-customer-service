from flask import Blueprint, jsonify, request

from routes.auth import admin_required
from services import feature_flags
from services.feature_flags import FeatureFlagError

features_bp = Blueprint('features', __name__)


@features_bp.route('/feature-flags', methods=['GET'])
def public_feature_flags():
    """前台读取开关状态（只读、不含内部细节），用于决定是否渲染入口。"""
    return jsonify({'flags': feature_flags.public_states()})


@features_bp.route('/admin/feature-flags', methods=['GET', 'PUT'])
@admin_required
def admin_feature_flags(current_user):
    if request.method == 'GET':
        return jsonify({'flags': feature_flags.list_states()})

    data = request.get_json(silent=True) or {}
    updates = data.get('flags')
    if not isinstance(updates, dict):
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': '缺少开关名称'}), 400
        updates = {name: data.get('enabled')}
    if not updates:
        return jsonify({'error': '没有需要更新的开关'}), 400

    try:
        for name, enabled in updates.items():
            if enabled is None:
                raise FeatureFlagError(f'开关 {name} 缺少 enabled 值')
            feature_flags.set_enabled(name, bool(enabled))
    except FeatureFlagError as exc:
        return jsonify({'error': exc.message}), exc.status_code
    return jsonify({'flags': feature_flags.list_states()})
