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

class LeafBot:
    def __init__(self, hub_host, hub_port):
        self.hub_host = hub_host
        self.hub_port = hub_port
        self.hub_reader = None
        self.hub_writer = None
        self.irc_reader = None
        self.irc_writer = None
        self.config = None
        self.commands = None
        self.nickname = None
        self.username = 'leafbot'
        self.realname = 'Leaf Bot'
        self.encryption = None

    async def connect_to_hub(self):
        while True:
            try:
                logging.info(f"Attempting to connect to hub at {self.hub_host}:{self.hub_port}")
                self.hub_reader, self.hub_writer = await asyncio.open_connection(self.hub_host, self.hub_port)
                logging.info("Connection to hub established")

                # Receive encryption key
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
                self.config = json.loads(decrypted_config)

                logging.info("Waiting for encrypted commands...")
                encrypted_commands = await asyncio.wait_for(self.hub_reader.readline(), timeout=30)
                if not encrypted_commands:
                    raise ConnectionError("Failed to receive commands from hub")
                logging.info(f"Received encrypted commands: {encrypted_commands}")
                decrypted_commands = self.encryption.decrypt(encrypted_commands.decode().strip())
                logging.info(f"Decrypted commands: {decrypted_commands}")
                self.commands = json.loads(decrypted_commands)

                self.nickname = self.config.get('nickname', 'LeafBot')

                logging.info(f"Successfully connected to hub at {self.hub_host}:{self.hub_port}")
                logging.info(f"Received config: {self.config}")
                logging.info(f"Received commands: {self.commands}")
                return
            except asyncio.TimeoutError:
                logging.error("Timeout while connecting to hub")
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse JSON: {e}")
            except Exception as e:
                logging.error(f"Failed to connect to hub: {e}")
            logging.info("Retrying connection to hub in 30 seconds...")
            await asyncio.sleep(30)  # Wait before retry

    async def connect_to_irc(self):
        while True:
            try:
                if not self.config:
                    raise ValueError("Configuration not received from hub")

                ip_type = get_ip_type(self.config['server'], self.config['port'])
                options = {
                    'host': self.config['server'],
                    'port': self.config['port'],
                    'ssl': ssl_ctx() if self.config['use_ssl'] else None,
                    'family': ip_type,
                    'limit': 1024
                }
                self.irc_reader, self.irc_writer = await asyncio.wait_for(asyncio.open_connection(**options), 15)

                if self.config.get('password'):
                    await self.raw(f"PASS {self.config['password']}")
                await self.raw(f"NICK {self.nickname}")
                await self.raw(f"USER {self.username} 0 * :{self.realname}")

                while True:
                    data = await asyncio.wait_for(self.irc_reader.readline(), 300)
                    message = data.decode('utf-8').strip()
                    if message:
                        await self.handle_irc_message(message)

                    if "376" in message:  # End of MOTD
                        if self.config.get('channel_password'):
                            await self.raw(f"JOIN {self.config['channel']} {self.config['channel_password']}")
                        else:
                            await self.raw(f"JOIN {self.config['channel']}")
                        break

                logging.info(f"Connected to IRC server {self.config['server']}:{self.config['port']} and joining {self.config['channel']}")
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

    async def handle_hub_message(self, encrypted_message):
        message = self.encryption.decrypt(encrypted_message)
        data = json.loads(message)
        if data['type'] == 'action':
            match data['action']:
                case 'send_message':
                    await self.raw(f"PRIVMSG {self.config['channel']} :{data['message']}")
                case 'join_channel':
                    await self.raw(f"JOIN {data['channel']}")
                case 'leave_channel':
                    await self.raw(f"PART {data['channel']}")
                case 'change_nick':
                    await self.raw(f"NICK {data['nickname']}")
                    self.nickname = data['nickname']
                case 'update_config':
                    await self.update_config(data['config'])
                case _:
                    logging.warning(f"Unknown action: {data['action']}")

    async def update_config(self, new_config):
        logging.info(f"Updating configuration: {new_config}")
        old_server = self.config['server']
        old_channel = self.config['channel']

        self.config = new_config

        if self.config['server'] != old_server:
            logging.info("Server changed. Reconnecting...")
            if self.irc_writer:
                self.irc_writer.close()
                await self.irc_writer.wait_closed()
            await self.connect_to_irc()
        elif self.config['channel'] != old_channel:
            logging.info("Channel changed. Joining new channel...")
            if old_channel:
                await self.raw(f"PART {old_channel}")
            if self.config.get('channel_password'):
                await self.raw(f"JOIN {self.config['channel']} {self.config['channel_password']}")
            else:
                await self.raw(f"JOIN {self.config['channel']}")

    async def run_irc(self):
        while True:
            try:
                if not self.config:
                    logging.info("Waiting for configuration from hub...")
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
                if not self.config:
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
    logging.basicConfig(level=logging.DEBUG,  # Changed to DEBUG for more detailed logs
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
