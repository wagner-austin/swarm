# Distributed Bot Logging and Monitoring Architecture

This document describes the comprehensive logging and monitoring system for the distributed multi-worker bot architecture.

## Overview

The bot system features a production-grade centralized logging and observability platform with:

- **Structured JSON logging** with rich metadata
- **Distributed worker monitoring** with heartbeat system  
- **Prometheus metrics** and health endpoints
- **Grafana integration** for visualization and alerting
- **Multi-frontend support** (Discord, Telegram, web, SMS)
- **Auto-scaling worker fleet** with real-time observability

## Architecture Components

### 1. Enhanced Logging System (`bot/core/logger_setup.py`)

#### Context Variables
Every log record includes comprehensive metadata:

```python
# Core service context
service: str          # "bot", "worker", "browser", "tankpit" 
worker_id: str        # "worker-1", "worker-2", etc.
job_id: str          # "browser.navigate.abc123"

# Deployment/infrastructure context  
hostname: str         # "bot-server-01"
container_id: str     # Docker container ID
deployment_env: str   # "local", "staging", "production"
region: str          # "us-west-1", "eu-central-1"
```

#### Usage
```python
from bot.core.logger_setup import (
    setup_logging,
    bind_log_context, 
    bind_deployment_context,
    auto_detect_deployment_context
)

# Configure logging (call once at startup)
setup_logging()

# Auto-detect deployment context
deployment_context = auto_detect_deployment_context()
bind_deployment_context(**deployment_context)

# Bind service context
bind_log_context(service="bot", worker_id="worker-1")

# All subsequent logs will include this metadata
logger.info("Processing user request")  # Includes all context automatically
```

### 2. HTTP Monitoring Endpoints (`bot/distributed/monitoring/http.py`)

Each worker exposes monitoring endpoints on port 9200 (configurable):

#### Health Endpoint (`/health`)
Returns detailed health information:

```json
{
  "status": "healthy",
  "state": "BUSY", 
  "worker_id": "worker-1",
  "uptime_seconds": 3600.5,
  "system": {
    "hostname": "bot-server-01",
    "platform": "Linux-5.4.0",
    "python_version": "3.11.2"
  },
  "resources": {
    "memory_mb": 245.7,
    "memory_percent": 2.4,
    "cpu_percent": 15.3,
    "num_threads": 12
  },
  "timestamp": 1688851200.123
}
```

#### Metrics Endpoint (`/metrics`)
Prometheus-compatible metrics with rich labels:

```
# HELP worker_state Current state of the worker
# TYPE worker_state gauge
worker_state{worker_id="worker-1",hostname="bot-server-01",container_id="a1b2c3",deployment_env="production",region="us-west-1"} 2

# HELP worker_memory_bytes Worker memory usage in bytes
# TYPE worker_memory_bytes gauge  
worker_memory_bytes{worker_id="worker-1",hostname="bot-server-01",container_id="a1b2c3",deployment_env="production",region="us-west-1"} 257654784

# Additional metrics: CPU, uptime, jobs processed/failed, threads, file handles
```

### 3. Heartbeat System (`bot/distributed/monitoring/heartbeat.py`)

#### Features
- **Periodic status reporting** to Redis (default: 30s intervals)
- **Automatic cleanup** of stale worker data (TTL-based)
- **Time-series storage** in Redis streams for analysis
- **Comprehensive system metrics** collection

#### Usage
```python
from bot.distributed.monitoring.heartbeat import WorkerHeartbeat
import redis.asyncio as redis

redis_client = redis.from_url("redis://localhost:6379")
heartbeat = WorkerHeartbeat(
    redis_client=redis_client,
    worker_id="worker-1", 
    interval_seconds=30.0,
    worker=worker_instance
)

await heartbeat.start()  # Starts background heartbeat task
# ... worker runs ...
await heartbeat.stop()   # Graceful shutdown
```

#### Redis Data Structure
```
# Worker status hash (latest data)
worker:heartbeat:worker-1 -> {
  "worker_id": "worker-1",
  "state": "BUSY", 
  "timestamp": "1688851200.123",
  "resources": {...},
  "system": {...}
}

# Status stream (time-series)
worker:status -> [
  {"worker_id": "worker-1", "timestamp": "...", ...},
  {"worker_id": "worker-2", "timestamp": "...", ...}
]
```

### 4. Log Directory Structure

```
logs/
├── bot/                    # Main bot service logs
│   ├── bot.jsonl          # Production JSON logs
│   └── bot-dev.log        # Development logs
├── workers/               # Distributed worker logs  
│   ├── worker-1.jsonl     # Worker-specific logs
│   ├── worker-2.jsonl
│   └── browser-session.log # Session-specific logs
└── archive/               # Rotated/archived logs
    ├── bot.jsonl.1.gz
    └── worker-1.jsonl.1.gz
```

## Deployment Configurations

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `LOG_LEVEL` | Logging level | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | Output format | `json` | `json`, `pretty` |
| `LOG_TO_FILE` | Enable file logging | `0` | `1` for enabled |
| `DEPLOYMENT_ENV` | Environment name | `local` | `production`, `staging` |
| `HEARTBEAT_INTERVAL` | Heartbeat frequency (seconds) | `30` | `10`, `60` |
| `METRICS_PORT` | HTTP metrics port | `9200` | Any available port |

### Docker Compose Integration

