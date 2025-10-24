"""Worker lifecycle management for Celery workers."""

import json
import logging
import os
import platform
import threading
import time
from datetime import UTC, datetime, timezone
from functools import cached_property
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

import redis

from swarm.core.settings import Settings

if TYPE_CHECKING:
    # For type checking, Redis is generic
    RedisSyncClient = redis.Redis[Any]
else:
    # At runtime, Redis is not generic
    RedisSyncClient = redis.Redis

# Using Any for Redis client type to avoid type stub issues
RedisT = Any

logger = logging.getLogger(__name__)


class WorkerLifecycle:
    """Manages worker registration, heartbeat, and cleanup."""

    def __init__(self, worker_id: str, redis_client: RedisT | None = None):
        """Initialize worker lifecycle manager.

        Args:
            worker_id: Unique identifier for this worker
            redis_client: Redis client instance (uses default if not provided)
        """
        self.worker_id = worker_id
        settings = Settings()
        if not settings.redis.url:
            raise ValueError("Redis URL not configured")
        self.redis: RedisT = redis_client or redis.from_url(
            settings.redis.url, decode_responses=True
        )
        self.shutdown_event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._registered = False

        # Configuration
        self.heartbeat_interval = getattr(settings, "WORKER_HEARTBEAT_INTERVAL", 20)
        self.heartbeat_timeout = getattr(settings, "WORKER_HEARTBEAT_TIMEOUT", 60)
        self.max_sessions = getattr(settings, "WORKER_MAX_SESSIONS", 10)

        logger.info(
            f"Worker lifecycle initialized: {worker_id}",
            extra={
                "worker_id": worker_id,
                "capabilities": self.capabilities,
                "max_sessions": self.max_sessions,
            },
        )

    @cached_property
    def capabilities(self) -> list[str]:
        """Detect worker capabilities (cached)."""
        caps = ["browser"]  # Base capability

        # Check for GPU (basic check)
        if self._has_gpu():
            caps.append("gpu")

        # Check available browsers (basic checks)
        if self._has_chrome():
            caps.append("chrome")
        if self._has_firefox():
            caps.append("firefox")

        # Check for special features from environment
        if os.getenv("ENABLE_STEALTH"):
            caps.append("stealth")
        if os.getenv("ENABLE_VNC"):
            caps.append("vnc")
        if os.getenv("DEBUG_WORKER"):
            caps.append("debug")

        # Add platform capability
        caps.append(platform.system().lower())

        return caps

    def register(self) -> None:
        """Register worker in Redis with initial metadata."""
        if self._registered:
            logger.warning(f"Worker {self.worker_id} already registered")
            return

        worker_key = f"browser:worker:{self.worker_id}"
        sessions_key = f"browser:worker_sessions:{self.worker_id}"

        # Use pipeline for atomic multi-field writes
        with self.redis.pipeline() as pipe:
            # Set worker data
            pipe.hset(
                worker_key,
                mapping={
                    "hostname": self.worker_id,
                    "capabilities": json.dumps(self.capabilities),
                    "started_at": datetime.now(UTC).isoformat(),
                    "last_heartbeat": datetime.now(UTC).isoformat(),
                    "status": "active",
                    "current_sessions": "0",
                    "max_sessions": str(self.max_sessions),
                    "platform": platform.system(),
                    "python_version": platform.python_version(),
                },
            )

            # Set TTL on worker key
            pipe.expire(worker_key, self.heartbeat_timeout)

            # Initialize empty session set
            pipe.delete(sessions_key)  # Clear any old data
            pipe.expire(sessions_key, self.heartbeat_timeout)

            pipe.execute()

        self._registered = True
        logger.info(
            f"Worker registered: {self.worker_id}",
            extra={"worker_id": self.worker_id, "capabilities": self.capabilities},
        )

    def start_heartbeat(self) -> None:
        """Start background heartbeat thread."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            logger.warning(f"Heartbeat already running for worker {self.worker_id}")
            return

        self.shutdown_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"heartbeat-{self.worker_id}", daemon=True
        )
        self._heartbeat_thread.start()
        logger.info(f"Started heartbeat thread for worker {self.worker_id}")

    def stop_heartbeat(self) -> None:
        """Stop heartbeat and mark sessions as orphaned."""
        logger.info(f"Stopping heartbeat for worker {self.worker_id}")

        # Signal shutdown
        self.shutdown_event.set()

        # Update worker status and cleanup
        worker_key = f"browser:worker:{self.worker_id}"
        sessions_key = f"browser:worker_sessions:{self.worker_id}"

        try:
            with self.redis.pipeline() as pipe:
                # Update status
                pipe.hset(worker_key, "status", "shutting_down")

                # Get all sessions owned by this worker
                sessions = self.redis.smembers(sessions_key)

                # Clear ownership for each session
                for session_id in sessions:
                    affinity_key = f"browser:affinity:{session_id}"
                    pipe.delete(affinity_key)

                # Remove worker data
                pipe.delete(worker_key)
                pipe.delete(sessions_key)

                pipe.execute()

            if sessions:
                logger.info(
                    f"Cleared {len(sessions)} sessions from worker {self.worker_id}",
                    extra={"worker_id": self.worker_id, "orphaned_sessions": list(sessions)},
                )

        except Exception as e:
            logger.error(f"Error during worker shutdown: {e}", exc_info=True)

        # Wait for heartbeat thread to stop
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)

        self._registered = False

    def add_session(self, session_id: str) -> None:
        """Add a session to this worker's session set."""
        sessions_key = f"browser:worker_sessions:{self.worker_id}"
        try:
            self.redis.sadd(sessions_key, session_id)
            # Refresh TTL on session set
            self.redis.expire(sessions_key, self.heartbeat_timeout)
        except Exception as e:
            logger.error(f"Failed to add session {session_id} to worker: {e}")

    def remove_session(self, session_id: str) -> None:
        """Remove a session from this worker's session set."""
        sessions_key = f"browser:worker_sessions:{self.worker_id}"
        try:
            self.redis.srem(sessions_key, session_id)
        except Exception as e:
            logger.error(f"Failed to remove session {session_id} from worker: {e}")

    def _heartbeat_loop(self) -> None:
        """Background thread that updates heartbeat."""
        logger.debug(f"Heartbeat loop started for worker {self.worker_id}")

        while not self.shutdown_event.is_set():
            try:
                worker_key = f"browser:worker:{self.worker_id}"
                sessions_key = f"browser:worker_sessions:{self.worker_id}"

                # Use pipeline for atomic updates
                with self.redis.pipeline() as pipe:
                    # Update heartbeat and session count
                    session_count = self.redis.scard(sessions_key)
                    pipe.hset(
                        worker_key,
                        mapping={
                            "last_heartbeat": datetime.now(UTC).isoformat(),
                            "current_sessions": str(session_count),
                        },
                    )

                    # Extend TTLs
                    pipe.expire(worker_key, self.heartbeat_timeout)
                    pipe.expire(sessions_key, self.heartbeat_timeout)

                    pipe.execute()

                logger.debug(
                    f"Heartbeat updated for worker {self.worker_id}",
                    extra={"session_count": session_count},
                )

            except Exception as e:
                logger.error(f"Heartbeat failed for worker {self.worker_id}: {e}", exc_info=True)

            # Wait for interval or shutdown
            self.shutdown_event.wait(self.heartbeat_interval)

        logger.debug(f"Heartbeat loop stopped for worker {self.worker_id}")

    def _has_gpu(self) -> bool:
        """Check if GPU is available."""
        # Simple check - could be enhanced with actual GPU detection
        return bool(os.getenv("CUDA_VISIBLE_DEVICES")) or os.path.exists("/dev/nvidia0")

    def _has_chrome(self) -> bool:
        """Check if Chrome is available."""
        # Simple check - could be enhanced
        chrome_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        ]
        return any(os.path.exists(path) for path in chrome_paths)

    def _has_firefox(self) -> bool:
        """Check if Firefox is available."""
        firefox_paths = [
            "/usr/bin/firefox",
            "C:\\Program Files\\Mozilla Firefox\\firefox.exe",
            "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
        ]
        return any(os.path.exists(path) for path in firefox_paths)

    def get_status(self) -> dict[str, Any]:
        """Get current worker status."""
        worker_key = f"browser:worker:{self.worker_id}"
        data = self.redis.hgetall(worker_key)

        if not data:
            return {"status": "not_found"}

        # Decode bytes and parse JSON fields
        status = {}
        for key, value in data.items():
            key_str = key.decode() if isinstance(key, bytes) else key
            value_str = value.decode() if isinstance(value, bytes) else value

            if key_str == "capabilities":
                status[key_str] = json.loads(value_str)
            elif key_str in ["current_sessions", "max_sessions"]:
                status[key_str] = int(value_str)
            else:
                status[key_str] = value_str

        return status

    def is_healthy(self) -> bool:
        """Check if this worker is healthy based on Redis TTL."""
        worker_key = f"browser:worker:{self.worker_id}"
        try:
            # If key exists, worker is healthy
            return bool(self.redis.exists(worker_key))
        except Exception:
            return False
