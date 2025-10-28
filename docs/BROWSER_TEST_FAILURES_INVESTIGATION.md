# Browser Test Failures Investigation Report

**Date:** 2025-10-28
**Issue:** Intermittent timeout failures in browser integration tests
**Status:** Root cause identified, solution proposed

## Executive Summary

Browser integration tests are failing intermittently with 30-second timeouts when waiting for elements. The root cause is **resource exhaustion from leaked browser engines**, not network issues or selector problems. When engines accumulate, system resources are exhausted, causing new Chromium instances to take >30 seconds to launch instead of <1 second, which exceeds the hard-coded timeout.

## Failing Tests

1. `test_browser_click_thread_pool` - TimeoutError waiting for element
2. `test_cleanup_does_not_deadlock_and_clears_state` - Browser still active after cleanup

## Evidence

### 1. Engine Leak Statistics

From worker logs (container `82078cc653f9`):
```
Engines created:  129
Engines cleaned:  112
Engines leaked:   17 (13% failure rate)
```

### 2. Engine Count Progression

```
04:32:07 - Engine #9 created
04:34:29 - Engine #11 created
04:34:44 - Engine #12 created
04:34:44 - Engine #13 created
04:35:49 - Engine #13 created
04:35:55 - Engine #14 created
04:36:00 - Engine #15 created
04:36:01 - Engine #16 created  ← Peak accumulation
```

**Pattern:** Engines continuously accumulate throughout test run, never dropping below 11 after initial buildup.

### 3. Timeout Sequence

```json
{
  "asctime": "2025-10-28T04:32:07+0000",
  "message": "Creating browser engine for session 68de80f0-5590-4e8d-93f5-37804253f3f0"
}
{
  "asctime": "2025-10-28T04:32:07+0000",
  "message": "Launching Chromium (headless=True, DISPLAY=:99) in BrowserEngine.start"
}
{
  "asctime": "2025-10-28T04:32:07+0000",
  "message": "Stored engine for session 68de80f0... (total engines: 9)"
}
{
  "asctime": "2025-10-28T04:32:37+0000",  ← 30 seconds later
  "levelname": "ERROR",
  "message": "Task browser.wait_for[478f85c2...] raised unexpected: TimeoutError()",
  "exc_info": "asyncio.exceptions.CancelledError\n...\nTimeoutError"
}
```

**Critical observation:** The task times out exactly 30 seconds after starting, matching the hard-coded timeout in `engine.py:236`.

## Root Cause Analysis

### Primary Cause: Resource Exhaustion

When too many browser engines exist simultaneously:

1. **CPU exhaustion** - Each Chromium instance consumes significant CPU
2. **Memory exhaustion** - Each browser uses ~100-200MB RAM
3. **File descriptor exhaustion** - Each browser opens many file handles
4. **Launch delays** - Chrome takes >30s to start instead of <1s

### Why Engines Leak

Engines fail to clean up in ~13% of cases due to:

1. **Test failures before cleanup** - When `wait_for` times out, test may not reach `finally` block
2. **Test runner kills** - Test timeouts causing process termination
3. **Concurrent execution** - Engines created faster than cleanup can remove them
4. **Missing cleanup calls** - Some test patterns don't call cleanup (e.g., `browser.start` tasks)

### The Timeout Chain

```
Test calls wait_for()
  ↓
wait_for creates NEW engine (engine #9)
  ↓
engine.start() launches Chromium
  ↓
System resources exhausted (8 other Chrome instances running)
  ↓
Chrome takes >30 seconds to initialize
  ↓
engine.run_write() timeout (30s) fires BEFORE Chrome finishes launching
  ↓
asyncio.CancelledError → TimeoutError
  ↓
Test fails, cleanup may not run
  ↓
Engine leak persists, problem worsens
```

## Technical Details

### Hard-Coded Timeout

File: `swarm/browser/engine.py:236`

```python
async def run_write(self, fn: Callable[[], Awaitable[T]]) -> T:
    # ...
    future = asyncio.run_coroutine_threadsafe(_on_engine_loop(), loop)
    return await asyncio.wait_for(asyncio.wrap_future(future), timeout=30.0)  ← HARD-CODED
```

**Problem:** 30-second timeout is shorter than:
- Playwright's `wait_for` timeout (60 seconds via `timeout_ms=60000`)
- Browser launch time under resource exhaustion (can exceed 30s)

### Engine Storage

File: `swarm/tasks/browser.py:258-262`

