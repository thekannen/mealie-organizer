from __future__ import annotations

import pytest
from fastapi import HTTPException

from cookdex.webui_server.rate_limit import ActionRateLimiter, LoginRateLimiter


class TestLoginRateLimiter:
    def test_allows_under_limit(self):
        limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
        limiter.check("user1")
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        limiter.check("user1")  # Should still pass (2 failures, limit is 3)

    def test_blocks_at_limit(self):
        limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)
        limiter.record_failure("user1")
        limiter.record_failure("user1")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("user1")
        assert exc_info.value.status_code == 429

    def test_clear_resets_count(self):
        limiter = LoginRateLimiter(max_attempts=1, window_seconds=60)
        limiter.record_failure("user1")
        limiter.clear("user1")
        limiter.check("user1")  # Should pass after clear

    def test_separate_keys_are_independent(self):
        limiter = LoginRateLimiter(max_attempts=1, window_seconds=60)
        limiter.record_failure("user1")
        limiter.check("user2")  # Different key, should pass


class TestActionRateLimiter:
    def test_allows_under_limit(self):
        limiter = ActionRateLimiter(max_per_minute=5)
        for _ in range(5):
            limiter.check("user1")

    def test_blocks_over_limit(self):
        limiter = ActionRateLimiter(max_per_minute=3)
        limiter.check("user1")
        limiter.check("user1")
        limiter.check("user1")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("user1")
        assert exc_info.value.status_code == 429

    def test_separate_keys_are_independent(self):
        limiter = ActionRateLimiter(max_per_minute=1)
        limiter.check("user1")
        limiter.check("user2")  # Different key, should pass
