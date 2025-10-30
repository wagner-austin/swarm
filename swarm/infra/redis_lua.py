"""
Typed helpers for Redis Lua scripts used across the codebase.

- Batch TTL-based health checks via SCAN (async)
- TTL flags for a provided key set (sync)
- Server-side LLEN sum across multiple keys (sync)

No casts and no Any; return types are guaranteed by runtime guards.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .redis_protocols import RedisAsyncProtocol, RedisSyncProtocol

# Lua script: count keys matching pattern with TTL > 0 using SCAN
_LUA_COUNT_TTL_MATCH = r"""
local cursor = "0"
local match = ARGV[1]
local step = tonumber(ARGV[2]) or 1000
local healthy = 0
repeat
  local res = redis.call('SCAN', cursor, 'MATCH', match, 'COUNT', step)
  cursor = res[1]
  local keys = res[2]
  for i = 1, #keys do
    local t = redis.call('TTL', keys[i])
    if type(t) == 'number' and t > 0 then
      healthy = healthy + 1
    end
  end
until cursor == "0"
return healthy
"""


# Lua script: return list of 0/1 flags for KEYS based on TTL>0
_LUA_TTL_FLAGS_FOR_KEYS = r"""
local out = {}
for i = 1, #KEYS do
  local t = redis.call('TTL', KEYS[i])
  if type(t) == 'number' and t > 0 then out[i] = 1 else out[i] = 0 end
end
return out
"""


# Lua script: sum LLEN for given KEYS
_LUA_SUM_LLEN_FOR_KEYS = r"""
local total = 0
for i = 1, #KEYS do
  local n = redis.call('LLEN', KEYS[i])
  if type(n) == 'number' then total = total + n end
end
return total
"""

# -------------------------------
# Additional Lua scripts
# -------------------------------

# Lua: atomic heartbeat pulse
_LUA_HEARTBEAT_PULSE_ATOMIC = r"""
local sc = redis.call('SCARD', KEYS[2])
if type(sc) ~= 'number' then sc = 0 end
redis.call('HSET', KEYS[1], 'last_heartbeat', ARGV[1], 'current_sessions', tostring(sc))
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[3]))
redis.call('HSET', KEYS[3], 'timestamp', ARGV[2], 'worker_type', ARGV[6], 'worker_id', ARGV[5])
redis.call('EXPIRE', KEYS[3], tonumber(ARGV[4]))
return sc
"""


# Lua: orphaned sessions by server-side scan (with TTL cache to avoid duplicates)
_LUA_ORPHANED_SESSIONS_BY_SCAN = r"""
local cursor = '0'
local match = ARGV[1]
local hb_prefix = ARGV[2]
local af_prefix = ARGV[3]
local step = tonumber(ARGV[4]) or 1000
local out = {}
local ttl_cache = {}
local prefix_len = string.len(af_prefix)
repeat
  local res = redis.call('SCAN', cursor, 'MATCH', match, 'COUNT', step)
  cursor = res[1]
  local keys = res[2]
  for i = 1, #keys do
    local key = keys[i]
    local wid = redis.call('HGET', key, 'worker_id')
    if wid then
      local flag = ttl_cache[wid]
      if flag == nil then
        local t = redis.call('TTL', hb_prefix .. wid)
        if type(t) == 'number' and t > 0 then flag = 1 else flag = 0 end
        ttl_cache[wid] = flag
      end
      if flag == 0 then
        local sid = string.sub(key, prefix_len + 1)
        table.insert(out, sid)
      end
    end
  end
until cursor == '0'
return out
"""


# Lua: worker hashes for alive ids (TTL cache, ensure hostname present)
_LUA_WORKER_HASHES_FOR_ALIVE = r"""
local w_prefix = ARGV[1]
local hb_prefix = ARGV[2]
local count = tonumber(ARGV[3]) or 0
local out = {}
local ttl_cache = {}
for i = 1, count do
  local wid = ARGV[3 + i]
  local flag = ttl_cache[wid]
  if flag == nil then
    local t = redis.call('TTL', hb_prefix .. wid)
    if type(t) == 'number' and t > 0 then flag = 1 else flag = 0 end
    ttl_cache[wid] = flag
  end
  if flag == 1 then
    local wkey = w_prefix .. wid
    local flat = redis.call('HGETALL', wkey)
    local present = false
    for j = 1, #flat, 2 do
      if flat[j] == 'hostname' then present = true; break end
    end
    if not present then
      table.insert(flat, 'hostname')
      table.insert(flat, wid)
    end
    table.insert(out, flat)
  end
