from flask import Blueprint, request, jsonify
from models import create_product, get_all_products, get_product_by_id, update_product, delete_product, reorder_products, get_product_category_order, set_product_category_order
from routes.auth import admin_required
from services.content_security import sanitize_media_url, sanitize_rich_html

products_bp = Blueprint('products', __name__)

@products_bp.route('', methods=['GET'])
def list_products():
    products = get_all_products()
    for product in products:
        product['content'] = sanitize_rich_html(product.get('content', ''))
        product['image_url'] = sanitize_media_url(product.get('image_url', ''))
    categories = get_product_category_order()
    cats = list(dict.fromkeys(p['category'] or '其他' for p in products))
    if categories:
        ordered = [c for c in categories if c in cats]
        ordered += [c for c in cats if c not in ordered]
    else:
        ordered = cats
    return jsonify({'products': products, 'categories': ordered})

@products_bp.route('/<int:product_id>', methods=['GET'])
def get_product(product_id):
    item = get_product_by_id(product_id)
    if not item:
        return jsonify({'error': 'Not found'}), 404
    item['content'] = sanitize_rich_html(item.get('content', ''))
    item['image_url'] = sanitize_media_url(item.get('image_url', ''))
    return jsonify(item)

@products_bp.route('', methods=['POST'])
@admin_required
def add_product(current_user):
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()[:200]
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    id = create_product(
        data.get('category', '').strip()[:80],
        name,
        str(data.get('summary') or '')[:1000],
        sanitize_rich_html(data.get('content', '')),
        sanitize_media_url(data.get('image_url', '')),
        str(data.get('highlights') or '')[:1000],
        data.get('sort_order', 0)
    )
    return jsonify({'id': id, 'message': 'Product created'}), 201

@products_bp.route('/<int:product_id>', methods=['PUT'])
@admin_required
def edit_product(current_user, product_id):
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()[:200]
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    update_product(
        product_id,
        str(data.get('category') or '')[:80],
        name,
        str(data.get('summary') or '')[:1000],
        sanitize_rich_html(data.get('content', '')),
        sanitize_media_url(data.get('image_url', '')),
        str(data.get('highlights') or '')[:1000],
        data.get('sort_order', 0)
    )
    return jsonify({'message': 'Product updated'})

@products_bp.route('/<int:product_id>', methods=['DELETE'])
@admin_required
def remove_product(current_user, product_id):
    delete_product(product_id)
    return jsonify({'message': 'Product deleted'})

@products_bp.route('/category-order', methods=['POST'])
@admin_required
def save_category_order(current_user):
    data = request.get_json(silent=True) or {}
    order = data.get('categories', [])
    set_product_category_order(order)
    return jsonify({'message': 'Category order saved'})

@products_bp.route('/reorder', methods=['POST'])
@admin_required
def reorder(current_user):
    data = request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return jsonify({'error': 'items 格式不正确'}), 400
    try:
        order_list = [
            (int(item['id']), int(item.get('sort_order', 0)))
            for item in items
            if isinstance(item, dict) and 'id' in item
        ]
    except (TypeError, ValueError, KeyError):
        return jsonify({'error': '排序参数格式不正确'}), 400
    reorder_products(order_list)
    return jsonify({'message': 'Reordered'})
