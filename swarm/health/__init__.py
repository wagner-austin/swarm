"""
Uniform, typed health checks for Swarm services.

Subcommands are provided via ``python -m swarm.health``.

This module avoids ad-hoc inline health checks, keeps a single source of truth
for readiness, and is safe to use from container HEALTHCHECKs.
"""

__all__: list[str] = []
