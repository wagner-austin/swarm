# Claude Context for AI Task Assistant Project

## True Project Vision
This is NOT a Discord bot - it's an AI-powered task execution system that can handle complex, real-world tasks like:
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

### Critical Issues Found (2025-07-16)
1. **Missing Browser Methods**: The web commands call `browser.status`, `browser.close_channel`, and `browser.close_all` which don't exist in BrowserEngine, causing jobs to remain pending forever.

2. **Autoscaler Creating Excess Workers**: 
   - ScalingService uses simple `xlen()` instead of QueueMetricsService
   - Doesn't distinguish between pending (being processed) and new messages
   - With `scale_up_threshold=1`, creates workers for already-processing jobs
   - Failed jobs remain pending, triggering more useless workers

3. **No Job Acknowledgment on Failure**: When jobs fail, they're never acknowledged in Redis, creating an infinite retry loop.

4. **Channel-Centric Design Mismatch**: The codebase assumes Discord channels map to browser sessions, but this doesn't align with the task-oriented vision.

### Existing Solutions Not Being Used
- **QueueMetricsService** exists and properly handles pending vs new messages but isn't integrated
- **Redis XPENDING** support is implemented but not used for scaling decisions
- **Worker state machine** exists but job lifecycle visibility is poor

### Quick Wins vs Proper Fixes
- Quick Fix: Add missing browser methods → ❌ Wrong (addresses symptom not cause)
- Proper Fix: Rethink session management for task-based architecture → ✅ Right
- Quick Fix: Increase scale thresholds → ❌ Wrong (band-aid)
- Proper Fix: Integrate QueueMetricsService and handle failures properly → ✅ Right

## Key Commands
- **Run tests**: `make test` or `poetry run pytest`
- **Lint & format**: `make lint` (runs ruff fix, ruff format, mypy strict, yamllint)
- **Run bot locally**: `make run` or `poetry run python -m bot.core`
- **Docker compose**: `make compose-up`, `make compose-down`
- **Deploy to Fly.io**: `make deploy`
- **Build bot**: `make bot-build`
- **Update bot**: `make bot-update` (builds, restarts, and tails logs)

## Port Configuration

The bot uses several ports for different services:
- **9200**: Bot metrics (main Discord frontend)
- **9150**: Manager metrics (job orchestrator)
- **9100**: Worker metrics (default, configurable via WORKER_METRICS_PORT)
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
- **bot/core/**: Main bot functionality
  - `containers.py`: Dependency injection setup
  - `lifecycle.py`: Bot lifecycle management
- **bot/distributed/**: Distributed system components
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
- Refactoring tests away from mocks to test actual features
- Adding orchestrating cogs
- Implementing distributed backends
- All tests currently passing

## Important: Current Worker Scaling Issues

**The autoscaler has critical bugs:**

1. **Uses wrong queue depth calculation**: Just counts all messages with `xlen`, not distinguishing between pending and new
2. **Creates excess workers**: With `scale_up_threshold=1`, it creates workers for already-processing jobs
3. **Failed jobs stay pending forever**: Worker doesn't acknowledge failed messages, causing infinite retry loops
4. **Solution exists but not wired**: QueueMetricsService properly handles pending vs new messages but isn't integrated

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
2. ✅ All backends (Docker Compose, Fly.io, Kubernetes) implement the protocol
3. ✅ Fixed all mypy strict mode errors
4. ✅ Added comprehensive test coverage
5. ✅ Created integration tests with dependency injection
6. ✅ Cleaned up test organization and naming

## Handoff Context for Next Conversation

### Where We Left Off (2025-07-16)
1. **Discovered the root cause** of why `/web` commands fail and autoscaler creates excess workers
2. **Identified mismatch** between Discord-centric codebase and true vision of AI task assistant
3. **Already integrated** QueueMetricsService into ScalingService (but not committed)
4. **Updated documentation** to reflect true project vision

### Immediate Next Steps (Phase 1) - With Specific Implementation

1. **Fix job acknowledgment in worker.py**:
   - In `dispatch()` method after line 199, add: `await broker.ack_job(job.id, job.stream)`
   - Implement `ack_job()` in Broker class using `xack` command
   - Even failed jobs must be ACK'd to prevent infinite retries

2. **Complete QueueMetrics integration**:
   - Test the modified `get_queue_depth()` in scaling_service.py
   - Update autoscaler to pass queue metrics to `make_scaling_decision()`
   - Set browser `scale_up_threshold=3` (not 1) in config.py line 88

3. **Add dead letter queue**:
   - After 3 failures, move job to "failed:jobs" stream
   - Add `retry_count` to job metadata
   - Create worker command to reprocess dead letter queue

4. **Replace Discord-centric with task-centric design**:
   - Delete `close_channel` from web.py (lines 306-348)
   - Remove channel_id from browser session management
   - Create abstract `Context` class to replace Discord interactions

### Key Insights Gained
- The project is an AI task assistant, NOT a Discord bot
- Discord is just one frontend among many planned
- Need task decomposition and capability-based workers
- Session management should be task-scoped, not channel-scoped
- Existing QueueMetricsService solves the scaling problem but isn't used

### Working Files Modified Today
- `bot/distributed/services/scaling_service.py` - Started integrating QueueMetricsService
- `bot/browser/engine.py` - Started adding missing methods (status, close_channel, close_all)
- `CLAUDE.md` - Updated with true vision and collaboration guidelines
- `PLAN.md` - Reframed as AI Task Assistant with phased approach

## Architecture Decisions Made

### Technology Stack (Decided)
1. **Queue System**: Migrate from custom broker.py to **Celery** with Redis backend
   - Reduces codebase by 30%
   - Handles retries, routing, monitoring automatically
   - Scales from 1 to 10,000 workers without code changes

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

**Phase 1: Core Fixes (Next 2 weeks)**
- Fix job acknowledgment (prevents infinite retries)
- Complete QueueMetrics integration (fixes excess workers)
- Remove Discord-channel assumptions
- Add basic dead letter queue

**Phase 2: Celery Migration (Following month)**
- Replace broker.py with Celery
- Migrate job types to Celery tasks
- Set up Celery routing for different worker types
- Add Flower for monitoring

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