# pylons
modern async eggdrop in pure python

# IRC Bot Network: Hub and Leaf System

## Overview

This project implements a flexible and extensible IRC bot network using a hub-and-leaf architecture. The system consists of a central hub bot that manages multiple leaf bots, allowing for distributed IRC presence and easy scalability.

## Version History

- v1.0.0: Initial release with basic hub and leaf functionality
- v1.1.0: Added plugin support and dynamic command handling
- v1.2.0: Implemented encryption for hub-leaf communication
- v1.3.0: Added support for IPv6 and improved error handling
- v1.4.0: Introduced dynamic configuration updates (UPDATECONF commands)

## Features

- Centralized hub bot managing multiple leaf bots
- Secure communication between hub and leaf bots using custom encryption
- Plugin system for easy extension of functionality
- Support for both IPv4 and IPv6
- Dynamic nick generation using Pokémon names
- Automatic reconnection and error recovery
- Runtime configuration updates

## How It Works

1. The hub bot starts and listens for incoming connections from leaf bots.
2. Leaf bots connect to the hub and receive their initial configuration and available commands.
3. The hub bot manages all leaf bots, broadcasting commands and updates as necessary.
4. Leaf bots connect to IRC servers and channels based on their configuration from the hub.
5. Commands entered in the hub are executed across all connected leaf bots.

## Command List

- `test`: Send a test message to the channel
- `join <channel>`: Join a new channel
- `leave <channel>`: Leave a channel
- `nick`: Change nickname (generates a new random Pokémon-based nickname)
- `UPDATECONF <address> <port>`: Update hub configuration
- `UPDATECONF.IRC <server> <port> <channel> [channel_password] [-ssl]`: Update IRC configuration

## Setup and Usage

### Hub Bot

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/irc-bot-network.git
   cd irc-bot-network
   ```

2. Run the hub bot:
   ```
   python hub_bot.py --hub-address 0.0.0.0 --hub-port 8888 --server irc.example.com --port 6667 --channel "#your-channel"
   ```

   Add `--ssl` if your IRC server uses SSL.

### Leaf Bot

1. Run the leaf bot, pointing it to your hub:
   ```
   python leaf_bot.py hub.example.com 8888
   ```

   Replace `hub.example.com` with the address of your hub bot.

## Plugin Development

To create a new plugin:

1. Create a new Python file in the `plugins` directory.
2. Define a class that inherits from `BasePlugin`.
3. Implement the `on_command` method and define a `commands` property.

Example:
```python
from hub_bot import BasePlugin

class MyPlugin(BasePlugin):
    async def on_command(self, sender, channel, command, args):
        if command == "hello":
            return {"type": "action", "action": "send_message", "channel": channel, "message": "Hello, World!"}

    @property
    def commands(self):
        return {"hello": "Say hello"}
```

## Requirements

- Python 3.7+
- asyncio

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Links

- [Project Homepage](https://github.com/strangeprogram/pylons)
- [Issue Tracker](https://github.com/strangeprogram/pylons/issues)
- [IRC Channel](#): #dev on irc.supernets.org

## Contact

For any questions or concerns, please open an issue on the GitHub repository.
