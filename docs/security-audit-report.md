# Security Audit Report: Swarm Web Commands & Infrastructure
**Date:** 2025-10-24
**Scope:** `/web` commands, URL validation, Redis usage, error handling, authorization
**Auditor:** Code inspection (no code changes)

---

## Executive Summary

This document corrects and updates the prior audit against the actual codebase. Key risks are:

- Critical
  - file:// navigation allowed for all users can expose local files via screenshots
    - Evidence: `swarm/utils/urls.py:26`, `swarm/plugins/commands/web.py:145`
  - Redis credentials leakage in logs (full URL logged by SessionRegistry)
    - Evidence: `swarm/distributed/session_registry.py:55`
- Medium
  - User-facing error messages disclose raw exception details
    - Evidence: `swarm/plugins/commands/web.py:137`, `swarm/plugins/commands/web.py:190`, `swarm/plugins/commands/web.py:267`, `swarm/plugins/commands/web.py:312`
  - Inconsistent authorization posture across cogs; `/web` commands are open to all channel members
  - Screenshots are posted non-ephemerally (channel-visible) by default
    - Evidence: `swarm/plugins/commands/web.py:211`
- Low
  - `/web status` displays raw Python structures (UX only)
    - Evidence: `swarm/plugins/commands/web.py:284`
  - Session ID content not validated; currently not user-controlled for `/web` entry points
  - Redis key manipulation (theoretical) due to string interpolation; not user-reachable today
  - Windows-incompatible `:` used in temp file name (reliability)
    - Evidence: `swarm/tasks/browser.py:380`

Out of scope (accepted risk per stakeholder): application-level rate limiting.

---

## 1. URL Validation & Navigation

### 1.1 Centralized HTTP(S) Validation

- Strengths
  - Centralized validator `validate_and_normalise_web_url()` enforces scheme/host rules
    - Evidence: `swarm/utils/urls.py:13`, `swarm/utils/urls.py:30-43`
  - Used by `/web start` and `/web open`
    - Evidence: `swarm/plugins/commands/web.py:91`, `swarm/plugins/commands/web.py:149`

### 1.2 file:// Allowed For Everyone (Critical)

- Code permits `file://` (and `about:`) URLs without restriction
  - Evidence: `swarm/utils/urls.py:26`
- Combined with `/web open` and `/web screenshot`, this enables local file exposure in screenshots by any channel member using `/web`
  - Evidence of usage path: `swarm/plugins/commands/web.py:145` (open), `swarm/plugins/commands/web.py:199` (screenshot)
- Severity: CRITICAL
- Recommendation: Disable `file://` for general users or gate it behind strict roles/config; if retained, ensure screenshots are ephemeral and scope tightly.

---

## 2. Screenshot Saving and Filenames

- Prior reportÃ¢â‚¬â„¢s path traversal concern on user-supplied `filename` is not applicable.
  - The Discord `filename` parameter is used only as the attachment filename in the reply; it is not used to write server-side files.
  - Worker writes screenshots to a temp path derived from `session_id` and `pid`, not from the user-supplied name:
    - Evidence: `swarm/tasks/browser.py:380`
- Non-security reliability note: `session_id` contains `:`, which is invalid in Windows paths; consider sanitizing in temp filenames.

---

## 3. Session ID Handling & Redis Keys

- Current `/web` commands derive session ids from Discord interaction context and do not accept arbitrary session id input from users.
  - Evidence: `swarm/plugins/commands/web.py:54`
- Tasks accept optional `session_id`, but the commands do not expose this to users; default resolves to Celery request id/UUID when not provided.
  - Evidence: `swarm/tasks/_base.py:35`
- Redis keys interpolate `session_id`:
  - Evidence: `swarm/tasks/browser.py:248`, `swarm/tasks/browser.py:420`, `swarm/tasks/browser.py:214`
- Risk today: low (not user-supplied). Future risk: higher if APIs accept user-provided session ids.
- Recommendation: If future endpoints expose `session_id`, add a validation utility and centralized sanitizer before key construction.

---

## 4. Authorization & Access Control

- Patterns observed
  - Owner-only check: `swarm/plugins/commands/shutdown.py:55`
  - Admin-only via default permissions: `swarm/plugins/commands/persona_admin.py: @app_commands.default_permissions(administrator=True)`
  - `/web` commands (`start`, `open`, `screenshot`, `status`) are open to channel members; session id is tied to the current channel, not user.
