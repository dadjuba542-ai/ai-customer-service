import ipaddress
import json
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from config import Config
from models import get_setting

logger = logging.getLogger(__name__)

CASE_RECOGNITION_FIELDS = (
    'title',
    'customer_profile',
    'symptom_tags',
    'product_tags',
    'scenario',
    'summary',
    'content',
    'image_url',
    'status',
    'sort_order',
)


class CaseRecognitionError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class _HtmlTextParser(HTMLParser):
    IGNORED_TAGS = {'script', 'style', 'noscript', 'svg', 'canvas', 'nav', 'header', 'footer'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.description = ''
        self.image_url = ''
        self._title_parts = []
        self._text_parts = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = {k.lower(): (v or '') for k, v in attrs}
        if tag in self.IGNORED_TAGS:
            self._ignored_depth += 1
        if tag == 'title':
            self._in_title = True
        if tag == 'meta':
            name = (attrs.get('name') or attrs.get('property') or '').lower()
            content = attrs.get('content') or ''
            if name in ('description', 'og:description') and content and not self.description:
                self.description = _clean_text(content)
            if name in ('og:image', 'twitter:image') and content and not self.image_url:
                self.image_url = content.strip()
        if tag == 'img' and not self.image_url:
            self.image_url = (attrs.get('data-src') or attrs.get('src') or '').strip()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.IGNORED_TAGS and self._ignored_depth > 0:
            self._ignored_depth -= 1
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        text = _clean_text(data)
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
            return
        if self._ignored_depth == 0:
            self._text_parts.append(text)

    def result(self):
        title = _clean_text(' '.join(self._title_parts)) or self.title
        body = _clean_text(' '.join(self._text_parts))
        return title, self.description, body, self.image_url


def recognize_case_from_link(url):
    source_url = (url or '').strip()
    if not source_url:
        raise CaseRecognitionError('请输入案例链接')

    warnings = []
    _assert_safe_url(source_url)
    html, final_url = _fetch_html(source_url)
    title, description, body, image_url = _extract_html_content(html, final_url)
    if not body and not description:
        warnings.append('页面正文为空，请手动补充详细记录')

    raw_text = _clean_text(' '.join([title, description, body]))
    raw_excerpt = raw_text[:1800]
    fields = _fallback_fields(source_url, title, description, body, image_url)

    ai_fields, ai_warning = _extract_fields_with_ai(raw_excerpt)
    if ai_warning:
        warnings.append(ai_warning)
    if ai_fields:
        fields.update(_normalize_ai_fields(ai_fields))
        if image_url and not fields.get('image_url'):
            fields['image_url'] = image_url
    else:
        warnings.append('已使用规则识别结果，请人工确认标签和摘要')

    return {
        'source_url': source_url,
        'final_url': final_url,
        'fields': _normalize_fields(fields),
        'raw_excerpt': raw_excerpt,
        'warnings': _dedupe_warnings(warnings),
    }


def _fetch_html(source_url):
    current_url = source_url
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 CaseRecognizer/1.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    for _ in range(4):
        _assert_safe_url(current_url)
        response = session.get(current_url, headers=headers, timeout=8, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get('Location', '')
            if not location:
                break
            current_url = urljoin(current_url, location)
            continue
        response.raise_for_status()
        content_type = (response.headers.get('Content-Type') or '').lower()
        if content_type and 'html' not in content_type and 'text/' not in content_type:
            raise CaseRecognitionError('链接内容不是可识别的网页文本')
        response.encoding = response.encoding or response.apparent_encoding or 'utf-8'
        return response.text[:800000], current_url
    raise CaseRecognitionError('链接跳转次数过多或无法访问')


def _assert_safe_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise CaseRecognitionError('仅支持 http/https 网页链接')
    host = (parsed.hostname or '').strip().lower()
    if not host or host in ('localhost',):
        raise CaseRecognitionError('不支持本地或内网链接')
    try:
        ip = ipaddress.ip_address(host)
        _assert_public_ip(ip)
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise CaseRecognitionError('链接域名无法解析') from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        _assert_public_ip(ip)


def _assert_public_ip(ip):
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise CaseRecognitionError('不支持本地或内网链接')


def _extract_html_content(html, base_url):
    parser = _HtmlTextParser()
    parser.feed(html or '')
    title, description, body, image_url = parser.result()
    if image_url:
        image_url = urljoin(base_url, image_url)
    return title, description, body[:12000], image_url


def _extract_fields_with_ai(raw_excerpt):
    if not raw_excerpt:
        return None, '页面正文为空，无法进行 AI 识别'
    api_key = get_setting('coze_api_key', Config.COZE_API_KEY)
    if not api_key:
        return None, '未配置 Coze API Key，跳过 AI 识别'
    prompt = (
        '请从下面的客户案例网页文本中抽取案例档案字段，只返回严格 JSON，不要解释。\n'
        'JSON 字段包括：title, customer_profile, symptom_tags, product_tags, scenario, summary, content。\n'
        'symptom_tags 和 product_tags 用中文逗号或英文逗号分隔，最多 5 个；没有把握就留空。\n'
        'summary 控制在 120 字以内；content 保留关键背景、使用过程和反馈结果。\n\n'
        f'网页文本：\n{raw_excerpt[:6000]}'
    )
    try:
        response = requests.post(
            Config.COZE_API_URL,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'bot_id': Config.DEFAULT_BOT_ID,
                'user': 'case-recognizer',
                'query': prompt,
                'stream': False,
            },
            timeout=(5, 45),
        )
        response.raise_for_status()
        answer = _extract_coze_answer(response.json())
        fields = _parse_json_answer(answer)
        if not fields:
            return None, 'AI 返回格式不可用，已降级为规则识别'
        return fields, ''
    except Exception as exc:
        logger.info('case recognition ai fallback: %s', exc)
        return None, 'AI 识别失败，已降级为规则识别'


def _extract_coze_answer(payload):
    if payload.get('code') == 0:
        for msg in payload.get('messages', []):
            if msg.get('type') in ('answer', 'assistant_answer'):
                return msg.get('content', '')
    return ''


def _parse_json_answer(answer):
    answer = (answer or '').strip()
    if not answer:
        return None
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', answer, re.S)
    if fenced:
        answer = fenced.group(1)
    else:
        match = re.search(r'\{.*\}', answer, re.S)
        if match:
            answer = match.group(0)
    try:
        data = json.loads(answer)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _fallback_fields(source_url, title, description, body, image_url):
    summary_source = description or body
    return {
        'title': title or '未命名案例',
        'customer_profile': '',
        'symptom_tags': '',
        'product_tags': '',
        'scenario': '',
        'summary': _truncate(summary_source, 120),
        'content': body or description or '',
        'image_url': image_url or '',
        'status': 1,
        'sort_order': 0,
    }


def _normalize_ai_fields(data):
    fields = {}
    for key in CASE_RECOGNITION_FIELDS:
        if key in ('status', 'sort_order', 'image_url'):
            continue
        value = _clean_text(str(data.get(key) or ''))
        if value:
            fields[key] = value
    return fields


def _normalize_fields(fields):
    normalized = {}
    for key in CASE_RECOGNITION_FIELDS:
        value = fields.get(key, '')
        if key == 'status':
            normalized[key] = 1 if str(value) != '0' else 0
        elif key == 'sort_order':
            try:
                normalized[key] = int(value or 0)
            except (TypeError, ValueError):
                normalized[key] = 0
        else:
            normalized[key] = _clean_text(str(value or ''))
    return normalized


def _clean_text(value):
    return re.sub(r'\s+', ' ', (value or '').replace('\xa0', ' ')).strip()


def _truncate(value, length):
    value = _clean_text(value)
    return value[:length]


def _dedupe_warnings(warnings):
    seen = set()
    result = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.add(warning)
            result.append(warning)
    return result
