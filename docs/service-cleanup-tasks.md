# Service Cleanup Tasks

Quick reference for cleaning up the Swarm service architecture.

## Immediate Tasks

### 1. Remove Orphaned Code
```bash
# Files to remove or refactor:
- swarm/distributed/services/scaling_service.py  # Replaced by celery_autoscaler
- swarm/distributed/services/queue_metrics.py    # Not compatible with Celery
- Remove scaling_service from swarm/core/containers.py
```

### 2. Move Protocols
```python
# Create swarm/distributed/protocols.py with:
- ScalingBackend (protocol)
- ScalingDecision (enum)

# Update imports in:
- scripts/celery_autoscaler.py
- swarm/distributed/backends/*.py
```

### 3. Consolidate Service Directories

**Current Structure** (messy):
```
swarm/
├── browser/engine.py           # BrowserEngine service
├── core/
│   ├── containers.py          # DI container with unused services
│   ├── service_base.py        # Base service protocol
│   └── telemetry.py           # Metrics service
├── distributed/
│   ├── services/              # Mix of used/unused services
│   └── monitoring/            # Worker monitoring
└── infra/
    └── tankpit/engine.py      # Unused proxy service
```

**Proposed Structure** (clean):
```
swarm/
├── services/
│   ├── __init__.py
│   ├── base.py               # ServiceABC protocol
│   ├── browser/
│   │   └── engine.py         # BrowserEngine
│   ├── monitoring/
│   │   ├── telemetry.py      # Prometheus metrics
│   │   └── health.py         # Health checks
│   └── registry.py           # Future service registry
├── tasks/                    # Keep Celery tasks separate
└── infrastructure/           # Deployment configs
```

## Code to Remove

### From containers.py
```python
# REMOVE these imports:
from swarm.distributed.services.scaling_service import ScalingService

# REMOVE these providers:
scaling_service = providers.Singleton(
    ScalingService,
    redis_client=redis_client,
    config=distributed_config,
    backend=scaling_backend,
)
```

### Update celery_autoscaler.py
```python
# CHANGE:
from swarm.distributed.services.scaling_service import ScalingBackend, ScalingDecision

# TO:
from swarm.distributed.protocols import ScalingBackend, ScalingDecision
```

## Testing Impact

### Tests to Update
1. `tests/distributed/test_scaling_service.py` - Remove entirely
2. `tests/distributed/test_backends.py` - Update import
3. `tests/scripts/test_celery_autoscaler.py` - Update import

### Tests to Keep
- All backend tests (Docker, K8s, Fly)
- Autoscaler tests
- Worker tests

## Docker Compose Changes

### Remove flower-refresher (already done)
```yaml
# REMOVED - flower-refresher service
```

### Consider Removing (Phase 2)
```yaml
# If not using Flower UI in production:
# - flower service (keep celery-exporter instead)
```

## Verification Steps

1. **Check imports**: `grep -r "ScalingService" swarm/`
2. **Check DI usage**: `grep -r "scaling_service" swarm/`
3. **Run tests**: `make test`
4. **Check metrics**: `curl localhost:9200/metrics`
5. **Verify autoscaler**: `docker-compose logs autoscaler`

## Benefits After Cleanup

1. **Clarity**: Clear which services are actually used
2. **Maintainability**: Less dead code to maintain
3. **Onboarding**: Easier for new developers to understand
4. **Performance**: Slightly faster startup (no unused services)
5. **Future-proof**: Clean foundation for capability-based routing