# Celery Monitoring Setup Guide

This guide helps you set up comprehensive monitoring for Swarm's Celery workers using industry-standard tools.

## Architecture Overview

```
┌─────────────┐     ┌─────────────────┐     ┌────────────┐     ┌─────────┐
│   Workers   │────▶│ celery-exporter │────▶│ Prometheus │────▶│ Grafana │
└─────────────┘     └─────────────────┘     └────────────┘     └─────────┘
       │                                                               │
       │                   ┌──────┐                                   │
       └──────────────────▶│ Loki │───────────────────────────────────┘
                           └──────┘
                         (via Alloy)
```

## What's Changed

### Before (Old System)
- Custom Worker class with built-in metrics endpoint
- Metrics like `worker_state`, `worker_memory_bytes`
- Custom dashboard reading these metrics

### After (Current System)
- Celery workers with celery-exporter
- Industry-standard metrics like `celery_task_runtime_seconds`, `celery_queue_length`
- Grafana Labs community dashboards

## Step 1: Verify Services Are Running

```bash
# Check that all monitoring services are up
docker compose ps

# You should see:
# - celery-exporter (port 9808)
# - prometheus (port 9090)
# - grafana (port 3000)
# - loki (port 3100)
# - alloy
```

## Step 2: Import Celery Dashboard

1. Open Grafana at http://localhost:3000
2. Default login: admin/admin
3. Go to Dashboards → Import
4. Enter dashboard ID: **10026** (Celery Monitoring by danihodovic)
5. Select your Prometheus data source
6. Click Import

Alternative dashboards:
- **20076** - Celery Tasks Dashboard (more detailed task view)
- **13681** - Celery Exporter (simpler overview)

## Step 3: Configure Dashboard Variables

Most Grafana dashboards have variables at the top. Configure:
- `datasource`: Select your Prometheus instance
- `job`: Select `celery_exporter`

## Step 4: View Worker Logs in Grafana

1. Go to Explore in Grafana
2. Select Loki as data source
3. Use this query to see worker logs with context:
   ```
   {service="celery-worker"} | json | line_format "[{{.worker_id}}] [{{.job_id}}] {{.message}}"
   ```

4. To see only errors:
   ```
   {service="celery-worker"} | json | level=~"ERROR|CRITICAL"
   ```

## Available Metrics

### From celery-exporter (port 9808)

| Metric | Description | Use Case |
|--------|-------------|----------|
| `celery_worker_up` | Worker liveness (1=up, 0=down) | Alerting on worker failures |
| `celery_queue_length{queue_name="browser"}` | Tasks waiting in queue | Autoscaling decisions |
| `celery_task_runtime_seconds` | Task execution time histogram | Performance monitoring |
| `celery_task_sent_total` | Tasks sent counter | Throughput tracking |
| `celery_task_succeeded_total` | Successful tasks | Success rate calculation |
| `celery_task_failed_total` | Failed tasks | Error rate monitoring |
| `celery_task_retried_total` | Retried tasks | Retry rate analysis |

### From Worker Prometheus Endpoint (port 9100)

Each worker also exposes basic process metrics:
- `process_cpu_seconds_total` - CPU usage
- `process_resident_memory_bytes` - Memory usage
- `python_info` - Python version and platform

## Creating Custom Dashboards

### Example: Task Success Rate Panel
1. Add new panel in Grafana
2. Use this query:
   ```promql
   (sum(rate(celery_task_succeeded_total[5m])) / sum(rate(celery_task_sent_total[5m]))) * 100
   ```
3. Set unit to "percent"
4. Add threshold: 95% = green, 90% = yellow, below = red

### Example: Queue Depth by Queue
```promql
celery_queue_length
```
Legend: `{{queue_name}}`

### Example: P95 Task Runtime
```promql
histogram_quantile(0.95, sum(rate(celery_task_runtime_seconds_bucket[5m])) by (le))
```

## Alerting Rules

Add these to Prometheus for proactive monitoring:

```yaml
groups:
  - name: celery_alerts
    rules:
      - alert: CeleryWorkerDown
        expr: celery_worker_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Celery worker {{ $labels.hostname }} is down"
      
      - alert: CeleryQueueBacklog
        expr: celery_queue_length > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Queue {{ $labels.queue_name }} has {{ $value }} pending tasks"
      
      - alert: CeleryHighFailureRate
        expr: |
          (sum(rate(celery_task_failed_total[5m])) / sum(rate(celery_task_sent_total[5m]))) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Task failure rate is {{ $value | humanizePercentage }}"
```

## Troubleshooting

### No metrics showing up?
1. Check celery-exporter logs: `docker compose logs celery-exporter`
2. Verify Prometheus can reach exporter: http://localhost:9090/targets
3. Check Redis connection: `docker compose logs celery-exporter | grep redis`

### Workers not visible?
- Celery workers register when they process tasks
- Send a test task to make them appear
- Check Grafana dashboards and Prometheus metrics; Flower is no longer part of the default stack.

### Logs not appearing in Loki?
1. Check Alloy is running: `docker compose logs alloy`
2. Verify JSON logging: `docker compose logs swarm | Select-Object -First 10`
3. Check Loki data source in Grafana settings

## Best Practices

1. [removed] Flower has been removed from the default deployment; use Grafana/Prometheus or logs for monitoring.
   - Great for debugging task chains
   - Disable in production (memory/performance issues)

2. **Use Labels for Filtering**
   - Queue name: `{queue_name="browser"}`
   - Task name: `{name="swarm.tasks.browser.goto"}`
   - Worker hostname: `{hostname="worker-1"}`

3. **Set Appropriate Retention**
   - Metrics: 15-30 days (Prometheus)
   - Logs: 7 days (Loki)
   - Adjust based on disk space

4. **Monitor the Monitors**
   - Set up alerts for Prometheus/Loki disk usage
   - Monitor celery-exporter memory usage

## Next Steps

1. **Phase 2**: Add Redis Sentinel for broker HA
2. **Phase 3**: Migrate to Kubernetes with KEDA autoscaling
3. **Phase 4**: Add OpenTelemetry for distributed tracing

## References

- [Celery Exporter Documentation](https://github.com/danihodovic/celery-exporter)
- [Grafana Celery Dashboards](https://grafana.com/grafana/dashboards/?search=celery)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)
- [Loki Label Best Practices](https://grafana.com/docs/loki/latest/best-practices/)
