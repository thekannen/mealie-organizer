from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException


class LoginRateLimiter:
    """Sliding-window rate limiter for login attempts, keyed by IP or username."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            attempts = [t for t in self._attempts[key] if t > cutoff]
            self._attempts[key] = attempts
            if len(attempts) >= self.max_attempts:
                raise HTTPException(
                    status_code=429,
                    detail="Too many login attempts. Try again later.",
                )

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._attempts[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


class ActionRateLimiter:
    """Simple per-key rate limiter for sensitive operations."""

    def __init__(self, max_per_minute: int = 30) -> None:
        self.max_per_minute = max_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            cutoff = now - 60
            hits = [t for t in self._hits[key] if t > cutoff]
            hits.append(now)
            self._hits[key] = hits
            if len(hits) > self.max_per_minute:
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down.",
                )
