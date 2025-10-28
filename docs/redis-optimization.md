# Redis Command Optimization Guide

Date: 2025-10-27
Scope: Reducing Redis command usage for cost optimization on free-tier plans

## Current Redis Usage Analysis

### Command Statistics (Idle Bot)

From `redis-cli INFO commandstats`:

| Command | Calls | Purpose |
|---------|-------|---------|
| LLEN | 10,074 | Check queue lengths (autoscaler + celery-exporter) |
| BRPOP | 5,264 | Worker task polling (1s timeout) |
| DEL | 4,728 | Cleanup reply queues after Inspect calls |
| EXEC | 3,719 | Transaction commits (with MULTI) |
| MULTI | 3,719 | Transaction starts (priority queue checks) |
| PUBLISH | ~2,000 | Worker heartbeats + Inspect broadcasts |
| AUTH | ~1,000 | Connection authentication |
| CLIENT | ~1,000 | Client metadata (redis-py) |
| EXPIRE | ~500 | TTL management |

Total (idle, 1 worker): ~259,200 commands/day

## Command Sources Breakdown

### 1. Worker Task Polling (~86,400 commands/day)

Pattern:
```
BRPOP "browser.direct.{worker_id}" "browser" ... "1"
```
Frequency: Every 1 second per worker
Optimization: Cannot reduce (Celery core behavior)

### 2. Celery Autoscaler (~43,200 commands/day)

Pattern (every 30s):
```
PUBLISH "/0.celery.pidbox" (inspect.active_queues)
MULTI
LLEN "reply.celery.pidbox" x4
EXEC
BRPOP "reply.celery.pidbox" ...
DEL "reply.celery.pidbox" x4
```
Savings options:
- Increase CHECK_INTERVAL (e.g., 300s) — ~90% reduction
- Stop autoscaler when idle (dev only)

### 3. Celery Exporter (~86,400 commands/day)

Pattern (Prometheus scrapes):
```
PUBLISH "/0.celery.pidbox" (inspect.stats, inspect.active_queues)
MULTI/LLEN/EXEC/BRPOP/DEL cycle
```
Savings option:
- Set scrape_interval to 60s in `config/prometheus.yml` — ~75% reduction

### 4. Worker Heartbeats (~43,200 commands/day)

Event stream disabled by default to reduce chatter; basic heartbeats are essential.

## Recommended Optimizations

### Idle Development Bot
```bash
docker compose stop autoscaler celery-exporter
docker compose start autoscaler celery-exporter
```

### Production
```yaml
# docker compose.yml
autoscaler:
  environment:
    - CHECK_INTERVAL=300

# config/prometheus.yml
scrape_configs:
  - job_name: 'celery-exporter'
    scrape_interval: 60s
```

Result expiry (already configured): one hour to prevent unbounded accumulation.

## Free Tier Cost Analysis (Upstash)

- Limit: 500,000 commands/month (~16,666/day)
- Idle (monitoring stopped): ~129,600/day
- Production optimized: ~155,520/day

Conclusion: Free tier insufficient for 24/7 operation; use local Redis or paid plans.

## Alternatives

### Use Local Redis (no Upstash)
```env
HAPROXY_REDIS_URLS=redis://default:${REDIS_PASSWORD}@redis:6379/0
```

