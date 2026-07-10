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
CLASS_PATTERN = re.compile(r'^(?:ql-(?:align|direction|font|indent|size)-[\w-]+|ql-syntax)$')
DATA_IMAGE_PATTERN = re.compile(r'^data:image/(?:png|jpeg|jpg|gif|webp);base64,', re.I)


def sanitize_rich_html(value, max_length=200_000):
    parser = _AllowlistHtmlParser()
    parser.feed(str(value or '')[:max_length])
    parser.close()
    return ''.join(parser.output)


def sanitize_media_url(value):
    return _safe_url(str(value or '').strip(), image=True)


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
        self.handle_starttag(tag, attrs)

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