```python
with _engines_lock:
    _engines[session_id] = engine
    engine_count = sum(1 for v in _engines.values() if isinstance(v, BrowserEngine))
    logger.info(f"Stored engine for session {session_id} (total engines: {engine_count})")
```

**Problem:** No limit enforcement. Engines accumulate indefinitely.

### Session ID Mismatch Pattern

Some test failures show session ID mismatches where `wait_for` creates a new engine instead of reusing the one from `goto`:

```
goto returns:     session_id = "36a63439-bf17-4e56-b492-de133674a441"
wait_for uses:    session_id = "68de80f0-5590-4e8d-93f5-37804253f3f0"  ← DIFFERENT!
```

**Potential causes:**
- Test passing wrong session_id
- Multiple workers with session affinity routing issues
- Router not finding affinity key (wrong DB, timing issue)

## Proof of Concept

### Leaked Sessions

17 sessions were created but never cleaned up:

```
141acff4-d54e-41e0-acfb-714187c26bd7  ← browser.start + goto + screenshot (NO cleanup called)
4938994d-e86e-45bf-a7e2-bcb4b4df0a23
e51f6a98-4d93-4b85-8922-934685af9489
b83e78f5-348d-4b95-aab0-746db59641b2
d7ab3035-a12b-4ae0-98d8-516255981392
... (12 more)
```

Example leaked session `141acff4`:
```
04:37:17 - browser.start task creates engine
04:37:17 - browser.goto succeeds
04:37:17 - browser.screenshot received
           ← NO cleanup task ever called
```

**Pattern:** Tests using `browser.start` don't call cleanup, tests timing out don't reach cleanup.

## Root Cause Diagnosis

The fundamental issue is **missing lifecycle management** for browser sessions. The system has no automatic cleanup mechanism, relying entirely on manual cleanup calls which are fragile and error-prone.

### Architectural Flaws

1. **No session lifecycle tracking** - Sessions created but never expire
2. **No automatic cleanup** - Entirely relies on manual cleanup() calls
3. **No worker-level cleanup** - Engines orphaned when worker shuts down
4. **Test design dependency** - Production code depends on tests being perfect
5. **No resource limits** - Engines can accumulate unbounded

## Proper Integrated Solution

### 1. Session Lifecycle Management (Core Fix)

**Problem:** Sessions have no concept of lifecycle, TTL, or automatic expiration.

**Solution:** Implement proper session lifecycle with TTL and automatic cleanup.

**Location:** `swarm/distributed/session_lifecycle.py` (new file)

```python
"""
Session lifecycle management with automatic TTL-based cleanup.

Design principles:
- Sessions automatically expire after TTL (default 1 hour)
- Background cleanup job removes expired sessions
- Sessions can be extended (heartbeat pattern)
- Worker shutdown cleans up owned sessions
"""

import asyncio
import time
from typing import Dict, Set
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class SessionMetadata:
    session_id: str
    worker_id: str
    created_at: float
    last_activity: float
    ttl_seconds: float = 3600  # 1 hour default

class SessionLifecycleManager:
    """Manages session lifecycle with automatic TTL-based cleanup."""

    def __init__(self, cleanup_interval: float = 60.0):
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task | None = None
        self._sessions: Dict[str, SessionMetadata] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("SessionLifecycleManager started")

    async def stop(self):
        """Stop background cleanup and clean all sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cleanup all remaining sessions
        async with self._lock:
            session_ids = list(self._sessions.keys())

        for sid in session_ids:
            await self._cleanup_session(sid)

        logger.info("SessionLifecycleManager stopped")

    async def register_session(
        self,
        session_id: str,
        worker_id: str,
        ttl_seconds: float = 3600
    ):
        """Register a new session with TTL."""
        async with self._lock:
            self._sessions[session_id] = SessionMetadata(
                session_id=session_id,
                worker_id=worker_id,
                created_at=time.time(),
                last_activity=time.time(),
                ttl_seconds=ttl_seconds
            )
        logger.info(f"Registered session {session_id} with TTL {ttl_seconds}s")

    async def heartbeat_session(self, session_id: str):
        """Update session last_activity to extend TTL."""
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].last_activity = time.time()

    async def unregister_session(self, session_id: str):
        """Manually unregister and cleanup session."""
        async with self._lock:
            self._sessions.pop(session_id, None)
        await self._cleanup_session(session_id)
        logger.info(f"Unregistered session {session_id}")

    async def _cleanup_loop(self):
        """Background task that periodically cleans up expired sessions."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}", exc_info=True)

    async def _cleanup_expired_sessions(self):
        """Find and cleanup sessions that exceeded their TTL."""
        now = time.time()
        expired = []

        async with self._lock:
            for sid, meta in self._sessions.items():
                age = now - meta.last_activity
                if age > meta.ttl_seconds:
                    expired.append(sid)

        if expired:
            logger.info(f"Found {len(expired)} expired sessions to cleanup")
            for sid in expired:
                await self.unregister_session(sid)

    async def _cleanup_session(self, session_id: str):
        """Actually cleanup the browser engine for a session."""
        from swarm.tasks.browser import _engines, _engines_lock
        from swarm.browser.engine import BrowserEngine
        from swarm.distributed.session_registry import SessionRegistry

        # Remove from engine registry
        with _engines_lock:
            engine = _engines.pop(session_id, None)

        # Stop the engine
        if isinstance(engine, BrowserEngine):
            try:
                await engine.stop(graceful=True)
                logger.info(f"Cleaned up engine for session {session_id}")
            except Exception as e:
                logger.error(f"Error stopping engine for {session_id}: {e}")

        # Clear affinity
        try:
            registry = SessionRegistry()
            await registry.clear_owner(session_id)
        except Exception as e:
            logger.debug(f"Error clearing affinity for {session_id}: {e}")
```

