import json
import logging
import os
import threading
import time
import uuid

from config import Config
from models import get_db_connection
from services.chat_service import ChatServiceError, build_chat_context, execute_sync_chat


logger = logging.getLogger(__name__)

JOB_STATUSES = {'queued', 'running', 'completed', 'failed', 'expired', 'cancelled'}
ACTIVE_STATUSES = ('queued', 'running')
STALE_RUNNING_SECONDS = 180


def _now_request_id():
    return uuid.uuid4().hex[:12]


def _row_to_dict(row):
    return dict(row) if row else None


def _decode_json(value, fallback=None):
    try:
        return json.loads(value or '')
    except (TypeError, ValueError):
        return fallback if fallback is not None else {}


def queue_size():
    conn = get_db_connection()
    try:
        return int(conn.execute("SELECT COUNT(*) AS count FROM chat_jobs WHERE status = 'queued'").fetchone()['count'])
    finally:
        conn.close()


def has_waiting_jobs():
    return queue_size() > 0


def _position_locked(conn, job_id):
    row = conn.execute(
        '''SELECT COUNT(*) AS position
           FROM chat_jobs AS older
           JOIN chat_jobs AS current ON current.job_id = ?
          WHERE older.status = 'queued'
            AND (older.id < current.id)''',
        (job_id,),
    ).fetchone()
    return int(row['position']) + 1 if row else 1


def _public_job(row, conn=None):
    if not row:
        return None
    result = {
        'job_id': row['job_id'],
        'status': row['status'],
        'request_id': row['request_id'],
        'created_at': row['created_at'],
        'started_at': row['started_at'],
        'finished_at': row['finished_at'],
        'expires_at': row['expires_at'],
    }
    if row['status'] == 'queued' and conn is not None:
        result['position'] = _position_locked(conn, row['job_id'])
        result['queue_size'] = int(conn.execute("SELECT COUNT(*) AS count FROM chat_jobs WHERE status = 'queued'").fetchone()['count'])
    if row['status'] == 'completed':
        result.update(_decode_json(row['result_json']))
    if row['status'] in {'failed', 'expired', 'cancelled'}:
        result['error'] = row['error_message'] or '任务未能完成'
        result['error_code'] = row['error_code'] or f'chat_{row["status"]}'
        result['retryable'] = bool(row['status'] == 'failed')
    return result


def _cleanup_locked(conn):
    conn.execute(
        '''UPDATE chat_jobs
              SET status = 'expired', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                  error_code = 'chat_queue_expired', error_message = '排队时间过长，任务已取消'
            WHERE status = 'queued' AND expires_at <= CURRENT_TIMESTAMP'''
    )
    conn.execute(
        '''UPDATE chat_jobs
              SET status = 'expired', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                  error_code = 'chat_queue_expired', error_message = '任务已过期'
            WHERE status = 'running' AND expires_at <= CURRENT_TIMESTAMP'''
    )
    conn.execute(
        '''UPDATE chat_jobs
              SET status = 'queued', started_at = NULL, worker_pid = NULL, worker_token = '',
                  expires_at = datetime('now', ?), attempt = attempt + 1,
                  updated_at = CURRENT_TIMESTAMP
            WHERE status = 'running'
              AND started_at <= datetime('now', ?)
              AND expires_at > CURRENT_TIMESTAMP''',
        (f'+{Config.CHAT_QUEUE_TTL_SECONDS} seconds', f'-{STALE_RUNNING_SECONDS} seconds'),
    )


