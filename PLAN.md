# AI Task Assistant - Distributed Architecture Plan

## Project Vision
Building an AI-powered task execution system capable of handling complex, real-world tasks through intelligent decomposition and distributed worker execution. NOT just a Discord integration - Discord is just one of many possible frontends.

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

## Current Implementation Status (2025-07-17)
- ✅ Migrated from custom broker to Celery distributed task queue
- ✅ Fixed job lifecycle with proper retry/timeout handling via Celery
- ✅ Autoscaler now uses Flower API for accurate queue monitoring
- ✅ Workers can be scaled from zero (no chicken-and-egg problem)
- ⏳ System is still Discord-channel-centric instead of task-centric
- ⏳ No task planning or decomposition logic yet
- ⏳ Workers are type-based (browser, tankpit) instead of capability-based
- ⏳ Need to implement task-scoped sessions

## Implementation History & Lessons Learned
### Key Architectural Patterns Established
1. **Dynamic Dispatch Safety**: Always filter kwargs using `filter_kwargs_for_method` before calling dynamically dispatched methods
2. **Worker State Machine**: Formal states (IDLE, WAITING, BUSY, ERROR, SHUTDOWN) with proper transitions
3. **Idempotent Stream Creation**: Redis streams and consumer groups created safely for concurrent startup
4. **Session Cleanup**: Browser and TankPit engines cleaned up after each job and at shutdown
5. **Observability First**: Health/metrics endpoints, structured logging, deployment context awareness

## Priority Task List

### Phase 1: Fix Critical Issues ✅ MOSTLY COMPLETE
- [x] **Fix job acknowledgment** - Celery handles this automatically
- [x] **Complete QueueMetrics integration** - Autoscaler uses Flower API
- [x] **Implement dead letter queue** - Celery handles with max_retries
- [ ] **Remove Discord-channel code** (Still needed)
  - Delete close_channel, closeall commands
  - Remove channel_id from session management
  - Create abstract Context interface

### Phase 2: Celery Migration & Task Architecture ✅ MIGRATION COMPLETE
- [x] **Migrate to Celery** 
  - Installed celery[redis]
  - Created celery_app.py with Redis broker config
  - Converted browser jobs to Celery tasks
  - Replaced Broker class with Celery
  - Set up Celery routing for different queues
- [x] **Add Flower monitoring** - Running on port 5555
- [x] **Update autoscaler** - Uses Flower API for queue stats
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
  - Add TelegramFrontend with python-telegram integration
- [ ] **Kubernetes Deployment** (Week 3-4)
  - Create k8s manifests for all services
  - Set up ingress for web frontend
  - Configure horizontal pod autoscaling
  - Add persistent volumes for models

### Completed Technical Foundation
- [x] Distributed worker architecture with Celery
- [x] Scaling backends for Docker API, Kubernetes, Fly.io
- [x] Celery task queue with Redis backend
- [x] Flower monitoring UI integration
- [x] Worker autoscaling via Flower API
- [x] SSL support for Upstash Redis
- [x] Zero-worker bootstrap capability

## Master Checklist

### Distributed Swarm/Worker System
- [x] Migrate to Celery distributed task queue
- [x] Implement Celery tasks for browser operations
- [x] Add CeleryBrowserRuntime adapter
- [x] Build Celery worker entrypoint
    - [x] Updated entrypoint.worker.sh for Celery
    - [x] Support for different queue types (browser, tankpit, llm)
    - [x] Proper SSL configuration for Upstash Redis
- [x] Add Flower monitoring integration
- [x] Implement Celery autoscaler using Flower API
- [x] Update all tests to work with Celery
- [ ] Add multi-frontend support (Discord, Telegram, web, SMS, etc.)
    - [ ] Separate out logic from frontend specific code in swarm/plugins/commands/
- [ ] Add worker capability advertisement/heartbeat
- [x] Refactor queue naming in ProxyService/engines for generic MITM support
- [x] Add docker-compose example for swarm and workers

### Observability
- [x] Add HTTP server for /health and /metrics endpoints
- [x] Flower UI for real-time Celery task monitoring (port 5555)
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
- [x] Autoscaling workers based on queue depth via Flower API
- [x] Task retries and dead letter queue via Celery

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

### Celery Migration Success (2025-07-17)
1. **Accurate Queue Monitoring**: Autoscaler uses Flower API for real queue depths
2. **Proper Task Lifecycle**: Celery handles retries, timeouts, and failures automatically
3. **Smart Worker Scaling**: Only creates workers for truly pending tasks
4. **Zero-Worker Bootstrap**: Can start from no workers without deadlock

## Handoff Notes for Next Session
### Celery Migration Complete
- All browser tasks now use Celery instead of custom broker
- Autoscaler uses Flower API for accurate monitoring
- Workers can scale from zero
- Type safety maintained throughout

### Next Priorities
1. **Remove channel-centric design** - Delete close_channel commands
2. **Add task decomposition** - Break complex requests into subtasks
3. **Multi-frontend support** - Extract Discord-specific code
4. **Add more worker types** - Tankpit, LLM, etc.

### Remember the Vision
This is an AI task execution system, not a Discord-only system. Focus on:
- Task decomposition and planning
- Capability-based worker routing  
- Platform-agnostic frontends
- Massive scalability for complex tasks