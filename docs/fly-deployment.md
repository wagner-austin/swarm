# Fly.io Deployment Guide

This guide covers deploying the Swarm distributed system to Fly.io with Celery workers, autoscaling, and monitoring.

## Prerequisites

1. Install the Fly CLI: https://fly.io/docs/flyctl/install/
2. Authenticate: `fly auth login`
3. Create app if not exists: `fly apps create corvis-ai` (or your app name)

## Required Secrets

Before deploying, set these secrets using `fly secrets set`:

```bash
# Redis connection (via HAProxy proxy app). See haproxy-deployment.md
# Point application to the proxy's internal address on port 6380
fly secrets set REDIS__URL="redis://default:your-password@swarm-redis-proxy.internal:6380/0"
# Celery can use the same surface (or omit to fall back to REDIS__URL)
fly secrets set CELERY_BROKER_URLS="redis://default:your-password@swarm-redis-proxy.internal:6380/0"

# Discord bot token
fly secrets set DISCORD_TOKEN="your-discord-bot-token"

# Fly.io API token for autoscaler (create at https://fly.io/user/personal_access_tokens)
fly secrets set FLY_API_TOKEN="your-fly-api-token"

# Optional: Other Discord/app settings
fly secrets set DISCORD_CHANNEL_ID="your-channel-id"
fly secrets set AUTHORIZED_USERS='["user1", "user2"]'
```

## Deployment

1. **Initial deployment:**
   ```bash
   fly deploy --remote-only
   ```

2. **Scale processes:**
   ```bash
   # Set initial process counts
   fly scale count swarm=1 worker=2 autoscaler=1
   
   # Or scale specific processes
   fly scale count worker=5  # Scale workers based on load
   ```

3. **Monitor deployment:**
   ```bash
   fly status
   fly logs
   ```

## Process Overview

- **swarm**: Main Discord bot process (1 instance)
- **worker**: Celery workers for browser automation (scale as needed)
- [removed] Flower (Celery monitoring UI)
- **autoscaler**: Automatically scales workers based on queue depth (1 instance)

## Monitoring

1. **Metrics**: Available at internal endpoint on port 9200
2. [removed] Flower UI
3. **Logs**: Stream with `fly logs` or view in Fly dashboard

## Troubleshooting

1. **Workers not starting**: Check Redis connection and browser dependencies
2. **Autoscaler not working**: Verify FLY_API_TOKEN is set correctly
3. **Health checks failing**: Workers may need more grace period for browser startup

## Cost Optimization

- Flower is removed from fly.toml in the default configuration
- Use shared-cpu-1x for light workloads
- Scale workers down during off-peak hours