- The earlier claim that Ã¢â‚¬Å“any channelÃ¢â‚¬â„¢s session can be accessed arbitrarilyÃ¢â‚¬Â is not accurate; commands do not accept cross-channel session ids.
- However, because `/web open` is public, file:// risk (Section 1.2) applies to any channel where the bot is present.
- Recommendation: Define a consistent policy for `/web` usage (e.g., restrict to admins, specific roles, or dedicated channels) and/or gate risky schemes.

---

## 5. Error Handling & Information Disclosure

- Fallback error handlers send raw exception messages to users:
  - Evidence: `swarm/plugins/commands/web.py:137`, `swarm/plugins/commands/web.py:190`, `swarm/plugins/commands/web.py:267`, `swarm/plugins/commands/web.py:312`
- Severity: MEDIUM (ephemeral in many places, but content may reveal internals)
- Recommendation: Log full details server-side, return a generic user message.

---

## 6. Logging & Secrets

- SessionRegistry logs the full Redis URL (likely containing credentials)
  - Evidence: `swarm/distributed/session_registry.py:55`
- Severity: CRITICAL
- Recommendation: Mask credentials in logs or log only non-sensitive host/endpoint info.

---

## 7. `/web status` Formatting (UX)

- Displays raw Python structures via `str(v)` for nested data
  - Evidence: `swarm/plugins/commands/web.py:284`
- Severity: LOW (usability)
- Recommendation: Format nested fields (e.g., iterate sessions and present key fields per session).

---

## 8. Input Length Limits (Nice to Have)

- No explicit length checks for URL/filename inputs in `/web`; Discord caps inputs but explicit checks improve robustness.
- Severity: LOW

---

## 9. Accepted Risk / Out of Scope

- Application-level rate limiting (per-user/per-guild/command) is not required at this time per stakeholder direction. No changes recommended in this area in this report.

---

## 10. Summary of Findings

| # | Finding | Severity | Location | Status |
|---|---------|----------|----------|--------|
| 1 | file:// navigation allowed for all users enables local file exposure via screenshots | CRITICAL | `swarm/utils/urls.py:26`, `swarm/plugins/commands/web.py:145`, `swarm/plugins/commands/web.py:199` | Needs fix |
| 2 | Redis URL (credentials) logged by SessionRegistry | CRITICAL | `swarm/distributed/session_registry.py:55` | Needs fix |
| 3 | Raw exception details returned to users | MEDIUM | `swarm/plugins/commands/web.py:137,190,267,312` | Needs fix |
| 4 | Screenshots posted non-ephemerally (channel-visible) | MEDIUM | `swarm/plugins/commands/web.py:211` | Consider change |
| 5 | Inconsistent authorization posture | MEDIUM | `shutdown.py:55`, `persona_admin.py` (admin-only), `/web` (public) | Define policy |
| 6 | `/web status` shows raw structures (UX) | LOW | `swarm/plugins/commands/web.py:284` | Improvement |
| 7 | Session id content not validated (future risk) | LOW | `swarm/plugins/commands/web.py:54`, `swarm/tasks/_base.py:35` | Monitor |
| 8 | Redis key manipulation theoretical (not user-controlled today) | LOW | `swarm/tasks/browser.py:248,420,214` | Monitor |
| 9 | Windows-incompatible `:` in temp filename (reliability) | LOW | `swarm/tasks/browser.py:380` | Improvement |

---

## 11. Recommended Fixes (Prioritized)

### Priority 1 (Critical)

- Restrict file:// navigation
  - Option A (simple): Remove `file://` allowance for general users in `validate_and_normalise_web_url()`.
  - Option B (policy-based): Gate `file://` behind admin-only/role checks or a per-guild config flag.

- Sanitize logging for Redis URL
  - Modify SessionRegistry to avoid logging credentials; log host or masked URL only.

### Priority 2 (High/Medium)

- Replace user-facing `{exc}` with generic messages; keep detailed logs server-side
  - Affects fallback branches in `/web start`, `/web open`, `/web screenshot`, `/web status`.

- Consider making `/web screenshot` ephemeral by default
  - Evidence of current behavior: `swarm/plugins/commands/web.py:211`.
  - If public screenshots are desired, document this clearly and consider a config/flag.

### Priority 3 (Medium/Low)

- Improve `/web status` formatting for nested structures
  - Present session list with key fields per session.

- Add TTL to session metadata keys (optional)
  - Affinity entries already use expiry; extending to metadata prevents stale keys.

- Input length checks (optional hardening)
  - E.g., URL max length ~2048; filename length caps.

- Windows-safe temp filenames (reliability)
  - Replace `:` with `_` when composing temp filenames from `session_id` in workers.

### Monitoring / Future Considerations

- If future APIs accept user-supplied `session_id` values, add a centralized validator (allow-list of characters, length limits, colon count, etc.) before using in Redis keys or file paths.

