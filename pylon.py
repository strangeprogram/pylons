import asyncio
import json
import random
import logging
import argparse
import socket
import ssl
import base64
import os
import inspect
import importlib

POKEMON_NAMES = [
    "Bulbasaur", "Ivysaur", "Venusaur", "Charmander", "Charmeleon", "Charizard",
    "Squirtle", "Wartortle", "Blastoise", "Caterpie", "Metapod", "Butterfree",
    "Weedle", "Kakuna", "Beedrill", "Pidgey", "Pidgeotto", "Pidgeot", "Rattata",
    "Raticate", "Spearow", "Fearow", "Ekans", "Arbok", "Pikachu", "Raichu",
    "Sandshrew", "Sandslash", "Nidoran♀", "Nidorina", "Nidoqueen", "Nidoran♂",
    "Nidorino", "Nidoking", "Clefairy", "Clefable", "Vulpix", "Ninetales",
    "Jigglypuff", "Wigglytuff", "Zubat", "Golbat", "Oddish", "Gloom", "Vileplume",
    "Paras", "Parasect", "Venonat", "Venomoth", "Diglett", "Dugtrio", "Meowth",
    "Persian", "Psyduck", "Golduck", "Mankey", "Primeape", "Growlithe", "Arcanine",
    "Poliwag", "Poliwhirl", "Poliwrath", "Abra", "Kadabra", "Alakazam", "Machop",
    "Machoke", "Machamp", "Bellsprout", "Weepinbell", "Victreebel", "Tentacool",
    "Tentacruel", "Geodude", "Graveler", "Golem", "Ponyta", "Rapidash", "Slowpoke",
    "Slowbro", "Magnemite", "Magneton", "Farfetchd", "Doduo", "Dodrio", "Seel",
    "Dewgong", "Grimer", "Muk", "Shellder", "Cloyster", "Gastly", "Haunter",
    "Gengar", "Onix", "Drowzee", "Hypno", "Krabby", "Kingler", "Voltorb",
    "Electrode", "Exeggcute", "Exeggutor", "Cubone", "Marowak", "Hitmonlee",
    "Hitmonchan", "Lickitung", "Koffing", "Weezing", "Rhyhorn", "Rhydon", "Chansey",
    "Tangela", "Kangaskhan", "Horsea", "Seadra", "Goldeen", "Seaking", "Staryu",
    "Starmie", "MrMime", "Scyther", "Jynx", "Electabuzz", "Magmar", "Pinsir",
    "Tauros", "Magikarp", "Gyarados", "Lapras", "Ditto", "Eevee", "Vaporeon",
    "Jolteon", "Flareon", "Porygon", "Omanyte", "Omastar", "Kabuto", "Kabutops",
    "Aerodactyl", "Snorlax", "Articuno", "Zapdos", "Moltres", "Dratini",
    "Dragonair", "Dragonite", "Mewtwo", "Mew"
]

def generate_nick():
    return f"{random.choice(POKEMON_NAMES)}{random.randint(100, 999)}"

class SimpleEncryption:
    def __init__(self, key):
        self.key = key

    def encrypt(self, data):
        encrypted = bytearray()
        for i, char in enumerate(data):
            encrypted.append(ord(char) ^ self.key[i % len(self.key)])
        return base64.b64encode(encrypted).decode()

    def decrypt(self, data):
        encrypted = base64.b64decode(data)
        decrypted = bytearray()
        for i, byte in enumerate(encrypted):
            decrypted.append(byte ^ self.key[i % len(self.key)])
        return decrypted.decode()

class BasePlugin:
    def __init__(self, bot):
        self.bot = bot

    async def on_command(self, sender, channel, command, args):
        pass

    @property
    def commands(self):
        return {}

