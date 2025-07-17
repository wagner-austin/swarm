# Celery Migration Guide

## Overview

We've migrated from custom Redis streams to Celery for distributed task processing. This provides:
- Built-in retry logic and error handling
- Automatic failover between Upstash and local Redis
- Better monitoring via Flower
- Process-level autoscaling within workers
- Container-level autoscaling based on queue depth

## Redis Configuration

The system supports multiple Redis configurations:

1. **Primary: Upstash Redis** (configured in `.env` as `REDIS_URL`)
   - Used for production workloads
   - Has rate limits but is cloud-hosted
   - SSL support with rediss:// URLs

2. **Fallback: Local Redis** (configured in `.env` as `REDIS_FALLBACK_URL`)
   - Used when REDIS_FALLBACK_ENABLED=true
   - Points to redis://redis:6379/0 in Docker
   - Useful for development or when Upstash hits rate limits

## Running with Celery

```bash
# Start all services (includes Flower, Redis, autoscaler)
docker-compose up -d

# View logs
docker-compose logs -f

# The autoscaler automatically manages worker containers
# To manually create workers, use:
docker run -d --name browser-worker-1 \
  --network swarm_default \
  -e CELERY_QUEUES=browser \
  swarm:latest /usr/local/bin/entrypoint.worker.sh
```

## Key Services

### Flower (Port 5555)
Web UI for monitoring Celery tasks and workers
- View real-time task execution
- Monitor queue depths
- See worker status
- Access at http://localhost:5555

### Celery Workers
- **Browser Worker**: Handles web automation tasks
  - Uses prefork pool (Playwright compatible)
  - Process autoscaling: 1-4 processes per container
  - Container autoscaling: Based on queue depth

### Autoscaler
- Monitors Celery queues via Flower API
- Creates/destroys worker containers based on demand
- Configurable thresholds in `config.yaml`

## Worker Configuration

Each worker supports these environment variables:
- `CELERY_QUEUES`: Comma-separated queue names (default: browser)
- `CELERY_CONCURRENCY`: Number of worker processes (default: 1)
- `CELERY_AUTOSCALE`: Process autoscaling "max,min" (e.g., "4,1")
- `CELERY_POOL`: Pool type - prefork/solo (default: prefork)
- `CELERY_LOGLEVEL`: Log level (default: info)
- `CELERY_MAX_TASKS`: Tasks before worker restart (default: 100)

## Monitoring

1. **Flower Dashboard**: http://localhost:5555
   - Real-time task monitoring
   - Queue statistics
   - Worker health

2. **Prometheus Metrics**: http://localhost:9090
   - Worker metrics on ports 9100+
   - Autoscaler metrics

3. **Grafana Dashboards**: http://localhost:3000
   - Import dashboards from `config/Example Dashboards/`

## Troubleshooting

### Redis Connection Issues
If you see Redis connection errors:
1. Check Upstash dashboard for rate limits (500K request limit)
2. Verify Upstash credentials in `.env`
3. Enable fallback: Set `REDIS_FALLBACK_ENABLED=true` in `.env`
4. Ensure local Redis is running: `docker-compose up redis`

### Worker Not Processing Tasks
1. Check Flower UI for worker status
2. Verify queue names match between producer and worker
3. Check worker logs: `docker logs celery-worker-browser`

### Autoscaler Issues
1. Ensure Flower is running and accessible
2. Check autoscaler logs: `docker logs autoscaler`
3. Verify Docker socket is mounted correctly

## Migration from Old System

| Old Component | New Component | Notes |
|--------------|---------------|-------|
| `broker.py` | Celery | Handles job distribution |
| `worker.py` | `celery_worker.py` | Celery-based worker |
| Redis streams | Celery queues | Different data structure |
| `manager.py` | Built into Celery | No separate manager needed |
| `autoscaler.py` | `celery_autoscaler.py` | Uses Flower API |

## Next Steps

1. **Add more worker types**: Create workers for different task types (LLM, analysis, etc.)
2. **Configure routing**: Route tasks to specific queues based on type
3. **Set up monitoring**: Import Grafana dashboards and configure alerts
4. **Production deployment**: Use Kubernetes with KEDA for cloud-native autoscaling