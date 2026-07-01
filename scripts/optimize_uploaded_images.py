#!/usr/bin/env python3
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import Config
from services.image_service import optimize_image_file


IMAGE_FIELDS = (
    ('news', 'image_url'),
    ('products', 'image_url'),
    ('case_documents', 'image_url'),
    ('agent_configs', 'avatar_url'),
)


def main():
    parser = argparse.ArgumentParser(description='Optimize local uploaded images and update SQLite references.')
    parser.add_argument('--apply', action='store_true', help='write optimized images and update database references')
    parser.add_argument('--max-size', type=int, default=1200, help='main image max edge')
    parser.add_argument('--thumb-size', type=int, default=480, help='thumbnail max edge')
    parser.add_argument('--min-bytes', type=int, default=120 * 1024, help='skip tiny files below this size')
    args = parser.parse_args()

    db_path = Config.DATABASE_PATH
    upload_dir = os.path.join(ROOT_DIR, 'static', 'uploads')
    refs = collect_image_refs(db_path)
    jobs = build_jobs(refs, upload_dir, args.min_bytes)

    if not jobs:
        print('No local upload images need optimization.')
        return

    print(f'Found {len(jobs)} referenced local upload image(s) to optimize.')
    total_before = sum(job['source_size'] for job in jobs)

    if args.apply:
        backup_database(db_path)
        updates = {}
        for job in jobs:
            result = optimize_image_file(
                job['source_path'],
                job['dest_path'],
                job['thumb_path'],
                main_max_size=args.max_size,
                thumb_max_size=args.thumb_size,
            )
            updates[job['url']] = job['new_url']
            print_result(job, result.size, result.thumb_size, applied=True)
        update_database_refs(db_path, updates)
        print(f'Updated {len(updates)} image URL(s) in database.')
    else:
        with tempfile.TemporaryDirectory() as tmp_dir:
            total_after = 0
            for job in jobs:
                tmp_main = os.path.join(tmp_dir, os.path.basename(job['dest_path']))
                tmp_thumb = os.path.join(tmp_dir, os.path.basename(job['thumb_path']))
                result = optimize_image_file(
                    job['source_path'],
                    tmp_main,
                    tmp_thumb,
                    main_max_size=args.max_size,
                    thumb_max_size=args.thumb_size,
                )
                total_after += result.size
                print_result(job, result.size, result.thumb_size, applied=False)
            saved = total_before - total_after
            print(f'Dry-run only. Estimated main-image saving: {format_size(saved)}.')
            print('Run with --apply to create optimized files, backup DB, and update references.')


def collect_image_refs(db_path):
    if not os.path.exists(db_path):
        raise SystemExit(f'Database not found: {db_path}')
    conn = sqlite3.connect(db_path)
    refs = set()
    try:
        for table, column in IMAGE_FIELDS:
            if not table_exists(conn, table) or not column_exists(conn, table, column):
                continue
            rows = conn.execute(
                f'SELECT DISTINCT {column} AS url FROM {table} WHERE {column} IS NOT NULL AND {column} != ""'
            ).fetchall()
            refs.update(row[0].strip() for row in rows if row[0])
    finally:
        conn.close()
    return refs


def build_jobs(refs, upload_dir, min_bytes):
    jobs = []
    seen_sources = set()
    for url in sorted(refs):
        path = local_upload_path(url, upload_dir)
        if not path or path in seen_sources or not os.path.exists(path):
            continue
        seen_sources.add(path)
        source_size = os.path.getsize(path)
        if source_size < min_bytes or '_thumb.' in os.path.basename(path) or '_opt.' in os.path.basename(path):
            continue
        root, _ = os.path.splitext(path)
        dest_path = f'{root}_opt.jpg'
        thumb_path = f'{root}_opt_thumb.jpg'
        new_url = upload_url_for(dest_path)
        jobs.append({
            'url': url,
            'new_url': new_url,
            'source_path': path,
            'dest_path': dest_path,
            'thumb_path': thumb_path,
            'source_size': source_size,
        })
    return jobs


def update_database_refs(db_path, updates):
    conn = sqlite3.connect(db_path)
    try:
        for old_url, new_url in updates.items():
            for table, column in IMAGE_FIELDS:
                if not table_exists(conn, table) or not column_exists(conn, table, column):
                    continue
                conn.execute(f'UPDATE {table} SET {column} = ? WHERE {column} = ?', (new_url, old_url))
        conn.commit()
    finally:
        conn.close()


def backup_database(db_path):
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_path = f'{db_path}.bak.{ts}'
    shutil.copy2(db_path, backup_path)
    print(f'Database backup: {backup_path}')


def table_exists(conn, table):
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def column_exists(conn, table, column):
    rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return any(row[1] == column for row in rows)


def local_upload_path(url, upload_dir):
    if not url.startswith('/uploads/'):
        return ''
    name = url.split('?', 1)[0].split('#', 1)[0].replace('/uploads/', '', 1)
    if not name or '/' in name or '\\' in name:
        return ''
    return os.path.join(upload_dir, name)


def upload_url_for(path):
    return f'/uploads/{os.path.basename(path)}'


def format_size(size):
    sign = '-' if size < 0 else ''
    size = abs(size)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024:
            return f'{sign}{size:.1f}{unit}'
        size /= 1024
    return f'{sign}{size:.1f}TB'


def print_result(job, main_size, thumb_size, applied):
    verb = 'created' if applied else 'would create'
    before = format_size(job['source_size'])
    after = format_size(main_size)
    thumb = format_size(thumb_size)
    print(f'- {job["url"]}: {before} -> {after}, thumb {thumb}; {verb} {job["new_url"]}')


if __name__ == '__main__':
    main()
