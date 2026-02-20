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
