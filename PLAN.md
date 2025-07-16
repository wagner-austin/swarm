# AI Task Assistant - Distributed Architecture Plan

## Project Vision
Building an AI-powered task execution system capable of handling complex, real-world tasks through intelligent decomposition and distributed worker execution. NOT a Discord bot - Discord is just one of many possible frontends.

### Example Tasks the System Should Handle:
- "Do my latest homework assignment"
- "Research upcoming environmental bills and prepare talking points"
- "Analyze and improve the logging system in my codebase"
- "Monitor this website for changes and summarize daily"
- "Compare these three insurance policies and recommend the best one"

## Core Architecture Goals
1. **Task Decomposition**: Manager service that breaks high-level tasks into executable subtasks
2. **Capability-Based Workers**: Workers advertise capabilities (browse web, edit code, run analysis, etc.)
3. **Intelligent Routing**: Match subtasks to appropriate workers based on capabilities
4. **Platform Agnostic**: Support Discord, Telegram, Web UI, API, SMS as frontends
5. **Massively Scalable**: Support hundreds of concurrent workers across multiple machines
6. **Observable**: Full visibility into task progress, worker status, and system health

## Current Implementation Gaps
- System is Discord-channel-centric instead of task-centric
- No task planning or decomposition logic
- Workers are type-based (browser, tankpit) instead of capability-based
- Poor job lifecycle visibility and error handling
- Missing integration between existing components (QueueMetricsService unused)
- Browser methods (status, close_channel, close_all) called but not implemented
- Failed jobs remain pending forever (no acknowledgment on error)
- Autoscaler uses wrong queue depth calculation (xlen instead of pending-aware)

## Implementation History & Lessons Learned
### Key Architectural Patterns Established
1. **Dynamic Dispatch Safety**: Always filter kwargs using `filter_kwargs_for_method` before calling dynamically dispatched methods
2. **Worker State Machine**: Formal states (IDLE, WAITING, BUSY, ERROR, SHUTDOWN) with proper transitions
3. **Idempotent Stream Creation**: Redis streams and consumer groups created safely for concurrent startup
4. **Session Cleanup**: Browser and TankPit engines cleaned up after each job and at shutdown
5. **Observability First**: Health/metrics endpoints, structured logging, deployment context awareness

## Priority Task List

### Phase 1: Fix Critical Issues (1-2 weeks)
- [ ] **Fix job acknowledgment** (Day 1-2)
  - Add `ack_job()` method to Broker using Redis `xack`
  - Call in worker.dispatch() even on failure
  - Test with intentionally failing jobs
- [ ] **Complete QueueMetrics integration** (Day 3-4)
  - Finish testing scaling_service.py changes
  - Update config.py: set `BROWSER_SCALE_UP_THRESHOLD=3`
  - Deploy and verify autoscaler stops creating excess workers
- [ ] **Implement dead letter queue** (Day 5-7)
  - Add retry_count to Job model
  - After 3 retries, move to "failed:jobs" stream
  - Create admin command to reprocess failed jobs
- [ ] **Remove Discord-channel code** (Week 2)
  - Delete close_channel, closeall commands
  - Remove channel_id from session management
  - Create abstract Context interface

### Phase 2: Celery Migration & Task Architecture (Month 2)
- [ ] **Migrate to Celery** (Week 1-2)
  - Install celery[redis]==5.3.0
  - Create celery_app.py with Redis broker config
  - Convert browser jobs to @celery.task functions
  - Replace Broker class with Celery's app.send_task()
  - Set up Celery routing: `{'browser.*': {'queue': 'browser'}}`
- [ ] **Implement Task Model** (Week 3)
  - Create Task, Subtask, Job hierarchy in models/
  - Task has: id, description, status, subtasks[]
  - Subtask has: capability_required, job_id, depends_on[]
- [ ] **Add Task Decomposer** (Week 4)
  - Simple rule engine first (if "research" in task → create search subtasks)
  - Map high-level requests to capability requirements
  - Create execution plan with dependencies

### Phase 3: Local LLM Integration (Month 3)
- [ ] **Set up LLM Infrastructure** (Week 1)
  - Install llama-cpp-python with CUDA support
  - Download Llama 2 70B-Q4_K_M (fits in 24GB VRAM)
  - Create LLMWorker class with load_model(), generate()
  - Add to Celery as new worker type
- [ ] **Create LLM Capabilities** (Week 2)
  - analyze_document(text) → insights
  - summarize(text, max_length) → summary
  - extract_entities(text) → {people, orgs, locations}
  - answer_questions(context, questions[]) → answers
- [ ] **Integrate with Task System** (Week 3-4)
  - Route analysis tasks to LLM workers
  - Add prompt templates for different domains
  - Cache results to avoid reprocessing

### Phase 4: Multi-Frontend & Scale (Month 4+)
- [ ] **Abstract Frontend Layer** (Week 1-2)
  - Create IFrontend interface with send_message(), get_input()
  - Move Discord code to DiscordFrontend adapter
  - Add WebAPIFrontend with REST endpoints
  - Add TelegramFrontend with python-telegram-bot
- [ ] **Kubernetes Deployment** (Week 3-4)
  - Create k8s manifests for all services
  - Set up ingress for web frontend
  - Configure horizontal pod autoscaling
  - Add persistent volumes for models

### Completed Technical Foundation
- [x] Distributed worker/manager architecture with Redis
- [x] Scaling backends for Docker, Kubernetes, Fly.io
- [x] Job queue system with Redis streams
- [x] Worker state machine implementation
- [x] Basic monitoring and metrics
- [x] Autoscaler service (needs QueueMetrics integration)

## Master Checklist

