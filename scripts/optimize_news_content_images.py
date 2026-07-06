#!/usr/bin/env python3
import argparse
import base64
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from io import BytesIO

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import Config
from services.image_service import process_uploaded_image


DATA_IMAGE_RE = re.compile(
    r'(<img\b[^>]*?\bsrc=["\'])data:(image/(?:png|jpe?g|webp|gif));base64,([^"\']+)(["\'][^>]*>)',
    re.IGNORECASE,
)


def main():
    parser = argparse.ArgumentParser(description='Move base64 images in news.content to static/uploads URLs.')
    parser.add_argument('--apply', action='store_true', help='write uploaded images and update news.content')
    args = parser.parse_args()

    db_path = Config.DATABASE_PATH
    upload_dir = os.path.join(ROOT_DIR, 'static', 'uploads')
    rows = load_news_with_data_images(db_path)

    if not rows:
        print('No news content contains data:image.')
        return

    print(f'Found {len(rows)} news item(s) containing data:image.')
    for row in rows:
        content = row['content'] or ''
        matches = list(DATA_IMAGE_RE.finditer(content))
        estimated = estimate_replaced_content(content, matches)
        print(
            f'- #{row["id"]} {row["title"]}: {len(matches)} image(s), '
            f'{format_size(len(content.encode("utf-8")))} -> about {format_size(len(estimated.encode("utf-8")))}'
        )

    if not args.apply:
        print('Dry-run only. Run with --apply to backup database, create upload files, and update news.content.')
        return

    backup_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for row in rows:
            new_content, converted = convert_content_images(row['content'] or '', upload_dir)
            conn.execute('UPDATE news SET content = ? WHERE id = ?', (new_content, row['id']))
            print(f'Updated #{row["id"]}: converted {converted} image(s).')
        conn.commit()
    finally:
        conn.close()


def load_news_with_data_images(db_path):
    if not os.path.exists(db_path):
        raise SystemExit(f'Database not found: {db_path}')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            'SELECT id, title, content FROM news WHERE content LIKE ? ORDER BY id',
            ('%data:image%',),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def estimate_replaced_content(content, matches):
    output = content
    for index, match in enumerate(matches, start=1):
        replacement = f'{match.group(1)}/uploads/news_content_{index}.jpg{match.group(4)}'
        output = output.replace(match.group(0), replacement, 1)
    return output


def convert_content_images(content, upload_dir):
    converted = 0

    def replace(match):
        nonlocal converted
        converted += 1
        data = decode_base64_image(match.group(3))
        result = process_uploaded_image(BytesIO(data), upload_dir, filename_stem=f'news_content_{datetime.now().strftime("%Y%m%d%H%M%S%f")}')
        return f'{match.group(1)}{result.url}{match.group(4)}'

    return DATA_IMAGE_RE.sub(replace, content), converted


def decode_base64_image(value):
    compact = re.sub(r'\s+', '', value)
    try:
        return base64.b64decode(compact, validate=True)
    except Exception as exc:
        raise ValueError('Invalid base64 image data') from exc


def backup_database(db_path):
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_path = f'{db_path}.bak.news-content.{ts}'
    shutil.copy2(db_path, backup_path)
    print(f'Database backup: {backup_path}')


def format_size(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024:
            return f'{size:.1f}{unit}'
        size /= 1024
    return f'{size:.1f}TB'


if __name__ == '__main__':
    main()
