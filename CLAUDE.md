# Claude Context for AI Task Assistant Project

## True Project Vision
This is NOT just a Discord integration - it's an AI-powered task execution system that can handle complex, real-world tasks like:
- "Do my latest homework assignment"
- "Research upcoming bills and prepare comments on the environmental bill"  
- "Improve the logging system in my codebase"
- "Analyze this company's financials and summarize the key risks"

Discord is merely ONE frontend interface. The system is designed to be platform-agnostic, with planned support for Telegram, web UI, SMS, and other interfaces.

## Core Architecture Philosophy
1. **Task-Oriented**: Users submit high-level tasks, not low-level commands
2. **Intelligent Decomposition**: A manager service breaks complex tasks into subtasks
3. **Capability-Based Workers**: Different workers have different skills (web browsing, code analysis, file editing, research, etc.)
4. **Distributed & Scalable**: Can scale to hundreds of workers for complex multi-step tasks
5. **Platform-Agnostic**: The core system doesn't care if requests come from Discord, Telegram, or API

## What Still Needs to Change
- **Remove Channel-Centric Design**: Current `/close_channel` and channel-to-browser mapping is wrong
- **Add Task Planning**: Need intelligent task decomposition and planning capabilities
- **Worker Capabilities**: Workers should advertise what they can do, not be hardcoded types
- **Session Management**: ~~Sessions should be task-scoped, not channel-scoped~~ - IN PROGRESS with browser session affinity design
- ✅ ~~**Job Visibility**: Need better monitoring~~ - DONE with celery-exporter and structured logging

## Collaboration Guidelines for Claude

### Code Quality Standards
1. **Production-Grade Only**: No quick fixes or patches. Every solution should be scalable and maintainable.
2. **Type Annotations Required**: All new code MUST have proper type hints for mypy strict mode.
3. **Real Tests, Not Mocks**: Write integration tests that test actual behavior. Avoid excessive mocking or monkey patching.
4. **Think Before Coding**: Understand existing systems before adding new code. Check for existing utilities/patterns.

### Communication Protocol
1. **Explain Changes First**: Before making code changes, provide a paragraph explaining what you're doing and why.
2. **Pause Between Files**: When switching files, pause to allow collaboration and ensure we stay on track.
3. **Ask About Design**: For significant architectural decisions, discuss options before implementing.
4. **Document Decisions**: Important design decisions should be documented in code comments or docs.

### Working Style
1. **Check Existing Code**: Always search for existing implementations before creating new ones.
2. **Understand the Why**: Don't just fix symptoms - understand root causes.
3. **Consider Standard Tools**: Before building custom solutions, consider if Redis, Docker, K8s, or other tools already solve the problem.
4. **Visibility Matters**: Design with observability in mind - we need to see what workers are doing.

## Key Commands
- **Run tests**: `make test` or `poetry run pytest`
- **Lint & format**: `make lint` (runs ruff fix, ruff format, mypy strict, yamllint)
- **Run swarm locally**: `make run` or `poetry run python -m swarm.core`
- **Run Celery worker**: `make celery-worker` (starts a browser worker)
- **Run Flower monitoring**: `make flower` (starts on port 5555)
- **Docker compose**: `make compose-up`, `make compose-down`
- **Deploy to Fly.io**: `make deploy`
- **Build swarm**: `make swarm-build`
- **Update swarm**: `make swarm-update` (builds, restarts, and tails logs)

## Port Configuration

Swarm uses several ports for different services:
- **9200**: Swarm metrics (main Discord frontend)
- **9100**: Worker metrics (default, configurable via WORKER_METRICS_PORT)
- **5555**: Flower (Celery monitoring UI)
- **9808**: Celery-exporter (Prometheus metrics for Celery)
- **9090**: Prometheus
- **3000**: Grafana
- **3100**: Loki
- **12345**: Alloy UI
- **6379**: Redis
- **6380**: HAProxy-Redis (failover proxy)

To avoid port conflicts:
1. Set `WORKER_METRICS_PORT` environment variable to change worker metrics port
2. Workers are dynamically created and don't expose ports to host by default
3. All paths are auto-detected (no hardcoded Windows/Linux paths)

## Architecture Notes

