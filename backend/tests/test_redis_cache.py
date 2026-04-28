"""Unit tests for Redis caching functionality in redis_client.py."""

import pytest
import json
from unittest.mock import patch
from redis_client import (
    get_redis,
    reset_redis,
    get_cached_user,
    invalidate_user_cache,
)


class TestGetRedis:
    """Tests for the get_redis singleton connection."""

    def test_returns_none_when_unavailable(self):
        """When Redis can't connect, get_redis() returns None."""
        reset_redis()  # Clear singleton state

        # Patch redis.Redis to fail on ping()
        with patch("redis_client.redis.Redis") as mock_redis_cls:
            mock_instance = mock_redis_cls.return_value
            mock_instance.ping.side_effect = Exception("Connection refused")

            result = get_redis()

            assert result is None
            mock_instance.ping.assert_called_once()

        reset_redis()  # Clean up for next test


class TestUserCache:
    """Tests for user profile caching functionality."""

    def test_get_cached_user_db_fallback(self, db_session, test_user, mock_redis_none):
        """When Redis unavailable, falls back to DB query."""
        reset_redis()  # Clear singleton state

        # Call get_cached_user with Redis unavailable
        user = get_cached_user(test_user.id, db_session)

        # Should return the user from DB
        assert user is not None
        assert user.id == test_user.id
        assert user.username == test_user.username
        assert user.email == test_user.email

        reset_redis()

    def test_get_cached_user_with_redis(self, db_session, test_user, mock_redis):
        """With Redis, caches and retrieves user."""
        reset_redis()  # Clear singleton state

        # First call - cache miss, should query DB and cache
        user1 = get_cached_user(test_user.id, db_session)
        assert user1 is not None
        assert user1.id == test_user.id

        # Verify data was cached in Redis
        cache_key = f"user:{test_user.id}"
        cached_data = mock_redis.get(cache_key)
        assert cached_data is not None
        parsed = json.loads(cached_data)
        assert parsed["id"] == test_user.id
        assert parsed["username"] == test_user.username
        assert parsed["email"] == test_user.email

        # Second call - cache hit, should not query DB again
        # (We can verify by checking the cached data still exists)
        user2 = get_cached_user(test_user.id, db_session)
        assert user2 is not None
        assert user2.id == test_user.id

        reset_redis()

    def test_invalidate_user_cache(self, db_session, test_user, mock_redis):
        """After invalidation, cached key is gone."""
        reset_redis()  # Clear singleton state

        cache_key = f"user:{test_user.id}"

        # First, cache the user
        user = get_cached_user(test_user.id, db_session)
        assert user is not None

        # Verify cache key exists
        assert mock_redis.exists(cache_key) == 1

        # Invalidate the cache
        invalidate_user_cache(test_user.id)

        # Verify cache key is gone
        assert mock_redis.exists(cache_key) == 0

        reset_redis()

    def test_invalidate_no_redis(self, test_user, mock_redis_none):
        """invalidate_user_cache is no-op when Redis unavailable."""
        reset_redis()  # Clear singleton state

        # Should not raise an exception
        try:
            invalidate_user_cache(test_user.id)
        except Exception as e:
            pytest.fail(f"invalidate_user_cache raised exception: {e}")

        reset_redis()
