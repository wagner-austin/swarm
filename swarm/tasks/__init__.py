"""
Celery tasks for Swarm.

This module contains all Celery tasks organized by type:
- browser: Web browser automation tasks
- tankpit: Tank pit proxy tasks
- llm: Language model tasks
"""

from swarm.tasks.base import SwarmTask
from swarm.tasks.browser import (
    cleanup,
    click,
    fill,
    goto,
    scrape_data,
    screenshot,
    start,
    status,
    upload,
    wait_for,
)

__all__ = [
    "SwarmTask",
    "cleanup",
    "click",
    "fill",
    "goto",
    "scrape_data",
    "screenshot",
    "start",
    "status",
    "upload",
    "wait_for",
]