### Core Components
- **swarm/core/**: Main swarm functionality
  - `containers.py`: Dependency injection setup
  - `lifecycle.py`: Swarm lifecycle management
- **swarm/distributed/**: Distributed system components
  - `monitoring/heartbeat.py`: Health monitoring
  - `backends/`: Scaling backend implementations
  - `core/`: Core distributed functionality
  - `services/`: Distributed services

### Distributed Backends Status
Successfully implemented three scaling backends:
1. **DockerApiBackend** (`docker_api.py`): 
   - Uses Docker API directly for proper container lifecycle management
   - Auto-detects network and application paths
   - Configurable worker metrics port
   - Status: ✅ Replaced DockerComposeBackend due to orphaned container issues
   
2. **FlyIOBackend** (`fly_io.py`):
   - Uses fly CLI for Fly.io deployments
   - Manages machine counts in regions
   - Status: ✅ Complete with type safety (assert statements for runtime checks)
   
3. **KubernetesBackend** (`kubernetes.py`):
   - Uses kubectl for Kubernetes deployments
   - Scales deployment replicas
   - Status: ✅ Complete with type safety

### Key Architectural Patterns Established
1. **Dynamic Dispatch Safety**: Always filter kwargs using `filter_kwargs_for_method` before calling dynamically dispatched methods
2. **Worker State Machine**: Formal states (IDLE, WAITING, BUSY, ERROR, SHUTDOWN) with proper transitions
3. **Idempotent Stream Creation**: Redis streams and consumer groups created safely for concurrent startup
4. **Session Cleanup**: Browser and TankPit engines cleaned up after each job and at shutdown
5. **Observability First**: Health/metrics endpoints, structured logging, deployment context awareness

### Testing Approach
- Moving away from mocks to test actual features
- Test files in `tests/distributed/`:
  - `test_config.py` - Tests distributed configuration
  - `test_pool.py` - Tests worker pool management
  - `test_scaling_service.py` - Tests ScalingService (ORPHANED - to be removed)
  - `test_backends.py` - Tests backend implementations (uses subprocess mocking)
  - `test_celery_autoscaler.py` - Tests the Celery autoscaler script
  - `test_scaling_integration.py` - Integration tests for complete scaling flow
- Fake implementations in `tests/fakes/`:
  - `fake_redis.py` (FakeRedisClient)
  - `fake_scaling_backend.py` (FakeScalingBackend - implements protocol)

### Testing Recommendations
The `test_backends.py` currently uses AsyncMock and patches for subprocess testing. This could be improved by:
1. Creating a fake subprocess executor that can be injected
2. Using the FakeScalingBackend for integration tests
3. Testing command construction separately from execution

### Key Architectural Patterns Established
1. **Dynamic Dispatch Safety**: Always filter kwargs using `filter_kwargs_for_method` before calling dynamically dispatched methods
2. **Worker State Machine**: Formal states (IDLE, WAITING, BUSY, ERROR, SHUTDOWN) with proper transitions
3. **Idempotent Stream Creation**: Redis streams and consumer groups created safely for concurrent startup
4. **Session Cleanup**: Browser and TankPit engines cleaned up after each job and at shutdown
5. **Observability First**: Health/metrics endpoints, structured logging, deployment context awareness

### Dependencies
- Redis for distributed state management
- Docker/Docker Compose for containerization
- Poetry for dependency management
- Ruff for linting/formatting
- MyPy for type checking

## Recent Observability Improvements (2025-08-03)

### Monitoring Stack Enhanced
1. **Added celery-exporter** - Lightweight Prometheus metrics (20MB) replacing flower-refresher
2. **Enhanced Worker Logging**:
   - Celery signals automatically bind job_id to all task logs
   - Worker startup binds deployment context (hostname, container_id)
   - All logs now have structured context: service, worker_id, job_id
3. **Removed flower-refresher** - Was spamming logs every 5 seconds
4. **Updated Prometheus** - Now scrapes celery-exporter on port 9808
5. **Documentation Created**:
   - `docs/celery-monitoring-setup.md` - Complete monitoring setup guide
   - `docs/capability-queue-mapping.md` - Future capability-based routing design
   - `docs/service-architecture.md` - Maps all services and identifies orphaned code
   - `docs/service-cleanup-tasks.md` - Specific cleanup instructions
   - `docs/browser-session-affinity-design.md` - Production-grade solution for session routing
   - `docs/haproxy-deployment.md` - HAProxy Redis proxy deployment guide

### Recent Infrastructure Improvements (2025-08-03)
1. **HAProxy Configuration** - Added configurable connection limits and timeouts via env vars
2. **Docker Compose Profiles** - Added monitoring profile for optional services
3. **Debug Worker** - Created VNC-enabled worker configuration for visual debugging
4. **Fly.io Redis Proxy** - Separate deployment config for dedicated Redis proxy service

### Discovered Issues
1. **ScalingService is orphaned** - Defined but never used (replaced by celery_autoscaler)
2. **Services scattered** - No central organization or registry
3. **Old dashboard outdated** - Expects metrics from old Worker system, not Celery
4. **Browser session affinity** - Tasks with same session routed to different workers (design complete, implementation pending)

### Monitoring Commands
- **Check monitoring health**: `python scripts/check_monitoring.py`
- **Import Grafana dashboard**: Use ID 10026 (Celery Monitoring)
- **View worker logs**: Loki query: `{service="celery-worker"} | json`
- **Check metrics**: `curl localhost:9808/metrics` (celery-exporter)

## Handoff Context for Next Conversation

### Current State (2025-08-03)
- **Celery migration complete** - All browser tasks use Celery with proper retry/timeout handling
- **Observability enhanced** - Added celery-exporter, structured logging with job_id context
- **Architecture documented** - Created comprehensive guides including session affinity design
- **Infrastructure improved** - HAProxy configuration, Docker profiles, debug worker with VNC
- **Session affinity designed** - Production-grade solution with Lua scripts, TTL management, cleanup jobs

### Immediate Next Steps (Phase 1)

1. **Implement browser session affinity**:
   - Create SessionRegistry with Lua scripts for atomicity
   - Implement BrowserSessionRouter for Celery task routing
   - Add worker heartbeat with capability advertisement
   - Update BrowserTask to register/unregister sessions
   - Create direct worker queues for session-affined routing
   - Add integration test for concurrent goto/click operations

2. **Clean up orphaned code**: ✅ COMPLETE
   - ✅ Remove ScalingService from containers.py and its file (DONE)
   - ✅ Remove QueueMetricsService (DONE)
   - ✅ ScalingBackend protocol already in `swarm/distributed/protocols.py` (DONE)
   - ✅ All imports already use correct path (DONE)

3. **Organize services**:
   - Create `swarm/services/` directory structure
   - Move services to appropriate subdirectories
   - Document service lifecycle and dependencies

4. **Remove Discord-centric design**:
   - Delete `close_channel` from web.py (still exists)
   - Remove channel_id from browser session management
   - Create abstract `Context` class to replace Discord interactions

5. **Add more worker types**:
   - Implement tankpit worker queue and tasks
   - Add LLM worker type for local model inference
   - Create capability-based task routing

6. **Improve task decomposition**:
   - Add task planner that breaks complex requests into subtasks
   - Implement dependency graph for subtask execution
   - Add progress streaming via Redis pub/sub

7. **Multi-frontend support**:
   - Extract Discord-specific code to adapter
   - Add Telegram frontend
   - Add REST API frontend

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

### 5. Technology Stack (Implemented)
1. **Queue System**: ✅ COMPLETED - Migrated to **Celery** with Redis backend
   - Reduced codebase complexity significantly
   - Handles retries, routing, monitoring automatically  
   - Scales from 1 to 10,000 workers without code changes
   - Flower UI provides real-time task monitoring

2. **Orchestration**: Keep both backends, use **Kubernetes** for production
   - Docker Compose for development and simple deployments
   - Kubernetes for 100+ workers and production scale
   - Already have backends for both, minimal maintenance overhead

3. **Local LLM Integration** (Planned):
   - New worker type: `llm_worker` using llama.cpp or vLLM
   - Runs on local RTX 3090 Ti (24GB VRAM)
   - Capabilities: analyze, summarize, extract, reason
   - Models: Llama 2 70B quantized, Mixtral 8x7B

## Master Implementation Checklist

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
- [ ] Add worker capability advertisement/heartbeat (IN PROGRESS - session affinity design complete)
- [x] Refactor queue naming in ProxyService/engines for generic MITM support
- [x] Add docker-compose example for swarm and workers

### Observability
- [x] Add HTTP server for /health and /metrics endpoints
- [x] Flower UI for real-time Celery task monitoring (port 5555)
- [x] Add celery-exporter for Prometheus metrics (port 9808)
- [x] Integrate Prometheus metrics for workers
- [x] Centralize logs with Loki and Alloy
- [x] Enhanced structured logging with job_id and worker_id context
- [ ] Add comprehensive Grafana dashboards for job queue, worker health, and resource usage

### Operational Excellence
- [x] Docker Compose/Fly.io/Kubernetes configs for orchestrator + scalable workers + Redis
- [x] Healthchecks and graceful shutdown for all services
- [x] HAProxy for Redis failover (Upstash ↔ local Redis)
- [ ] Document scaling, rolling upgrades, and zero-downtime deploys
- [ ] Document security model (network, secrets, etc.)
- [ ] Add Redis Sentinel for production HA

### Advanced Features
- [ ] Streaming results/logs via Redis Pub/Sub
- [ ] Smart job routing based on worker capabilities
- [x] Autoscaling workers based on queue depth via Flower API
- [x] Task retries and dead letter queue via Celery
- [ ] Task decomposition and dependency management
- [ ] Progress tracking for complex multi-step tasks