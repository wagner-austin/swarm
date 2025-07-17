#!/bin/bash
# Run Celery integration test

echo "Starting Celery integration test..."
echo "=================================="

# First ensure services are up
echo "1. Checking Docker services..."
docker compose ps

echo -e "\n2. Waiting for services to be ready..."
sleep 5

echo -e "\n3. Running integration test..."
docker compose exec swarm python /app/scripts/test_celery_integration.py

echo -e "\n4. Checking autoscaler logs..."
docker compose logs --tail=20 autoscaler

echo -e "\n5. Checking for any workers created..."
docker ps --filter "name=worker" --format "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}"