---

## 12. Notes On Prior Report Changes

- Removed the path traversal finding on screenshot filenames (not applicable: server writes do not use user-supplied names).
- Corrected claim about cross-channel session access: `/web` commands are tied to the current channel; no parameter to target arbitrary channels.
- Redis key Ã¢â‚¬Å“injectionÃ¢â‚¬Â remains theoretical for current `/web` entry points; severity lowered to Low with a future risk note.
- Rate limiting is explicitly marked out-of-scope per stakeholder direction.

### Issue Location
`swarm/plugins/commands/web.py:284-285`

### Problem
```python
for k, v in status.items():
    embed.add_field(name=str(k), value=str(v), inline=False)
```

When the `status` dict contains nested structures like:
```python
{
    "active_sessions": 1,
    "sessions": [{"worker_id": "...", "status": "healthy", ...}]
}
```

The `str(v)` conversion renders the "sessions" list as raw Python representation:
```
[{'worker_id': 'worker-1', 'status': 'healthy', 'browser_active': True, ...}]
```

### Impact
- **Severity: LOW** (UX issue, not security)
- Hard to read for users
- Unprofessional appearance
- May leak internal implementation details

### Root Cause
Direct string conversion of complex data structures without proper formatting.

---

## 2. Input Validation & Sanitization

### 2.1 URL Validation Ã¢Å“â€¦ GOOD
**Location:** `swarm/utils/urls.py:13-52`

**Strengths:**
- Centralized validation in `validate_and_normalise_web_url()`
- Scheme whitelisting (http, https, file, about)
- Host validation (requires TLD or localhost)
- Allow-list enforcement via `settings.allowed_hosts`
- Normalizes host casing to prevent bypass
- Proper error handling with ValueError

**Example:**
```python
def validate_and_normalise_web_url(raw: str, *, allowed_hosts: Iterable[str] | None = None) -> str:
    if not raw:
        raise ValueError("URL cannot be empty")
    # ... validates scheme, host, allow-list
    return url
```

**Used consistently in:**
- `web.py:91` (start command)
- `web.py:149` (open command)

---

### 2.2 Session ID Validation Ã¢ÂÅ’ CRITICAL GAP

**Location:** Multiple files (`web.py`, `tasks/browser.py`, `tasks/_base.py`)

**Problem:**
Session IDs are constructed from Discord interaction IDs but never validated:

```python
# web.py:54-61
def _session_id_for_interaction(self, interaction: discord.Interaction) -> str:
    guild_part = str(interaction.guild_id) if interaction.guild_id is not None else "dm"
    channel_part = str(interaction.channel_id)
    return f"discord:{guild_part}:{channel_part}"
```

**Issues:**
1. **No validation on format** - session_id is just `str | None`
2. **No sanitization** - Direct string interpolation into Redis keys
3. **Type safety only** - MyPy checks types but not content
4. **Inconsistent source** - Some session IDs come from Celery request.id (UUIDs), others from Discord IDs, others are user-supplied

**Vulnerable Code Patterns:**
```python
# tasks/browser.py:266 - Redis key construction with unvalidated input
await redis.hset(f"browser:session:{session_id}", "url", url)

# tasks/browser.py:420
session_data = await redis.hgetall(f"browser:session:{session_id}")

# tasks/browser.py:214
await redis.delete(f"browser:session:{session_id}")
```

**Attack Vector (Theoretical):**
If `session_id` could be manipulated to contain `:` characters or be set to a different key pattern, an attacker could:
- Access other users' sessions
- Delete arbitrary Redis keys
- Inject malicious data into unintended keys

**Current Mitigation:**
- Discord IDs are integers (safe when converted to strings)
- UUIDs from Celery are safe
- **BUT:** No validation prevents future code from passing unsafe strings

**Severity: HIGH**
- Current practical risk: LOW (Discord IDs are safe)
- Future risk: HIGH (no defensive validation if input source changes)

---

### 2.3 Filename Validation Ã¢Å¡Â Ã¯Â¸Â MODERATE RISK

**Location:** `web.py:199-209`

```python
async def screenshot(self, interaction: discord.Interaction, filename: str | None = None) -> None:
    actual_filename = filename or "screenshot.png"
    if not any(actual_filename.endswith(ext) for ext in [".png", ".jpg", ".jpeg"]):
        actual_filename += ".png"

    timestamp = int(time.time())
    unique_name = f"{timestamp}_{actual_filename}"
```

