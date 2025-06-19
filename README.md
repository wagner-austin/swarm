# README.md - Discord Bot Setup & Usage

This file provides setup, configuration, and usage instructions for the Discord bot.

## Quickstart

1. Install [Poetry](https://python-poetry.org/) and project dependencies:

```bash
pipx install poetry
poetry install --with dev            # runtime + dev dependencies
poetry run playwright install chromium   # one-off: download Chromium
```

2. Copy `.env.example` (or create `.env`) and define at minimum your Discord token:

```ini
DISCORD_TOKEN=your-bot-token-here
```

3. Launch the bot:

```bash
make run                      # preferred (uses Poetry venv)
# or
poetry run python -m bot.core  # same entry-point without Makefile
```

The embedded Chromium window is **visible by default**. Set `BROWSER_HEADLESS=true` for headless/CI use.

Run `make test` to execute the pytest suite and `make lint` for formatting, ruff, and mypy.

---

Installation:
1. Install Python:
   Download Python (3.9 or later) from python.org.
   Verify installation with: python --version

2. Install discord.py:
   Download the latest discord.py release (e.g., discord.py-2.0.1.tar.gz).
   Extract the file to a directory (for example, C:\Users\YourName\Projects\discord.py).
   Rename the extracted folder to "discord.py" for clarity.
   Add the folder C:\Users\YourName\Projects\discord.py\bin to your system PATH.

3. Verify discord.py installation:
   Open PowerShell and run:
   python -m discord --version

Registration and Verification:
1. Create a Discord bot account:
   Go to the Discord Developer Portal and create a new bot.
   Copy the bot token.

2. Configure your bot:
   Create a `.env` file in your project root with your bot token.

3. Verify your bot:
   Start the bot and test its functionality.

4. Test sending a message:
   Use the `!help` command to see available commands.

Next Steps:
1. Set your bot's profile name:
   discord.py.bat -u YOUR_SIGNAL_NUMBER updateProfile --name "Your Bot Name"
2. To read incoming messages, run:
   discord.py.bat -u YOUR_SIGNAL_NUMBER receive

Replace YOUR_SIGNAL_NUMBER with your actual Signal Bot number.


#### Configuration

### Browser Session Settings

The following environment variables can be set to control the browser session:
- `CHROME_PROFILE_DIR`: Path to the Chrome user data directory.
- `CHROME_PROFILE_NAME`: Name of the Chrome profile to use (default: Profile 1).
- `CHROMEDRIVER_PATH`: Path to the ChromeDriver executable.
- `BROWSER_DOWNLOAD_DIR`: Directory for browser downloads and screenshots.
- `BROWSER_HEADLESS`: Launch Chrome in headless mode (default: false). Set to `true` for CI or servers without a display.
- `BROWSER_DISABLE_GPU`: Disable GPU hardware acceleration (default: true).
- `BROWSER_WINDOW_SIZE`: Window size for the browser, e.g., `1920,1080` (default: `1920,1080`).
- `BROWSER_NO_SANDBOX`: Disable Chrome's sandbox (default: true; required for some CI environments).

Example usage:

```
@bot browser start [<url>]
@bot browser open <url>
@bot browser screenshot
@bot browser stop
@bot browser status
```

Create a `.env` file in your project root with the following contents:

```ini
# .env - Discord Bot configuration
DISCORD_TOKEN=your-bot-token-here
ROLE_NAME_MAP={"123456789012345678": "owner", "987654321098765432": "admin"}
GEMINI_API_KEY=your-gemini-key-here
OPENAI_API_KEY=your-openai-key-here
```

- **DISCORD_TOKEN** is required for the bot to run.
- All other fields are optional and have sensible defaults.
- The `ROLE_NAME_MAP` must be valid JSON.

> **Note:** Pydantic automatically loads environment variables from the `.env` file. You do not need to export variables in your shell. Just create or edit the `.env` file and restart the bot.

> **Note:** Run Alembic migrations to initialize the database schema and restart the bot.

## Building multi-step wizards

You can build interactive, multi-step workflows using the `WizardPlugin` mix-in. Wizards keep short-lived, per-user state (TTL: 1 hour) and can be extended for REST or chat use. Example:

```python
class MyWizard(WizardPlugin):
    def __init__(self):
        self.command_name = "mywiz"
        self.steps = {"start": self.ask, "next": self.next_step}
    async def ask(self, ctx, convo):
        convo.data["step"] = "next"
        return "What is your input?"
    async def next_step(self, ctx, convo, answer):
        return f"You said: {answer}"
```
See `plugins/wizard.py` for details. Wizards are channel-agnostic and can be used in REST APIs or chatbots alike.


### Security toggles
* `ALLOWED_HOSTS=github.com,internal-portal.local` → restricts navigation targets for `/browser open`.

### Persona management (admin only)
The bot ships with a YAML-backed persona registry.  Operators can:

* `/persona list` – list built-in and custom personas
* `/persona show <name>` – display the prompt for a persona (read-only)
* `/persona reload` – re-parse all YAML files from disk
* `/persona import` – (owner-only) upload secret personas

The previous `/persona add`, `/persona delete` and `/persona edit` commands have been removed in favour of managing YAML files directly on disk.
