# Discord Bot Command Plugins

This directory contains the command plugins for the Discord bot.

## Command Naming Guidelines

To maintain consistency and avoid bugs across command implementations, follow these guidelines:

1. **Use constants for command names**: Define command names as constants at the top of your file
2. **Use the constants in both decorator and documentation**: Never hardcode command names
3. **Implement error handlers**: Add custom error handlers for better user experience
4. **Keep usage documentation in sync**: Use f-strings with constants to ensure consistency
5. **Write tests**: Use the test_command_consistency.py framework to verify commands

## Available Command Plugins

### Browser Commands

The browser automation plugin provides a set of commands for controlling a Chrome browser instance.

| Command | Arguments | Description |
|---------|-----------|-------------|
| `!browser` | - | Shows usage information for browser commands |
| `!browser start` | `<url> [visible]` | Starts a browser session, optionally navigates to a URL and makes it visible |
| `!browser open` | `<url>` | Navigates to a URL in the active browser session |
| `!browser close` | - | Closes the active browser session |
| `!browser screenshot` | `[filename]` | Takes a screenshot and sends it in the chat |
| `!browser status` | - | Checks if the browser is running |

#### Implementation Notes

- Commands are defined in `browser.py`
- Error handling for unknown commands is implemented
- Timeout mechanism prevents hanging during browser initialization
- Close and stop functionalities are implemented by the same method

#### Example Usage

```
!browser start https://example.com visible
!browser screenshot
!browser close
```
