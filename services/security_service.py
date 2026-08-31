import logging
import time
from collections import OrderedDict, deque
from functools import wraps
from threading import BoundedSemaphore, Lock

from flask import g, jsonify, request


logger = logging.getLogger(__name__)

_request_buckets = OrderedDict()
_bucket_lock = Lock()
_MAX_REQUEST_BUCKETS = 10_000


class ConcurrentRequestLimiter:
    """Non-blocking, process-local concurrency limiter for long requests."""

    def __init__(self, limit):
        self.limit = max(1, int(limit))
        self._semaphore = BoundedSemaphore(self.limit)
        self._active = 0
        self._active_lock = Lock()

    @property
    def active(self):
        with self._active_lock:
            return self._active

    def try_acquire(self):
        if not self._semaphore.acquire(blocking=False):
            return None
        with self._active_lock:
            self._active += 1
            return self._active

    def release(self):
        with self._active_lock:
            if self._active <= 0:
                raise RuntimeError('Concurrent request limiter released without an active request')
            self._semaphore.release()
            self._active -= 1
            return self._active


def rate_limit(scope, limit, window_seconds=60):
    """Small per-process limiter; deployment-level limiting should remain the outer layer."""
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            identity = getattr(g, 'request_identity', None) or {}
            if not identity and scope.startswith(('chat', 'handoff', 'lead')):
                logger.warning(
                    'rate_limit scope=%s without request_identity; falling back to IP-based limiting',
                    scope,
                )
            subject = identity.get('user_id') or request.remote_addr or 'unknown'
            key = f'{scope}:{subject}'
            now = time.monotonic()
            cutoff = now - window_seconds

            with _bucket_lock:
                bucket = _request_buckets.get(key)
                if bucket is None:
                    if len(_request_buckets) >= _MAX_REQUEST_BUCKETS:
                        _request_buckets.popitem(last=False)
                    bucket = deque()
                    _request_buckets[key] = bucket
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= limit:
                    retry_after = max(1, int(window_seconds - (now - bucket[0])))
                    response = jsonify({'error': '请求过于频繁，请稍后重试', 'retry_after': retry_after})
                    response.status_code = 429
                    response.headers['Retry-After'] = str(retry_after)
                    return response
                bucket.append(now)
                _request_buckets.move_to_end(key)
                if not bucket:
                    # Keep the OrderedDict bounded even when keys become empty.
                    _request_buckets.pop(key, None)

            return func(*args, **kwargs)
        return wrapped
    return decorator


def reset_rate_limits_for_tests():
    with _bucket_lock:
        _request_buckets.clear()
