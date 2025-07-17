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

## What Needs to Change
- **Remove Channel-Centric Design**: Current `/close_channel` and channel-to-browser mapping is wrong
- **Add Task Planning**: Need intelligent task decomposition and planning capabilities
- **Worker Capabilities**: Workers should advertise what they can do, not be hardcoded types
- **Session Management**: Sessions should be task-scoped, not channel-scoped
- **Job Visibility**: Need better monitoring of what each worker is doing and job progress

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

## Current Implementation Notes

### Major Migration Completed (2025-07-17)
Successfully migrated from custom Redis streams broker to **Celery** distributed task queue:

1. **Celery Integration Complete**: 
   - All browser tasks now use Celery with proper retry/timeout handling
   - Flower monitoring UI integrated for task visibility (port 5555)
   - Automatic failover between Upstash and local Redis

2. **Autoscaler Rewritten**:
   - Uses Celery's inspect API via Flower for queue monitoring
   - Properly distinguishes between active and pending tasks
   - Can bootstrap from zero workers (no chicken-and-egg problem)

3. **Type Safety Maintained**:
   - All code passes mypy strict mode
   - Proper handling of Task generic types using TYPE_CHECKING pattern
   - Async Redis operations using redis.asyncio

4. **Channel-Centric Design Still Present**: 
   - `/close_channel` commands still exist but less critical with Celery
   - Session management needs refactoring for task-scoped design

### Migration Benefits Realized
- **Automatic retries**: Celery handles failed tasks with exponential backoff
- **Task routing**: Different queues for browser, tankpit, llm workers  
- **Better monitoring**: Flower provides real-time task status and history
- **Connection pooling**: Redis connections managed efficiently by Celery
- **No more zombie jobs**: Failed tasks properly handled, no infinite loops

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
- **9090**: Prometheus
- **3000**: Grafana
- **3100**: Loki
- **12345**: Alloy UI
- **6379**: Redis

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

### Recent Improvements
1. **Protocol Implementation**: All backends now properly implement the `ScalingBackend` protocol
   - Made protocol `@runtime_checkable` for better type safety
   - All backends explicitly inherit from `ScalingBackend`
   
2. **Type Safety**: Fixed all mypy strict mode errors
   - Added assert statements for runtime safety checks
   - Fixed subprocess command type issues
   - Added comprehensive type annotations to tests
   
3. **Integration Updates**:
   - `autoscaler.py`: Now properly uses the backends with type safety
   - `orchestrator.py`: Updated to use `check_and_scale_all()` method
   - Both handle None backend cases gracefully

### Testing Approach
- Moving away from mocks to test actual features
- Test files in `tests/distributed/`:
  - `test_config.py` - Tests distributed configuration
  - `test_pool.py` - Tests worker pool management
  - `test_scaling_service.py` - Tests ScalingService with FakeScalingBackend
  - `test_backends.py` - Tests backend implementations (uses subprocess mocking)
  - `test_autoscaler.py` - Tests the production autoscaler script
  - `test_scaling_integration.py` - Integration tests for complete scaling flow
- Fake implementations in `tests/fakes/`:
  - `fake_redis.py` (FakeRedisClient)
  - `fake_scaling_backend.py` (FakeScalingBackend - implements protocol)

### Testing Recommendations
The `test_backends.py` currently uses AsyncMock and patches for subprocess testing. This could be improved by:
1. Creating a fake subprocess executor that can be injected
2. Using the FakeScalingBackend for integration tests
3. Testing command construction separately from execution

### Dependencies
- Redis for distributed state management
- Docker/Docker Compose for containerization
- Poetry for dependency management
- Ruff for linting/formatting
- MyPy for type checking

## Recent Changes (from git log)
- Successfully migrated from custom broker.py to Celery (2025-07-17)
- Integrated Flower for Celery monitoring
- Fixed all mypy strict mode errors with TYPE_CHECKING pattern
- Autoscaler now uses Celery's inspect API via Flower
- All tests updated to work with Celery

## Celery Migration Details

**Successfully replaced custom Redis streams with Celery (2025-07-17):**

1. **Queue Monitoring**: Celery autoscaler uses Flower API to get accurate queue depths
2. **Worker Scaling**: Properly scales based on pending tasks, not active ones  
3. **Task Lifecycle**: Celery handles retries, timeouts, and dead letter queues automatically
4. **Zero-worker Bootstrap**: Autoscaler can start workers from zero (fixed chicken-and-egg problem)
5. **SSL Support**: Added proper SSL configuration for Upstash Redis with rediss:// URLs

## Test Organization

### Unit Tests
- Individual component testing with mocks where necessary
- Backend command construction verification