class CommandHub:
    def __init__(self, hub_address, hub_port, irc_server, irc_port, irc_channel, use_ssl=False, channel_password=None, server_password=None):
        self.hub_config = {
            "address": hub_address,
            "port": hub_port,
        }
        self.leaf_bots = set()
        self.irc_config = {
            "server": irc_server,
            "port": irc_port,
            "channel": irc_channel,
            "use_ssl": use_ssl,
            "channel_password": channel_password,
            "password": server_password,
        }
        self.encryption_key = os.urandom(32)
        self.encryption = SimpleEncryption(self.encryption_key)
        self.plugins = []
        self.commands = {
            "test": "Send a test message to the channel",
            "join": "Join a new channel",
            "leave": "Leave a channel",
            "nick": "Change nickname",
            "UPDATECONF": "Update hub configuration",
            "UPDATECONF.IRC": "Update IRC configuration"
        }
        self.load_plugins()

    def load_plugins(self):
        new_plugins = []
        plugins_dir = os.path.join(os.path.dirname(__file__), "plugins")
        for filename in os.listdir(plugins_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = f"plugins.{filename[:-3]}"
                module = importlib.import_module(module_name)
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, BasePlugin) and obj != BasePlugin:
                        plugin = obj(self)
                        self.plugins.append(plugin)
                        self.commands.update(plugin.commands)
                        new_plugins.append(name)
                        logging.info(f"Loaded new plugin: {name}")
        return new_plugins

    async def handle_leaf_connection(self, reader, writer):
        addr = writer.get_extra_info('peername')
        logging.info(f"New leaf bot connected: {addr}")

        writer.write(self.encryption_key)
        await writer.drain()

        leaf_config = self.irc_config.copy()
        leaf_config["nickname"] = generate_nick()

        encrypted_config = self.encryption.encrypt(json.dumps(leaf_config))
        writer.write(encrypted_config.encode() + b'\n')
        await writer.drain()

        encrypted_commands = self.encryption.encrypt(json.dumps(self.commands))
        writer.write(encrypted_commands.encode() + b'\n')
        await writer.drain()

        self.leaf_bots.add(writer)
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                encrypted_message = data.decode().strip()
                message = self.encryption.decrypt(encrypted_message)
                logging.info(f"Received from leaf bot {addr}: {message}")
                await self.process_leaf_message(writer, message)
        finally:
            self.leaf_bots.remove(writer)
            writer.close()
            await writer.wait_closed()
            logging.info(f"Leaf bot disconnected: {addr}")

    async def process_leaf_message(self, writer, message):
        try:
            data = json.loads(message)
            if data['type'] == 'command':
                response = await self.execute_command(data['sender'], data['channel'], data['command'], data.get('args', []))
                encrypted_response = self.encryption.encrypt(json.dumps(response))
                writer.write(encrypted_response.encode() + b'\n')
                await writer.drain()
        except json.JSONDecodeError:
            logging.error(f"Received invalid JSON from leaf bot: {message}")

    async def execute_command(self, sender, channel, command, args):
        if command in self.commands:
            if command == "test":
                return {"type": "action", "action": "send_message", "channel": channel, "message": "Test message from hub"}
            elif command == "join":
                return {"type": "action", "action": "join_channel", "channel": args[0] if args else channel}
            elif command == "leave":
                return {"type": "action", "action": "leave_channel", "channel": args[0] if args else channel}
            elif command == "nick":
                new_nick = generate_nick()
                return {"type": "action", "action": "change_nick", "nickname": new_nick}
            elif command == "UPDATECONF":
                return self.update_hub_config(args)
            elif command == "UPDATECONF.IRC":
                return self.update_irc_config(args)
            else:
                for plugin in self.plugins:
                    result = await plugin.on_command(sender, channel, command, args)
                    if result:
                        return result
        return {"type": "error", "message": "Unknown command"}

    def update_hub_config(self, params):
        if len(params) >= 2:
            self.hub_config["address"] = params[0]
            self.hub_config["port"] = int(params[1])
        elif len(params) == 1:
            if params[0].isdigit():
                self.hub_config["port"] = int(params[0])
            else:
                self.hub_config["address"] = params[0]
        logging.info(f"Updated hub configuration: {self.hub_config}")
        return {"type": "action", "action": "update_hub_config", "config": self.hub_config}

    def update_irc_config(self, params):
        if len(params) >= 3:
            self.irc_config["server"] = params[0]
            self.irc_config["port"] = int(params[1])
            self.irc_config["channel"] = params[2]
            self.irc_config["channel_password"] = params[3] if len(params) > 3 else None
            self.irc_config["use_ssl"] = True if len(params) > 4 and params[4] == "-ssl" else False
        logging.info(f"Updated IRC configuration: {self.irc_config}")
        return {"type": "action", "action": "update_irc_config", "config": self.irc_config}

    async def broadcast_command(self, command, params):
        response = await self.execute_command("Console", "Hub", command, params)
        encrypted_response = self.encryption.encrypt(json.dumps(response))
        for bot in self.leaf_bots:
            try:
                bot.write(encrypted_response.encode() + b'\n')
                await bot.drain()
            except Exception as e:
                logging.error(f"Error broadcasting command to leaf bot: {e}")

    async def run_hub_server(self):
        servers = []

        # Try to start IPv6 server
        try:
            server_ipv6 = await asyncio.start_server(
                self.handle_leaf_connection, '::', self.hub_config['port'], family=socket.AF_INET6)
            servers.append(server_ipv6)
            logging.info(f'Serving on IPv6: {server_ipv6.sockets[0].getsockname()}')
        except Exception as e:
            logging.warning(f"Failed to start server on IPv6: {e}")

        # Try to start IPv4 server
        try:
            server_ipv4 = await asyncio.start_server(
                self.handle_leaf_connection, self.hub_config['address'], self.hub_config['port'], family=socket.AF_INET)
            servers.append(server_ipv4)
            logging.info(f'Serving on IPv4: {server_ipv4.sockets[0].getsockname()}')
        except Exception as e:
            logging.warning(f"Failed to start server on IPv4: {e}")

        if not servers:
            logging.error("Failed to start any servers. Exiting.")
            return

        await asyncio.gather(*(server.serve_forever() for server in servers))

    async def console_input(self):
        while True:
            try:
                command = await asyncio.get_event_loop().run_in_executor(None, input, "Enter command: ")
                parts = command.split()
                if parts:
                    await self.broadcast_command(parts[0], parts[1:])
                else:
                    logging.warning("Empty command entered")
            except Exception as e:
                logging.error(f"Error processing console input: {e}")

    async def run(self):
        await asyncio.gather(
            self.run_hub_server(),
            self.console_input()
        )

