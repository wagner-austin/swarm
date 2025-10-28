#!/usr/bin/env python
"""Check for leaked browser sessions in Redis."""

import os

import redis
from dotenv import load_dotenv

load_dotenv()

password = os.getenv("REDIS_PASSWORD", "")
auth_part = f"default:{password}@" if password else ""
redis_url = f"redis://{auth_part}localhost:6380/0"

print(f"Connecting to Redis at {redis_url.replace(password, '***') if password else redis_url}")

try:
    client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=5)

    # Check for browser:affinity:* keys (session affinity mappings)
    affinity_keys = list(client.scan_iter(match="browser:affinity:*", count=100))

    print("\n=== Browser Session Check ===")
    print(f"Active browser sessions (affinity keys): {len(affinity_keys)}")

    if affinity_keys:
        print("\n[WARNING] Leaked session IDs:")
        for key in affinity_keys:
            parts = key.split(":", 2)
            if len(parts) == 3:
                session_id = parts[2]
                ttl = client.ttl(key)
                print(f"  - {session_id} (TTL: {ttl}s)")
    else:
        print("\n[OK] No leaked sessions found - Redis is clean!")

    client.close()

except redis.ConnectionError as e:
    print(f"[ERROR] Could not connect to Redis: {e}")
    print("Is Redis running? Try: docker compose up -d")
except Exception as e:
    print(f"[ERROR] Error: {e}")
