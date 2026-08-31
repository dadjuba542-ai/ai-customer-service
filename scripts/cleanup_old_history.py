#!/usr/bin/env python3
"""Delete chat history older than the configured retention period.

Run manually or from cron; startup cleanup is disabled by default.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from models import cleanup_old_history


def main():
    parser = argparse.ArgumentParser(description='Delete old chat history')
    parser.add_argument(
        '--days', type=int, default=Config.CHAT_RETENTION_DAYS,
        help=f'Retention period in days (default: {Config.CHAT_RETENTION_DAYS})',
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error('--days must be >= 1')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Cleaning chat history older than %s days', args.days)
    cleanup_old_history(days=args.days)
    logging.info('Cleanup finished')


if __name__ == '__main__':
    main()
