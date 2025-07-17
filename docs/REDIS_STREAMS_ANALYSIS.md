# Redis Streams Job Queue Analysis

## Overview

This document analyzes how Redis streams are used for job queuing in the Discord bot's distributed architecture, with a focus on understanding pending messages and calculating true queue depth for scaling decisions.

## Current Implementation

### 1. Message Flow

1. **Publishing**: Jobs are added to streams using `XADD`
   - Stream names: `browser:jobs`, `tankpit:jobs`, or default `jobs`
   - Messages contain serialized Job objects in JSON format

2. **Consuming**: Workers read messages using `XREADGROUP`
   - Uses consumer groups for distributed processing
   - Messages are immediately acknowledged with `XACK` after reading
   - Pattern: `XREADGROUP group consumer {stream: ">"} count=1 block=1000`

3. **Acknowledgment**: Messages are ACKed immediately upon receipt
   - See `broker.py` line 126: `await self._r.xack(stream_name, group, msg_id)`
   - This happens BEFORE processing the job

### 2. Queue Depth Calculation

Current implementation uses `XLEN` to get total stream length:
```python
async def get_queue_depth(self, worker_type: str) -> int:
    """Get current queue depth for a worker type."""
    # ...
    depth: int = await self.redis.xlen(config.job_queue)
    return depth
```

**Problem**: `XLEN` returns the TOTAL number of messages in the stream, including:
- Already processed and acknowledged messages
- Messages currently being processed (pending)
- New unprocessed messages

This leads to inaccurate scaling decisions because the autoscaler can't distinguish between:
- Historical messages that have been processed
- Messages actively being worked on
- Messages waiting to be picked up

### 3. Redis Streams Concepts

#### Consumer Groups
- Allow multiple consumers to process messages from the same stream
- Each message is delivered to only one consumer in the group
- Track which messages have been delivered and acknowledged

#### Message States
1. **New**: Messages not yet delivered to any consumer
2. **Pending**: Messages delivered but not yet acknowledged
3. **Acknowledged**: Messages that have been processed and ACKed

#### Key Redis Commands
- `XADD`: Add message to stream
- `XREADGROUP`: Read messages as part of a consumer group
- `XACK`: Acknowledge message processing
- `XLEN`: Get total stream length
- `XPENDING`: Get information about pending messages
- `XINFO GROUPS`: Get consumer group information

## Issues with Current Implementation

### 1. Immediate ACK Pattern
The current code ACKs messages immediately after reading:
```python
msgs = await self._r.xreadgroup(group, consumer, {stream: ">"}, count=1, block=1000)
if msgs:
    stream_name, entries = msgs[0]
    msg_id, fields = entries[0]
    await self._r.xack(stream_name, group, msg_id)  # Immediate ACK
    return Job.loads(fields["json"])
```

**Problems**:
- If worker crashes after ACK but before processing, the job is lost
- Can't track which jobs are actually being processed
- No visibility into processing time or stuck jobs

### 2. Inaccurate Queue Depth
Using `XLEN` includes all messages ever added to the stream:
- Doesn't account for stream trimming
- Includes already-processed messages
- Can grow indefinitely without cleanup

### 3. No Pending Message Tracking
The system doesn't query or monitor pending messages:
- Can't detect stuck workers
- Can't see processing bottlenecks
- Can't make informed scaling decisions

## Recommendations

### 1. Proper Queue Depth Calculation

To get the "true" queue depth for scaling decisions, we need to calculate:
```
True Queue Depth = New Messages + Pending Messages
```

This can be achieved by:

```python
async def get_true_queue_depth(self, worker_type: str, group: str) -> int:
    """Get the actual number of unprocessed messages."""
    config = self.config.get_worker_type(worker_type)
    if not config:
        return 0
    
    stream = config.job_queue
    
    # Get pending messages count
    pending_info = await self.redis.xpending(stream, group)
    pending_count = pending_info[0] if pending_info else 0
    
    # Get stream info to find last delivered ID
    groups_info = await self.redis.xinfo_groups(stream)
    last_delivered_id = None
    for group_info in groups_info:
        if group_info['name'] == group:
            last_delivered_id = group_info['last-delivered-id']
            break
    
    if not last_delivered_id:
        # No messages delivered yet, return total length
        return await self.redis.xlen(stream)
    
    # Count messages after last delivered ID (new messages)
    # This requires XRANGE which isn't ideal for performance
    # Alternative: track metrics differently
    
    return pending_count  # For now, just return pending
```