### 2. Worker Shutdown Hook (Guaranteed Cleanup)

**Problem:** Workers shut down without cleaning up their engines.

**Solution:** Add shutdown handler to cleanup all owned sessions.

**Location:** `swarm/celery_worker.py`

```python
import signal
import asyncio
from swarm.distributed.session_lifecycle import SessionLifecycleManager

# Global lifecycle manager instance
lifecycle_manager = SessionLifecycleManager()

async def cleanup_all_sessions():
    """Cleanup all sessions on worker shutdown."""
    logger.info("Worker shutting down, cleaning up all sessions...")
    await lifecycle_manager.stop()
    logger.info("All sessions cleaned up")

def shutdown_handler(signum, frame):
    """Handle SIGTERM/SIGINT by cleaning up sessions."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(cleanup_all_sessions())
    finally:
        loop.close()
    sys.exit(0)

# Register shutdown handlers
signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

# Start lifecycle manager when worker starts
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(lifecycle_manager.start())
```

### 3. Integrate with Browser Tasks

**Problem:** Tasks create sessions but don't register them with lifecycle manager.

**Solution:** Auto-register sessions on creation, heartbeat on activity.

**Location:** `swarm/tasks/browser.py`

```python
async def get_or_create_engine(self, session_id: str) -> BrowserEngine:
    """Get or create browser engine with lifecycle management."""
    from swarm.distributed.session_lifecycle import lifecycle_manager

    # ... existing code ...

    # After creating engine
    engine = BrowserEngine(headless=True, proxy=None, timeout_ms=60000)
    await engine.start()

    with _engines_lock:
        _engines[session_id] = engine

    # Register with lifecycle manager
    worker_id = canonical_worker_id(getattr(self.request, "hostname", None))
    await lifecycle_manager.register_session(
        session_id=session_id,
        worker_id=worker_id,
        ttl_seconds=3600  # 1 hour
    )

    # ... rest of code ...

# Add heartbeat to every task that uses a session
async def goto(self, url: str, session_id: str | None = None):
    from swarm.distributed.session_lifecycle import lifecycle_manager

    session_id = self.resolve_session_id(session_id)
    engine = await self.get_or_create_engine(session_id)

    # Heartbeat to extend TTL
    await lifecycle_manager.heartbeat_session(session_id)

    await engine.goto(url)
    # ... rest of code ...
```

### 4. Fix Tests with Guaranteed Cleanup

**Problem:** Tests rely on manual cleanup which fails when tests timeout/error.

**Solution:** Use pytest fixtures with guaranteed cleanup in teardown.

**Location:** `tests/conftest.py`

```python
import pytest
from typing import List

# Track all sessions created during test run
_test_sessions: List[str] = []

@pytest.fixture(autouse=True)
def cleanup_test_sessions():
    """Automatically cleanup all sessions created during test."""
    global _test_sessions
    _test_sessions = []

    yield

    # Guaranteed cleanup in teardown (runs even if test fails)
    if _test_sessions:
        from swarm.tasks.browser import cleanup
        for session_id in _test_sessions:
            try:
                cleanup.delay(session_id=session_id).get(timeout=5)
            except Exception as e:
                # Best effort cleanup, don't fail test
                pass
        _test_sessions = []

@pytest.fixture
def track_session():
    """Helper to track sessions for auto-cleanup."""
    def _track(session_id: str):
        _test_sessions.append(session_id)
        return session_id
    return _track
```

