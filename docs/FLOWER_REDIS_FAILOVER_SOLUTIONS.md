# Flower Redis Failover Solutions

## Problem Statement

Flower monitoring UI doesn't natively support Redis failover when using multiple Redis brokers. When the primary Redis (Upstash) hits rate limits or fails, Celery can automatically failover to the fallback Redis, but Flower continues trying to connect to the primary broker and fails.

## Implemented Solution

We implemented **Option 1: HAProxy Redis Proxy** as the production solution. This provides automatic, transparent failover for all services including Flower.

### Implementation Details

1. **HAProxy Service**: Added to main `docker-compose.yml`
   - Builds from `Dockerfile.haproxy` with Python for config generation
   - Generates configuration at runtime from environment variables
   - Listens on port 6380 for Redis connections
   - Stats dashboard available at http://localhost:8080/stats

2. **All Services Updated**: 
   - `swarm`: Uses `redis://haproxy-redis:6380/0`
   - `flower`: Uses `redis://haproxy-redis:6380/0` 
   - `autoscaler`: Uses `redis://haproxy-redis:6380/0`
   - New workers: Inherit HAProxy URL from autoscaler

3. **Automatic Failover**:
   - Primary: Upstash Redis (SSL enabled)
   - Fallback: Local Redis container
   - Health checks every 3 seconds
   - Automatic switch on failure

### How It Works

1. **On Startup**:
   - HAProxy container starts and runs `entrypoint.haproxy.sh`
   - Script generates config from `REDIS_URL` and `REDIS_FALLBACK_URL` 
   - HAProxy starts with the generated configuration

2. **During Operation**:
   - All services connect to HAProxy on port 6380
   - HAProxy forwards to Upstash (primary)
   - If Upstash fails/rate limits, HAProxy switches to local Redis
   - Services continue working without interruption

3. **No Manual Steps**:
   - Just run `docker compose up -d --build`
   - Everything is automated

## Solution Options

### Option 1: HAProxy Redis Proxy (✅ IMPLEMENTED)

Use HAProxy as a Redis connection proxy that automatically detects the master and routes traffic.

**Advantages:**
- Transparent to Flower - it just connects to HAProxy
- Handles authentication and SSL termination
- Can check Redis health and role
- Production-tested solution

**Implementation:**

1. Add HAProxy service to docker-compose.yml:
```yaml
haproxy:
  image: haproxy:2.8-alpine
  container_name: haproxy-redis
  volumes:
    - ./config/haproxy-redis.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
  ports:
    - "6380:6380"  # HAProxy Redis endpoint
  depends_on:
    - redis
  restart: unless-stopped
```

2. Create config/haproxy-redis.cfg:
```
global
    daemon
    maxconn 256
    # Enable runtime API for dynamic configuration
    stats socket /var/run/haproxy.sock mode 600 level admin

defaults
    mode tcp
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms
    option tcplog

# Redis frontend - what Flower connects to
frontend redis_frontend
    bind *:6380
    default_backend redis_backend

backend redis_backend
    mode tcp
    balance first
    option tcp-check
    
    # For Upstash with auth
    tcp-check send AUTH\ ${UPSTASH_PASSWORD}\r\n
    tcp-check expect string +OK
    tcp-check send PING\r\n
    tcp-check expect string +PONG
    tcp-check send QUIT\r\n
    tcp-check expect string +OK
    
    # Primary: Upstash (with SSL passthrough)
    server upstash ${UPSTASH_HOST}:${UPSTASH_PORT} check inter 2s fall 3 rise 2 ssl verify none
    
    # Fallback: Local Redis
    server local redis:6379 check inter 2s fall 3 rise 2 backup
```

3. Update Flower configuration:
```yaml
flower:
  command:
    - celery
    - --broker=redis://haproxy-redis:6380/0
    - flower
```

### Option 2: Custom Flower Broker URL Wrapper

Create a Python wrapper that monitors Redis health and updates Flower's broker URL dynamically.

**Implementation:**

