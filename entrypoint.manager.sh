#!/bin/bash
set -e

echo "🎯 Starting Job Manager..."

# Change to the app directory
cd /app

# Set default environment variables
export METRICS_PORT=${METRICS_PORT:-9150}
export REDIS_URL=${REDIS_URL:-redis://redis:6379/0}

# Install dependencies if needed
if [ -f pyproject.toml ]; then
    echo "📦 Installing dependencies..."
    poetry install --only main
fi

echo "🚀 Launching Job Manager on port $METRICS_PORT"
echo "📡 Connecting to Redis: $REDIS_URL"

# Start the manager
exec poetry run python -m bot.distributed.manager
