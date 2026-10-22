from flask import Blueprint, jsonify, request, Response
from routes.auth import identity_required, admin_required
from services.chat_service import ChatServiceError
from services.security_service import rate_limit
from services import practice_service as practice
from services import practice_learning as learning
from services import practice_path as path

practice_bp = Blueprint('practice', __name__)
admin_practice_bp = Blueprint('admin_practice', __name__)


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise practice.PracticeError('请提交有效的 JSON 对象', 400)
    return data


@practice_bp.errorhandler(ChatServiceError)
@admin_practice_bp.errorhandler(ChatServiceError)
def handle_error(exc):
    return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code


@practice_bp.route('/catalog')
@identity_required
def catalog(identity):
    return jsonify(practice.catalog(identity))


@practice_bp.route('/daily')
@identity_required
def daily(identity):
    return jsonify(practice.daily(request.args.get('stage_id', 0, type=int)))


@practice_bp.route('/sessions', methods=['POST'])
@identity_required
@rate_limit('practice-create', 10)
def create(identity):
    return jsonify(practice.create_session(identity, body()))


@practice_bp.route('/sessions', methods=['GET'])
@identity_required
def records(identity):
    return jsonify(practice.records(identity, request.args.get('page', 1, type=int)))


@practice_bp.route('/sessions/<session_id>')
@identity_required
def get_session(identity, session_id):
    return jsonify(practice.get_session(session_id, identity))


@practice_bp.route('/sessions/<session_id>/<action>', methods=['POST'])
@identity_required
@rate_limit('practice-action', 60)
def action(identity, session_id, action):
    return jsonify(practice.perform(session_id, identity, action, body()))


@practice_bp.route('/scores')
@identity_required
def scores(identity):
    return jsonify(practice.scores(identity))


@practice_bp.route('/learning/home')
@identity_required
def learning_home(identity):
    return jsonify(learning.home(identity))


@practice_bp.route('/learning/path')
@identity_required
def learning_path(identity):
    return jsonify(path.home(identity))


@practice_bp.route('/learning/products/<int:product_id>')
@identity_required
def learning_product(identity, product_id):
    return jsonify(learning.course(identity, product_id))


@practice_bp.route('/learning/sessions', methods=['POST'])
@identity_required
@rate_limit('practice-create', 10)
def learning_create(identity):
    return jsonify(learning.create_session(identity, body()))


@practice_bp.route('/learning/sessions/<session_id>')
@identity_required
def learning_session(identity, session_id):
    return jsonify(learning.get_session(identity, session_id))


@practice_bp.route('/learning/sessions/<session_id>/<action>', methods=['POST'])
@identity_required
@rate_limit('practice-action', 60)
def learning_action(identity, session_id, action):
    return jsonify(learning.perform(identity, session_id, action, body()))


@admin_practice_bp.route('', methods=['GET'])
@admin_required
def admin_data(user):
    return jsonify(practice.admin_data(request.args.get('stage_id', 0, type=int)))


@admin_practice_bp.route('/learning')
@admin_required
def learning_admin_data(user):
    return jsonify(learning.admin_data())


@admin_practice_bp.route('/learning/path')
@admin_required
def path_admin_data(user):
    return jsonify(path.admin_data())


@admin_practice_bp.route('/learning/path/initialize', methods=['POST'])
@admin_required
def path_initialize(user):
    return jsonify(path.initialize(body().get('product_name')))


@admin_practice_bp.route('/learning/path/units/<int:unit_id>', methods=['PUT'])
@admin_required
def path_save_unit(user, unit_id):
    return jsonify(path.save_unit(unit_id, body()))


@admin_practice_bp.route('/learning/path/publish', methods=['POST'])
@admin_required
def path_publish(user):
    return jsonify(path.publish())


@admin_practice_bp.route('/learning/path/suggestions/<int:suggestion_id>', methods=['POST'])
@admin_required
def path_review_suggestion(user, suggestion_id):
    return jsonify(path.review(suggestion_id, body().get('accepted')))


