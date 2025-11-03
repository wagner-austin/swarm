# Swarm Scaling Architecture

## Overview

The Discord integration uses a distributed architecture where Discord commands trigger jobs that are processed by dynamically scaled workers. Important: Worker scaling is NOT automatic when commands are issued — it requires the autoscaler service to be running.

## How It Works

### 1. Discord Command Flow

When a user runs a command like `/web start`:

```
User -> Discord -> Swarm -> CeleryBrowserRuntime -> Celery -> Redis (via HAProxy)
```

1. User executes `/web start` in Discord
2. The Web cog receives the interaction
3. `CeleryBrowserRuntime.start()` creates a Celery task
4. Celery publishes the task to Redis queue via HAProxy (port 6380)
5. Task waits in the queue

### 2. Worker Scaling Flow

The autoscaler service must be running for workers to be created:

```
Autoscaler -> Redis/Celery (queue depth) -> ScalingBackend -> Docker/K8s/Fly
```

1. Autoscaler runs continuously (default: every 30s)
2. Reads Celery queue depth (via Kombu/Redis transport)
3. Makes scaling decisions based on thresholds
4. Executes scaling via the configured backend

### 3. Job Processing Flow

Once workers exist:

```
Worker -> Celery Worker -> Process Task -> Redis (result) -> User gets response
```

## Key Components

### Autoscaler Service (`scripts/celery_autoscaler.py`)

This service MUST be running for automatic scaling to work!

```bash
python -m scripts.celery_autoscaler --orchestrator=docker-api

# Or with environment variables
ORCHESTRATOR=docker-api \
CHECK_INTERVAL=30 \
python -m scripts.celery_autoscaler
```

### Scaling Configuration

Each worker type has scaling thresholds in `DistributedConfig`:

```python
"browser": WorkerTypeConfig(
    scaling=ScalingConfig(
        min_workers=1,
        max_workers=10,
        scale_up_threshold=5,
        scale_down_threshold=0,
        cooldown_seconds=60,
    )
)
```

### Scaling Backends

- DockerApiBackend: Uses Docker SDK for direct container management
- KubernetesBackend: Uses `kubectl scale deployment`
- FlyIOBackend: Uses `fly scale count`

## Important Notes

### Redis High Availability via HAProxy

All services connect to Redis through HAProxy (port 6380) which provides:
- Automatic failover between Upstash (primary) and local Redis (backup)
- Health checks every few seconds (per-server intervals)
- Transparent to all services — they just connect to `haproxy-redis:6380`

### Workers Are NOT Created Automatically!

1. Discord commands only create jobs — they don't create workers
2. Jobs will timeout if no workers exist and no autoscaler is running
3. The autoscaler must be running to create workers based on demand

### Testing Scaling

To test if scaling works:

1. Start with no workers: `docker compose down`
2. Start the autoscaler: `python -m scripts.celery_autoscaler`
3. Run a Discord command: `/web start`
4. Watch the autoscaler logs — it should detect the job and scale up
5. Check workers: `docker compose ps`

### Manual Scaling

```bash
# Docker Compose (if you maintain a static worker service)
docker compose up -d --scale worker=3

# Kubernetes
kubectl scale deployment/discord-worker-browser --replicas=3

# Fly.io
fly scale count worker-browser=3
```

## Monitoring

### Check Queue Depths

Celery uses Redis lists for queues. To check queue size:

```
LLEN browser
```

### Check Worker Health

```python
SCAN 0 MATCH worker:heartbeat:browser:*
```

### View Scaling Events

```python
XRANGE scaling:events - +
```

## Troubleshooting

### Jobs Timing Out?

1. Check if autoscaler is running
2. Check Redis connectivity
3. Check scaling backend (Docker/K8s/Fly)
4. Check worker health

### Workers Not Scaling?

1. Check queue depth vs `scale_up_threshold`
2. Check cooldown (`cooldown_seconds`)
3. Check `max_workers` limit
4. Check backend subprocess errors

### Integration Test Example

See `tests/distributed/test_discord_to_worker_flow.py` for a complete example.