**Usage in tests:**

```python
def test_browser_click(track_session):
    goto_res = goto.delay(url="https://example.com").get(timeout=30)
    session_id = track_session(goto_res["session_id"])  # Auto-cleanup on teardown

    # Test code - cleanup happens automatically even if this fails
    wait_for.delay(session_id=session_id, selector="a").get(timeout=60)
    click.delay(session_id=session_id, selector="a").get(timeout=30)
```

### 5. Add Resource Limits (Safety Net)

**Problem:** No upper bound on engine count per worker.

**Solution:** Enforce limits with proper logging and rejection.

**Location:** `swarm/tasks/browser.py`

```python
MAX_ENGINES_PER_WORKER = 10  # Hard limit

async def get_or_create_engine(self, session_id: str) -> BrowserEngine:
    # Check limit before creating
    with _engines_lock:
        engine_count = sum(1 for v in _engines.values() if isinstance(v, BrowserEngine))

        if engine_count >= MAX_ENGINES_PER_WORKER:
            # Log all current sessions for debugging
            session_ids = [sid for sid, v in _engines.items() if isinstance(v, BrowserEngine)]
            logger.error(
                f"Engine limit reached ({engine_count}/{MAX_ENGINES_PER_WORKER}). "
                f"Active sessions: {session_ids}"
            )
            raise RuntimeError(
                f"Worker at capacity ({engine_count} engines). "
                "Sessions may have leaked. Check logs for cleanup issues."
            )

    # ... rest of creation logic ...
```

## Implementation Plan

### Step 1: Core Infrastructure (Week 1)
- [ ] Create `session_lifecycle.py` with SessionLifecycleManager
- [ ] Add worker shutdown hooks in `celery_worker.py`
- [ ] Write unit tests for lifecycle manager
- [ ] Add integration test for TTL-based cleanup

### Step 2: Integration (Week 1)
- [ ] Integrate lifecycle manager with browser tasks
- [ ] Add session registration on engine creation
- [ ] Add heartbeat calls to all browser tasks
- [ ] Update cleanup task to unregister from lifecycle manager

### Step 3: Test Fixes (Week 2)
- [ ] Add auto-cleanup fixture to `conftest.py`
- [ ] Update all browser tests to use `track_session` fixture
- [ ] Remove manual cleanup calls (now handled by fixture)
- [ ] Add tests for cleanup-on-failure scenarios

### Step 4: Monitoring (Week 2)
- [ ] Add Prometheus metrics for active sessions
- [ ] Add Prometheus metrics for expired/cleaned sessions
- [ ] Add alerts for session leaks (count growing over time)
- [ ] Add Grafana dashboard for session lifecycle

### Step 5: Validation (Week 2)
- [ ] Run full test suite 20 times, verify zero leaks
- [ ] Load test with concurrent sessions
- [ ] Test worker shutdown cleanup
- [ ] Test TTL expiration cleanup

## Testing Strategy

### Verify the Fix

```bash
# Run tests that previously failed
poetry run pytest tests/integration/test_browser_thread_pool.py::test_browser_click_thread_pool -xvs
poetry run pytest tests/integration/test_browser_session_affinity.py::test_cleanup_does_not_deadlock_and_clears_state -xvs

# Monitor engine count
docker logs <worker-id> 2>&1 | grep "total engines" | tail -20

# Verify no engines leak
docker logs <worker-id> 2>&1 | python -c "
import sys, re
created = set()
cleaned = set()
for line in sys.stdin:
    if m := re.search(r'Stored engine for session ([a-f0-9-]+)', line):
        created.add(m.group(1))
    elif m := re.search(r'Cleaned up browser engine for session ([a-f0-9-]+)', line):
        cleaned.add(m.group(1))
print(f'Leaked: {len(created - cleaned)} sessions')
"
```

### Success Criteria

#### After Step 1-2 (Infrastructure):
- ✅ SessionLifecycleManager passes all unit tests
- ✅ Worker shutdown cleanly removes all sessions
- ✅ TTL-based cleanup removes expired sessions within 60s of expiration
- ✅ Background cleanup loop runs without errors

#### After Step 3 (Test Fixes):
- ✅ All tests use `track_session` fixture
- ✅ Tests pass consistently even when they fail/timeout
- ✅ Zero manual cleanup calls in tests (all automatic)
- ✅ Cleanup happens in teardown even on test failure

