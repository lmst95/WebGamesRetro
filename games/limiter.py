from __future__ import annotations

import threading
import time
from typing import Dict, Tuple

_lock = threading.Lock()
_buckets: Dict[str, Tuple[int, float]] = {}
_MAX_BUCKETS = 10000


def allow_request(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    with _lock:
        count, window_start = _buckets.get(key, (0, now))
        if now - window_start >= window_seconds:
            count = 0
            window_start = now
        count += 1
        _buckets[key] = (count, window_start)
        if len(_buckets) > _MAX_BUCKETS:
            _prune(now, window_seconds)
        return count <= limit


def _prune(now: float, window_seconds: int) -> None:
    expired = [key for key, (_, start) in _buckets.items() if now - start >= window_seconds]
    for key in expired:
        _buckets.pop(key, None)