```yaml
services:
  worker:
    environment:
      - LOG_LEVEL=INFO
      - LOG_FORMAT=json  
      - DEPLOYMENT_ENV=production
      - HEARTBEAT_INTERVAL=30
      - METRICS_PORT=9200
      - FLY_REGION=us-west-1
    volumes:
      - ./logs:/app/logs
    labels:
      - "prometheus.io/scrape=true"
      - "prometheus.io/port=9200"
      - "prometheus.io/path=/metrics"
```

## Log Aggregation Pipeline

### 1. Grafana Alloy Configuration (`alloy-config.river`)

Collects logs from Docker containers and ships to Loki:

```hcl
// Discover Docker containers
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// Collect logs from discovered containers
loki.source.docker "containers" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.containers.targets
  forward_to = [loki.process.bot_logs.receiver]
}

// Process and enrich logs
loki.process "bot_logs" {
  // Extract container name
  stage.regex {
    expression = "(?P<container_name>bot|worker)"
    source     = "__meta_docker_container_name"
  }

  // Parse JSON logs
  stage.json {
    expressions = {
      timestamp       = "timestamp",
      level          = "levelname", 
      service        = "service",
      worker_id      = "worker_id",
      hostname       = "hostname",
      deployment_env = "deployment_env",
      message        = "message"
    }
  }

  // Apply labels for filtering/grouping
  stage.labels {
    values = {
      container_name = "container_name",
      level          = "level",
      service        = "service", 
      worker_id      = "worker_id",
      hostname       = "hostname",
      deployment_env = "deployment_env"
    }
  }

  forward_to = [loki.write.loki.receiver]
}
```

### 2. Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'bot-workers'
    static_configs:
      - targets: ['worker-1:9200', 'worker-2:9200']
    scrape_interval: 15s
    metrics_path: /metrics
    
  - job_name: 'bot-main'
    static_configs:
      - targets: ['bot:9200']
    scrape_interval: 30s
```

## Grafana Dashboards

### Example Queries

```
# Worker State Overview
worker_state

# Resource Usage by Worker
worker_memory_bytes / 1024 / 1024

# Job Processing Rate  
rate(worker_jobs_processed_total[5m])

# Error Rate
rate(worker_jobs_failed_total[5m]) / rate(worker_jobs_processed_total[5m])

# Log Analysis (Loki)
{service="worker", level="ERROR"} |= "browser"
{deployment_env="production"} | json | memory_mb > 500
```

### Dashboard Panels
- **Worker Fleet Status** - Real-time state of all workers
- **Resource Usage** - CPU, memory, threads across workers
- **Job Processing** - Throughput, success/failure rates
- **Error Analysis** - Recent errors with context
- **System Health** - Uptime, heartbeat status

## Multi-Frontend Support

The logging system is designed for multi-frontend architectures:

```python
# Different service types get appropriate logging
bind_log_context(service="discord_bot")
bind_log_context(service="telegram_bot")  
bind_log_context(service="web_frontend")
bind_log_context(service="sms_gateway")

# Logs include frontend type for filtering
{service="telegram_bot"} |= "message_received"
```

## Testing and Development

### Local Development
```bash
# Pretty console logs
export LOG_FORMAT=pretty LOG_LEVEL=DEBUG

# Run with file logging
export LOG_TO_FILE=1

poetry run bot
```

### Testing Log Structure
```python
import json
from bot.core.logger_setup import setup_logging, bind_log_context

def test_structured_logging(caplog):
    setup_logging({"root": {"level": "DEBUG"}})
    bind_log_context(service="test", worker_id="test-worker")
    
    logger = logging.getLogger("test")
    logger.info("Test message", extra={"custom_field": "value"})
    
    # Verify log structure
    record = caplog.records[0]
    assert record.service == "test"
    assert record.worker_id == "test-worker"
```

## Troubleshooting

### Common Issues

1. **Missing psutil dependency**
   ```bash
   poetry add psutil
   ```

2. **Alloy configuration errors**
   - Check Docker socket permissions
   - Verify Loki endpoint connectivity
   - Test regex patterns with sample logs

3. **Worker heartbeat failures**
   - Check Redis connectivity
   - Verify Redis streams creation
   - Monitor Redis memory usage

4. **High memory usage**
   - Check log rotation settings
   - Monitor open file handles
   - Adjust heartbeat interval

### Debug Commands

```bash
# Check worker status via Redis
redis-cli HGETALL worker:heartbeat:worker-1

# View recent heartbeats
redis-cli XREAD COUNT 10 STREAMS worker:status 0

# Test metrics endpoint
curl http://localhost:9200/metrics

# Verify log structure
docker logs bot-worker-1 | jq .
```

## Performance Considerations

- **Log Volume**: JSON logs are larger but provide more value
- **Heartbeat Frequency**: Balance monitoring granularity vs. Redis load
- **Metric Collection**: psutil calls have minimal overhead
- **File Rotation**: Configure based on disk space and retention needs
- **Stream Storage**: Monitor Redis memory usage for time-series data

## Security Notes

- **Container Isolation**: Each worker logs to separate files/streams
- **Metadata Sanitization**: Ensure no sensitive data in log metadata
- **Access Control**: Secure Grafana/Prometheus endpoints in production
- **Log Retention**: Configure appropriate retention policies for compliance

This architecture provides production-grade observability for the distributed bot system while maintaining performance and scalability.
