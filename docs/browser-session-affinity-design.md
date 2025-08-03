# Browser Session Affinity Design

## Executive Summary

This document outlines a production-grade solution for browser session affinity in our distributed Celery worker system. The design ensures browser sessions remain accessible across multiple tasks while supporting horizontal scaling, fault tolerance, and high availability.

## Key Improvements Over Initial Design

1. **True Atomicity**: Lua scripts for multi-key operations instead of simple pipelines
2. **Proper TTL Semantics**: Separate volatile keys prevent accidental TTL renewal on read
3. **Distributed Locking**: SETNX with expiry prevents session double-claiming during migration
4. **Robust Health Checks**: Time-based heartbeat validation (not just status flags)
5. **Capability Advertisement**: Workers announce what they can do via heartbeats
6. **Automatic Cleanup**: Celery Beat job cleans orphaned sessions every 2 minutes
7. **Session Affinity Metrics**: Track hit/miss rates to detect routing problems
8. **Type Safety**: TypedDict schemas for all Redis data structures

## Key Design Principles

1. **Fail Fast**: If session requested but not found, error immediately (don't create new)
2. **Explicit Over Implicit**: All operations have clear success/failure semantics
3. **Observability First**: Every routing decision emits metrics
4. **Progressive Enhancement**: Start with basic affinity, add migration/failover later
5. **Key-space Hygiene**: All keys prefixed with `bs:` for easy identification
6. **Compressed State**: Browser context compressed and encrypted before storage

## Problem Statement

### Current Issues
1. Browser sessions (Playwright instances) are stored in worker process memory
2. Tasks requiring the same browser session may be routed to different workers
3. Workers cannot access sessions created by other workers
4. Session state is lost if a worker dies or restarts
5. No mechanism for session migration or recovery

### Impact
- Intermittent test failures when multiple workers exist
- Cannot scale browser workers horizontally
- Session continuity breaks in production workloads
- No fault tolerance for worker failures

## Architecture Overview

### Components

#### 1. Session Registry Service
- Centralized session-to-worker mapping in Redis
- Tracks session lifecycle and ownership
- Handles worker failure detection and session cleanup
- Provides session discovery API

#### 2. Intelligent Task Router
- Custom Celery router with session awareness
- Routes tasks to workers owning required sessions
- Implements fallback strategies for missing sessions
- Supports load balancing for new sessions

#### 3. Worker Session Manager
- Manages local browser session pool
- Registers sessions with central registry
- Implements session health checks
- Handles graceful session handoff on shutdown

#### 4. Session State Persistence
- Stores browser state snapshots in object storage
- Enables session reconstruction on different workers
- Supports session migration between workers
- Maintains session history for debugging

## Detailed Design

### Session Registry Schema

```python
from typing import TypedDict, Literal, List

class WorkerHeartbeat(TypedDict):
    """Worker registration and capability advertisement"""
    worker_id: str
    hostname: str
    queues: List[str]
    capabilities: List[str]  # e.g., ["browser.goto", "browser.click", "browser.screenshot"]
    capacity: int
    current_sessions: int
    current_load: float  # 0.0 to 1.0
    version: str
    started_at: str  # ISO timestamp
    last_heartbeat: str  # ISO timestamp
    direct_queue: str  # e.g., "browser.direct.worker-abc123"

class SessionData(TypedDict):
    """Browser session metadata"""
    session_id: str
    worker_hostname: str
    created_at: str
    last_accessed: str
    status: Literal["active", "idle", "migrating", "orphaned"]
    task_count: int
    browser_context: str  # Compressed and encrypted JSON

# Key Schema with Proper TTL Management
# --------------------------------------
# Note: Current implementation uses "browser:" prefix, design uses "bs:" (browser session)
# for brevity. Either works, but should be consistent.

# Worker heartbeat (persistent hash, TTL via separate key)
bs:worker:{hostname} = WorkerHeartbeat (hash)
bs:worker:{hostname}:ttl = "" (string, expires in 60s)

# Session data (persistent hash, TTL via separate key)  
bs:session:{session_id} = SessionData (hash)
bs:session:{session_id}:ttl = "" (string, expires in 3600s)

# Worker to Sessions Index
bs:worker:{hostname}:sessions = SET of session_ids

# Distributed Lock for Session Operations
bs:session:{session_id}:lock = "worker-hostname|timestamp"
SET with NX EX 30 (atomic set-if-not-exists with 30s expiry)

# Worker Capabilities Index (for routing new sessions)
bs:capabilities:{capability} = SET of worker_ids
```

### Task Routing Algorithm

```python
class BrowserSessionRouter:
    """Production-grade router with session affinity and capability matching"""
    
    def route_for_task(self, task, args=None, kwargs=None, **options):
        if not task.startswith('browser.'):
            return None
            
        session_id = kwargs.get('session_id') or kwargs.get('task_id')
        
        # Step 1: Session affinity - route to existing session owner
        if session_id:
            worker = self._get_session_owner(session_id)
            if worker:
                redis.incr('metrics:session_affinity_hit')
                return self._route_to_worker(worker)
            else:
                # Session not found or worker dead
                redis.incr('metrics:session_affinity_miss')
                # Fail fast for explicit session requests
                raise SessionNotFoundError(f"Session {session_id} not found or worker dead")
        
        # Step 2: Capability-based routing for new sessions
        required_capability = task  # e.g., "browser.goto"
        worker = self._select_capable_worker(required_capability)
        
        if not worker:
            raise NoCapableWorkerError(f"No worker available for {required_capability}")
            
        return self._route_to_worker(worker)
    
    def _get_session_owner(self, session_id: str) -> Optional[str]:
        """Get worker that owns session with robust health check"""
        session_data = redis.hgetall(f"bs:session:{session_id}")
        if not session_data:
            return None
            
        worker_hostname = session_data.get('worker_hostname')
        if not worker_hostname:
            return None
            
        # Robust health check: verify heartbeat recency
        worker_data = redis.hgetall(f"bs:worker:{worker_hostname}")
        if not worker_data:
            return None
            
        last_heartbeat = datetime.fromisoformat(worker_data.get('last_heartbeat'))
        age = (datetime.now(timezone.utc) - last_heartbeat).total_seconds()
        
        if age > 60:  # Worker TTL
            logger.warning(f"Worker {worker_hostname} heartbeat too old: {age}s")
            return None
            
        return worker_hostname
    
    def _select_capable_worker(self, capability: str) -> Optional[str]:
        """Select least loaded worker with required capability"""
        # Get workers with this capability from index
        capable_workers = redis.smembers(f"bs:capabilities:{capability}")
        if not capable_workers:
            return None
            
        best_worker = None
        min_load = float('inf')
        
        for worker_id in capable_workers:
            worker_data = redis.hgetall(f"bs:worker:{worker_id}")
            if not worker_data:
                continue
                
            # Skip unhealthy workers  
            last_heartbeat = datetime.fromisoformat(worker_data.get('last_heartbeat'))
            if (datetime.now(timezone.utc) - last_heartbeat).total_seconds() > 60:
                continue
                
            # Calculate load
            load = float(worker_data.get('current_load', 1.0))
            if load < min_load:
                min_load = load
                best_worker = worker_id
                
        return best_worker
```

### Atomic Operations with Lua Scripts

```lua
-- register_session.lua: Atomically register a session with all indexes
-- Args: session_id, worker_id, session_data_json, ttl
local session_id = ARGV[1]
local worker_id = ARGV[2]
local session_data = ARGV[3]
local ttl = tonumber(ARGV[4])

-- Keys
local session_key = "bs:session:" .. session_id
local session_ttl_key = session_key .. ":ttl"
local worker_key = "bs:worker:" .. worker_id
local worker_sessions_key = worker_key .. ":sessions"

-- Check worker exists
if redis.call("EXISTS", worker_key) == 0 then
    return {err="Worker not found"}
end

-- Register session atomically
redis.call("HSET", session_key, "data", session_data)
redis.call("SETEX", session_ttl_key, ttl, "")
redis.call("SADD", worker_sessions_key, session_id)
redis.call("HINCRBY", worker_key, "current_sessions", 1)

return {ok="Session registered"}
```

```lua
-- claim_orphaned_session.lua: Atomically claim an orphaned session
-- Args: session_id, new_worker_id
local session_id = ARGV[1]
local new_worker_id = ARGV[2]

-- Keys
local session_key = "bs:session:" .. session_id
local lock_key = session_key .. ":lock"

-- Try to acquire lock
if redis.call("SET", lock_key, new_worker_id, "NX", "EX", "30") then
    -- Lock acquired, check session status
    local status = redis.call("HGET", session_key, "status")
    if status == "orphaned" then
        -- Update session ownership
        local old_worker = redis.call("HGET", session_key, "worker_hostname")
        redis.call("HSET", session_key, "worker_hostname", new_worker_id)
        redis.call("HSET", session_key, "status", "active")
        
        -- Update worker session counts
        if old_worker then
            redis.call("SREM", "bs:worker:" .. old_worker .. ":sessions", session_id)
            redis.call("HINCRBY", "bs:worker:" .. old_worker, "current_sessions", -1)
        end
        redis.call("SADD", "bs:worker:" .. new_worker_id .. ":sessions", session_id)
        redis.call("HINCRBY", "bs:worker:" .. new_worker_id, "current_sessions", 1)
        
        return {ok="Session claimed"}
    else
        -- Session not orphaned, release lock
        redis.call("DEL", lock_key)
        return {err="Session not orphaned"}
    end
else
    return {err="Lock acquisition failed"}
end
```

### Worker Lifecycle Management

#### Worker Startup
1. Register with session registry
2. Create direct queue for session-affined tasks
3. Start heartbeat thread
4. Recover any assigned orphaned sessions

#### Worker Heartbeat
```python
class WorkerHeartbeat:
    """Robust heartbeat with capability advertisement"""
    
    def __init__(self, worker_id: str, session_manager: SessionManager):
        self.worker_id = worker_id
        self.session_manager = session_manager
        self.capabilities = self._detect_capabilities()
        
    def _detect_capabilities(self) -> List[str]:
        """Detect what this worker can do based on installed tasks"""
        from celery import current_app
        capabilities = []
        for task_name in current_app.tasks:
            if task_name.startswith('browser.'):
                capabilities.append(task_name)
        return capabilities
    
    async def run(self):
        while not self.stopped:
            try:
                # Prepare heartbeat data
                heartbeat_data = {
                    "worker_id": self.worker_id,
                    "hostname": socket.gethostname(),
                    "queues": ["browser"],  # From worker config
                    "capabilities": json.dumps(self.capabilities),
                    "capacity": 10,  # From settings
                    "current_sessions": len(self.session_manager.sessions),
                    "current_load": len(self.session_manager.sessions) / 10.0,
                    "version": "1.4.0",  # From package version
                    "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                    "direct_queue": f"browser.direct.{self.worker_id}"
                }
                
                # Update worker data and TTL separately
                pipe = redis.pipeline()
                pipe.hset(f"bs:worker:{self.worker_id}", mapping=heartbeat_data)
                pipe.setex(f"bs:worker:{self.worker_id}:ttl", 60, "")
                
                # Update capability indexes
                for capability in self.capabilities:
                    pipe.sadd(f"bs:capabilities:{capability}", self.worker_id)
                    pipe.expire(f"bs:capabilities:{capability}", 300)  # 5 min TTL
                    
                pipe.execute()
                
                # Periodically check for orphaned sessions
                if random.random() < 0.1:  # 10% chance each heartbeat
                    await self._adopt_orphaned_sessions()
                    
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                
            await asyncio.sleep(30)
    
    async def _adopt_orphaned_sessions(self):
        """Try to claim orphaned sessions if we have capacity"""
        if len(self.session_manager.sessions) >= 8:  # 80% capacity
            return
            
        # Find orphaned sessions
        orphaned = []
        for key in redis.scan_iter(match="bs:session:*"):
            if ":ttl" in key or ":lock" in key:
                continue
            session_data = redis.hget(key, "status")
            if session_data == b"orphaned":
                session_id = key.split(":")[-1]
                orphaned.append(session_id)
                
        # Try to claim one
        for session_id in orphaned[:1]:  # Only claim one at a time
            result = redis.eval(CLAIM_ORPHANED_SESSION_LUA, 0, session_id, self.worker_id)
            if result.get("ok"):
                logger.info(f"Adopted orphaned session {session_id}")
                # Restore session state from S3/object storage
                # S3 = Amazon S3 or compatible object storage (MinIO, GCS, etc.)
                await self.session_manager.restore_session(session_id)
```

#### Worker Shutdown
1. Mark all sessions as "migrating"
2. Persist session state to object storage
3. Update session registry
4. Gracefully close browser instances
5. Deregister from worker registry

### Session State Persistence (Future Enhancement)

Note: Session state persistence is not required for basic session affinity. The current design maintains sessions in worker memory with proper routing. State persistence would only be needed for:
- Live migration of sessions between workers
- Recovery after unexpected worker crashes  
- Multi-region session handoff

When implemented, the state would include:
- Current URL and page state
- Cookies and authentication tokens
- Local/session storage
- Viewport and device settings
- Custom headers

Storage options:
- **Redis**: For small state data and quick access (current design)
- **S3/Object Storage**: For larger snapshots, screenshots, and long-term storage
  - S3 = Amazon S3, MinIO, Google Cloud Storage, Azure Blob Storage, etc.
  - Provides versioning, encryption at rest, and high durability
  - Cost-effective for infrequent access patterns

The state would be compressed, encrypted, and have appropriate TTLs based on use case.

### Fault Tolerance

#### Worker Failure Detection
1. Missing heartbeats for 60 seconds
2. Failed health check endpoints
3. Celery worker offline events
4. Container/pod termination signals

#### Automatic Recovery
1. **Orphan Detection**: Registry service marks sessions as orphaned
2. **Session Adoption**: Healthy workers claim orphaned sessions
3. **State Recovery**: Restore from last persisted state
4. **Task Retry**: Retry failed tasks on new worker

#### Circuit Breaker
```python
class SessionCircuitBreaker:
    def __init__(self):
        self.failure_threshold = 5
        self.recovery_timeout = 300  # 5 minutes
        self.failure_counts = defaultdict(int)
        self.circuit_open_time = {}
    
    def is_open(self, worker):
        if worker in self.circuit_open_time:
            if time.time() - self.circuit_open_time[worker] > self.recovery_timeout:
                # Try to recover
                del self.circuit_open_time[worker]
                self.failure_counts[worker] = 0
                return False
            return True
        return False
    
    def record_failure(self, worker):
        self.failure_counts[worker] += 1
        if self.failure_counts[worker] >= self.failure_threshold:
            self.circuit_open_time[worker] = time.time()
            logger.error(f"Circuit breaker opened for worker {worker}")
```

## Implementation Plan

### Phase 1: Core Session Affinity (Current Sprint)
- [ ] Implement SessionRegistry with Lua scripts for atomicity
- [ ] Create BrowserSessionRouter with capability-based routing
- [ ] Add worker heartbeat with capability advertisement
- [ ] Update BrowserTask to register/unregister sessions
- [ ] Create direct worker queues for session-affined routing
- [ ] Add integration test for concurrent goto/click operations

### Phase 2: Observability & Reliability (Next Sprint)
- [ ] Add session affinity metrics (hit/miss rates)
- [ ] Implement Celery Beat cleanup job for orphaned sessions
- [ ] Create Grafana dashboard for session lifecycle monitoring
- [ ] Add alerts for high orphan rates and affinity misses
- [ ] Implement circuit breaker for unhealthy workers

### Phase 3: Advanced Features (Future)
- [ ] Session state persistence (if needed for migration)
- [ ] Live session migration between workers
- [ ] Multi-region session routing
- [ ] Session pooling and pre-warming

### Cleanup Cron Job

```python
# Celery Beat Schedule
from celery.schedules import crontab

app.conf.beat_schedule = {
    'cleanup-orphaned-sessions': {
        'task': 'swarm.tasks.maintenance.cleanup_orphaned_sessions',
        'schedule': crontab(minute='*/2'),  # Every 2 minutes
    },
}

# Cleanup Task
@app.task
def cleanup_orphaned_sessions():
    """Find and clean up orphaned browser sessions"""
    orphaned_count = 0
    cleaned_count = 0
    
    # Find all sessions
    for key in redis.scan_iter(match="bs:session:*"):
        if ":ttl" in key or ":lock" in key:
            continue
            
        session_id = key.decode().split(":")[-1]
        session_data = redis.hgetall(key)
        
        if not session_data:
            continue
            
        # Check worker health
        worker_id = session_data.get(b"worker_hostname", b"").decode()
        if not worker_id:
            continue
            
        # Check if worker is dead (no TTL key)
        if not redis.exists(f"bs:worker:{worker_id}:ttl"):
            # Mark as orphaned
            age = time.time() - float(session_data.get(b"created_at", 0))
            
            if session_data.get(b"status") != b"orphaned":
                redis.hset(key, "status", "orphaned")
                orphaned_count += 1
                logger.warning(f"Marked session {session_id} as orphaned (worker {worker_id} dead)")
                
            # Clean up old orphaned sessions
            if age > 300 and session_data.get(b"status") == b"orphaned":  # 5 min
                redis.delete(key)
                redis.delete(f"{key}:ttl")
                cleaned_count += 1
                logger.info(f"Cleaned up old orphaned session {session_id}")
    
    # Emit metrics
    redis.incr(f"metrics:sessions_orphaned_total", orphaned_count)
    redis.incr(f"metrics:sessions_cleaned_total", cleaned_count)
    
    # Alert if too many orphans
    if orphaned_count > 10:
        logger.error(f"High orphan rate detected: {orphaned_count} sessions orphaned")
        # Send alert via your alerting system
        
    return {"orphaned": orphaned_count, "cleaned": cleaned_count}
```

## Monitoring & Observability

### Key Metrics
- `browser_sessions_total{worker}` - Total sessions per worker
- `browser_session_routing_duration_seconds` - Routing decision time
- `browser_session_affinity_hit_total` - Successful session affinity routes
- `browser_session_affinity_miss_total` - Failed session lookups
- `browser_session_migrations_total{reason}` - Session migrations
- `browser_worker_heartbeat_age_seconds` - Time since last heartbeat
- `browser_session_orphaned_total` - Orphaned sessions
- `browser_session_recovery_duration_seconds` - Recovery time

### Alerts
- Worker heartbeat missing > 60s
- Session orphan rate > 1%
- Session affinity miss rate > 5% (rate(browser_session_affinity_miss_total[5m]) / rate(browser_session_affinity_hit_total[5m]) > 0.05)
- Routing failures > 0.1%
- Circuit breaker open
- Session capacity > 80%

### Prometheus Scrape Config
```yaml
scrape_configs:
  - job_name: 'swarm-worker'
    static_configs:
      - targets: ['worker1:9100', 'worker2:9100']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: '([^:]+):[0-9]+'
        replacement: '${1}'
```

### Dashboards
1. **Worker Health**: Status, capacity, session distribution
2. **Session Lifecycle**: Creation, migration, termination
3. **Routing Performance**: Latency, success rate, distribution
4. **System Overview**: Total capacity, active sessions, queue depths

## Security Considerations

1. **Session Data Encryption**: All session state encrypted at rest
2. **Network Isolation**: Worker-to-worker communication via Redis only
3. **Access Control**: IAM roles for S3/object storage (when state persistence is implemented)
4. **Audit Logging**: All session operations logged
5. **Secret Management**: Browser credentials via environment variables (future: HashiCorp Vault or similar)

## Performance Targets

- Session routing latency: < 10ms (p99)
- Session creation time: < 2s
- Session migration time: < 5s
- Worker failure detection: < 60s
- System capacity: 10,000 concurrent sessions
- Horizontal scaling: Support 1000+ workers

## Alternative Approaches Considered

### 1. Sticky Sessions via Load Balancer
- **Pros**: Simple, proven pattern
- **Cons**: Doesn't work with Celery's internal routing

### 2. Shared Browser Pool (Selenium Grid Style)
- **Pros**: Complete session portability
- **Cons**: High complexity, network latency, single point of failure

### 3. Session Serialization to Redis
- **Pros**: True stateless workers
- **Cons**: Cannot serialize browser runtime state

### 4. Single Browser Worker
- **Pros**: Trivial implementation
- **Cons**: No horizontal scaling, single point of failure

## Decision

Implement the **Session Registry with State Persistence** approach because:
1. Balances complexity with functionality
2. Supports horizontal scaling
3. Provides fault tolerance
4. Enables gradual rollout
5. Uses proven patterns (service registry, state machines)

## Future Enhancements

1. **Session Pre-warming**: Predictively create sessions
2. **Geographic Distribution**: Route based on latency
3. **Session Pooling**: Reuse sessions across tasks
4. **A/B Testing**: Compare routing algorithms
5. **ML-based Routing**: Predict optimal worker assignment