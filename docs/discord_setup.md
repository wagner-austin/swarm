# Discord Bot Setup Guide

Follow these steps to set up your Discord bot with this project:

## 1. Create a Discord Bot Application
- Go to the [Discord Developer Portal](https://discord.com/developers/applications)
- Click **New Application** and give your bot a name
- Under **Bot** section, click **Add Bot**
- Copy the bot token (you'll need it in step 3)

## 2. Invite the Bot to Your Server
- In the Developer Portal, select **OAuth2 > URL Generator**
- Under **Scopes**, select `bot`
- Under **Bot Permissions**, select the permissions your bot needs (at minimum: `Send Messages`, `Read Message History`)
- Copy the generated URL and open it in your browser
- Select your server and authorize the bot

## 3. Add the Bot Token to Your .env File
- In your project root, open or create a `.env` file
- Add the following line (replace `YOUR_TOKEN` with your actual token):

```
DISCORD_TOKEN=YOUR_TOKEN
```

---

Your Discord bot is now ready to run with this project!
