#!/usr/bin/env python3
"""清理音频课程产生但已无引用的本地音频文件。

默认只做 dry-run 列出孤儿文件；``--apply`` 会先备份 SQLite，再删除孤儿。
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import Config
from services.audio_service import AUDIO_SUBDIR, _URL_PREFIX


def referenced_basenames(db_path):
    if not os.path.exists(db_path):
        return set()
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audio_courses'"
        ).fetchone()
        if not row:
            return set()
        names = set()
        for (url,) in conn.execute('SELECT audio_url FROM audio_courses'):
            url = str(url or '').strip()
            if url.startswith(_URL_PREFIX):
                names.add(url[len(_URL_PREFIX):])
        return names
    finally:
        conn.close()


def find_orphans(audio_dir, referenced):
    if not os.path.isdir(audio_dir):
        return []
    orphans = []
    for name in sorted(os.listdir(audio_dir)):
        path = os.path.join(audio_dir, name)
        if os.path.isfile(path) and name not in referenced:
            orphans.append(path)
    return orphans


def backup_database(db_path):
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_path = f'{db_path}.bak.audio-cleanup.{ts}'
    shutil.copy2(db_path, backup_path)
    print(f'Database backup: {backup_path}')


def main():
    parser = argparse.ArgumentParser(description='Remove unreferenced audio course files.')
    parser.add_argument('--apply', action='store_true', help='actually delete orphan files (backs up DB first)')
    args = parser.parse_args()

    db_path = Config.DATABASE_PATH
    audio_dir = os.path.join(Config.UPLOAD_DIR, AUDIO_SUBDIR)
    referenced = referenced_basenames(db_path)
    orphans = find_orphans(audio_dir, referenced)

    if not orphans:
        print('No orphan audio files found.')
        return

    total_bytes = sum(os.path.getsize(path) for path in orphans)
    print(f'Found {len(orphans)} orphan audio file(s), {total_bytes / 1024 / 1024:.1f} MB:')
    for path in orphans:
        print(f'  {path}')

    if not args.apply:
        print('Dry run only. Re-run with --apply to delete.')
        return

    backup_database(db_path)
    deleted = 0
    for path in orphans:
        try:
            os.remove(path)
            deleted += 1
        except OSError as exc:
            print(f'  failed: {path} ({exc})')
    print(f'Deleted {deleted}/{len(orphans)} orphan audio file(s).')


if __name__ == '__main__':
    main()
