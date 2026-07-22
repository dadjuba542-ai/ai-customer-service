import json
import logging
import os
import time
from threading import Lock

from flask import Blueprint, Response, jsonify, request, stream_with_context

from config import Config
from routes.auth import identity_required
from services.security_service import ConcurrentRequestLimiter, rate_limit
from services.chat_service import ChatServiceError, build_chat_context, execute_sync_chat, iter_coze_stream
from services.chat_queue_service import (
    cancel_job,
    enqueue_job,
    get_dispatcher,
    get_job,
    has_waiting_jobs,
)

chat_bp = Blueprint('chat', __name__)
logger = logging.getLogger(__name__)
_stream_limiter = ConcurrentRequestLimiter(Config.CHAT_STREAM_MAX_CONCURRENT_PER_WORKER)


@chat_bp.route('/send', methods=['POST'])
@identity_required
@rate_limit('chat', limit=Config.CHAT_RATE_LIMIT, window_seconds=60)
def send_to_coze(identity):
    try:
        ctx = build_chat_context(request.get_json(silent=True) or {}, identity)
        return jsonify(execute_sync_chat(ctx))
    except ChatServiceError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code


@chat_bp.route('/stream', methods=['POST'])
@identity_required
@rate_limit('chat', limit=Config.CHAT_RATE_LIMIT, window_seconds=60)
def stream_to_coze(identity):
    try:
        ctx = build_chat_context(request.get_json(silent=True) or {}, identity)
    except ChatServiceError as exc:
        return jsonify({'error': exc.message, 'retryable': exc.retryable}), exc.status_code

    get_dispatcher(_stream_limiter)
    try:
        waiting = has_waiting_jobs()
    except Exception:
        logger.exception('chat.queue status check failed request_id=%s worker_pid=%s', ctx.request_id, os.getpid())
        waiting = False

    if waiting:
        return _enqueue_stream_request(ctx)

    active = _stream_limiter.try_acquire()
    if active is None:
        return _enqueue_stream_request(ctx)

    # A queued request may have arrived in another worker while this request
    # was acquiring the local slot. Give the existing queue priority.
    try:
        queue_arrived = has_waiting_jobs()
    except Exception:
        queue_arrived = False
    if queue_arrived:
        _stream_limiter.release()
        return _enqueue_stream_request(ctx)

    acquired_at = time.monotonic()
    release_lock = Lock()
    released = False

    logger.info(
        'chat.stream started request_id=%s worker_pid=%s active=%s limit=%s',
        ctx.request_id,
        os.getpid(),
        active,
        _stream_limiter.limit,
    )

    def release_slot():
        nonlocal released
        with release_lock:
            if released:
                return
            released = True
            remaining = _stream_limiter.release()
        duration_ms = int((time.monotonic() - acquired_at) * 1000)
        logger.info(
            'chat.stream finished request_id=%s worker_pid=%s active=%s duration_ms=%s',
            ctx.request_id,
            os.getpid(),
            remaining,
            duration_ms,
        )

    @stream_with_context
    def generate():
        try:
            for event in iter_coze_stream(ctx):
                yield _format_sse(event['event'], event['data'])
        except ChatServiceError as exc:
            yield _format_sse(
                'error',
                {
                    'message': exc.message,
                    'retryable': exc.retryable,
                    'request_id': ctx.request_id,
                },
            )
        finally:
            release_slot()

    headers = {
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    }
    response = Response(generate(), mimetype='text/event-stream', headers=headers)
    response.call_on_close(release_slot)
    return response


def _enqueue_stream_request(ctx):
    try:
        result = enqueue_job(ctx)
    except Exception:
        logger.exception('chat.queue enqueue failed request_id=%s worker_pid=%s', ctx.request_id, os.getpid())
        response = jsonify({
            'error': '当前排队服务暂时不可用，请稍后重试',
            'error_code': 'chat_queue_unavailable',
            'retryable': True,
            'retry_after': 5,
        })
        response.status_code = 503
        response.headers['Retry-After'] = '5'
        return response

    if result.get('duplicate'):
        response = jsonify({
            'error': '您已有一个问题正在排队或处理中，请稍候查看回答',
            'error_code': 'chat_pending',
            'retryable': False,
            'job': result['job'],
        })
        response.status_code = 409
        return response

    if result.get('full'):
        logger.warning(
            'chat.queue rejected_full request_id=%s worker_pid=%s queue_size=%s limit=%s',
            ctx.request_id,
            os.getpid(),
            result.get('queue_size'),
            Config.CHAT_QUEUE_MAX_SIZE,
        )
        response = jsonify({
            'error': '当前排队人数较多，请稍后重试',
            'error_code': 'chat_queue_full',
            'retryable': True,
            'retry_after': 5,
        })
        response.status_code = 503
        response.headers['Retry-After'] = '5'
        return response

    job = result['job']
    logger.info(
        'chat.queue queued job_id=%s request_id=%s worker_pid=%s position=%s queue_size=%s',
        job['job_id'],
        ctx.request_id,
        os.getpid(),
        result['position'],
        result['queue_size'],
    )
    response = jsonify({
        'status': 'queued',
        'job_id': job['job_id'],
        'position': result['position'],
        'queue_size': result['queue_size'],
        'retry_after': Config.CHAT_QUEUE_POLL_INTERVAL_SECONDS,
        'expires_in': result['expires_in'],
    })
    response.status_code = 202
    response.headers['Retry-After'] = str(Config.CHAT_QUEUE_POLL_INTERVAL_SECONDS)
    return response


@chat_bp.route('/jobs/<job_id>', methods=['GET'])
@identity_required
@rate_limit('chat-job-status', limit=120, window_seconds=60)
def chat_job_status(identity, job_id):
    job = get_job(str(job_id or ''), identity['user_id'])
    if not job:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(job)


@chat_bp.route('/jobs/<job_id>/cancel', methods=['POST'])
@identity_required
@rate_limit('chat-job-cancel', limit=20, window_seconds=60)
def chat_job_cancel(identity, job_id):
    job = cancel_job(str(job_id or ''), identity['user_id'])
    if not job:
        return jsonify({'error': '任务不存在'}), 404
    if job['status'] in {'queued', 'cancelled'}:
        return jsonify(job)
    if job['status'] == 'running':
        return jsonify({
            'error': '任务已经开始生成，暂时不能取消',
            'error_code': 'chat_job_running',
            'retryable': False,
            'status': job['status'],
        }), 409
    return jsonify(job), 409


@chat_bp.route('/feedback', methods=['POST'])
@identity_required
@rate_limit('feedback', limit=30, window_seconds=60)
def submit_feedback(identity):
    data = request.get_json(silent=True) or {}
    history_id = data.get('history_id')
    feedback = data.get('feedback')
    reason = (data.get('reason') or '').strip()[:200]

    if not history_id or feedback not in (0, 1):
        return jsonify({'error': 'history_id and feedback(0/1) are required'}), 400

    from models import set_chat_feedback, set_feedback_reason
    updated = set_chat_feedback(history_id, identity['user_id'], feedback)
    if not updated:
        return jsonify({'error': 'History record not found'}), 404
    if feedback == 0 and reason:
        set_feedback_reason(history_id, identity['user_id'], reason)
    return jsonify({'message': 'Feedback saved'})


def _format_sse(event_name, payload):
    return f'event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
