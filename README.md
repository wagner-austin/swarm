# README.md - Discord Bot Setup & Usage

This file provides setup, configuration, and usage instructions for the Discord bot.

## Running locally

After installing dependencies and configuring your `.env`, you can start the bot in either of these ways:

```sh
python -m bot_core.main
```

or

```sh
python bot.py
```

The bot will respond to commands that start with `!` or when mentioned:

```
!help
!browser start
!info
```

---

Installation:
1. Install Java:
   Download Java (JDK 17 or later) from Adoptium.net.
   Verify installation with: java -version

2. Install signal-cli:
   Download the latest signal-cli release (e.g., signal-cli-0.13.13.tar.gz).
   Extract the file to a directory (for example, C:\Users\YourName\Projects\signal-cli).
   Rename the extracted folder to "signal-cli" for clarity.
   Add the folder C:\Users\YourName\Projects\signal-cli\bin to your system PATH.

3. Verify signal-cli installation:
   Open PowerShell and run:
   signal-cli.bat --version

Registration and Verification:
1. Register your Signal Bot using your Google Voice number.
   In PowerShell, run:
   signal-cli.bat -u YOUR_SIGNAL_NUMBER register

2. Complete CAPTCHA verification:
   Open the CAPTCHA link provided in the registration output in your browser.
   Copy the CAPTCHA token link.
   Run the register command again with the token:
   signal-cli.bat -u YOUR_SIGNAL_NUMBER register --captcha "PASTE-LINK-HERE"

3. Verify your bot:
   When you receive the verification code via SMS, run:
   signal-cli.bat -u YOUR_SIGNAL_NUMBER verify CODE

4. Test sending a message:
   signal-cli.bat -u YOUR_SIGNAL_NUMBER send RECIPIENT_NUMBER -m "Signal bot successfully verified!"

Next Steps:
1. Set your bot's profile name:
   signal-cli.bat -u YOUR_SIGNAL_NUMBER updateProfile --name "Your Bot Name"
2. To read incoming messages, run:
   signal-cli.bat -u YOUR_SIGNAL_NUMBER receive

Replace YOUR_SIGNAL_NUMBER with your actual Signal Bot number.


#### Configuration

### Browser Session Settings

The following environment variables can be set to control the browser session:
- `CHROME_PROFILE_DIR`: Path to the Chrome user data directory.
- `CHROME_PROFILE_NAME`: Name of the Chrome profile to use (default: Profile 1).
- `CHROMEDRIVER_PATH`: Path to the ChromeDriver executable.
- `BROWSER_DOWNLOAD_DIR`: Directory for browser downloads and screenshots.

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
DB_NAME=bot_data.db
BACKUP_INTERVAL=3600
BACKUP_RETENTION=10
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