**Issues:**
1. **No path traversal protection** - User could supply `../../etc/passwd.png`
2. **No character sanitization** - Special chars like `\0`, `/`, `\` not filtered
3. **Extension check only** - Only validates extension, not full path safety

**Severity: LOW-MEDIUM**
- Screenshot saved to temp directory (limits impact)
- Unique timestamp prefix reduces collision risk
- **BUT:** No explicit path sanitization

---

## 3. Redis Injection Vulnerabilities

### 3.1 Key Construction Pattern

**Vulnerable Pattern:**
```python
f"browser:session:{session_id}"
f"browser:worker:{worker_hostname}"
```

**Why This Matters:**
Unlike SQL, Redis doesn't have traditional injection, but key manipulation is possible if input contains:
- Colons (`:`) - delimiter in key naming conventions
- Spaces - can break key matching patterns
- Wildcards (`*`, `?`) - if used in key scanning operations

**Current Safety:**
Ã¢Å“â€¦ Session IDs from Discord are safe (integers)
Ã¢Å“â€¦ Worker hostnames are from system, not user input
Ã¢ÂÅ’ No validation layer prevents unsafe strings

---

### 3.2 Redis Operations Safety

**Operations Used:**
- `redis.hset()` - Safe (parameterized)
- `redis.hgetall()` - Safe (parameterized)
- `redis.delete()` - Safe (parameterized)
- `redis.hget()` - Safe (parameterized)

**Lua usage present** - OK with guardrails (typed helpers only). Redis Lua is used in `swarm/infra/redis_lua.py` for TTL counting, heartbeat pulse, and batch LLEN. Usage is centralized and typed; no ad-hoc EVAL in application logic.

**Severity: MEDIUM**
- Current implementation is safe
- Lacks defensive validation for future changes
- Redis commands are properly parameterized

---

## 4. Rate Limiting Analysis

### 4.1 Command-Level Rate Limiting Ã¢ÂÅ’ MISSING

**Discord Commands Analyzed:**
- `/web start` - No rate limit
- `/web open` - No rate limit
- `/web screenshot` - No rate limit
- `/web status` - No rate limit
- `/shutdown` - No rate limit (only owner check)
- `/persona add/delete/list` - No rate limit

**Risk:**
- User can spam expensive operations (browser launches, screenshots)
- No per-user quotas
- No cooldown periods
- No burst limiting

**Example Attack:**
```
User spams: /web screenshot every second for 60 seconds
Result: 60 browser screenshot operations, potential resource exhaustion
```

---

### 4.2 Infrastructure Rate Limiting

**What Exists:**
1. **Discord API Rate Limits** (external, platform-level)
   - Discord limits interactions to ~50/5s per user
   - Helps but doesn't prevent application-level abuse

2. **Redis Rate Limit Detection** (monitoring only)
   - `swarm/core/exceptions.py:59-65` - `RedisRateLimitError`
   - Used for detecting Upstash limits
   - **NOT used for limiting users**

**What's Missing:**
1. Ã¢ÂÅ’ Per-user rate limiting
2. Ã¢ÂÅ’ Per-IP rate limiting (N/A for Discord, but critical for future HTTP API)
3. Ã¢ÂÅ’ Per-endpoint rate limiting
4. Ã¢ÂÅ’ Concurrent operation limiting (e.g., max 5 browser sessions per user)
5. Ã¢ÂÅ’ Resource quotas (e.g., max 100 screenshots per day)

---

### 4.3 Celery Task Rate Limiting Ã¢Å¡Â Ã¯Â¸Â PARTIAL

**Celery Queue Configuration:**
- Tasks queued to `"browser"` queue
- No per-user task rate limiting
- No task priority system
- Workers process tasks FIFO

**Risk:**
Single user can flood the task queue, causing DoS for other users.

---

## 5. Authorization & Access Control

### 5.1 Inconsistent Permission Model

**Three Different Patterns Found:**

#### Pattern 1: Owner Check (Manual)
```python
# swarm/plugins/commands/shutdown.py:55-57
owner = await self.get_owner(self.discord_bot)
if interaction.user.id != owner.id:
    await self.safe_send(interaction, "Ã¢ÂÅ’ Owner only.", ephemeral=True)
    return
```
Ã¢Å“â€¦ **Used in:** `/shutdown`

#### Pattern 2: Decorator-Based Permissions
```python
# swarm/plugins/commands/persona_admin.py:100
@app_commands.command(name="list", description="Show all personas")
@app_commands.default_permissions(administrator=True)
```
Ã¢Å“â€¦ **Used in:** `/persona` commands

#### Pattern 3: No Authorization (Public)
```python
# swarm/plugins/commands/web.py - NO CHECKS
@app_commands.command(name="start", description="Start a browser...")
async def start(self, interaction: discord.Interaction, url: str | None = None) -> None:
    # Anyone can use this
