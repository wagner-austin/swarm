# Test Fakes Documentation

## Overview

This directory contains fake implementations of external dependencies designed to make tests faster, more reliable, and easier to understand. Fakes simulate real behavior without requiring actual infrastructure.

## Available Fakes

### FakeRedisClient
- Simulates Redis operations in-memory
- Supports keys, hget/hset/hgetall, expire, streams
- Tracks call history for verification
- Can simulate connection failures

### FakeDiscordInteraction
- Simulates Discord interaction objects
- Tracks responses and followups
- No actual Discord connection required
- Provides realistic interaction flow

### FakeHistoryBackend
- In-memory conversation storage
- Simulates the history backend interface
- Configurable max turns
- Easy verification of recorded conversations

### FakeBroker
- Simulates message broker operations
- Supports publish/subscribe patterns
- Configurable response delays
- Can simulate timeouts

### FakeBrowserRuntime
- Simulates browser operations
- Already exists in codebase
- Supports screenshots, navigation, status checks

## Usage Examples

### Using FakeRedisClient

```python
from tests.fakes import FakeRedisClient

@pytest.fixture
def fake_redis():
    return FakeRedisClient()

async def test_something(fake_redis):
    # Use like real Redis
    await fake_redis.hset("key", "field", "value")
    result = await fake_redis.hget("key", "field")
    assert result == b"value"
    
    # Verify calls
    assert fake_redis.was_called("hset")
```

### Using FakeInteraction

```python
from tests.fakes import FakeInteraction

def test_discord_command():
    interaction = FakeInteraction(
        user_id=123,
        user_name="TestUser",
        channel_id=456
    )
    
    # Use in command
    await my_command(interaction)
    
    # Verify response
    last_response = interaction.get_last_response()
    assert "success" in last_response["content"]
```

### Using FakeHistoryBackend

```python
from tests.fakes import FakeHistoryBackend

async def test_chat_history():
    history = FakeHistoryBackend()
    
    # Record conversation
    await history.record(
        channel_id=1,
        user_id=2,
        user_name="User",
        prompt="Hello",
        response="Hi there!"
    )
    
    # Verify
    assert history.get_turn_count(1, 2) == 2
    recent = await history.recent(1, 2)
    assert recent[0]["content"] == "Hello"
```

## Best Practices

1. **Use fakes instead of mocks** when you need to test interactions with external systems
2. **Reset fakes between tests** using the `reset()` method
3. **Use call tracking** to verify methods were called correctly
4. **Simulate failures** by setting `should_fail=True` when creating fakes
5. **Keep fakes simple** - they should simulate behavior, not replicate entire systems

## When to Use Fakes vs Mocks

### Use Fakes When:
- Testing complex interactions with external systems
- You need stateful behavior (e.g., storing and retrieving data)
- Multiple components interact with the same dependency
- You want to test error scenarios reliably

### Use Mocks When:
- Testing simple method calls
- The interaction is trivial
- You're testing a single unit in isolation
- The real implementation is lightweight and fast

## Adding New Fakes

When creating new fakes:

1. Implement the same interface as the real component
2. Add call tracking with `_record_call()`
3. Include a `reset()` method
4. Support failure simulation with `should_fail` parameter
5. Keep behavior predictable and deterministic
6. Document any limitations or differences from real implementation