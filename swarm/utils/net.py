import asyncio
import contextlib
import socket


async def pick_free_port(base: int, attempts: int = 5, *, delay: float = 0.1) -> int:
    """
    Return the first available TCP port >= *base* within *attempts* tries.

    The additional short *delay* between the double‑check reduces the race
    window on platforms that keep sockets in TIME_WAIT.
    """
    for off in range(attempts):
        cand = base + off
        if is_port_free(cand):
            await asyncio.sleep(delay)
            if is_port_free(cand):
                return cand
    raise RuntimeError(f"No free port in range {base}‑{base + attempts - 1}")


def is_port_free(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.connect_ex(("127.0.0.1", port)) != 0
