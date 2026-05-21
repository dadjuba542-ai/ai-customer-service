from flask import Blueprint, request, jsonify
from models import create_product, get_all_products, get_product_by_id, update_product, delete_product, reorder_products
from routes.auth import admin_required

products_bp = Blueprint('products', __name__)

@products_bp.route('', methods=['GET'])
def list_products():
    products = get_all_products()
    return jsonify({'products': products})

@products_bp.route('/<int:product_id>', methods=['GET'])
def get_product(product_id):
    item = get_product_by_id(product_id)
    if not item:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(item)

@products_bp.route('', methods=['POST'])
@admin_required
def add_product(current_user):
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    id = create_product(
        data.get('category', '').strip(),
        name,
        data.get('summary', ''),
        data.get('content', ''),
        data.get('image_url', ''),
        data.get('highlights', ''),
        data.get('sort_order', 0)
    )
    return jsonify({'id': id, 'message': 'Product created'}), 201

@products_bp.route('/<int:product_id>', methods=['PUT'])
@admin_required
def edit_product(current_user, product_id):
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    update_product(
        product_id,
        data.get('category', ''),
        name,
        data.get('summary', ''),
        data.get('content', ''),
        data.get('image_url', ''),
        data.get('highlights', ''),
        data.get('sort_order', 0)
    )
    return jsonify({'message': 'Product updated'})

@products_bp.route('/<int:product_id>', methods=['DELETE'])
@admin_required
def remove_product(current_user, product_id):
    delete_product(product_id)
    return jsonify({'message': 'Product deleted'})

@products_bp.route('/reorder', methods=['POST'])
@admin_required
def reorder(current_user):
    data = request.get_json()
    items = data.get('items', [])
    reorder_products([(i['id'], i['sort_order']) for i in items])
    return jsonify({'message': 'Reordered'})
