#!/usr/bin/env python3
"""
Test Browser Job Submission
===========================

Simulates what happens when a Discord user runs /web commands.
"""

import asyncio
import sys
import time
from datetime import datetime

sys.path.insert(0, "/app")

from swarm.distributed.celery_browser import CeleryBrowserRuntime


async def test_browser_flow() -> bool:
    """Test the complete browser job flow."""
    print("=" * 60)
    print("BROWSER JOB TEST")
    print(f"Started at: {datetime.now()}")
    print("=" * 60)

    # Create browser runtime (same as Discord bot uses)
    browser = CeleryBrowserRuntime()

    try:
        # Test 1: Start browser
        print("\n1. Starting browser session...")
        await browser.start()
        print("✅ Browser started successfully")

        # Test 2: Navigate to URL
        print("\n2. Navigating to example.com...")
        await browser.goto("https://example.com")
        print("✅ Navigation completed")

        # Test 3: Take screenshot
        print("\n3. Taking screenshot...")
        screenshot_data = await browser.screenshot()
        print(f"✅ Screenshot taken ({len(screenshot_data)} bytes)")

        # Test 4: Get status
        print("\n4. Getting browser status...")
        status = await browser.status()
        print(f"✅ Status retrieved: {status}")

        print("\n🎉 All browser operations completed successfully!")
        return True

    except Exception as e:
        print(f"\n❌ Browser test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def monitor_queue_depth() -> None:
    """Monitor queue depth during the test."""
    import aiohttp

    print("\n" + "=" * 60)
    print("QUEUE MONITORING")
    print("=" * 60)

    # Flower-free: skip queue monitoring; keep a small heartbeat instead
    for _ in range(5):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Queue monitoring skipped (Flower-free)")
        await asyncio.sleep(2)


async def main() -> None:
    """Run browser test with monitoring."""
    # Run browser test and queue monitoring concurrently
    browser_task = asyncio.create_task(test_browser_flow())
    monitor_task = asyncio.create_task(monitor_queue_depth())

    # Wait for browser test to complete
    success = await browser_task

    # Cancel monitoring
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    if success:
        print("\n✅ Browser job test completed successfully!")
    else:
        print("\n❌ Browser job test failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
