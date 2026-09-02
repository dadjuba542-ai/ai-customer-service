import ipaddress
import json
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from config import Config
from models import get_case_tags, get_setting
from services.secret_service import get_secret_setting

logger = logging.getLogger(__name__)

CASE_RECOGNITION_FIELDS = (
    'title',
    'customer_profile',
    'symptom_tags',
    'product_tags',
    'scenario',
    'summary',
    'content',
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
        return title, self.description, body


def recognize_case_from_link(url):
    source_url = (url or '').strip()
    if not source_url:
        raise CaseRecognitionError('请输入案例链接')

    warnings = []
    _assert_safe_url(source_url)
    html, final_url = _fetch_html(source_url)
    title, description, body = _extract_html_content(html, final_url)
    if not body and not description:
        warnings.append('页面正文为空，请手动补充详细记录')

    raw_text = _clean_text(' '.join([title, description, body]))
    raw_excerpt = raw_text[:1800]
    fields = _fallback_fields(source_url, title, description, body)

    ai_fields, ai_warning = _extract_fields_with_ai(raw_excerpt)
    if ai_warning:
        warnings.append(ai_warning)
    if ai_fields:
        fields.update(_normalize_ai_fields(ai_fields))
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
    title, description, body = parser.result()
    return title, description, body[:12000]


def _extract_fields_with_ai(raw_excerpt):
    if not raw_excerpt:
        return None, '页面正文为空，无法进行 AI 识别'
    api_key = get_secret_setting('coze_api_key', Config.COZE_API_KEY)
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


def _fallback_fields(source_url, title, description, body):
    summary_source = description or body
    return {
        'title': title or '未命名案例',
        'customer_profile': '',
        'symptom_tags': '',
        'product_tags': '',
        'scenario': '',
        'summary': _truncate(summary_source, 120),
        'content': body or description or '',
        'status': 1,
        'sort_order': 0,
    }


def _normalize_ai_fields(data):
    fields = {}
    for key in CASE_RECOGNITION_FIELDS:
        if key in ('status', 'sort_order'):
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


# ===== 批量识别：一段文字（按行拆分）或表格（前端解析为行文本） =====

BATCH_TEXT_FIELDS = ('title', 'customer_profile', 'scenario', 'summary', 'content')
BATCH_TAG_FIELDS = (('symptom_tags', 'symptom'), ('product_tags', 'product'))
MAX_BATCH_ROWS = 40
AI_BATCH_SIZE = 8
MAX_ROW_CHARS = 800
TAG_LABELS = {'symptom': '症状标签', 'product': '产品标签'}


def recognize_cases_from_rows(rows):
    """把多行原始文本（表格行或粘贴的分段）批量识别为案例档案字段。"""
    cleaned = []
    for item in rows or []:
        text = _clean_text(str(item or ''))
        if text:
            cleaned.append(text[:MAX_ROW_CHARS])
    if not cleaned:
        raise CaseRecognitionError('没有识别到有效内容，请检查输入')
    if len(cleaned) > MAX_BATCH_ROWS:
        raise CaseRecognitionError(
            f'单次最多识别 {MAX_BATCH_ROWS} 条，当前 {len(cleaned)} 条，请拆分后再试'
        )

    vocabulary = _load_tag_vocabulary()
    total_tags = len(vocabulary.get('symptom', [])) + len(vocabulary.get('product', []))
    warnings = []
    cases = []

    for start in range(0, len(cleaned), AI_BATCH_SIZE):
        chunk = cleaned[start:start + AI_BATCH_SIZE]
        ai_items, ai_warning = _extract_batch_fields_with_ai(chunk, vocabulary)
        if ai_warning:
            warnings.append(ai_warning)
        if not ai_items:
            for text in chunk:
                cases.append(_fallback_row_fields(text))
            continue
        for offset, text in enumerate(chunk):
            row_no = start + offset + 1
            item = ai_items[offset] if offset < len(ai_items) else None
            if not isinstance(item, dict):
                cases.append(_fallback_row_fields(text))
                warnings.append(f'第 {row_no} 条 AI 未返回结果，已按原文填充，请人工确认')
                continue
            cases.append(_normalize_batch_row(item, text, vocabulary, warnings, row_no))

    if total_tags == 0:
        warnings.append('标准标签库为空，标签需人工补充；可在案例设置里先维护标签')
    return {
        'cases': cases,
        'warnings': _dedupe_warnings(warnings),
        'total': len(cases),
    }


def _load_tag_vocabulary():
    vocabulary = {'symptom': [], 'product': []}
    try:
        rows = get_case_tags()
    except Exception as exc:  # 标签库不可用不应阻断识别
        logger.info('load case tags failed: %s', exc)
        return vocabulary
    for row in rows or []:
        tag_type = row.get('type')
        if tag_type not in vocabulary or not int(row.get('status', 1) or 0):
            continue
        name = _clean_text(str(row.get('name') or ''))
        if name:
            vocabulary[tag_type].append({'name': name, 'aliases': _split_tags(row.get('aliases'))})
    return vocabulary


def _extract_batch_fields_with_ai(chunk, vocabulary):
    api_key = get_secret_setting('coze_api_key', Config.COZE_API_KEY)
    if not api_key:
        return None, '未配置 Coze API Key，已使用规则识别结果'
    try:
        response = requests.post(
            Config.COZE_API_URL,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'bot_id': Config.DEFAULT_BOT_ID,
                'user': 'case-batch-recognizer',
                'query': _build_batch_prompt(chunk, vocabulary),
                'stream': False,
            },
            timeout=(5, 60),
        )
        response.raise_for_status()
        items = _parse_json_payload(_extract_coze_answer(response.json()))
        if not isinstance(items, list) or not items:
            return None, 'AI 返回格式不可用，已降级为规则识别'
        return items, ''
    except Exception as exc:
        logger.info('case batch recognition ai fallback: %s', exc)
        return None, 'AI 识别失败，已降级为规则识别'


