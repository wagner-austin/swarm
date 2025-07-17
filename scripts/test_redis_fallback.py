#!/usr/bin/env python3
"""
Test script to demonstrate Redis fallback functionality.

Run this to see the automatic failover in action when Upstash rate limit is hit.
"""

import asyncio
import logging

from swarm.core.settings import Settings
from swarm.infra.redis_factory import create_redis_backend

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def main() -> None:
    """Test Redis backend with automatic fallback."""
    print("Testing Redis backend with automatic fallback...\n")

    # Create backend with automatic fallback
    backend = create_redis_backend()

    try:
        # Connect to Redis
        await backend.connect()
        print(f"Connected to Redis backend: {backend.name}")

        # Try some operations
        print("\nTesting basic operations:")

        # Set a value
        await backend.execute("set", "test:key", "Hello from swarm!")
        print("✓ SET operation successful")

        # Get the value
        value = await backend.execute("get", "test:key")
        print(f"✓ GET operation successful: {value}")

        # Test list operations
        await backend.execute("lpush", "test:list", "item1", "item2", "item3")
        print("✓ LPUSH operation successful")

        list_items = await backend.execute("lrange", "test:list", 0, -1)
        print(f"✓ LRANGE operation successful: {list_items}")

        # Test hash operations
        await backend.execute("hset", "test:hash", "field1", "value1", "field2", "value2")
        print("✓ HSET operation successful")

        hash_data = await backend.execute("hgetall", "test:hash")
        print(f"✓ HGETALL operation successful: {hash_data}")

        # Clean up test data
        await backend.execute("del", "test:key", "test:list", "test:hash")
        print("\n✓ Cleanup successful")

        print(
            f"\nAll operations completed successfully using: {backend._current_backend.name if hasattr(backend, '_current_backend') else backend.name}"
        )

    except Exception as e:
        print(f"\n✗ Error: {e}")
        logging.exception("Operation failed")
    finally:
        await backend.disconnect()
        print("\nDisconnected from Redis backend")


if __name__ == "__main__":
    asyncio.run(main())