```
Ã¢ÂÅ’ **Used in:** `/web start`, `/web open`, `/web screenshot`, `/web status`

---

### 5.2 Missing Access Controls

**Critical Gaps:**

1. **No per-channel isolation**
   - Session IDs are channel-specific: `f"discord:{guild_id}:{channel_id}"`
   - But anyone in the server can access any channel's session by calling commands
   - **Impact:** User in #general could screenshot user in #private's browser session

2. **No per-guild restrictions**
   - Single Swarm instance serves all guilds
   - No per-guild resource quotas
   - No per-guild feature toggles

3. **No role-based access control (RBAC)**
   - Either owner-only or everyone
   - No "browser_user" vs "browser_admin" roles

4. **No command audit logging**
   - No record of who used which command
   - No forensic capability after incident

---

### 5.3 Session Security

**Current Model:**
```python
session_id = f"discord:{guild_id}:{channel_id}"
```

**Issues:**
1. **Predictable session IDs** - Easy to guess other channels
2. **No session ownership** - No check if user created the session
3. **Shared sessions** - All users in channel share one browser session
4. **No session timeouts** - Sessions persist indefinitely
5. **No session invalidation** - Can't revoke access

**Attack Scenario:**
```
1. Attacker joins server
2. Guesses channel IDs (sequential integers)
3. Calls /web status with crafted session_id parameter
   (currently not possible, but no validation prevents future vulnerability)
4. Views other users' browsing sessions
```

**Current Mitigation:**
- Session ID derived from interaction, not user-supplied
- **BUT:** No validation prevents future parameter injection

---

## 6. Type Safety & Strong Typing

### Ã¢Å“â€¦ Strengths

1. **MyPy Strict Mode** - `make check` runs mypy
2. **Type annotations everywhere** - Functions, parameters, returns
3. **Protocol types** - Used for dependency injection
4. **Generic types** - Proper use of TypeVar, ParamSpec

**Example:**
```python
async def status(
    self, worker_hint: str | None = None, session_id: str | None = None
) -> dict[str, Any]:
```

### Ã¢Å¡Â Ã¯Â¸Â Limitations

1. **Runtime validation missing**
   - MyPy checks types, not values
   - `session_id: str` doesn't validate format

2. **Any types used**
   - `dict[str, Any]` too permissive
   - Loses type safety at runtime

3. **No Pydantic models**
   - No runtime validation
   - No automatic parsing/serialization

---

## 7. Prepared Statements (N/A - No SQL)

Ã¢Å“â€¦ **GOOD NEWS:** No SQL database in use.

**Current Database:**
- Redis only (key-value store)
- No SQL injection risk
- Redis commands are parameterized (safe)

**Future Consideration:**
If SQL is added later, ensure:
- Use parameterized queries (prepared statements)
- Never concatenate user input into SQL
- Use ORM (SQLAlchemy) or query builders

---

## 8. Error Handling & Information Disclosure

### 8.1 Comprehensive Error Handling Ã¢Å“â€¦

**Example from `web.py:113-139`:**
```python
except ValueError as e:
    await self.safe_send(interaction, f"Ã¢ÂÅ’ Invalid URL: {e}. ...", ephemeral=True)
except WorkerUnavailableError:
    await self.safe_send(interaction, "Ã¢Å¡Â Ã¯Â¸Â Browser workers temporarily unavailable...", ephemeral=True)
except OperationTimeoutError:
    await self.safe_send(interaction, "Ã¢ÂÂ±Ã¯Â¸Â Browser startup timed out...", ephemeral=True)
except BrowserError:
    await self.safe_send(interaction, "Ã°Å¸Å’Â Browser error occurred...", ephemeral=True)
else:
    await self.safe_send(interaction, f"Ã¢ÂÅ’ Failed to start browser: {exc}", ephemeral=True)
```

**Strengths:**
- Specific exception handling
- User-friendly error messages
- Logging for debugging

### Ã¢Å¡Â Ã¯Â¸Â Information Disclosure Risk

**Line 137:**
```python
await self.safe_send(interaction, f"Ã¢ÂÅ’ Failed to start browser: {exc}", ephemeral=True)
```

**Issue:** Fallback handler leaks raw exception message to user
- Could expose internal paths, Redis connection strings, etc.
- Should use generic message: "An unexpected error occurred"

**Severity: LOW-MEDIUM**
- Ephemeral messages reduce exposure
- But still leaks internal details

---

## 9. Additional Security Observations

### 9.1 No Input Length Limits

**Missing:**
- Max URL length (current: unlimited, allows DoS via huge URLs)
- Max filename length
- Max session ID length

**Discord Mitigations:**
- Discord limits message length (2000 chars)
- Command parameters have implicit limits
- But explicit validation is better

---

### 9.2 No Content Security Policy (CSP)

**N/A for Discord bot**, but critical for future web UI:
- XSS protection
- Frame-ancestors
- Script-src policies

---

### 9.3 Secrets Management Ã¢Å“â€¦ GOOD

**From `alert_pump.py` and `celery_app.py`:**
- Uses environment variables for secrets
- No hardcoded credentials
- Passwords not in logs (masked in URLs)

**Example:**
```python
redis_url = settings.redis.url
# alert_pump.py:176 - Masks password in logs
if "@" in redis_url:
    host_part = redis_url.split("@")[1].split("/")[0]