def enqueue_job(ctx):
    payload = {
        'message': ctx.message,
        'query_type': ctx.query_type,
        'agent_id': ctx.agent_id,
        'channel': getattr(ctx, 'channel', ''),
    }
    identity = {
        'user_id': ctx.user_id,
        'team_name': ctx.team_name,
        'member_name': ctx.member_name,
    }
    job_id = uuid.uuid4().hex
    request_id = ctx.request_id or _now_request_id()
    expires_seconds = max(60, int(Config.CHAT_QUEUE_TTL_SECONDS))
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        _cleanup_locked(conn)
        existing = conn.execute(
            '''SELECT * FROM chat_jobs
                WHERE user_id = ? AND status IN ('queued', 'running')
                ORDER BY id ASC LIMIT 1''',
            (ctx.user_id,),
        ).fetchone()
        if existing:
            conn.commit()
            return {'duplicate': True, 'job': _public_job(existing, conn)}

        count = conn.execute("SELECT COUNT(*) AS count FROM chat_jobs WHERE status = 'queued'").fetchone()['count']
        if count >= Config.CHAT_QUEUE_MAX_SIZE:
            conn.commit()
            return {'full': True, 'queue_size': int(count)}

        conn.execute(
            '''INSERT INTO chat_jobs
               (job_id, user_id, request_id, payload_json, identity_json, status, expires_at)
               VALUES (?, ?, ?, ?, ?, 'queued', datetime('now', ?))''',
            (
                job_id,
                ctx.user_id,
                request_id,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(identity, ensure_ascii=False),
                f'+{expires_seconds} seconds',
            ),
        )
        row = conn.execute('SELECT * FROM chat_jobs WHERE job_id = ?', (job_id,)).fetchone()
        position = _position_locked(conn, job_id)
        queue_count = int(conn.execute("SELECT COUNT(*) AS count FROM chat_jobs WHERE status = 'queued'").fetchone()['count'])
        conn.commit()
        return {
            'job': _public_job(row),
            'position': position,
            'queue_size': queue_count,
            'expires_in': expires_seconds,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_next_job(worker_pid=None):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        _cleanup_locked(conn)
        row = conn.execute(
            '''SELECT * FROM chat_jobs
                WHERE status = 'queued' AND expires_at > CURRENT_TIMESTAMP
                ORDER BY id ASC LIMIT 1'''
        ).fetchone()
        if not row:
            conn.commit()
            return None
        worker_token = uuid.uuid4().hex
        cursor = conn.execute(
            '''UPDATE chat_jobs
                  SET status = 'running', started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                      worker_pid = ?, worker_token = ?
                WHERE job_id = ? AND status = 'queued' ''',
            (str(worker_pid or os.getpid()), worker_token, row['job_id']),
        )
        if cursor.rowcount != 1:
            conn.commit()
            return None
        claimed = conn.execute('SELECT * FROM chat_jobs WHERE job_id = ?', (row['job_id'],)).fetchone()
        conn.commit()
        return _row_to_dict(claimed)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_job(job_id, result, worker_token=''):
    conn = get_db_connection()
    try:
        conn.execute(
            '''UPDATE chat_jobs
                  SET status = 'completed', result_json = ?, finished_at = CURRENT_TIMESTAMP,
                      updated_at = CURRENT_TIMESTAMP, error_code = '', error_message = ''
                WHERE job_id = ? AND status = 'running' AND worker_token = ? ''',
            (json.dumps(result or {}, ensure_ascii=False), job_id, worker_token),
        )
        conn.commit()
    finally:
        conn.close()


def fail_job(job_id, message, error_code='chat_failed', worker_token=''):
    conn = get_db_connection()
    try:
        conn.execute(
            '''UPDATE chat_jobs
                  SET status = 'failed', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                      error_code = ?, error_message = ?
                WHERE job_id = ? AND status = 'running' AND worker_token = ? ''',
            (error_code, str(message or '回答生成失败')[:500], job_id, worker_token),
        )
        conn.commit()
    finally:
        conn.close()


def get_job(job_id, user_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT * FROM chat_jobs WHERE job_id = ? AND user_id = ?',
            (job_id, user_id),
        ).fetchone()
        return _public_job(row, conn) if row else None
    finally:
        conn.close()


def cancel_job(job_id, user_id):
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            'SELECT * FROM chat_jobs WHERE job_id = ? AND user_id = ?',
            (job_id, user_id),
        ).fetchone()
        if not row:
            conn.commit()
            return None
        if row['status'] == 'queued':
            conn.execute(
                '''UPDATE chat_jobs
                      SET status = 'cancelled', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
                          error_code = 'chat_cancelled', error_message = '已取消排队'
                    WHERE job_id = ? AND status = 'queued' ''',
                (job_id,),
            )
            row = conn.execute('SELECT * FROM chat_jobs WHERE job_id = ?', (job_id,)).fetchone()
        conn.commit()
        return _public_job(row, conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class ChatQueueDispatcher:
    """A process-local dispatcher backed by the shared SQLite queue."""

    def __init__(self, limiter):
        self.limiter = limiter
        self._stop = threading.Event()
        self._thread = None
        self._jobs_lock = threading.Lock()
        self._jobs = set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='chat-queue-dispatcher', daemon=True)
        self._thread.start()

    def stop_for_tests(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        with self._jobs_lock:
            jobs = list(self._jobs)
        for job in jobs:
            job.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            try:
                self._dispatch_available()
            except Exception:
                logger.exception('chat.queue dispatcher error worker_pid=%s', os.getpid())
            self._stop.wait(max(1, int(Config.CHAT_QUEUE_POLL_INTERVAL_SECONDS)))

    def _dispatch_available(self):
        while not self._stop.is_set():
            active = self.limiter.try_acquire()
            if active is None:
                return
            job = None
            try:
                job = claim_next_job(os.getpid())
            except Exception:
                self.limiter.release()
                raise
            if not job:
                self.limiter.release()
                return
            thread = threading.Thread(
                target=self._process_job,
                args=(job, active),
                name=f'chat-queue-job-{job["job_id"][:8]}',
                daemon=True,
            )
            with self._jobs_lock:
                self._jobs.add(thread)
            try:
                thread.start()
            except Exception:
                with self._jobs_lock:
                    self._jobs.discard(thread)
                fail_job(job['job_id'], '任务启动失败', 'chat_dispatch_failed', job.get('worker_token', ''))
                self.limiter.release()
                raise

    def _process_job(self, job, active):
        started = time.monotonic()
        job_id = job['job_id']
        logger.info(
            'chat.queue started job_id=%s request_id=%s worker_pid=%s active=%s',
            job_id, job['request_id'], os.getpid(), active,
        )
        try:
            payload = _decode_json(job['payload_json'])
            identity = _decode_json(job['identity_json'])
            ctx = build_chat_context(payload, identity)
            ctx.request_id = job['request_id']
            result = execute_sync_chat(ctx)
            complete_job(job_id, result, job.get('worker_token', ''))
            logger.info(
                'chat.queue finished job_id=%s request_id=%s worker_pid=%s active=%s duration_ms=%s outcome=success',
                job_id, job['request_id'], os.getpid(), self.limiter.active,
                int((time.monotonic() - started) * 1000),
            )
        except ChatServiceError as exc:
            fail_job(job_id, exc.message, f'chat_upstream_{exc.status_code}', job.get('worker_token', ''))
            logger.warning(
                'chat.queue finished job_id=%s request_id=%s worker_pid=%s active=%s duration_ms=%s outcome=error',
                job_id, job['request_id'], os.getpid(), self.limiter.active,
                int((time.monotonic() - started) * 1000),
            )
        except Exception:
            fail_job(job_id, '回答生成失败，请稍后重试', 'chat_queue_failed', job.get('worker_token', ''))
            logger.exception(
                'chat.queue failed job_id=%s request_id=%s worker_pid=%s active=%s',
                job_id, job['request_id'], os.getpid(), self.limiter.active,
            )
        finally:
            self.limiter.release()
            with self._jobs_lock:
                self._jobs.discard(threading.current_thread())


_dispatchers = {}
_dispatchers_lock = threading.Lock()


def get_dispatcher(limiter):
    pid = os.getpid()
    with _dispatchers_lock:
        dispatcher = _dispatchers.get(pid)
        if dispatcher is None:
            dispatcher = ChatQueueDispatcher(limiter)
            _dispatchers[pid] = dispatcher
        dispatcher.start()
        return dispatcher
