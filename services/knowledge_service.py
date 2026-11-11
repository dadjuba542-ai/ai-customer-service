"""Small, agent-scoped text retrieval over the application's existing SQLite DB."""
import json
import re
from html import unescape
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from models import get_agent_config, get_db_connection

MAX_TEXT = 200_000
CHUNK_SIZE = 850
CHUNK_OVERLAP = 120
MAX_TEXT_UPLOAD_BYTES = 600_000
MAX_DOCX_UPLOAD_BYTES = 5_000_000
MAX_DOCX_EXPANDED_BYTES = 25_000_000


def extract_upload_text(filename, stream):
    """Read an upload into plain text without storing the original file."""
    extension = str(filename or '').rsplit('.', 1)[-1].lower()
    if extension == 'doc':
        raise ValueError('旧版 .doc 暂不支持，请在 Word 中另存为 .docx 后上传')
    if extension not in {'txt', 'md', 'docx'}:
        raise ValueError('仅支持 TXT、MD 或 DOCX 文件')
    max_bytes = MAX_DOCX_UPLOAD_BYTES if extension == 'docx' else MAX_TEXT_UPLOAD_BYTES
    raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('DOCX 文件不能超过5MB' if extension == 'docx' else '文本文件不能超过600KB')
    if extension != 'docx':
        try:
            return raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('TXT/MD 文件须为 UTF-8 编码') from exc

    try:
        with ZipFile(BytesIO(raw)) as archive:
            parts = archive.infolist()
            if (len(parts) > 1000 or
                    sum(part.file_size for part in parts) > MAX_DOCX_EXPANDED_BYTES or
                    'word/document.xml' not in archive.namelist()):
                raise ValueError('Word 文件内容过大或格式不正确')
    except BadZipFile as exc:
        raise ValueError('无法读取 DOCX 文件，请确认文件未损坏') from exc

    from docx import Document
    from docx.opc.exceptions import PackageNotFoundError
    from docx.table import Table
    try:
        document = Document(BytesIO(raw))
    except (PackageNotFoundError, ValueError, KeyError, BadZipFile) as exc:
        raise ValueError('无法读取 DOCX 文件，请确认文件未加密或损坏') from exc
    lines = []
    total_chars = 0
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                line = ' | '.join(cell for cell in cells if cell)
                if line:
                    lines.append(line)
                    total_chars += len(line)
        else:
            line = block.text.strip()
            if line:
                lines.append(line)
                total_chars += len(line)
        if total_chars > MAX_TEXT:
            raise ValueError('提取后的 Word 正文不能超过20万字')
    return '\n'.join(lines)


def _chunks(content):
    content = content.strip()
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for start in range(0, len(content), step):
        part = content[start:start + CHUNK_SIZE].strip()
        if part:
            yield part
        if start + CHUNK_SIZE >= len(content):
            break


def _validate(title, content, agent_ids):
    title = str(title or '').strip()
    content = str(content or '').strip()
    if not title or len(title) > 150:
        raise ValueError('资料标题不能为空且不能超过150字')
    if not content or len(content) > MAX_TEXT:
        raise ValueError('资料正文不能为空且不能超过20万字')
    if not isinstance(agent_ids, list) or not agent_ids or len(agent_ids) > 30:
        raise ValueError('请至少选择一个智能体')
    ids = list(dict.fromkeys(str(item) for item in agent_ids))
    if any(not get_agent_config(item) for item in ids):
        raise ValueError('智能体不存在')
    return title, content, ids