```

---

### 9.4 No CSRF Protection

**Status:** Not applicable to Discord commands (Discord handles authentication)

**Future Risk:** If REST API added, MUST implement:
- CSRF tokens
- SameSite cookies
- Origin validation

---

## 10. Summary of Findings

| # | Finding | Severity | Location | Status |
|---|---------|----------|----------|--------|
| 1 | `/web status` displays ugly JSON | LOW | `web.py:284` | Needs fix |
| 2 | Missing session ID validation | HIGH | Multiple files | **CRITICAL** |
| 3 | No path traversal protection on filenames | MEDIUM | `web.py:204` | Needs fix |
| 4 | Redis key injection (theoretical) | MEDIUM | `tasks/browser.py:266,420` | Needs defense |
| 5 | No command-level rate limiting | HIGH | All commands | **CRITICAL** |
| 6 | No per-user rate limiting | HIGH | N/A | **CRITICAL** |
| 7 | Inconsistent authorization model | MEDIUM | `web.py`, `shutdown.py` | Needs policy |
| 8 | No session ownership checks | HIGH | `web.py:54` | **CRITICAL** |
| 9 | Predictable session IDs | MEDIUM | `web.py:61` | Needs crypto |
| 10 | No session timeouts | LOW | N/A | Enhancement |
| 11 | Error messages leak internals | LOW | `web.py:137` | Needs sanitization |
| 12 | No input length limits | MEDIUM | All commands | Needs validation |
| 13 | No command audit logs | MEDIUM | N/A | Enhancement |

---

## 11. Recommended Fixes (Prioritized)

### Priority 1 (Critical - Fix Immediately)

#### 1.1 Add Session ID Validation
```python
# New file: swarm/utils/validation.py
import re

def validate_session_id(session_id: str) -> str:
    """Validate and sanitize session ID.

    Raises ValueError if invalid.
    """
    if not session_id:
        raise ValueError("Session ID cannot be empty")

    # Max length check
    if len(session_id) > 256:
        raise ValueError("Session ID too long")

    # Allow only alphanumeric, hyphens, underscores, colons
    if not re.match(r'^[a-zA-Z0-9:_-]+$', session_id):
        raise ValueError("Session ID contains invalid characters")

    # Prevent Redis key injection via excessive colons
    if session_id.count(':') > 3:
        raise ValueError("Session ID format invalid")

    return session_id
```

#### 1.2 Implement Rate Limiting
```python
# Use Redis-based rate limiting
# Example: max 10 commands per user per minute

from swarm.utils.rate_limit import RateLimiter

rate_limiter = RateLimiter(redis, max_calls=10, period=60)

@app_commands.command(name="start")
async def start(self, interaction: discord.Interaction, url: str | None = None):
    # Check rate limit
    if not await rate_limiter.check(interaction.user.id):
        await self.safe_send(
            interaction,
            "Ã¢ÂÂ±Ã¯Â¸Â Rate limit exceeded. Please wait before using this command again.",
            ephemeral=True
        )
        return

    # ... rest of command
```

#### 1.3 Add Session Ownership Checks
```python
def _session_id_for_interaction(self, interaction: discord.Interaction) -> str:
    """Derive session id that includes user ID for ownership."""
    guild_part = str(interaction.guild_id) if interaction.guild_id else "dm"
    channel_part = str(interaction.channel_id)
    user_part = str(interaction.user.id)  # ADD THIS
    return f"discord:{guild_part}:{channel_part}:{user_part}"

# In Redis, store session owner
await redis.hset(
    f"browser:session:{session_id}",
    mapping={
        "owner_id": str(interaction.user.id),
        "created_at": str(time.time()),
        "url": url
    }
)

# Check ownership before operations
async def _check_session_ownership(self, session_id: str, user_id: int) -> bool:
    redis = await self.get_redis()
    owner_id = await redis.hget(f"browser:session:{session_id}", "owner_id")
    return owner_id and int(owner_id) == user_id
