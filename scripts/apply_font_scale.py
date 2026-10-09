#!/usr/bin/env python3
"""一次性脚本：把前台 CSS 里的 `font-size: Npx` 转成 `calc(Npx * var(--fs-scale))`。

背景（大字·清晰版 P1）：
  全站字号硬编码 px、无 rem 根字号，无法靠 html{font-size} 一键缩放。
  改成 calc 乘法后，--fs-scale=1 时计算结果与原值完全一致，因此改造前后
  应像素级相同——这也是本方案的回归基准。

用法：
  python3 scripts/apply_font_scale.py --dry-run   # 只统计不改文件
  python3 scripts/apply_font_scale.py             # 实际改写

注意：
  - 排除 text-size.css（其 px 是按钮/面板尺寸，刻意不缩放）
  - 排除 admin.css（后台不加载 base.css，没有 --fs-scale 变量，改了会失效）
  - 幂等：已转 calc 的写法不会被重复匹配
"""
import argparse
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CSS_DIR = BASE_DIR / 'static' / 'css'

SKIP_FILES = {'text-size.css', 'admin.css'}

# font-size: 14px / font-size:14px / font-size:  14px
# 负向断言排除已转换的 `font-size: calc(...` 与 `14px *`
PATTERN = re.compile(r'(font-size:\s*)(\d+(?:\.\d+)?)px\b(?!\s*\*)')


def convert(source: str):
    return PATTERN.subn(lambda m: f'{m.group(1)}calc({m.group(2)}px * var(--fs-scale))', source)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='只统计，不写文件')
    args = parser.parse_args()

    total = 0
    for path in sorted(CSS_DIR.glob('*.css')):
        if path.name in SKIP_FILES:
            continue
        source = path.read_text(encoding='utf-8')
        converted, count = convert(source)
        if count:
            total += count
            flag = 'would change' if args.dry_run else 'changed'
            print(f'{path.name}: {count} ({flag})')
            if not args.dry_run:
                path.write_text(converted, encoding='utf-8')

    print(f'---\ntotal: {total}')
    if args.dry_run:
        print('(dry-run, no file written)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
