#!/usr/bin/env python3
"""
Simple test script to submit a browser task to Celery.
This lets us test the system without needing Discord.
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swarm.tasks.browser import goto, screenshot


async def main() -> None:
    """Submit a test browser task."""
    print("Submitting browser goto task...")

    # Submit task asynchronously
    result = goto.delay(url="https://example.com")

    print(f"Task submitted! Task ID: {result.id}")
    print(f"Task state: {result.state}")

    # Wait a bit for task to process
    print("\nWaiting 5 seconds for task to process...")
    await asyncio.sleep(5)

    # Check result
    print(f"\nTask state: {result.state}")
    if result.ready():
        print(f"Result: {result.result}")
    else:
        print("Task still processing...")

    # Try a screenshot task
    print("\n\nSubmitting screenshot task...")
    screenshot_result = screenshot.delay(
        task_id=result.id  # Use the same task ID to share browser session
    )

    print(f"Screenshot task ID: {screenshot_result.id}")

    print("\nCheck Grafana/Prometheus for task metrics.")


if __name__ == "__main__":
    asyncio.run(main())
