from __future__ import annotations

import importlib
import logging
import sys  # Added for sys.modules
from typing import TYPE_CHECKING

from bot.core.containers import Container

if TYPE_CHECKING:
    from bot.core.settings import Settings  # For type hinting app_settings

logger = logging.getLogger(__name__)


def initialize_and_wire_container(
    app_settings: Settings,
    discovered_extension_paths: list[str],
    runner_module_name: str,
) -> Container:
    """
    Initializes the DI container, pre-imports extension modules, and wires them.
    """
    logger.info("Initializing Dependency Injection container...")
    container = Container()
    # Replace default Settings() singleton with the already-initialised one
    container.config.override(app_settings)
    logger.info("DI container initialized and application settings overridden.")

    logger.info("Pre-importing discovered extensions for DI wiring...")
    modules_to_wire = []
    for ext_module_path in discovered_extension_paths:
        try:
            module = importlib.import_module(ext_module_path)
            modules_to_wire.append(module)
            logger.debug(f"Successfully pre-imported extension: {ext_module_path}")
        except ImportError as e:
            # Log the error and continue, or re-raise if it's critical
            logger.error(
                f"Failed to import extension module {ext_module_path} for DI wiring: {e}"
            )
            # Depending on desired behavior, you might want to skip this module or raise
            # For now, let's mimic the original behavior which would likely fail at import_module

    logger.info(
        f"Attempting to wire modules: {[runner_module_name, *[m.__name__ for m in modules_to_wire]]}"
    )
    try:
        runner_mod = sys.modules[runner_module_name]
    except KeyError:
        # Fallback if not already imported, though lifecycle should ensure it is.
        logger.warning(
            f"Module {runner_module_name} not found in sys.modules, attempting importlib.import_module."
        )
        try:
            runner_mod = importlib.import_module(runner_module_name)
        except ImportError as e:
            logger.error(f"Failed to import runner module {runner_module_name}: {e}")
            # Decide on error handling: re-raise, or wire without it?
            # For now, let's try to wire without it if it fails, but log critical error.
            logger.critical(
                f"CRITICAL: Runner module {runner_module_name} could not be loaded for DI. Wiring will proceed without it."
            )
            container.wire(modules=modules_to_wire)  # Wire without runner_mod
            logger.info("DI container wiring complete (runner module failed to load).")
            return container

    container.wire(
        modules=[runner_mod, *modules_to_wire],  # runner + all command modules
    )
    logger.info("DI container wiring complete.")
    return container
