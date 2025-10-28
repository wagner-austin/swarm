# HAProxy Redis Proxy Deployment Guide

## Overview

The swarm project uses a separate HAProxy Fly app (`swarm-redis-proxy`) to handle Redis failover between Upstash and backup Redis instances. This keeps the main application containers lean and allows independent scaling/deployment of the proxy layer.

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│ corvis-ai   │────▶│ swarm-redis-proxy│────▶│ Upstash     │
│ (main app)  │     │   (HAProxy)      │     │ (primary)   │
└─────────────┘     └──────────────────┘     └─────────────┘
                              │                      
                              └──────────────▶┌─────────────┐
                                              │ Backup Redis│
                                              │ (failover)  │
                                              └─────────────┘
```

## Deployment Steps

### 1. Initial Setup (One-time)

```bash
# Create the HAProxy app
fly launch --name swarm-redis-proxy --no-deploy --config fly.redis-proxy.toml

# Set the Redis URLs secret
fly secrets set CELERY_BROKER_URLS="rediss://default:pass@upstash-host.upstash.io:6379;redis://default:pass@backup.redis.com:6379" -a swarm-redis-proxy
```

### 2. Deploy HAProxy (Must be done BEFORE main app)

```bash
# Build and deploy the HAProxy image
fly deploy -a swarm-redis-proxy -c fly.redis-proxy.toml
```

### 3. Configure Main App Secrets

```bash
# Set Redis connection to point to the proxy
fly secrets set \
  REDIS__URL="redis://default:yourpassword@swarm-redis-proxy.internal:6380/0" \
  CELERY_BROKER_URLS="redis://default:yourpassword@swarm-redis-proxy.internal:6380/0" \
  -a corvis-ai
```

### 4. Deploy Main App

```bash
# Deploy the main application
fly deploy -a corvis-ai
```

## CI/CD Integration

Add this to your GitHub Actions workflow:

```yaml
deploy-redis-proxy:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: superfly/flyctl-actions/setup-flyctl@master
    
    - name: Deploy HAProxy
      run: |
        fly deploy -a swarm-redis-proxy -c fly.redis-proxy.toml
      env:
        FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

deploy-main-app:
  needs: [deploy-redis-proxy]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: superfly/flyctl-actions/setup-flyctl@master
    
    - name: Deploy Main App
      run: |
        fly deploy -a corvis-ai
      env:
        FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

## Monitoring

- HAProxy stats: `fly ssh console -a swarm-redis-proxy` then `curl http://localhost:8080/stats`
- Check proxy logs: `fly logs -a swarm-redis-proxy`
- Verify connections: `fly logs -a corvis-ai | grep "redis-proxy.internal"`

## Troubleshooting

1. **Connection refused**: Ensure HAProxy is deployed and healthy before deploying main app
2. **Auth errors**: Verify the password in CELERY_BROKER_URLS matches what's in your Redis URLs
3. **Failover not working**: Check HAProxy logs and ensure both Redis backends are reachable
