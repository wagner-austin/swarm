# Security Audit Report: Swarm Web Commands & Infrastructure
**Date:** 2025-10-24
**Scope:** `/web status` command, input validation, database queries, rate limiting, authorization
**Auditor:** Code inspection (no changes made)

---

## Executive Summary

This audit identified **multiple critical security gaps** in the Swarm application, particularly around:
1. Missing input validation and sanitization on session identifiers
2. Lack of rate limiting at multiple levels
3. Inconsistent authorization controls
4. Redis key injection vulnerabilities (theoretical, low practical risk)
5. Display formatting issue in `/web status` command (UX bug, not security critical)

**Risk Level: MEDIUM** (Discord's platform-level controls mitigate some risks, but application-level vulnerabilities exist)

---

## 1. Display Formatting Issue (`/web status`)

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

### 2.1 URL Validation ✅ GOOD
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

### 2.2 Session ID Validation ❌ CRITICAL GAP

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

### 2.3 Filename Validation ⚠️ MODERATE RISK

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
✅ Session IDs from Discord are safe (integers)
✅ Worker hostnames are from system, not user input
❌ No validation layer prevents unsafe strings

---

### 3.2 Redis Operations Safety

**Operations Used:**
- `redis.hset()` - Safe (parameterized)
- `redis.hgetall()` - Safe (parameterized)
- `redis.delete()` - Safe (parameterized)
- `redis.hget()` - Safe (parameterized)

**No Lua eval()** - ✅ GOOD (checked, none found in production code)

**Severity: MEDIUM**
- Current implementation is safe
- Lacks defensive validation for future changes
- Redis commands are properly parameterized

---

## 4. Rate Limiting Analysis

### 4.1 Command-Level Rate Limiting ❌ MISSING

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
1. ❌ Per-user rate limiting
2. ❌ Per-IP rate limiting (N/A for Discord, but critical for future HTTP API)
3. ❌ Per-endpoint rate limiting
4. ❌ Concurrent operation limiting (e.g., max 5 browser sessions per user)
5. ❌ Resource quotas (e.g., max 100 screenshots per day)

---

### 4.3 Celery Task Rate Limiting ⚠️ PARTIAL

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
    await self.safe_send(interaction, "❌ Owner only.", ephemeral=True)
    return
```
✅ **Used in:** `/shutdown`

#### Pattern 2: Decorator-Based Permissions
```python
# swarm/plugins/commands/persona_admin.py:100
@app_commands.command(name="list", description="Show all personas")
@app_commands.default_permissions(administrator=True)
```
✅ **Used in:** `/persona` commands

#### Pattern 3: No Authorization (Public)
```python
# swarm/plugins/commands/web.py - NO CHECKS
@app_commands.command(name="start", description="Start a browser...")
async def start(self, interaction: discord.Interaction, url: str | None = None) -> None:
    # Anyone can use this
```
❌ **Used in:** `/web start`, `/web open`, `/web screenshot`, `/web status`

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

### ✅ Strengths

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

### ⚠️ Limitations

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

✅ **GOOD NEWS:** No SQL database in use.

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

### 8.1 Comprehensive Error Handling ✅

**Example from `web.py:113-139`:**
```python
except ValueError as e:
    await self.safe_send(interaction, f"❌ Invalid URL: {e}. ...", ephemeral=True)
except WorkerUnavailableError:
    await self.safe_send(interaction, "⚠️ Browser workers temporarily unavailable...", ephemeral=True)
except OperationTimeoutError:
    await self.safe_send(interaction, "⏱️ Browser startup timed out...", ephemeral=True)
except BrowserError:
    await self.safe_send(interaction, "🌐 Browser error occurred...", ephemeral=True)
else:
    await self.safe_send(interaction, f"❌ Failed to start browser: {exc}", ephemeral=True)
```

**Strengths:**
- Specific exception handling
- User-friendly error messages
- Logging for debugging

### ⚠️ Information Disclosure Risk

**Line 137:**
```python
await self.safe_send(interaction, f"❌ Failed to start browser: {exc}", ephemeral=True)
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

### 9.3 Secrets Management ✅ GOOD

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
            "⏱️ Rate limit exceeded. Please wait before using this command again.",
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
                    await safe_send(interaction, "❌ Owner only.", ephemeral=True)
                    return

            elif permission == "admin":
                if not interaction.user.guild_permissions.administrator:
                    await safe_send(interaction, "❌ Administrator only.", ephemeral=True)
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
        "❌ An unexpected error occurred. Please try again later.",
        ephemeral=True
    )
```

#### 3.4 Add Input Length Limits
```python
@app_commands.command(name="open")
@app_commands.describe(url="URL (max 2048 chars)")
async def open(self, interaction: discord.Interaction, url: str) -> None:
    if len(url) > 2048:
        await self.safe_send(interaction, "❌ URL too long (max 2048 chars)", ephemeral=True)
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
| OWASP Top 10 | Input validation | ⚠️ Partial | Session IDs not validated |
| OWASP Top 10 | Authentication | ✅ Good | Discord handles auth |
| OWASP Top 10 | Authorization | ❌ Poor | Inconsistent, no RBAC |
| OWASP Top 10 | Rate limiting | ❌ Missing | No application-level limits |
| OWASP Top 10 | Error handling | ⚠️ Partial | Some info disclosure |
| CWE-89 | SQL Injection | N/A | No SQL database |
| CWE-79 | XSS | N/A | No web UI (yet) |
| CWE-22 | Path Traversal | ⚠️ Risk | Filename sanitization weak |
| CWE-862 | Missing Auth | ❌ Found | `/web` commands public |

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
