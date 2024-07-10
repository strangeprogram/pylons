import asyncio
import json
import ssl
import logging
import argparse
import socket
import base64
import os

def ssl_ctx(verify: bool = False):
    return ssl.create_default_context() if verify else ssl._create_unverified_context()

def get_ip_type(host, port):
    try:
        addrinfo = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        if addrinfo[0][0] == socket.AF_INET6:
            return socket.AF_INET6
        else:
            return socket.AF_INET
    except socket.gaierror:
        return socket.AF_INET  # Default to IPv4 if resolution fails

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

    async def on_message(self, sender, channel, message):
        pass

    @property
    def commands(self):
        return {}

class LeafBot:
    def __init__(self, hub_host, hub_port):
        self.hub_config = {
            "address": hub_host,
            "port": hub_port
        }
        self.hub_reader = None
        self.hub_writer = None
        self.irc_reader = None
        self.irc_writer = None
        self.irc_config = None
        self.commands = None
        self.nickname = None
        self.username = 'leafbot'
        self.realname = 'Leaf Bot'
        self.encryption = None
        self.plugins = []

    async def connect_to_hub(self):
        while True:
            try:
                logging.info(f"Attempting to connect to hub at {self.hub_config['address']}:{self.hub_config['port']}")
                self.hub_reader, self.hub_writer = await asyncio.open_connection(self.hub_config['address'], self.hub_config['port'])

                logging.info("Waiting for encryption key...")
                encryption_key = await asyncio.wait_for(self.hub_reader.readexactly(32), timeout=30)
                logging.info(f"Received encryption key: {encryption_key.hex()}")
                self.encryption = SimpleEncryption(encryption_key)

                logging.info("Waiting for encrypted config...")
                encrypted_config = await asyncio.wait_for(self.hub_reader.readline(), timeout=30)
                if not encrypted_config:
                    raise ConnectionError("Failed to receive config from hub")
                logging.info(f"Received encrypted config: {encrypted_config}")
                decrypted_config = self.encryption.decrypt(encrypted_config.decode().strip())
                logging.info(f"Decrypted config: {decrypted_config}")
                self.irc_config = json.loads(decrypted_config)

                logging.info("Waiting for encrypted commands...")
                encrypted_commands = await asyncio.wait_for(self.hub_reader.readline(), timeout=30)
                if not encrypted_commands:
                    raise ConnectionError("Failed to receive commands from hub")
                logging.info(f"Received encrypted commands: {encrypted_commands}")
                decrypted_commands = self.encryption.decrypt(encrypted_commands.decode().strip())
                logging.info(f"Decrypted commands: {decrypted_commands}")
                self.commands = json.loads(decrypted_commands)

                self.nickname = self.irc_config.get('nickname', 'LeafBot')

                logging.info(f"Successfully connected to hub at {self.hub_config['address']}:{self.hub_config['port']}")
                logging.info(f"Received IRC config: {self.irc_config}")
                logging.info(f"Received commands: {self.commands}")
                return
            except Exception as e:
                logging.error(f"Failed to connect to hub: {e}")
                await asyncio.sleep(30)  # Wait before retry

    async def connect_to_irc(self):
        while True:
            try:
                if not self.irc_config:
                    raise ValueError("IRC Configuration not received from hub")

                ip_type = get_ip_type(self.irc_config['server'], self.irc_config['port'])
                options = {
                    'host': self.irc_config['server'],
                    'port': self.irc_config['port'],
                    'ssl': ssl_ctx() if self.irc_config['use_ssl'] else None,
                    'family': ip_type,
                    'limit': 1024
                }
                self.irc_reader, self.irc_writer = await asyncio.wait_for(asyncio.open_connection(**options), 15)

                if self.irc_config.get('password'):
                    await self.raw(f"PASS {self.irc_config['password']}")
                await self.raw(f"NICK {self.nickname}")
                await self.raw(f"USER {self.username} 0 * :{self.realname}")

                while True:
                    data = await asyncio.wait_for(self.irc_reader.readline(), 300)
                    message = data.decode('utf-8').strip()
                    if message:
                        await self.handle_irc_message(message)

                    if "376" in message:  # End of MOTD
                        if self.irc_config.get('channel_password'):
                            await self.raw(f"JOIN {self.irc_config['channel']} {self.irc_config['channel_password']}")
                        else:
                            await self.raw(f"JOIN {self.irc_config['channel']}")
                        break

                logging.info(f"Connected to IRC server {self.irc_config['server']}:{self.irc_config['port']} and joining {self.irc_config['channel']}")
                return
            except Exception as e:
                logging.error(f"Error in IRC connection: {e}")
                await asyncio.sleep(30)

    async def raw(self, data):
        logging.debug(f"Sending to IRC: {data}")
        self.irc_writer.write(f"{data}\r\n".encode('utf-8'))
        await self.irc_writer.drain()

    async def handle_irc_message(self, data):
        logging.debug(f"Received IRC message: {data}")
        parts = data.split()
        if parts[0] == 'PING':
            await self.raw(f"PONG {parts[1]}")
        elif parts[1] == 'PRIVMSG':
            sender = parts[0].split('!')[0][1:]
            channel = parts[2]
            message = ' '.join(parts[3:])[1:]

            if message.startswith('!'):
                command = message[1:].split()[0]
                args = message.split()[1:]
                await self.send_to_hub(json.dumps({
                    "type": "command",
                    "sender": sender,
                    "channel": channel,
                    "command": command,
                    "args": args
                }))

            for plugin in self.plugins:
                await plugin.on_message(sender, channel, message)

    async def send_to_hub(self, message):
        encrypted_message = self.encryption.encrypt(message)
        self.hub_writer.write(f"{encrypted_message}\r\n".encode())
        await self.hub_writer.drain()

    async def handle_hub_message(self, encrypted_message):
        message = self.encryption.decrypt(encrypted_message)
        data = json.loads(message)
        if data['type'] == 'action':
            match data['action']:
                case 'send_message':
                    await self.raw(f"PRIVMSG {data['channel']} :{data['message']}")
                case 'join_channel':
                    await self.raw(f"JOIN {data['channel']}")
                case 'leave_channel':
                    await self.raw(f"PART {data['channel']}")
                case 'change_nick':
                    await self.raw(f"NICK {data['nickname']}")
                    self.nickname = data['nickname']
                case 'update_hub_config':
                    await self.update_hub_config(data['config'])
                case 'update_irc_config':
                    await self.update_irc_config(data['config'])
                case _:
                    logging.warning(f"Unknown action: {data['action']}")
        elif data['type'] == 'error':
            logging.error(f"Error from hub: {data['message']}")

    async def update_hub_config(self, new_config):
        logging.info(f"Updating hub configuration: {new_config}")
        old_address = self.hub_config['address']
        old_port = self.hub_config['port']
        self.hub_config = new_config
        if self.hub_config['address'] != old_address or self.hub_config['port'] != old_port:
            logging.info("Hub address or port changed. Reconnecting...")
            if self.hub_writer:
                self.hub_writer.close()
                await self.hub_writer.wait_closed()
            await self.connect_to_hub()

    async def update_irc_config(self, new_config):
        logging.info(f"Updating IRC configuration: {new_config}")
        old_server = self.irc_config['server']
        old_channel = self.irc_config['channel']

        self.irc_config = new_config

        if self.irc_config['server'] != old_server:
            logging.info("Server changed. Reconnecting...")
            if self.irc_writer:
                self.irc_writer.close()
                await self.irc_writer.wait_closed()
            await self.connect_to_irc()
        elif self.irc_config['channel'] != old_channel:
            logging.info("Channel changed. Joining new channel...")
            if old_channel:
                await self.raw(f"PART {old_channel}")
            if self.irc_config.get('channel_password'):
                await self.raw(f"JOIN {self.irc_config['channel']} {self.irc_config['channel_password']}")
            else:
                await self.raw(f"JOIN {self.irc_config['channel']}")

    async def run_irc(self):
        while True:
            try:
                if not self.irc_config:
                    logging.info("Waiting for IRC configuration from hub...")
                    await asyncio.sleep(5)
                    continue

                await self.connect_to_irc()
                while True:
                    data = await self.irc_reader.readline()
                    if not data:
                        raise ConnectionResetError("IRC connection closed")
                    message = data.decode('utf-8').strip()
                    if message:
                        await self.handle_irc_message(message)
            except Exception as e:
                logging.error(f"Error in IRC connection: {e}")
                await asyncio.sleep(30)

    async def run_hub(self):
        while True:
            try:
                await self.connect_to_hub()
                while True:
                    encrypted_message = await self.hub_reader.readline()
                    if not encrypted_message:
                        raise ConnectionResetError("Hub connection closed")
                    message = encrypted_message.decode().strip()
                    if message:
                        await self.handle_hub_message(message)
            except Exception as e:
                logging.error(f"Error in hub connection: {e}")
                await asyncio.sleep(30)

    async def run(self):
        while True:
            try:
                # First, ensure we're connected to the hub and have the configuration
                if not self.irc_config:
                    await self.connect_to_hub()
                    continue  # Go back to the start of the loop to check if we have the config now

                # Now that we have the config, run both IRC and hub connections
                await asyncio.gather(
                    self.run_irc(),
                    self.run_hub()
                )
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                await asyncio.sleep(30)

def setup_logger():
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s | %(levelname)8s | %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

async def main(hub_host, hub_port):
    setup_logger()
    while True:
        try:
            leaf_bot = LeafBot(hub_host, hub_port)
            await leaf_bot.run()
        except Exception as e:
            logging.error(f"LeafBot crashed: {e}")
            logging.info("Restarting LeafBot in 30 seconds...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Leaf Bot for IRC")
    parser.add_argument("hub_host", help="Hostname or IP address of the hub bot")
    parser.add_argument("hub_port", type=int, help="Port number of the hub bot")
    args = parser.parse_args()

    asyncio.run(main(args.hub_host, args.hub_port))