### Integration Tests
- **test_scaling_integration.py**: Complete scaling flow with dependency injection
- **test_autoscaler.py**: Production autoscaler service testing
- Tests job timeout scenarios when no workers exist
- Tests autoscaler creating workers on demand

## Completed Tasks
1. ✅ Implemented ScalingBackend protocol with @runtime_checkable
2. ✅ All backends (Docker API, Fly.io, Kubernetes) implement the protocol
3. ✅ Fixed all mypy strict mode errors
4. ✅ Added comprehensive test coverage
5. ✅ Created integration tests with dependency injection
6. ✅ Cleaned up test organization and naming
7. ✅ Migrated from custom broker.py to Celery distributed task queue
8. ✅ Integrated Flower monitoring UI for task visibility
9. ✅ Fixed autoscaler to work with Celery and bootstrap from zero workers
10. ✅ Updated all tests to work with CeleryBrowserRuntime

## Handoff Context for Next Conversation

### Where We Left Off (2025-07-17)
1. **Completed Celery migration** - All browser tasks now use Celery instead of custom broker
2. **Fixed autoscaler issues** - Now uses Flower API for accurate queue monitoring  
3. **Maintained type safety** - All code passes mypy strict mode
4. **Updated documentation** - README reflects new Celery architecture

### Immediate Next Steps (Phase 1)

1. **Remove Discord-centric design**:
   - Delete `close_channel` from web.py (still exists)
   - Remove channel_id from browser session management
   - Create abstract `Context` class to replace Discord interactions

2. **Add more worker types**:
   - Implement tankpit worker queue and tasks
   - Add LLM worker type for local model inference
   - Create capability-based task routing

3. **Improve task decomposition**:
   - Add task planner that breaks complex requests into subtasks
   - Implement dependency graph for subtask execution
   - Add progress streaming via Redis pub/sub

4. **Multi-frontend support**:
   - Extract Discord-specific code to adapter
   - Add Telegram frontend
   - Add REST API frontend

### Key Insights Gained
- The project is an AI task assistant, NOT a Discord-only system
- Discord is just one frontend among many planned
- Need task decomposition and capability-based workers
- Session management should be task-scoped, not channel-scoped
- Existing QueueMetricsService solves the scaling problem but isn't used

### Key Files in Celery Migration
- `swarm/celery_app.py` - Celery configuration with task routing
- `swarm/tasks/browser.py` - Browser tasks using Celery
- `swarm/distributed/celery_runtime.py` - CeleryBrowserRuntime adapter
- `scripts/celery_autoscaler.py` - Autoscaler using Flower API
- `scripts/entrypoint.worker.sh` - Worker entrypoint for Celery
- `docker-compose.yml` - Added Flower service, updated for Celery

## Architecture Decisions Made

### Technology Stack (Decided)
1. **Queue System**: ✅ COMPLETED - Migrated to **Celery** with Redis backend
   - Reduced codebase complexity significantly
   - Handles retries, routing, monitoring automatically  
   - Scales from 1 to 10,000 workers without code changes
   - Flower UI provides real-time task monitoring

2. **Orchestration**: Keep both backends, use **Kubernetes** for production
   - Docker Compose for development and simple deployments
   - Kubernetes for 100+ workers and production scale
   - Already have backends for both, minimal maintenance overhead

3. **Local LLM Integration** (Phase 2):
   - New worker type: `llm_worker` using llama.cpp or vLLM
   - Runs on local RTX 3090 Ti (24GB VRAM)
   - Capabilities: analyze, summarize, extract, reason
   - Models: Llama 2 70B quantized, Mixtral 8x7B

### Specific Implementation Path

**Phase 1: Core Fixes** ✅ COMPLETED (2025-07-17)
- ✅ Fixed job lifecycle with Celery (no more infinite retries)
- ✅ Autoscaler uses Flower API (accurate worker scaling)
- ✅ Celery handles dead letter queue automatically
- ⏳ Still need to remove Discord-channel assumptions

**Phase 2: Celery Migration** ✅ COMPLETED (2025-07-17)
- ✅ Replaced broker.py with Celery
- ✅ Migrated browser jobs to Celery tasks
- ✅ Set up Celery routing for different queues
- ✅ Added Flower for monitoring

**Phase 3: Task Intelligence (Month 2-3)**
- Add LLM workers for local processing
- Implement task decomposition service
- Create capability-based routing
- Build simple web UI

**Phase 4: Scale & Polish (Month 3+)**
- Deploy to Kubernetes cluster
- Add more worker capabilities
- Implement task progress streaming
- Create Telegram & API frontends