def _build_batch_prompt(chunk, vocabulary):
    lines = [f'[{idx}] {text}' for idx, text in enumerate(chunk, 1)]
    return (
        '你是客户案例档案整理助手。下面是一批客户案例的原始记录，每条以 [序号] 开头。\n'
        '请逐条抽取字段，只返回一个严格 JSON 数组，数组长度必须与记录条数一致，不要输出解释或代码围栏。\n'
        '数组每项包含：title, customer_profile, symptom_tags, product_tags, scenario, summary, content。\n'
        f'候选症状标签（只许从中挑选，没有合适的就留空字符串）：{_vocabulary_hint(vocabulary.get("symptom"))}\n'
        f'候选产品标签（只许从中挑选，没有合适的就留空字符串）：{_vocabulary_hint(vocabulary.get("product"))}\n'
        '其他要求：标签多个用英文逗号分隔，最多 5 个；title 不超过 30 字，没有明确标题就概括；\n'
        'summary 控制在 120 字以内；content 保留关键背景、使用过程和反馈结果。\n\n'
        '原始记录：\n' + '\n'.join(lines)
    )


def _vocabulary_hint(entries):
    names = [entry.get('name') for entry in entries or [] if entry.get('name')]
    return '、'.join(names) if names else '（暂无候选）'


def _normalize_batch_row(item, raw_text, vocabulary, warnings, row_no):
    fields = {}
    for key in BATCH_TEXT_FIELDS:
        value = _clean_text(str(item.get(key) or ''))
        if value:
            fields[key] = value
    for key, tag_type in BATCH_TAG_FIELDS:
        matched, unmatched = _match_vocabulary_tags(item.get(key), vocabulary.get(tag_type))
        fields[key] = ','.join(matched)
        if unmatched:
            warnings.append(
                f'第 {row_no} 条的{TAG_LABELS[tag_type]}「{"、".join(unmatched)}」不在标准标签库，已忽略'
            )
    if not fields.get('title'):
        fields['title'] = _truncate(raw_text, 30) or '未命名案例'
    if not fields.get('content'):
        fields['content'] = raw_text
    if not fields.get('summary'):
        fields['summary'] = _truncate(fields['content'], 120)
    fields.setdefault('customer_profile', '')
    fields.setdefault('scenario', '')
    fields['status'] = 1
    fields['sort_order'] = 0
    return _normalize_fields(fields)


def _match_vocabulary_tags(raw_value, vocabulary):
    """把 AI 给出的标签映射到标准标签库（含别名），库中没有的一律丢弃。"""
    index = {}
    for entry in vocabulary or []:
        name = entry.get('name')
        if not name:
            continue
        index[name] = name
        for alias in entry.get('aliases') or []:
            index.setdefault(alias, name)
    matched, unmatched = [], []
    for part in re.split(r'[,，、;；/|]+', str(raw_value or '')):
        tag = part.strip()
        if not tag:
            continue
        canonical = index.get(tag)
        if canonical:
            if canonical not in matched:
                matched.append(canonical)
        elif tag not in unmatched:
            unmatched.append(tag)
    return matched, unmatched


def _fallback_row_fields(text):
    return _normalize_fields({
        'title': _truncate(text, 30) or '未命名案例',
        'customer_profile': '',
        'symptom_tags': '',
        'product_tags': '',
        'scenario': '',
        'summary': _truncate(text, 120),
        'content': text,
        'status': 1,
        'sort_order': 0,
    })


def _parse_json_payload(answer):
    """兼容 AI 返回数组、单个对象、或包在 cases/items/data 字段里的数组。"""
    answer = (answer or '').strip()
    if not answer:
        return None
    fenced = re.search(r'```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```', answer, re.S)
    if fenced:
        answer = fenced.group(1)
    else:
        match = re.search(r'(\[.*\]|\{.*\})', answer, re.S)
        if match:
            answer = match.group(0)
    try:
        data = json.loads(answer)
    except ValueError:
        return None
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ('cases', 'items', 'data', 'result'):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
        return [data]
    return None


def _split_tags(value):
    return [t.strip() for t in str(value or '').split(',') if t.strip()]