@admin_practice_bp.route('/learning/products/<int:product_id>/facts/<int:unit_no>', methods=['PUT'])
@admin_required
def learning_admin_fact(user, product_id, unit_no):
    return jsonify(learning.save_fact(product_id, unit_no, body()))


@admin_practice_bp.route('/learning/products/<int:product_id>/units/<int:unit_no>', methods=['PUT'])
@admin_required
def learning_admin_unit(user, product_id, unit_no):
    return jsonify(learning.assign_unit(product_id, unit_no, body()))


@admin_practice_bp.route('/learning/products/<int:product_id>/publish', methods=['POST'])
@admin_required
def learning_admin_publish(user, product_id):
    return jsonify(learning.publish(product_id))


@admin_practice_bp.route('/questions/<int:question_id>', methods=['PUT'])
@admin_required
def save_question(user, question_id):
    practice.save_question(question_id, bank_body())
    return jsonify({'ok': True})


@admin_practice_bp.route('/questions', methods=['POST'])
@admin_required
def add_question(user):
    return jsonify(practice.add_question(bank_body())), 201


@admin_practice_bp.route('/export')
@admin_required
def export_bank(user):
    return Response(practice.export_bank(request.args.get('stage_id', 0, type=int)), content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="practice-bank.csv"'})


@admin_practice_bp.route('/import/preview', methods=['POST'])
@admin_required
def preview_import(user):
    data=bank_body()
    if data.get('weekly_new_import'):
        from services import practice_weekly
        return jsonify(practice_weekly.preview_new(data['stage_id'],data))
    return jsonify(practice.preview_import(data))


@admin_practice_bp.route('/import', methods=['POST'])
@admin_required
def import_bank(user):
    data=bank_body()
    if data.get('weekly_new_import'):
        from services import practice_weekly
        return jsonify(practice_weekly.import_new(data['stage_id'],data))
    return jsonify(practice.import_bank(data))


def bank_body():
    data=body()
    if 'weekly_new_import' in data and type(data['weekly_new_import']) is not bool:
        raise practice.PracticeError('新题导入标识无效',400)
    return {**data, 'stage_id': request.args.get('stage_id', 0, type=int)}


@practice_bp.route('/promotion')
def promotion():
    return jsonify(practice.promotion())


@admin_practice_bp.route('/stages', methods=['POST'])
@admin_required
def add_stage(user):
    return jsonify(practice.save_stage(body())), 201


@admin_practice_bp.route('/stages/<int:stage_id>', methods=['PUT'])
@admin_required
def save_stage(user, stage_id):
    return jsonify(practice.save_stage(body(), stage_id))


@practice_bp.route('/entry')
@identity_required
def entry(identity):
    from services import practice_weekly
    return jsonify(practice_weekly.get_entry(identity))


@practice_bp.route('/entry/impression',methods=['POST'])
@identity_required
def entry_impression(identity):
    from services import practice_weekly
    return jsonify(practice_weekly.record_impression(identity,body()))


@admin_practice_bp.route('/stages/<int:stage_id>/weekly')
@admin_required
def weekly_builder(user,stage_id):
    from services import practice_weekly
    return jsonify(practice_weekly.builder(stage_id))


@admin_practice_bp.route('/stages/<int:stage_id>/weekly/selections',methods=['PUT'])
@admin_required
def weekly_selections(user,stage_id):
    from services import practice_weekly
    return jsonify(practice_weekly.save_selections(stage_id,body()))


@admin_practice_bp.route('/stages/<int:stage_id>/weekly/publish',methods=['POST'])
@admin_required
def weekly_publish(user,stage_id):
    from services import practice_weekly
    return jsonify(practice_weekly.publish(stage_id,body()))


@admin_practice_bp.route('/stages/<int:stage_id>/promotion')
@admin_required
def promotion_preview(user,stage_id):
    from services import practice_weekly
    return jsonify(practice_weekly.promotion_preview(stage_id))
