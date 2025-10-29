from __future__ import annotations

from typing import Final

import pytest

from scripts.generate_haproxy_config import generate_haproxy_config


@pytest.mark.unit
def test_mixed_mode_per_server_checks() -> None:
    """Mixed SSL/non-SSL uses per-server checks and no backend tcp-check."""
    urls: Final[str] = "rediss://default:pass@upstash.example.com:6380/0;redis://redis.local:6379/0"
    cfg: str = generate_haproxy_config(urls)

    # No backend-wide tcp-check in mixed mode
    assert "option tcp-check" not in cfg
    assert "tcp-check connect" not in cfg

    # SSL server line includes TLS handshake for health via check-ssl
    assert (
        "server redis_0 upstash.example.com:6380 check inter 3s fall 2 rise 2 ssl verify none check-ssl"
        in cfg
    )
    # Non-SSL server line includes plain check only
    assert "server redis_1 redis.local:6379 check inter 5s fall 3 rise 2" in cfg
    assert "redis.local:6379" in cfg and "check-ssl" not in cfg.split("redis.local:6379")[1]


@pytest.mark.unit
def test_uniform_ssl_full_tcpcheck_with_auth_ping() -> None:
    """Uniform SSL enables backend tcp-check connect ssl and AUTH+PING."""
    urls: Final[str] = (
        "rediss://default:secret@upstash1.example.com:6380/0;"
        "rediss://default:secret@upstash2.example.com:6380/0"
    )
    cfg: str = generate_haproxy_config(urls)

    # Backend-level tcp-check connect ssl and AUTH + PING must be present
    assert "option tcp-check" in cfg
    assert "tcp-check connect ssl" in cfg
    assert "tcp-check send-binary" in cfg  # AUTH
    assert "tcp-check expect string +OK" in cfg
    assert 'tcp-check send "PING' in cfg
    assert "tcp-check expect string +PONG" in cfg

    # Server lines include ssl verify none but not check-ssl (uniform SSL handled at backend)
    assert (
        "server redis_0 upstash1.example.com:6380 check inter 3s fall 2 rise 2 ssl verify none"
        in cfg
    )
    assert "check-ssl" not in cfg


@pytest.mark.unit
def test_uniform_nonssl_full_tcpcheck_with_auth_ping() -> None:
    """Uniform non-SSL enables backend tcp-check connect and AUTH+PING."""
    urls: Final[str] = (
        "redis://default:pw@redis1.local:6379/0;redis://default:pw@redis2.local:6379/0"
    )
    cfg: str = generate_haproxy_config(urls)

    # Backend-level tcp-check connect and AUTH + PING must be present
    assert "option tcp-check" in cfg
    assert "tcp-check connect\n" in cfg  # plain connect
    assert "tcp-check send-binary" in cfg
    assert "tcp-check expect string +OK" in cfg
    assert 'tcp-check send "PING' in cfg
    assert "tcp-check expect string +PONG" in cfg

    # Server lines should not include SSL flags
    assert "server redis_0 redis1.local:6379 check inter 3s fall 2 rise 2" in cfg
    assert "ssl verify none" not in cfg