```

---

### Priority 2 (High - Fix Soon)

#### 2.1 Add Filename Path Sanitization
```python
from pathlib import Path

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal."""
    # Remove path separators
    filename = os.path.basename(filename)

    # Remove null bytes
    filename = filename.replace('\0', '')

    # Allow only safe characters
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

    # Limit length
    if len(filename) > 100:
        filename = filename[:100]

    return filename
```

#### 2.2 Consistent Authorization Decorator
```python
# Create unified authorization decorator
def require_permission(permission: str = "user"):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            if permission == "owner":
                owner = await get_owner(self.discord_bot)
                if interaction.user.id != owner.id:
                    await safe_send(interaction, "Ã¢ÂÅ’ Owner only.", ephemeral=True)
                    return

            elif permission == "admin":
                if not interaction.user.guild_permissions.administrator:
                    await safe_send(interaction, "Ã¢ÂÅ’ Administrator only.", ephemeral=True)
                    return

            # permission == "user" allows everyone
            return await func(self, interaction, *args, **kwargs)
        return wrapper
    return decorator

# Usage
@app_commands.command(name="start")
@require_permission("user")  # or "admin" or "owner"
async def start(self, interaction: discord.Interaction, url: str | None = None):
    ...
```

---

### Priority 3 (Medium - Plan & Implement)

#### 3.1 Add Session Timeouts
```python
# Set TTL on session keys
await redis.hset(f"browser:session:{session_id}", mapping=data)
await redis.expire(f"browser:session:{session_id}", 3600)  # 1 hour
```

#### 3.2 Add Command Audit Logging
```python
async def audit_log(interaction: discord.Interaction, command: str, **params):
    """Log command usage for security auditing."""
    await redis.xadd(
        "audit:commands",
        {
            "timestamp": str(time.time()),
            "user_id": str(interaction.user.id),
            "guild_id": str(interaction.guild_id),
            "channel_id": str(interaction.channel_id),
            "command": command,
            "params": json.dumps(params)
        }
    )
```

#### 3.3 Improve Error Messages
```python
except Exception as exc:
    # Log full error for debugging
    logger.exception("Unexpected error in start command")

    # Send generic error to user
    await self.safe_send(
        interaction,
        "Ã¢ÂÅ’ An unexpected error occurred. Please try again later.",
        ephemeral=True
    )
```

#### 3.4 Add Input Length Limits
```python
@app_commands.command(name="open")
@app_commands.describe(url="URL (max 2048 chars)")
async def open(self, interaction: discord.Interaction, url: str) -> None:
    if len(url) > 2048:
        await self.safe_send(interaction, "Ã¢ÂÅ’ URL too long (max 2048 chars)", ephemeral=True)
        return
    # ... rest of command
```

---

### Priority 4 (Low - Nice to Have)

#### 4.1 Fix `/web status` Display
```python
@app_commands.command(name="status")
async def status(self, interaction: discord.Interaction) -> None:
    session_id = self._session_id_for_interaction(interaction)
    status = await self.browser.status(session_id=session_id)

    if not status:
        await self.safe_send(interaction, "No active browser workers.", ephemeral=True)
        return

    embed = discord.Embed(title="Browser Worker Status", description="Status for this channel")

    # Handle simple fields
    embed.add_field(name="Active Sessions", value=str(status.get("active_sessions", 0)), inline=False)

    # Format complex nested data properly
    sessions = status.get("sessions", [])
    if sessions:
        for i, session in enumerate(sessions, 1):
            session_info = []
            session_info.append(f"**Worker ID:** {session.get('worker_id', 'N/A')}")
            session_info.append(f"**Status:** {session.get('status', 'unknown')}")
            session_info.append(f"**URL:** {session.get('url', 'N/A')}")
            session_info.append(f"**Uptime:** {session.get('uptime', 0):.1f}s")

            embed.add_field(
                name=f"Session {i}",
                value="\n".join(session_info),
                inline=False
            )

    await self.safe_send(interaction, embed=embed, ephemeral=True)
```

#### 4.2 Implement Cryptographically Random Session IDs
```python
import secrets

def _session_id_for_interaction(self, interaction: discord.Interaction) -> str:
    """Generate cryptographically random session ID."""
    # Use combination of interaction context + random token
    context = f"discord:{interaction.guild_id}:{interaction.channel_id}:{interaction.user.id}"
    token = secrets.token_urlsafe(32)
    return f"{context}:{token}"
```

---

## 12. Testing Recommendations

### 12.1 Security Test Cases to Add

```python
# Test session ID validation
def test_invalid_session_ids():
    invalid_ids = [
        "",  # empty
        "a" * 300,  # too long
        "../../etc/passwd",  # path traversal
        "session;DROP TABLE users;",  # injection attempt
        "session\x00null",  # null byte
        "session:::::::::",  # excessive delimiters
    ]
    for invalid in invalid_ids:
        with pytest.raises(ValueError):
            validate_session_id(invalid)

# Test rate limiting
@pytest.mark.asyncio
async def test_rate_limiting():
    # Simulate 20 rapid requests from same user
    # First 10 should succeed, rest should be rate limited
    ...

# Test authorization
@pytest.mark.asyncio
async def test_non_owner_cannot_shutdown():
    # Non-owner user attempts /shutdown
    # Should receive "Owner only" error
    ...

# Test filename sanitization
def test_filename_sanitization():
    assert sanitize_filename("../../etc/passwd") == "etcpasswd"
    assert sanitize_filename("file\x00.png") == "file.png"
    ...
```

---

## 13. Compliance & Standards

### Current Status vs. Best Practices

| Standard | Requirement | Status | Gap |
|----------|-------------|--------|-----|
| OWASP Top 10 | Input validation | Ã¢Å¡Â Ã¯Â¸Â Partial | Session IDs not validated |
| OWASP Top 10 | Authentication | Ã¢Å“â€¦ Good | Discord handles auth |
| OWASP Top 10 | Authorization | Ã¢ÂÅ’ Poor | Inconsistent, no RBAC |
| OWASP Top 10 | Rate limiting | Ã¢ÂÅ’ Missing | No application-level limits |
| OWASP Top 10 | Error handling | Ã¢Å¡Â Ã¯Â¸Â Partial | Some info disclosure |
| CWE-89 | SQL Injection | N/A | No SQL database |
| CWE-79 | XSS | N/A | No web UI (yet) |
| CWE-22 | Path Traversal | Ã¢Å¡Â Ã¯Â¸Â Risk | Filename sanitization weak |
| CWE-862 | Missing Auth | Ã¢ÂÅ’ Found | `/web` commands public |

---

## 14. Long-Term Recommendations

### 14.1 Move to RESTful API Architecture
When adding web UI or other frontends:
- Use FastAPI or Flask with proper auth middleware
- Implement JWT-based authentication
- Add CORS, CSP, CSRF protection
- Use HTTPS only

### 14.2 Implement Proper RBAC
```yaml
roles:
  owner:
    - shutdown
    - view_all_sessions
    - manage_users

  admin:
    - create_sessions
    - delete_own_sessions
    - manage_personas

  user:
    - create_own_session
    - delete_own_session
    - screenshot_own_session

  guest:
    - view_status
```

### 14.3 Add Comprehensive Monitoring
- Security events dashboard
- Failed auth attempts
- Rate limit violations
- Suspicious session access patterns

### 14.4 Regular Security Audits
- Quarterly code reviews
- Dependency vulnerability scanning (already using poetry)
- Penetration testing before production deployment

---

## 15. Conclusion

The Swarm application has a **solid foundation** with good practices in:
- Type safety (MyPy)
- URL validation
- Error handling
- Secrets management
- No SQL injection risk

However, **critical gaps** exist in:
- Input validation (session IDs)
- Rate limiting
- Authorization consistency
- Session security

**Recommended Action Plan:**
1. **Week 1:** Implement session ID validation + rate limiting (Priority 1)
2. **Week 2:** Add authorization decorators + session ownership (Priority 1-2)
3. **Week 3:** Filename sanitization + audit logging (Priority 2-3)
4. **Week 4:** Session timeouts + improved error messages (Priority 3)
5. **Ongoing:** Security test suite + monitoring

**Risk Assessment:**
- **Current:** MEDIUM (Discord mitigates many risks, but gaps exist)
- **After fixes:** LOW (with proper validation, rate limiting, and authz)

---

## Appendix A: Files Audited

- `swarm/plugins/commands/web.py` - Main web commands
- `swarm/distributed/celery_browser.py` - Browser runtime
- `swarm/tasks/browser.py` - Browser tasks
- `swarm/tasks/_base.py` - Base task class
- `swarm/utils/urls.py` - URL validation
- `swarm/frontends/discord/discord_interactions.py` - Discord helpers
- `swarm/plugins/commands/shutdown.py` - Shutdown command
- `swarm/plugins/commands/persona_admin.py` - Persona management
- `swarm/plugins/commands/alert_pump.py` - Alert system
- `swarm/core/exceptions.py` - Exception classes
- `swarm/browser/engine.py` - Browser engine

**Total Lines Audited:** ~3,811 lines across core components

---

**End of Report**
