# Production-Grade Redis Fallback Solution

## Overview

This document describes the production-grade Redis backend abstraction that automatically handles Upstash rate limits by failing over to a local Redis instance.

## Architecture

### Design Principles

1. **No Brittle Conditionals**: Uses strategy pattern and protocol-based design
2. **Automatic Failover**: Detects rate limits and switches seamlessly
3. **Circuit Breaker**: Prevents cascade failures with intelligent backoff
4. **Integration**: Works with existing logging, metrics, and exception infrastructure
5. **Zero Code Changes**: Existing code continues to work without modification

### Components

```
RedisBackend (Protocol)
    ├── BaseRedisBackend (Abstract base with common logic)
    │   ├── UpstashRedisBackend (Detects rate limits)
    │   └── LocalRedisBackend (Docker/self-hosted)
    └── FallbackRedisBackend (Orchestrates failover)
```

### Key Features

1. **Rate Limit Detection**
   - UpstashRedisBackend parses rate limit errors
   - Raises `RedisRateLimitError` with limit/usage details
   - Triggers automatic failover to local Redis

2. **Circuit Breaker Pattern**
   - Tracks consecutive failures
   - Opens circuit after threshold (5 failures)
   - Resets after cooldown period (60 seconds)

3. **Health Monitoring**
   - Periodic health checks (30-second intervals)
   - Automatic recovery when primary becomes healthy
   - Metrics integration for monitoring

4. **Connection Resilience**
   - Retry logic with exponential backoff
   - Keep-alive settings for connection stability
   - Graceful handling of network issues

## Configuration

### Environment Variables

```bash
# Primary Redis (Upstash)
REDIS__URL=rediss://default:xxx@upstash.io:6379/0
REDIS_URL=rediss://default:xxx@upstash.io:6379/0

# Fallback configuration
REDIS_FALLBACK_ENABLED=true              # Enable automatic fallback
REDIS_FALLBACK_URL=redis://localhost:6379/0  # Local Redis URL
```

### Docker Compose

The local Redis is already configured in `docker-compose.yml`:

```yaml
redis:
  image: redis:7-alpine
  container_name: redis
  ports:
    - "6379:6379"
  volumes:
    - redis-data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
  restart: unless-stopped
```

## Usage

### Starting the System

1. **Start local Redis**:
   ```bash
   docker-compose up -d redis
   ```

2. **Run swarm**:
   ```bash
   make run
   ```

### Testing Fallback

```bash
# Test the fallback mechanism
poetry run python scripts/test_redis_fallback.py
```

### Monitoring

The system emits metrics for monitoring:

- `redis.upstash.connect.success/failure`
- `redis.upstash.command.success/failure`
- `redis.upstash.rate_limit_exceeded`
- `redis.local.connect.success/failure`
- `redis.local.command.success/failure`
- `redis.fallback.activated`
- `redis.fallback.switched`
- `redis.fallback.restored`
- `redis.{backend}.circuit_breaker.open`

## How It Works

### Normal Operation
1. All Redis operations go to Upstash
2. Health checks run every 30 seconds
3. Metrics track operation success/failure

### Rate Limit Hit
1. Upstash returns "max requests limit exceeded"
2. UpstashRedisBackend raises `RedisRateLimitError`
3. FallbackRedisBackend catches error
4. Automatically switches to local Redis
5. Sets 5-minute timer before retrying Upstash

### Recovery
1. Background task checks Upstash health
2. If healthy, switches back automatically
3. Logs restoration for visibility

## Integration Points

### Existing Code Compatibility

The `create_redis_client()` function returns a proxy that maintains compatibility with existing code expecting a Redis client:

```python
# Old code (unchanged)
redis_client = await create_redis_client()
await redis_client.set("key", "value")

# Behind the scenes uses new backend abstraction
```

### Future Integration

To fully integrate this solution:

1. Update `swarm/core/containers.py`:
   ```python
   # Replace line 109-116 with:
   redis_client = providers.Singleton(
       create_redis_client,
       config() if callable(config) else Settings()
   )
   ```

2. Update broker initialization similarly

3. Add Redis backend status to health endpoints

## Advantages

1. **No Manual Intervention**: Automatic failover and recovery
2. **Cost Effective**: Use free Upstash tier with local fallback
3. **Production Ready**: Circuit breakers, health checks, metrics
4. **Maintainable**: Clean abstraction, no nested conditionals
5. **Observable**: Full metrics and logging integration

## Next Steps

1. **Testing**: Run integration tests with simulated rate limits
2. **Monitoring**: Set up Grafana dashboards for Redis metrics
3. **Alerting**: Configure alerts for fallback activation
4. **Documentation**: Update operator runbooks

## Troubleshooting

### Fallback Not Working
- Check local Redis is running: `docker ps | grep redis`
- Verify REDIS_FALLBACK_ENABLED=true
- Check logs for connection errors

### Stuck on Fallback
- Check Upstash dashboard for rate limit reset
- Manually trigger health check in logs
- Verify network connectivity to Upstash

### Performance Issues
- Monitor Redis connection pool usage
- Check circuit breaker metrics
- Verify retry delays aren't too aggressive