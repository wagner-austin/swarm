"""
Queue Metrics Service
====================

Provides accurate queue depth calculations using Redis streams
consumer group information.
"""

import logging
from typing import Any, Dict, Optional

import redis.asyncio as redis_asyncio

logger = logging.getLogger(__name__)


class QueueMetricsService:
    """
    Service for calculating accurate queue metrics using Redis streams.

    This service provides better queue depth calculations by considering:
    - Pending messages (delivered but not acknowledged)
    - New messages (not yet delivered)
    - Processing time metrics
    """

    def __init__(self, redis_client: redis_asyncio.Redis):
        self.redis = redis_client

    async def get_pending_count(self, stream: str, group: str) -> int:
        """
        Get the number of pending messages for a consumer group.

        Pending messages are those that have been delivered to consumers
        but not yet acknowledged.
        """
        try:
            # XPENDING returns: [count, smallest_id, largest_id, [[consumer, count], ...]]
            result = await self.redis.xpending(stream, group)
            if result and isinstance(result, list | tuple) and len(result) > 0:
                return int(result[0])
            return 0
        except Exception as e:
            logger.error(f"Failed to get pending count for {stream}/{group}: {e}")
            return 0

    async def get_consumer_group_info(self, stream: str, group: str) -> dict[str, Any] | None:
        """Get information about a specific consumer group."""
        try:
            groups = await self.redis.xinfo_groups(stream)
            for group_info in groups:
                if group_info.get("name") == group:
                    return dict(group_info)
            return None
        except Exception as e:
            logger.error(f"Failed to get group info for {stream}/{group}: {e}")
            return None

    async def get_new_messages_count(self, stream: str, group: str) -> int:
        """
        Estimate the number of new (undelivered) messages.

        This is calculated as the difference between the stream's last ID
        and the group's last delivered ID.
        """
        try:
            # Get group info
            group_info = await self.get_consumer_group_info(stream, group)
            if not group_info:
                # Group doesn't exist, all messages are new
                return int(await self.redis.xlen(stream))

            last_delivered_id = group_info.get("last-delivered-id", "0-0")

            # If no messages delivered yet
            if last_delivered_id == "0-0":
                return int(await self.redis.xlen(stream))

            # Get stream info to find the latest message ID
            stream_info = await self.redis.xinfo_stream(stream)
            last_entry = stream_info.get("last-entry")

            if not last_entry:
                return 0

            last_stream_id = last_entry[0]

            # Count messages between last delivered and end of stream
            # Note: This is approximate, as we can't efficiently count
            # messages between two IDs without XRANGE
            # For production, consider tracking this metric separately

            # Simple heuristic: if last delivered != last stream, there are new messages
            if last_delivered_id != last_stream_id:
                # Get total length and subtract estimated processed
                total_len = await self.redis.xlen(stream)
                # This is still approximate but better than just using XLEN
                pending = await self.get_pending_count(stream, group)

                # Rough estimate: assume most old messages are processed
                # This works well if stream is regularly trimmed
                new_estimate = max(0, min(total_len - pending, total_len // 2))
                return int(new_estimate)

            return 0

        except Exception as e:
            logger.error(f"Failed to get new messages count for {stream}/{group}: {e}")
            # Fallback to total length
            try:
                return int(await self.redis.xlen(stream))
            except Exception:
                return 0

    async def get_true_queue_depth(self, stream: str, group: str) -> int:
        """
        Get the true queue depth: pending + new messages.

        This gives a more accurate representation of work to be done
        compared to just using XLEN.
        """
        pending = await self.get_pending_count(stream, group)
        new_messages = await self.get_new_messages_count(stream, group)

        # For scaling decisions, we care about:
        # 1. Messages being processed (pending) - these need workers
        # 2. Messages waiting to be picked up (new) - these need more workers

        return pending + new_messages

    async def get_oldest_pending_age_ms(self, stream: str, group: str) -> int:
        """
        Get the age of the oldest pending message in milliseconds.

        This helps detect stuck workers or processing bottlenecks.
        """
        try:
            # Get detailed pending info
            # XPENDING stream group - + COUNT
            pending_details = await self.redis.xpending_range(
                name=stream,
                groupname=group,
                min="-",
                max="+",
                count=1,  # Just need the oldest
            )

            if pending_details and len(pending_details) > 0:
                # Format: [[message_id, consumer, idle_time_ms, delivery_count]]
                oldest = pending_details[0]
                return int(oldest[2])  # idle_time_ms

            return 0

        except Exception as e:
            logger.error(f"Failed to get oldest pending age for {stream}/{group}: {e}")
            return 0

    async def get_comprehensive_metrics(self, stream: str, group: str) -> dict[str, Any]:
        """
        Get comprehensive queue metrics for monitoring and scaling decisions.
        """
        try:
            # Gather all metrics
            total_messages = await self.redis.xlen(stream)
            pending_count = await self.get_pending_count(stream, group)
            new_messages = await self.get_new_messages_count(stream, group)
            oldest_pending_ms = await self.get_oldest_pending_age_ms(stream, group)
            true_depth = pending_count + new_messages

            # Get consumer information
            group_info = await self.get_consumer_group_info(stream, group)
            consumers = group_info.get("consumers", 0) if group_info else 0

            return {
                "stream": stream,
                "group": group,
                "total_messages": total_messages,
                "pending_count": pending_count,
                "new_messages_estimate": new_messages,
                "true_queue_depth": true_depth,
                "oldest_pending_ms": oldest_pending_ms,
                "oldest_pending_seconds": oldest_pending_ms / 1000 if oldest_pending_ms else 0,
                "active_consumers": consumers,
                "health_status": self._calculate_health_status(
                    pending_count, oldest_pending_ms, consumers
                ),
            }

        except Exception as e:
            logger.error(f"Failed to get comprehensive metrics for {stream}/{group}: {e}")
            return {
                "stream": stream,
                "group": group,
                "error": str(e),
                "true_queue_depth": 0,
            }

    def _calculate_health_status(
        self, pending_count: int, oldest_pending_ms: int, consumers: int
    ) -> str:
        """Calculate queue health status based on metrics."""
        # No pending messages is healthy
        if pending_count == 0:
            return "healthy"

        # Old pending messages indicate problems
        if oldest_pending_ms > 60000:  # 1 minute
            return "unhealthy"
        elif oldest_pending_ms > 30000:  # 30 seconds
            return "degraded"

        # Many pending messages per consumer might indicate overload
        if consumers > 0 and pending_count / consumers > 10:
            return "degraded"

        return "healthy"