### Distributed Bot/Worker System
- [x] Implement job model and broker abstraction (`bot.distributed.model`, `bot.distributed.broker`)
- [x] Add remote execution adapters for browser and Tankpit
- [x] Refactor DI/container to support local vs remote runtimes
- [x] Build worker entrypoint (standalone worker)
    - [x] Design generic worker with dynamic dispatch for browser/tankpit jobs
    - [x] Implement CLI/env configuration for job type, worker ID, broker config
    - [x] Implement main loop: consume job, dispatch, reply
    - [x] Refactor worker to support multi-engine-per-worker (concurrent browser/TankPit sessions)
    - [x] Implement session cleanup logic for browser and TankPit engines (per-job and shutdown)
    - [x] Add unit tests for dispatch logic
    - [x] Dockerfile/CLI example for worker
- [x] Add orchestrator/scheduler cog for job dispatch from Discord
- [ ] Add multi-frontend support (Discord, Telegram, web, SMS, etc.)
    - [ ] Separate out logic from frontend specific code in bot/plugins/commands/
- [ ] Add worker capability advertisement/heartbeat
- [x] Refactor queue naming in ProxyService/engines for generic MITM support
- [x] Add docker-compose example for bot and workers

### Observability
- [x] Add HTTP server for /health and /metrics endpoints
- [ ] Integrate Prometheus metrics for orchestrator and workers
- [ ] Centralize logs with Loki (and label by worker, job, etc.)
- [ ] Add Grafana dashboards for job queue, worker health, and resource usage

### Operational Excellence
- [x] Docker Compose/Fly.io/Kubernetes configs for orchestrator + scalable workers + Redis
- [x] Healthchecks and graceful shutdown for all services
- [ ] Document scaling, rolling upgrades, and zero-downtime deploys
- [ ] Document security model (network, secrets, etc.)

### Advanced Features
- [ ] Streaming results/logs via Redis Pub/Sub
- [ ] Smart job routing based on worker capabilities
- [x] Autoscaling workers based on queue depth or resource usage

## Key Architectural Decisions

### 1. Task Execution Model
**Decision: Async with progress streaming via Redis pub/sub**
- Tasks execute asynchronously with real-time progress updates
- Frontends can subscribe to task progress streams
- Supports long-running complex tasks without timeout issues

### 2. Worker Capability Model  
**Decision: Start with static capabilities, evolve to learned**
- Phase 1: Workers declare capabilities in configuration
- Phase 2: Track success rates per capability
- Phase 3: ML-based capability matching and load balancing

### 3. Task Persistence
**Decision: Persistent task history with replay capability**
- All tasks stored with full execution history
- Can replay failed tasks from point of failure
- Optional audit trail export for compliance

### 4. Session Management
**Decision: Task-scoped sessions tied to task lifecycle**
- Resources (browser, connections, files) created per task
- Sessions shared across all subtasks within a task
- Automatic cleanup when task completes/fails
- Enables massive parallelism - different tasks get different sessions

#### Example Task-Scoped Session Flow:
```
Task: "Research and summarize competitor analysis"
├─ Create: Session Pool (5 browsers, 1 database connection)
├─ Subtask: Analyze competitor A → uses browser 1
├─ Subtask: Analyze competitor B → uses browser 2 (parallel)
├─ Subtask: Analyze competitor C → uses browser 3 (parallel)
├─ Subtask: Store results → uses database connection
├─ Subtask: Generate report → uses browsers 1-3 for screenshots
└─ Cleanup: All resources destroyed

Benefits:
- Workers remain stateless (just execute with provided resources)
- Failed workers can be replaced (session state in Redis)
- Natural parallelism (each task isolated)
- Resource efficiency (cleanup guaranteed)
```

## Current Status

### Completed Major Milestones
1. **Distributed Worker System** - Full implementation with Redis-based job queue
2. **Scaling Backends** - Docker Compose, Fly.io, and Kubernetes backends implemented
3. **Autoscaler Service** - Monitors queue depths and scales workers automatically
4. **Type Safety** - All code passes mypy strict mode with proper protocols
5. **Integration Tests** - Comprehensive test coverage with dependency injection
6. **Orchestrator Plugin** - Discord commands for manual worker control

### Architecture Highlights
- **ScalingBackend Protocol**: Type-safe interface for all scaling implementations
- **Worker State Machine**: Formal states (IDLE, WAITING, BUSY, ERROR, SHUTDOWN)
- **Job Dispatch**: Filtered kwargs pattern prevents test failures
- **Health/Metrics**: HTTP endpoints for monitoring

### Critical Worker Scaling Issues (2025-07-16)
1. **Wrong Queue Calculation**: Autoscaler uses `xlen` counting ALL messages, not just unprocessed ones
2. **Failed Jobs Loop Forever**: Worker doesn't ACK failed messages, they get redelivered infinitely
3. **Excess Worker Creation**: Each pending message triggers new worker with current thresholds
4. **Solution Already Exists**: QueueMetricsService handles pending vs new but isn't integrated

## Handoff Notes for Next Session
### Uncommitted Changes
- `bot/distributed/services/scaling_service.py` - Started QueueMetrics integration
- `bot/browser/engine.py` - Started adding missing methods (incomplete)

### Immediate Fixes Needed
1. **Worker must ACK failed jobs** - Add error handling in dispatch
2. **Complete QueueMetrics integration** - Finish and test the changes
3. **Implement dead letter queue** - For permanently failed jobs
4. **Remove channel-centric design** - These don't fit task architecture

### Remember the Vision
This is an AI task execution system, not a Discord bot. Focus on:
- Task decomposition and planning
- Capability-based worker routing  
- Platform-agnostic frontends
- Massive scalability for complex tasks