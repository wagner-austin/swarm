# Test Categories Guide

## Test Markers

### @pytest.mark.unit
Fast tests using mocks/fakes. Should run in < 1 second.
```python
@pytest.mark.unit
def test_parse_url():
    # Tests pure logic with no external dependencies
```

### @pytest.mark.integration
Tests requiring external services but not full Docker stack.
```python
@pytest.mark.integration
@pytest.mark.redis
async def test_redis_operations():
    # Requires Redis running but not full Docker Compose
```

### @pytest.mark.docker
Tests requiring Docker Compose services.
```python
@pytest.mark.docker
@pytest.mark.integration
async def test_haproxy_failover():
    # Requires: docker compose up -d
```

### @pytest.mark.slow
Tests taking > 5 seconds.
```python
@pytest.mark.slow
@pytest.mark.integration
async def test_browser_scraping():
    # Long-running browser automation
```

## Running Tests by Category

```bash
# Fast unit tests only
pytest -m "unit"

# Integration tests (skip if no services)
pytest -m "integration and not docker"

# Full integration with Docker
pytest -m "docker"

# Everything except slow tests
pytest -m "not slow"

# Run all tests
pytest
```

## Current Test Coverage Issues

### Over-mocked Tests
These tests should have integration variants:
- `test_scaling_service.py` - Only uses FakeRedisClient
- `test_backends.py` - Mocks Docker/Kubernetes commands
- `test_celery_autoscaler.py` - Mocks Flower API

### Missing Integration Tests
- No test verifies services connect through HAProxy
- No test for Redis failover with real Celery tasks
- No test for autoscaler creating real Docker containers

### Recommended New Tests
1. `test_haproxy_service_integration.py` - Verify each service uses HAProxy
2. `test_redis_failover_e2e.py` - Full failover with task execution
3. `test_autoscaler_docker_integration.py` - Real container scaling