def save_document(title, content, agent_ids, document_id=None, enabled=True):
    title, content, agent_ids = _validate(title, content, agent_ids)
    conn = get_db_connection()
    try:
        conn.execute('BEGIN')
        if document_id is None:
            document_id = conn.execute(
                'INSERT INTO knowledge_documents(title, content, agent_ids, enabled) VALUES(?,?,?,?)',
                (title, content, json.dumps(agent_ids), int(bool(enabled))),
            ).lastrowid
        else:
            old = conn.execute('SELECT id FROM knowledge_documents WHERE id=?', (document_id,)).fetchone()
            if not old:
                raise LookupError('资料不存在')
            conn.execute('UPDATE knowledge_documents SET title=?, content=?, agent_ids=?, enabled=?, '
                         'updated_at=CURRENT_TIMESTAMP WHERE id=?',
                         (title, content, json.dumps(agent_ids), int(bool(enabled)), document_id))
            ids = [row['id'] for row in conn.execute(
                'SELECT id FROM knowledge_chunks WHERE document_id=?', (document_id,))]
            conn.executemany('DELETE FROM knowledge_chunks_fts WHERE rowid=?', ((i,) for i in ids))
            conn.execute('DELETE FROM knowledge_chunks WHERE document_id=?', (document_id,))
        for position, part in enumerate(_chunks(content)):
            chunk_id = conn.execute(
                'INSERT INTO knowledge_chunks(document_id, position, content) VALUES(?,?,?)',
                (document_id, position, part),
            ).lastrowid
            conn.execute('INSERT INTO knowledge_chunks_fts(rowid, content) VALUES(?,?)',
                         (chunk_id, f'{title}\n{part}'))
        conn.commit()
        return document_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_documents(query='', agent_id=''):
    query = str(query or '').strip()[:100]
    agent_id = str(agent_id or '').strip()[:64]
    conn = get_db_connection()
    try:
        rows = conn.execute('''WITH matches AS (
                SELECT id, title, content, agent_ids, enabled, created_at, updated_at,
                       CASE WHEN ? = '' THEN 0 ELSE instr(lower(content), lower(?)) END AS match_pos
                FROM knowledge_documents
                WHERE (? = '' OR instr(lower(title), lower(?)) > 0
                       OR instr(lower(content), lower(?)) > 0)
                  AND (? = '' OR EXISTS(SELECT 1 FROM json_each(agent_ids) WHERE value = ?))
            )
            SELECT id, title, agent_ids, enabled, created_at, updated_at,
                   CASE WHEN match_pos > 0 THEN
                       substr(content, max(1, match_pos - 24), 190)
                   ELSE substr(content, 1, 160) END AS excerpt,
                   CASE WHEN match_pos > 25 THEN 1 ELSE 0 END AS excerpt_prefix,
                   CASE WHEN match_pos > 0 THEN match_pos - 1 ELSE NULL END AS match_offset
            FROM matches ORDER BY id DESC''',
            (query, query, query, query, query, agent_id, agent_id)).fetchall()
        return [{**dict(row), 'agent_ids': json.loads(row['agent_ids'])} for row in rows]
    finally:
        conn.close()


def get_document(document_id):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM knowledge_documents WHERE id=?', (document_id,)).fetchone()
        return {**dict(row), 'agent_ids': json.loads(row['agent_ids'])} if row else None
    finally:
        conn.close()


