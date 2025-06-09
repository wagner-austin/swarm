import contextlib
import socket
import asyncio


async def pick_free_port(base: int, attempts: int = 5) -> int:
    for off in range(attempts):
        cand = base + off
        if is_port_free(cand):  # Renamed function call
            await asyncio.sleep(0.1)
            if is_port_free(cand):  # Renamed function call
                return cand
    raise RuntimeError(f"No free port in range {base}-{base + attempts - 1}")


def is_port_free(port: int) -> bool:  # Renamed function
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.connect_ex(("127.0.0.1", port)) != 0