1. Create scripts/flower_wrapper.py:
```python
#!/usr/bin/env python3
import os
import subprocess
import time
import asyncio
from swarm.infra.redis_backends import create_redis_backend

async def get_active_broker_url():
    """Get the currently active broker URL."""
    backend = create_redis_backend()
    await backend.connect()
    url = backend.url
    await backend.disconnect()
    return url

def start_flower(broker_url):
    """Start Flower with the given broker URL."""
    cmd = [
        "celery",
        f"--broker={broker_url}",
        "flower",
        "--port=5555",
        "--url_prefix="
    ]
    return subprocess.Popen(cmd)

async def main():
    """Monitor broker health and restart Flower if needed."""
    current_url = await get_active_broker_url()
    process = start_flower(current_url)
    
    while True:
        await asyncio.sleep(30)  # Check every 30 seconds
        new_url = await get_active_broker_url()
        
        if new_url != current_url:
            print(f"Broker URL changed from {current_url} to {new_url}")
            process.terminate()
            process.wait()
            current_url = new_url
            process = start_flower(current_url)

if __name__ == "__main__":
    asyncio.run(main())
```

2. Update docker-compose.yml:
```yaml
flower:
  command:
    - python
    - -m
    - scripts.flower_wrapper
```

### Option 3: Nginx TCP Proxy with Health Checks

Use Nginx as a TCP proxy with upstream health checks.

**Implementation:**

1. Create config/nginx-redis.conf:
```nginx
stream {
    upstream redis_backend {
        zone redis_zone 64k;
        
        # Primary Upstash
        server upstash.io:6379 max_fails=3 fail_timeout=30s;
        
        # Fallback local
        server redis:6379 backup;
    }
    
    server {
        listen 6380;
        proxy_pass redis_backend;
        proxy_connect_timeout 1s;
        proxy_timeout 30s;
        proxy_socket_keepalive on;
    }
}
```

### Option 4: Envoy Proxy with Circuit Breaker

Use Envoy proxy with built-in circuit breaker and failover support.

**Advantages:**
- Advanced health checking
- Circuit breaker pattern
- Observability built-in
- Can handle SSL/TLS

**Implementation:**
```yaml
# config/envoy-redis.yaml
static_resources:
  listeners:
  - name: redis_listener
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 6380
    filter_chains:
    - filters:
      - name: envoy.filters.network.redis_proxy
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.redis_proxy.v3.RedisProxy
          stat_prefix: redis_stats
          settings:
            op_timeout: 5s
            enable_redirection: true
            enable_command_stats: true
          prefix_routes:
            routes:
            - prefix: "/"
              cluster: redis_cluster

  clusters:
  - name: redis_cluster
    connect_timeout: 1s
    type: STRICT_DNS
    lb_policy: ROUND_ROBIN
    outlier_detection:
      consecutive_5xx: 3
      interval: 30s
      base_ejection_time: 30s
    health_checks:
    - timeout: 1s
      interval: 5s
      interval_jitter: 1s
      unhealthy_threshold: 3
      healthy_threshold: 2
      custom_health_check:
        name: redis_health_check
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.health_checkers.redis.v3.Redis
          key: health
    load_assignment:
      cluster_name: redis_cluster
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: upstash.io
                port_value: 6379
          priority: 0
        - endpoint:
            address:
              socket_address:
                address: redis
                port_value: 6379
          priority: 1
```

### Option 5: Modify Flower to Use Celery's Connection

Fork Flower and modify it to use Celery's broker connection instead of creating its own.

**Note:** This requires maintaining a fork of Flower, which increases maintenance burden.

## Benefits of HAProxy Solution

1. **Zero Code Changes**: Services just connect to HAProxy
2. **Production-Grade**: HAProxy is battle-tested for high-traffic scenarios
3. **Transparent Failover**: Services don't know about backend switches
4. **Low Latency**: <1ms overhead for proxy layer
5. **Real-time Monitoring**: Stats dashboard shows backend health
6. **Automatic Recovery**: Returns to primary when it's healthy again

## Key Files

1. **Dockerfile.haproxy**: Builds HAProxy with Python for config generation
2. **scripts/entrypoint.haproxy.sh**: Generates config and starts HAProxy
3. **scripts/generate_haproxy_config.py**: Creates HAProxy config from environment
4. **docker-compose.yml**: All services configured to use haproxy-redis:6380

## Testing the Failover

```bash
# Start services
docker compose up -d --build

# Check HAProxy stats dashboard
open http://localhost:8080/stats
# Shows primary (Upstash) and backup (local) status

# Test Redis connection through HAProxy
redis-cli -h localhost -p 6380 ping

# Run the automated failover test
python tests/integration/test_haproxy_failover.py

# Check Flower monitoring
open http://localhost:5555
# Should work even during failover
```

## Future Enhancements

1. Add Redis Sentinel support for more robust failover
2. Implement connection pooling in HAProxy
3. Add metrics export from HAProxy to Prometheus
4. Consider Redis Cluster for horizontal scaling