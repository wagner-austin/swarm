# Swarm Scaling Architecture

## Overview

The Discord integration uses a distributed architecture where Discord commands trigger jobs that are processed by dynamically scaled workers. **Important: Worker scaling is NOT automatic when commands are issued - it requires the autoscaler service to be running.**

## How It Works

### 1. Discord Command Flow

When a user runs a command like `/web start`:

```
User -> Discord -> Swarm -> RemoteBrowserRuntime -> Broker -> Redis Stream
```

1. User executes `/web start` in Discord
2. The Web cog receives the interaction
3. `RemoteBrowserRuntime.start()` creates a job
4. Broker publishes the job to Redis stream (`jobs` or `browser:jobs`)
5. Job waits in the queue

### 2. Worker Scaling Flow

**The autoscaler service must be running for workers to be created:**

```
Autoscaler -> ScalingService -> Redis (check queues) -> ScalingBackend -> Docker/K8s/Fly
```

1. Autoscaler runs continuously (default: every 30s)
2. `ScalingService.check_and_scale_all()` checks queue depths
3. Makes scaling decisions based on thresholds
4. Executes scaling via the configured backend

### 3. Job Processing Flow

Once workers exist:

```
Worker -> Broker.consume() -> Process Job -> Redis (result) -> User gets response
```

## Key Components

### Autoscaler Service (`scripts/autoscaler.py`)

**This service MUST be running for automatic scaling to work!**

```bash
# Run the autoscaler
python -m scripts.autoscaler --orchestrator docker-compose

# Or with environment variables
REDIS_URL=redis://localhost:6379 \
ORCHESTRATOR=kubernetes \
CHECK_INTERVAL=30 \
python -m scripts.autoscaler
```

### Scaling Configuration

Each worker type has scaling thresholds in `DistributedConfig`:

```python
"browser": WorkerTypeConfig(
    scaling=ScalingConfig(
        min_workers=1,      # Minimum workers to maintain
        max_workers=10,     # Maximum workers allowed
        scale_up_threshold=5,   # Queue depth to trigger scale up
        scale_down_threshold=0, # Queue depth to trigger scale down
        cooldown_seconds=60,    # Wait between scaling operations
    )
)
```

### Scaling Backends

- **DockerApiBackend**: Uses Docker SDK for direct container management
- **KubernetesBackend**: Uses `kubectl scale deployment`
- **FlyIOBackend**: Uses `fly scale count`

## Important Notes

### Workers Are NOT Created Automatically!

1. **Discord commands only create jobs** - they don't create workers
2. **Jobs will timeout** if no workers exist and no autoscaler is running
3. **The autoscaler must be running** to create workers based on demand

### Testing Scaling

To test if scaling works:

1. Start with no workers: `docker-compose down`
2. Start the autoscaler: `python -m scripts.autoscaler`
3. Run a Discord command: `/web start`
4. Watch the autoscaler logs - it should detect the job and scale up
5. Check workers: `docker-compose ps`

### Manual Scaling

You can also manually scale workers:

```bash
# Docker Compose
docker-compose up -d --scale worker=3

# Kubernetes
kubectl scale deployment/discord-worker-browser --replicas=3

# Fly.io
fly scale count worker-browser=3
```

## Monitoring

### Check Queue Depths

```python
# In Redis
XLEN browser:jobs
XLEN tankpit:jobs
```

### Check Worker Health

```python
# Worker heartbeats in Redis
SCAN 0 MATCH worker:heartbeat:browser:*
```

### View Scaling Events

```python
# Scaling history in Redis
XRANGE scaling:events - +
```

## Troubleshooting

### Jobs Timing Out?

1. **Check if autoscaler is running**: Look for autoscaler process/logs
2. **Check Redis connectivity**: Ensure Redis is accessible
3. **Check scaling backend**: Ensure Docker/K8s/Fly CLI works
4. **Check worker health**: Workers might be unhealthy

### Workers Not Scaling?

1. **Check queue depth**: Must exceed `scale_up_threshold`
2. **Check cooldown**: Wait for `cooldown_seconds` between operations
3. **Check max workers**: Can't exceed `max_workers` limit
4. **Check backend errors**: Look for subprocess execution errors

### Integration Test Example

See `tests/distributed/test_discord_to_worker_flow.py` for a complete example of testing the entire flow from Discord command to worker creation.