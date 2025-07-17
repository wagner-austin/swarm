# Frontend Adapter Architecture

## Overview
This project is designed to support multiple user-facing frontends (Discord, Telegram, Web, SMS, etc.) through a clean, extensible adapter pattern. All frontend-specific logic is isolated, ensuring the core swarm logic and backend services (like Tankpit automation) remain UI-agnostic and reusable.

## Key Concepts

- **FrontendAdapter Interface:**
  - Defined in `swarm/frontends/base.py`.
  - All frontends must implement this interface, providing `start()`, `shutdown()`, and (optionally) `dispatch_message()` methods.

- **Discord Adapter:**
  - Implemented in `swarm/frontends/discord/adapter.py`.
  - Wraps the Discord frontend lifecycle and exposes it via the adapter interface.

- **Startup Logic:**
  - In `swarm/core/launcher.py`, swarm is started via the adapter interface.
  - To add a new frontend, implement its adapter and plug it into the startup selection logic.

## How to Add a New Frontend

1. **Implement an Adapter:**
    - Create a new adapter class in `swarm/frontends/<frontend>/adapter.py`.
    - Inherit from `FrontendAdapter` and implement the required methods.

2. **(Optional) Add UI Plugins:**
    - Place frontend-specific command handlers or plugins in `swarm/frontends/<frontend>/plugins/`.
    - Keep business logic in core modules for maximum reuse.

3. **Update Startup Logic:**
    - In `swarm/core/launcher.py`, instantiate your new adapter and use it in place of (or in addition to) the Discord adapter.
    - Example:
      ```python
      from swarm.frontends.telegram.adapter import TelegramFrontendAdapter
      # ...
      frontend = TelegramFrontendAdapter(...)
      await frontend.start()
      ```

4. **Done!**
    - Your new frontend is now isolated, testable, and easily maintainable alongside Discord and others.

## Example Directory Structure

```
swarm/
  frontends/
    base.py
    discord/
      adapter.py
      plugins/
    telegram/
      adapter.py
      plugins/
  core/
    launcher.py
  tankpit/
    engine.py
```

## Best Practices
- Keep all frontend-specific code (UI, commands, plugins) under the relevant frontend package.
- Put all shared/business logic in core modules (e.g., `swarm/tankpit/`, `swarm/core/logic/`).
- Use the adapter interface for all startup/shutdown and message dispatch logic.
- Document new frontends and their adapters in this file.

---

For questions or to add a new frontend, see the code in `swarm/frontends/base.py` and `swarm/core/launcher.py` for extension points.
