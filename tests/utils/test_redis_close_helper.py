"""Test the async_close_redis compatibility helper."""

import pytest

from swarm.infra import async_close_redis


class FakeRedisClient:
    """Fake Redis client for testing close behavior."""

    def __init__(self, has_aclose: bool) -> None:
        self.called = False
        self.has_aclose = has_aclose

        if has_aclose:
            # Define method with proper annotation
            async def aclose_method(self: "FakeRedisClient") -> None:
                self.called = True

            self.aclose = aclose_method.__get__(self, FakeRedisClient)
        else:
            # Define method with proper annotation
            async def close_method(self: "FakeRedisClient") -> None:
                self.called = True

            self.close = close_method.__get__(self, FakeRedisClient)


@pytest.mark.asyncio
@pytest.mark.parametrize("has_aclose", [True, False])
async def test_async_close_redis_helper(has_aclose: bool) -> None:
    """Test that the helper calls the right close method based on availability."""
    fake_client = FakeRedisClient(has_aclose)
    await async_close_redis(fake_client)
    assert fake_client.called, f"Expected close to be called (has_aclose={has_aclose})"
