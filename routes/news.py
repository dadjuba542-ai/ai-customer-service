from flask import Blueprint, request, jsonify
from models import create_news, get_all_news, get_news_by_id, update_news, delete_news, increment_news_views, get_pinned_news, get_featured_news, get_news_page, toggle_pin_news, toggle_featured_news, get_news_categories
from routes.auth import admin_required

news_bp = Blueprint('news', __name__)

@news_bp.route('', methods=['GET'])
def list_news():
    limit = request.args.get('limit', type=int)
    page = request.args.get('page', 1, type=int)
    mode = request.args.get('mode', 'all')

    if mode == 'home':
        items = get_featured_news(limit or 3)
        if len(items) < (limit or 3):
            taken = {i['id'] for i in items}
            recent = [n for n in get_all_news() if n['id'] not in taken]
            items += recent[:(limit or 3) - len(items)]
        return jsonify({'news': items})

    if mode == 'discover':
        category = request.args.get('category')
        pinned = get_pinned_news(3)
        pages = get_news_page(page, limit or 10, exclude_pinned=True, category=category)
        return jsonify({'pinned': pinned, 'page': pages, 'news': pages['items'], 'categories': get_news_categories()})

    news = get_all_news()
    return jsonify({'news': news})

@news_bp.route('', methods=['POST'])
@admin_required
def add_news(current_user):
    data = request.get_json()
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400
    id = create_news(title, data.get('summary', ''), data.get('content', ''), data.get('image_url', ''), data.get('category', ''))
    return jsonify({'id': id, 'message': 'News created'}), 201

@news_bp.route('/<int:news_id>', methods=['GET'])
def get_news(news_id):
    increment_news_views(news_id)
    item = get_news_by_id(news_id)
    if not item:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(item)

@news_bp.route('/<int:news_id>', methods=['PUT'])
@admin_required
def edit_news(current_user, news_id):
    data = request.get_json()
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400
    update_news(news_id, title, data.get('summary', ''), data.get('content', ''), data.get('image_url', ''), data.get('category', ''))
    return jsonify({'message': 'News updated'})

@news_bp.route('/<int:news_id>', methods=['DELETE'])
@admin_required
def remove_news(current_user, news_id):
    delete_news(news_id)
    return jsonify({'message': 'News deleted'})

@news_bp.route('/<int:news_id>/pin', methods=['PUT'])
@admin_required
def pin_news(current_user, news_id):
    val = toggle_pin_news(news_id)
    return jsonify({'pinned': val})

@news_bp.route('/<int:news_id>/feature', methods=['PUT'])
@admin_required
def feature_news(current_user, news_id):
    val = toggle_featured_news(news_id)
    return jsonify({'featured': val})