#### After Step 4-5 (Monitoring & Validation):
- ✅ Prometheus metrics show session count trends
- ✅ Grafana dashboard shows session lifecycle
- ✅ 20 consecutive full test runs with zero leaks
- ✅ Load test: 100 concurrent sessions with zero leaks
- ✅ Worker shutdown test: all sessions cleaned
- ✅ TTL test: sessions expire after inactivity

### Metrics to Track

```python
# Prometheus metrics to add

browser_sessions_active{worker_id}            # Current active sessions
browser_sessions_created_total{worker_id}     # Counter of sessions created
browser_sessions_cleaned_total{worker_id}     # Counter of sessions cleaned
browser_sessions_expired_total{worker_id}     # Counter of TTL expirations
browser_sessions_leaked_total{worker_id}      # Counter of force cleanups
browser_engines_active{worker_id}             # Current engine count
```

## Related Issues

- #XXX - Worker heartbeat tests also using DB 15 (fixed with cache clearing)
- #XXX - HAProxy container failing to start (fixed by removing dotenv dependency)
- #XXX - Redis DB mismatch between router and workers (fixed by using DB 0 for integration tests)

## Appendix A: Log Analysis Commands

```bash
# Count engines created vs cleaned
docker logs <worker-id> 2>&1 | grep "Stored engine" | wc -l
docker logs <worker-id> 2>&1 | grep "Cleaned up browser engine" | wc -l

# Find leaked sessions
docker logs <worker-id> 2>&1 | python -c "
import sys, re
created = set()
cleaned = set()
for line in sys.stdin:
    if m := re.search(r'Stored engine for session ([a-f0-9-]+)', line):
        created.add(m.group(1))
    elif m := re.search(r'Cleaned up browser engine for session ([a-f0-9-]+)', line):
        cleaned.add(m.group(1))
for s in created - cleaned:
    print(s)
"

# Track engine count over time
docker logs <worker-id> 2>&1 | grep "total engines:" | \
  awk '{print $2, $NF}' | sed 's/[()]//g'

# Monitor session lifecycle
docker logs <worker-id> 2>&1 | grep "SessionLifecycleManager" | tail -20
```

## Appendix B: Design Rationale

### Why TTL-Based Cleanup?

**Alternatives considered:**

1. **Reference counting** - Complex, error-prone, doesn't handle crashes
2. **Manual cleanup only** - Current approach, proven unreliable
3. **Connection pooling** - Major architectural change, doesn't solve leak problem
4. **TTL-based (chosen)** - Simple, robust, handles all failure modes

**TTL advantages:**
- Automatically cleans up after crashes, timeouts, forgotten cleanup
- Extends on activity (heartbeat), doesn't expire during use
- Works across worker restarts
- Simple to reason about and debug
- Industry standard (Redis keys, HTTP sessions, etc.)

### Why Background Cleanup Loop?

**Alternatives considered:**

1. **Cleanup on next task** - Delays cleanup, doesn't help under no load
2. **Redis TTL** - Doesn't cleanup browser engines, only metadata
3. **Background loop (chosen)** - Proactive, predictable, observable

**Background loop advantages:**
- Cleanup happens even when worker is idle
- Predictable cleanup interval for capacity planning
- Easy to monitor (metrics, logs)
- Can be tuned per deployment (test vs prod)

### Why Pytest Fixtures?

**Alternatives considered:**

1. **Manual try/finally** - Already proven unreliable
2. **Decorator** - Doesn't handle test framework timeouts
3. **Pytest plugin** - Overkill for this use case
4. **Autouse fixture (chosen)** - Guaranteed execution, framework-integrated

**Fixture advantages:**
- Runs even when test times out (pytest guarantee)
- No code changes in individual tests
- Works with pytest-xdist (parallel execution)
- Can be scoped (function, class, module, session)

## Conclusion

The intermittent browser test failures are caused by **missing lifecycle management** for browser sessions. The system relies entirely on manual cleanup calls which are fragile and fail in ~13% of cases, causing resource exhaustion.

The proper fix is a **complete session lifecycle system** with:
1. **Automatic TTL-based expiration** - Sessions expire after inactivity
2. **Worker shutdown hooks** - Guaranteed cleanup on worker termination
3. **Background cleanup loop** - Proactive removal of expired sessions
4. **Test fixture integration** - Automatic cleanup even on test failure
5. **Resource limits** - Safety net to prevent runaway accumulation

This is **production-critical** as the same leak pattern will occur in production. Without proper lifecycle management, every crashed connection, forgotten cleanup call, or unexpected error leaks a browser instance. Over time, workers become unstable and eventually crash from resource exhaustion.

**Implementation timeline:** 2 weeks for full rollout with monitoring and validation.
