import asyncio
import json
import random
import logging
import argparse
import socket
import ssl

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

class CommandHub:
    def __init__(self, hub_port, irc_server, irc_port, irc_channel, use_ssl=False, channel_password=None, server_password=None):
        self.hub_port = hub_port
        self.leaf_bots = set()
        self.commands = {
            "test": "Send a test message to the channel",
            "join": "Join a new channel",
            "leave": "Leave a channel",
            "nick": "Change nickname"
        }
        self.config = {
            "server": irc_server,
            "port": irc_port,
            "channel": irc_channel,
            "use_ssl": use_ssl,
            "channel_password": channel_password,
            "password": server_password,
        }

    async def handle_leaf_connection(self, reader, writer):
        addr = writer.get_extra_info('peername')
        logging.info(f"New leaf bot connected: {addr}")

        leaf_config = self.config.copy()
        leaf_config["nickname"] = generate_nick()

        writer.write(json.dumps(leaf_config).encode() + b'\n')
        await writer.drain()

        writer.write(json.dumps(self.commands).encode() + b'\n')
        await writer.drain()

        self.leaf_bots.add(writer)
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                message = data.decode().strip()
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
                await self.execute_command(writer, data['command'], data.get('params', []))
        except json.JSONDecodeError:
            logging.error(f"Received invalid JSON from leaf bot: {message}")

    async def execute_command(self, writer, command, params):
        match command:
            case 'test':
                response = {"type": "action", "action": "send_message", "message": "Test message from hub"}
            case 'join':
                response = {"type": "action", "action": "join_channel", "channel": params[0]}
            case 'leave':
                response = {"type": "action", "action": "leave_channel", "channel": params[0]}
            case 'nick':
                new_nick = generate_nick()
                response = {"type": "action", "action": "change_nick", "nickname": new_nick}
            case 'UPDATECONF':
                self.update_config(params)
                response = {"type": "action", "action": "update_config", "config": self.config}
            case _:
                response = {"type": "error", "message": "Unknown command"}

        writer.write(json.dumps(response).encode() + b'\n')
        await writer.drain()

    def update_config(self, params):
        if len(params) >= 3:
            self.config["server"] = params[0]
            self.config["port"] = int(params[1])
            self.config["channel"] = params[2]
            self.config["channel_password"] = params[3] if len(params) > 3 else None
            self.config["use_ssl"] = True if len(params) > 4 and params[4] == "-ssl" else False
        logging.info(f"Updated configuration: {self.config}")

    async def broadcast_command(self, command, params):
        for bot in self.leaf_bots:
            await self.execute_command(bot, command, params)

    async def run_hub_server(self):
        servers = []

        # Try to start IPv6 server
        try:
            server_ipv6 = await asyncio.start_server(
                self.handle_leaf_connection, '::', self.hub_port, family=socket.AF_INET6)
            servers.append(server_ipv6)
            logging.info(f'Serving on IPv6: {server_ipv6.sockets[0].getsockname()}')
        except Exception as e:
            logging.warning(f"Failed to start server on IPv6: {e}")

        # Try to start IPv4 server
        try:
            server_ipv4 = await asyncio.start_server(
                self.handle_leaf_connection, '0.0.0.0', self.hub_port, family=socket.AF_INET)
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
            command = await asyncio.get_event_loop().run_in_executor(None, input, "Enter command: ")
            parts = command.split()
            if parts:
                await self.broadcast_command(parts[0], parts[1:])

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
    hub_bot = CommandHub(
        args.hub_port,
        args.server,
        args.port,
        args.channel,
        use_ssl=args.ssl,
        channel_password=args.key,
        server_password=args.password,
    )
    await hub_bot.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IRC Hub Bot")
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