def delete_document(document_id):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN')
        ids = [row['id'] for row in conn.execute(
            'SELECT id FROM knowledge_chunks WHERE document_id=?', (document_id,))]
        if not ids:
            exists = conn.execute('SELECT id FROM knowledge_documents WHERE id=?', (document_id,)).fetchone()
            if not exists:
                return False
        conn.executemany('DELETE FROM knowledge_chunks_fts WHERE rowid=?', ((i,) for i in ids))
        conn.execute('DELETE FROM knowledge_chunks WHERE document_id=?', (document_id,))
        conn.execute('DELETE FROM knowledge_documents WHERE id=?', (document_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _query_terms(question):
    terms = []
    normalized = question.lower()
    simplified = re.sub(r'请问|我想|一下|怎么|如何|什么|是否|可以|应该|需要|能不能|吗|呢', '', normalized)
    for token in re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', normalized + ' ' + simplified):
        if len(token) >= 3:
            if re.search(r'[\u4e00-\u9fff]', token):
                terms.extend(token[i:i + 3] for i in range(len(token) - 2))
            else:
                terms.append(token)
    return list(dict.fromkeys(terms))[:32]


def search(question, agent_id, limit=4):
    terms = _query_terms(question)
    if not terms or not agent_id:
        return []
    expression = ' OR '.join('"' + term.replace('"', '') + '"' for term in terms)
    conn = get_db_connection()
    try:
        rows = conn.execute('''
            SELECT d.id AS document_id, d.title, c.id AS chunk_id, c.content,
                   bm25(knowledge_chunks_fts) AS rank
            FROM knowledge_chunks_fts
            JOIN knowledge_chunks c ON c.id=knowledge_chunks_fts.rowid
            JOIN knowledge_documents d ON d.id=c.document_id
            WHERE knowledge_chunks_fts MATCH ? AND d.enabled=1
              AND EXISTS(SELECT 1 FROM json_each(d.agent_ids) WHERE value=?)
            ORDER BY rank LIMIT ?
        ''', (expression, agent_id, max(1, min(int(limit), 8)))).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def search_products(question, limit=4):
    """Find current product records; the index is updated with each product edit."""
    terms = _query_terms(question)
    conn = get_db_connection()
    try:
        rows = conn.execute('''SELECT * FROM products
                               WHERE length(name)>=2 AND instr(lower(?), lower(name))>0
                               ORDER BY length(name) DESC LIMIT ?''',
                            (str(question or ''), limit)).fetchall()
        found = {row['id']: row for row in rows}
        if terms and len(found) < limit:
            expression = ' OR '.join('"' + term.replace('"', '') + '"' for term in terms)
            ranked = conn.execute('''SELECT p.* FROM products_fts
                                     JOIN products p ON p.id=products_fts.rowid
                                     WHERE products_fts MATCH ?
                                     ORDER BY bm25(products_fts) LIMIT ?''',
                                  (expression, limit)).fetchall()
            for row in ranked:
                found.setdefault(row['id'], row)
                if len(found) >= limit:
                    break
        results = []
        for row in list(found.values())[:limit]:
            detail = unescape(re.sub(r'<[^>]*>', ' ', str(row['content'] or '')))
            parts = [f'产品名称：{row["name"]}', f'分类：{row["category"]}']
            for label, key, cap in (('简介', 'summary', 400), ('亮点', 'highlights', 400),
                                    ('成分与含量', 'ingredients', 850),
                                    ('注意事项', 'precautions', 650),
                                    ('适用场景', 'use_cases', 650)):
                if row[key]:
                    parts.append(f'{label}：{str(row[key])[:cap]}')
            if detail.strip():
                parts.append('详情：' + re.sub(r'\s+', ' ', detail).strip()[:1800])
            results.append({'kind': 'product', 'product_id': row['id'],
                            'title': row['name'], 'content': '\n'.join(parts)[:4000]})
        return results
    finally:
        conn.close()


def product_catalog_preview(limit=40):
    """Small product overview for query planning, never used as final evidence."""
    conn = get_db_connection()
    try:
        rows = conn.execute('''SELECT p.id, p.name, p.summary, p.ingredients, p.use_cases,
                                      substr(f.content, 1, 700) AS indexed_text
                               FROM products p JOIN products_fts f ON f.rowid=p.id
                               ORDER BY p.sort_order ASC, p.id DESC LIMIT ?''',
                            (max(1, min(limit, 40)),)).fetchall()
        result = []
        for row in rows:
            result.append({'id': row['id'], 'name': row['name'],
                           'summary': str(row['summary'] or '')[:100],
                           'ingredients': str(row['ingredients'] or '')[:160],
                           'use_cases': str(row['use_cases'] or '')[:160],
                           'indexed_text': str(row['indexed_text'] or '')[:200]})
        return result
    finally:
        conn.close()
