from __future__ import annotations

import logging
import pkgutil
import sys
from importlib import import_module
from typing import TYPE_CHECKING

from swarm.core.containers import Container

if TYPE_CHECKING:
    from swarm.core.settings import Settings

logger = logging.getLogger(__name__)


def initialize_and_wire_container(
    app_settings: Settings,
    runner_module_name: str,
) -> Container:
    """Create the DI container and wire *all* packages under ``bot.plugins``.

    The caller only needs to provide the already-instantiated ``Settings``
    singleton and its own module name (so we wire the lifecycle/runners too).
    """

    logger.info("Initializing Dependency Injection container …")
    container = Container()
    container.config.override(app_settings)

    # --- auto-discover every sub-module under bot.plugins ------------------
    logger.info("Auto-discovering swarm.plugins sub-modules for DI wiring …")
    packages_to_wire = []

    try:
        root_pkg = import_module("swarm.plugins")
        packages_to_wire.append(root_pkg)

        for mod_info in pkgutil.walk_packages(root_pkg.__path__, "swarm.plugins."):
            try:
                packages_to_wire.append(import_module(mod_info.name))
            except ImportError as e:
                logger.error(f"Failed to import {mod_info.name} for DI wiring: {e}")
    except ImportError as e:
        logger.error(f"Could not import swarm.plugins package: {e}")

    # Ensure the runner (lifecycle) module is included
    try:
        runner_mod = sys.modules[runner_module_name]
    except KeyError:
        runner_mod = import_module(runner_module_name)

    packages_to_wire.append(runner_mod)

    logger.info(
        "Wiring DI container for packages: %s",
        ", ".join(sorted({pkg.__name__ for pkg in packages_to_wire})),
    )
    container.wire(packages=packages_to_wire)
    logger.info("Dependency Injection container wired successfully.")

    return container