def setup_logger():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s | %(levelname)8s | %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

async def main(args):
    setup_logger()
    while True:
        try:
            hub_bot = CommandHub(
                args.hub_address,
                args.hub_port,
                args.server,
                args.port,
                args.channel,
                use_ssl=args.ssl,
                channel_password=args.key,
                server_password=args.password,
            )
            await hub_bot.run()
        except Exception as e:
            logging.error(f"HubBot crashed: {e}")
            logging.info("Restarting HubBot in 30 seconds...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IRC Hub Bot")
    parser.add_argument("--hub-address", default="0.0.0.0", help="Address for the hub to listen on")
    parser.add_argument("--hub-port", type=int, default=8888, help="Port for the hub to listen on")
    parser.add_argument("--server", required=True, help="The IRC server address")
    parser.add_argument("--port", type=int, default=6667, help="The IRC server port")
    parser.add_argument("--channel", required=True, help="The IRC channel to join")
    parser.add_argument("--ssl", action="store_true", help="Use SSL for IRC connection")
    parser.add_argument("--key", help="The key (password) for the IRC channel, if required")
    parser.add_argument("--password", help="The password for the IRC server, if required")
    args = parser.parse_args()

    if args.ssl and args.port == 6667:
        args.port = 6697  # Default SSL port

    asyncio.run(main(args))