### 2. Delayed ACK Pattern

Move acknowledgment to after job completion:

```python
async def consume_and_process(self, group: str, consumer: str, stream: str | None = None) -> None:
    """Consume and process a job with proper ACK handling."""
    msgs = await self._r.xreadgroup(group, consumer, {stream: ">"}, count=1, block=1000)
    if not msgs:
        raise TimeoutError
    
    stream_name, entries = msgs[0]
    msg_id, fields = entries[0]
    job = Job.loads(fields["json"])
    
    try:
        # Process the job
        result = await self.process_job(job)
        
        # ACK only after successful processing
        await self._r.xack(stream_name, group, msg_id)
        
        return result
    except Exception as e:
        # On failure, message remains pending for retry
        # Could implement dead letter queue here
        logger.error(f"Job {job.id} failed: {e}")
        raise
```

### 3. Stream Maintenance

Implement stream trimming to prevent unbounded growth:

```python
async def publish(self, job: Job) -> None:
    """Publish a job with stream trimming."""
    stream = self._get_stream_for_job_type(job.type)
    # MAXLEN with ~ for approximate trimming (more efficient)
    await self._r.xadd(stream, {"json": job.dumps()}, maxlen=10000, approximate=True)
```

### 4. Monitoring Enhancements

Add pending message monitoring:

```python
async def get_queue_metrics(self, worker_type: str, group: str) -> dict:
    """Get comprehensive queue metrics."""
    config = self.config.get_worker_type(worker_type)
    if not config:
        return {}
    
    stream = config.job_queue
    
    # Get basic info
    total_messages = await self.redis.xlen(stream)
    
    # Get pending info
    pending_summary = await self.redis.xpending(stream, group)
    pending_count = pending_summary[0] if pending_summary else 0
    
    # Get detailed pending info (oldest, consumer distribution)
    if pending_count > 0:
        # XPENDING with details
        pending_details = await self.redis.xpending_range(
            stream, group, min='-', max='+', count=10
        )
        oldest_pending_ms = pending_details[0][2] if pending_details else 0
    else:
        oldest_pending_ms = 0
    
    return {
        'total_messages': total_messages,
        'pending_count': pending_count,
        'oldest_pending_ms': oldest_pending_ms,
        'estimated_new_messages': max(0, total_messages - pending_count),
    }
```

### 5. Scaling Decision Improvements

Update the autoscaler to use better metrics:

```python
async def make_scaling_decision_v2(
    self,
    worker_type: str,
    metrics: dict,
    current_workers: int,
) -> tuple[ScalingDecision, int]:
    """Make scaling decision based on comprehensive metrics."""
    config = self.config.get_worker_type(worker_type)
    if not config or not config.enabled:
        return ScalingDecision.NO_CHANGE, current_workers
    
    scaling = config.scaling
    
    # Use pending count as primary metric
    queue_pressure = metrics.get('pending_count', 0)
    
    # Consider age of oldest pending message
    oldest_pending_ms = metrics.get('oldest_pending_ms', 0)
    if oldest_pending_ms > 30000:  # 30 seconds
        # Force scale up if messages are getting old
        queue_pressure *= 2
    
    # Rest of scaling logic...
```

## Implementation Priority

1. **High Priority**: Fix queue depth calculation to use pending messages
2. **Medium Priority**: Implement stream trimming to prevent unbounded growth
3. **Low Priority**: Move to delayed ACK pattern (requires careful migration)

## Conclusion

The current implementation treats Redis streams as a simple queue but doesn't leverage consumer group features properly. By tracking pending messages and implementing proper ACK patterns, the system can make better scaling decisions and provide better reliability guarantees.