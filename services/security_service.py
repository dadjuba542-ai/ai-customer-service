import time
from collections import defaultdict, deque
from functools import wraps
from threading import Lock

from flask import g, jsonify, request


_request_buckets = defaultdict(deque)
_bucket_lock = Lock()


def rate_limit(scope, limit, window_seconds=60):
    """Small per-process limiter; deployment-level limiting should remain the outer layer."""
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            identity = getattr(g, 'request_identity', None) or {}
            subject = identity.get('user_id') or request.remote_addr or 'unknown'
            key = f'{scope}:{subject}'
            now = time.monotonic()
            cutoff = now - window_seconds

            with _bucket_lock:
                bucket = _request_buckets[key]
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= limit:
                    retry_after = max(1, int(window_seconds - (now - bucket[0])))
                    response = jsonify({'error': '请求过于频繁，请稍后重试', 'retry_after': retry_after})
                    response.status_code = 429
                    response.headers['Retry-After'] = str(retry_after)
                    return response
                bucket.append(now)

            return func(*args, **kwargs)
        return wrapped
    return decorator


def reset_rate_limits_for_tests():
    with _bucket_lock:
        _request_buckets.clear()
