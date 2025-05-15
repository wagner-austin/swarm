README.md - Signal Bot Setup Instructions
This file provides basic instructions for installing and using signal-cli with this bot.

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


#### .ENV FILE SETUP ####

# .env - Environment variables for the Signal Bot project.
# BOT_NUMBER: The phone number of your Signal Bot in E.164 format.
BOT_NUMBER=YOUR_SIGNAL_NUMBER

# POLLING_INTERVAL: The interval (in seconds) at which the bot checks for new messages.
POLLING_INTERVAL=1

# SIGNAL_CLI_COMMAND: The command used to run signal-cli (adjust if using a different OS).
SIGNAL_CLI_COMMAND=signal-cli.bat

# DIRECT_REPLY_ENABLED: Enable or disable direct reply quoting feature (True/False).
DIRECT_REPLY_ENABLED=True

# ENABLE_BOT_PREFIX: Toggle requirement of the @bot command prefix (true/false).
ENABLE_BOT_PREFIX=true

# DB_NAME: The name of the SQLite database file.
DB_NAME=bot_data.db


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
