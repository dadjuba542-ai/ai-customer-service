import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse


ALLOWED_TAGS = {
    'a', 'blockquote', 'br', 'code', 'div', 'em', 'h1', 'h2', 'h3', 'h4',
    'hr', 'img', 'li', 'ol', 'p', 'pre', 's', 'span', 'strong', 'sub', 'sup',
    'table', 'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul',
}
VOID_TAGS = {'br', 'hr', 'img'}
DROP_CONTENT_TAGS = {'canvas', 'iframe', 'math', 'object', 'script', 'style', 'svg', 'template'}

# Quill 排版样式。编辑器侧全部走 class（见 static/css/rich-text.css），不使用 style 属性，
# 因此这里只需放行有限前缀；字体颜色是预设色板而非自由取值，枚举空间是封闭的。
# 新增前缀必须与 static/js/admin.js 注册的 attributor keyName 和 rich-text.css 三者同步。
CLASS_PATTERN = re.compile(
    r'^(?:ql-(?:align|bg|color|direction|font|indent|line|para|size)-[\w-]+|ql-syntax)$'
)
DATA_IMAGE_PATTERN = re.compile(r'^data:image/(?:png|jpeg|jpg|gif|webp);base64,', re.I)


def sanitize_rich_html(value, max_length=200_000):
    parser = _AllowlistHtmlParser()
    parser.feed(str(value or '')[:max_length])
    parser.close()
    return ''.join(parser.output)


def sanitize_media_url(value):
    return _safe_url(str(value or '').strip(), image=True)


_AGE_PATTERN = re.compile(r'(\d{1,3})\s*(?:周岁|岁)')
# 精确到具体年龄 + 职业 + 生活习惯的组合具备可识别性，对外只保留粗粒度区间。
_AGE_BUCKETS = ((18, '未成年'), (35, '青年'), (50, '中年'), (200, '中老年'))


def redact_customer_profile(value):
    """Reduce a customer profile to a coarse age bucket plus gender.

    Stored profiles can combine an exact age, an occupation and daily habits
    (e.g. "45岁女性，久坐办公室，饮食不规律"), which is personal information
    under PIPL. Public endpoints only need enough context to read the case.
    Internal/AI retrieval paths keep calling models directly.
    """
    text = str(value or '').strip()
    if not text:
        return ''

    bucket = ''
    match = _AGE_PATTERN.search(text)
    if match:
        age = int(match.group(1))
        if 0 < age < 130:
            for upper, label in _AGE_BUCKETS:
                if age < upper:
                    bucket = label
                    break

    gender = ''
    if '女性' in text or '女士' in text or '女' in text:
        gender = '女性'
    elif '男性' in text or '男士' in text or '男' in text:
        gender = '男性'

    if bucket and gender:
        return f'{bucket}{gender}'
    return bucket or gender


def _safe_url(value, *, image=False):
    value = html.unescape(value or '').strip()
    if not value:
        return ''
    lowered = value.lower()
    if image and DATA_IMAGE_PATTERN.match(value):
        return value
    if any(char in value for char in ('\x00', '\r', '\n')):
        return ''
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ('', 'http', 'https', 'mailto', 'tel'):
        return ''
    if image and parsed.scheme.lower() in ('mailto', 'tel'):
        return ''
    if not parsed.scheme and not value.startswith(('/', '#', '?', './', '../')):
        return ''
    if lowered.startswith(('javascript:', 'vbscript:', 'file:')):
        return ''
    return value


class _AllowlistHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.drop_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth or tag not in ALLOWED_TAGS:
            return
        safe_attrs = self._sanitize_attrs(tag, attrs)
        rendered_attrs = ''.join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in safe_attrs
        )
        self.output.append(f'<{tag}{rendered_attrs}>')

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            # Self-closing dangerous tags never emit an end tag; do not change drop_depth.
            return
        self.handle_starttag(tag, attrs)
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.output.append(f'</{tag}>')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            if self.drop_depth:
                self.drop_depth -= 1
            return
        if not self.drop_depth and tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.output.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.drop_depth:
            self.output.append(html.escape(data, quote=False))

    def _sanitize_attrs(self, tag, attrs):
        result = []
        target_blank = False
        for raw_name, raw_value in attrs:
            name = (raw_name or '').lower()
            value = str(raw_value or '').strip()
            if name == 'class':
                classes = [item for item in value.split() if CLASS_PATTERN.fullmatch(item)]
                if classes:
                    result.append(('class', ' '.join(classes)))
            elif tag == 'a' and name == 'href':
                safe = _safe_url(value)
                if safe:
                    result.append(('href', safe))
            elif tag == 'a' and name == 'title':
                result.append(('title', value[:200]))
            elif tag == 'a' and name == 'target' and value in ('_blank', '_self'):
                result.append(('target', value))
                target_blank = value == '_blank'
            elif tag == 'img' and name == 'src':
                safe = _safe_url(value, image=True)
                if safe:
                    result.append(('src', safe))
            elif tag == 'img' and name in ('alt', 'title'):
                result.append((name, value[:300]))
            elif tag == 'img' and name in ('width', 'height') and value.isdigit():
                result.append((name, str(min(int(value), 4000))))
            elif tag in ('td', 'th') and name in ('colspan', 'rowspan') and value.isdigit():
                result.append((name, str(min(int(value), 100))))
        if tag == 'a' and target_blank:
            result.append(('rel', 'noopener noreferrer'))
        return result