end
return out
"""


async def count_ttl_healthy_by_scan(
    client: RedisAsyncProtocol, pattern: str, *, scan_count: int = 1000
) -> int:
    """Return count of keys whose TTL > 0 for a given scan ``pattern``.

    Runs a single EVAL with server-side SCAN + TTL checks.
    """
    # Pass ARGV positionally (numkeys=0 → all varargs are ARGV)
    res = await client.eval(_LUA_COUNT_TTL_MATCH, 0, pattern, str(int(scan_count)))
    # Guarantee int return without casts
    if isinstance(res, int):
        return int(res)
    if isinstance(res, bytes | str):
        try:
            return int(res)
        except Exception as e:
            raise TypeError("Unexpected LUA scalar value for count") from e
    raise TypeError(f"Unexpected LUA result type for count: {type(res)!r}")


def ttl_flags_for_keys_sync(client: RedisSyncProtocol, keys: list[str]) -> list[int]:
    """Return per-key liveness flags (1 if TTL>0 else 0) for provided keys.

    Uses a single EVAL returning an array. Output is validated and mapped to ints.
    """
    if not keys:
        return []
    # Pass KEYS positionally to support both redis-py and wrapped clients
    res = client.eval(_LUA_TTL_FLAGS_FOR_KEYS, len(keys), *keys)
    if isinstance(res, list):
        out: list[int] = []
        for v in res:
            if isinstance(v, int):
                out.append(1 if v > 0 else 0)
            elif isinstance(v, bytes | str):
                try:
                    out.append(1 if int(v) > 0 else 0)
                except Exception as e:
                    raise TypeError("Unexpected LUA value in TTL flags") from e
            else:
                out.append(0)
        return out
    # Fallback: scalar result – treat as zeroes
    return [0 for _ in keys]


@runtime_checkable
class SupportsEval(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


def sum_llen_via_eval(client: SupportsEval, keys: list[str]) -> int:
    """Sum LLEN across ``keys`` using a single EVAL on a sync client.

    Accepts any client that supports redis-py ``eval`` signature.
    """
    if not keys:
        return 0
    res = client.eval(_LUA_SUM_LLEN_FOR_KEYS, len(keys), *keys)
    if isinstance(res, int):
        return int(res)
    if isinstance(res, bytes | str):
        try:
            return int(res)
        except Exception as e:
            raise TypeError("Unexpected LUA scalar value for sum LLEN") from e
    raise TypeError(f"Unexpected LUA result type for sum LLEN: {type(res)!r}")


def heartbeat_pulse_atomic_sync(
    client: RedisSyncProtocol,
    *,
    worker_key: str,
    sessions_key: str,
    heartbeat_key: str,
    last_heartbeat_iso: str,
    heartbeat_timestamp: str,
    worker_ttl: int,
    heartbeat_ttl: int,
    worker_id: str,
    worker_type: str = "browser",
) -> int:
    """Atomically update worker heartbeat and TTLs; return current session count."""
    res = client.eval(
        _LUA_HEARTBEAT_PULSE_ATOMIC,
        3,
        worker_key,
        sessions_key,
        heartbeat_key,
        last_heartbeat_iso,
        heartbeat_timestamp,
        str(int(worker_ttl)),
        str(int(heartbeat_ttl)),
        worker_id,
        worker_type,
    )
    if isinstance(res, int):
        return int(res)
    if isinstance(res, bytes | str):
        try:
            return int(res)
        except Exception as e:
            raise TypeError("Unexpected LUA scalar value for heartbeat pulse") from e
    raise TypeError(f"Unexpected LUA result type for heartbeat pulse: {type(res)!r}")


def orphaned_sessions_by_scan_sync(
    client: RedisSyncProtocol,
    *,
    affinity_match_pattern: str,
    heartbeat_prefix: str,
    affinity_prefix: str,
    scan_count: int = 1000,
) -> list[str]:
    """Return session IDs whose owning worker is not live, by server-side scan."""
    res = client.eval(
        _LUA_ORPHANED_SESSIONS_BY_SCAN,
        0,
        affinity_match_pattern,
        heartbeat_prefix,
        affinity_prefix,
        str(int(scan_count)),
    )
    if isinstance(res, list):
        out: list[str] = []
        for v in res:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, bytes | bytearray):
                try:
                    out.append(v.decode())
                except Exception as e:
                    raise TypeError("Unexpected LUA bytes value in orphan list") from e
            else:
                out.append(str(v))
        return out
    raise TypeError(f"Unexpected LUA result type for orphaned sessions: {type(res)!r}")


def worker_hashes_for_alive_ids_sync(
    client: RedisSyncProtocol,
    *,
    worker_ids: list[str],
    worker_prefix: str,
    heartbeat_prefix: str,
) -> list[dict[str, str]]:
    """Return worker hash dicts for IDs whose heartbeats are live."""
    if not worker_ids:
        return []
    argv: list[str] = [worker_prefix, heartbeat_prefix, str(len(worker_ids)), *worker_ids]
    res = client.eval(_LUA_WORKER_HASHES_FOR_ALIVE, 0, *argv)
    if not isinstance(res, list):
        raise TypeError(f"Unexpected LUA result type for worker hashes: {type(res)!r}")
    out: list[dict[str, str]] = []
    for item in res:
        if not isinstance(item, list):
            raise TypeError("Unexpected LUA non-list element for worker hash")
        pairs: list[str] = []
        for el in item:
            if isinstance(el, str):
                pairs.append(el)
            elif isinstance(el, bytes | bytearray):
                try:
                    pairs.append(el.decode())
                except Exception as e:
                    raise TypeError("Unexpected LUA bytes in worker hash") from e
            else:
                pairs.append(str(el))
        if len(pairs) % 2 != 0:
            raise TypeError("Unexpected LUA odd-length HGETALL result")
        d: dict[str, str] = {}
        for i in range(0, len(pairs), 2):
            d[pairs[i]] = pairs[i + 1]
        out.append(d)
    return out


__all__ = [
    "count_ttl_healthy_by_scan",
    "ttl_flags_for_keys_sync",
    "SupportsEval",
    "sum_llen_via_eval",
    "heartbeat_pulse_atomic_sync",
    "orphaned_sessions_by_scan_sync",
    "worker_hashes_for_alive_ids_sync",
]
