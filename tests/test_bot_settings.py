import asyncio
import socket
import struct
import os
import unittest


os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("RCON_PASSWORD", "test-password")
os.environ.setdefault("DISCORD_GUILD_ID", "1507400273004331182")

import bot  # noqa: E402


class BotSettingsTests(unittest.TestCase):
    def test_load_settings_uses_custom_rcon_timeout(self):
        previous_timeout = os.environ.get("RCON_TIMEOUT_SECONDS")
        os.environ["RCON_TIMEOUT_SECONDS"] = "75.5"
        try:
            settings = bot.load_settings()
        finally:
            if previous_timeout is None:
                os.environ.pop("RCON_TIMEOUT_SECONDS", None)
            else:
                os.environ["RCON_TIMEOUT_SECONDS"] = previous_timeout

        self.assertEqual(settings.rcon_timeout_seconds, 75.5)

    def test_load_settings_defaults_to_whitelist_log_channel(self):
        previous_channel_id = os.environ.pop("WHITELIST_LOG_CHANNEL_ID", None)
        try:
            settings = bot.load_settings()
        finally:
            if previous_channel_id is not None:
                os.environ["WHITELIST_LOG_CHANNEL_ID"] = previous_channel_id

        self.assertEqual(settings.whitelist_log_channel_id, 1508093161329660116)

    def test_load_settings_defaults_to_longer_timeout(self):
        previous_timeout = os.environ.pop("RCON_TIMEOUT_SECONDS", None)
        try:
            settings = bot.load_settings()
        finally:
            if previous_timeout is not None:
                os.environ["RCON_TIMEOUT_SECONDS"] = previous_timeout

        self.assertEqual(settings.rcon_timeout_seconds, 60.0)

    def test_rcon_command_returns_first_response_when_terminator_is_missing(self):
        class FakeSocket:
            def __init__(self):
                self._buffer = bytearray(self._packet(1, 0, "whitelist updated"))

            def settimeout(self, timeout):
                self.timeout = timeout

            def sendall(self, data):
                self.sent = data

            def recv(self, size):
                if not self._buffer:
                    raise socket.timeout()
                chunk = bytes(self._buffer[:size])
                del self._buffer[:size]
                return chunk

            @staticmethod
            def _packet(request_id, packet_type, body):
                payload = struct.pack("<ii", request_id, packet_type) + body.encode("utf-8") + b"\x00\x00"
                return struct.pack("<i", len(payload)) + payload

        client = bot.RconClient("127.0.0.1", "secret", 25575, timeout=1.0)
        client._socket = FakeSocket()
        client._next_request_id = 1

        result = client.command("whitelist add Steve")

        self.assertEqual(result, "whitelist updated")

    def test_add_to_whitelist_only_sends_one_rcon_command(self):
        commands = []

        class FakeBot:
            async def run_rcon(self, command):
                commands.append(command)
                return "ok"

        result = asyncio.run(bot.WhitelistBot.add_to_whitelist(FakeBot(), "Steve"))

        self.assertEqual(result, "ok")
        self.assertEqual(commands, ["whitelist add Steve"])

    def test_send_whitelist_log_sends_to_configured_channel(self):
        messages = []

        class FakeChannel:
            async def send(self, content):
                messages.append(content)

        class FakeBot:
            def __init__(self):
                self.settings = type("Settings", (), {"whitelist_log_channel_id": 12345})()
                self.log = bot.logging.getLogger("test")

            def get_channel(self, channel_id):
                self.channel_id = channel_id
                return FakeChannel()

            async def fetch_channel(self, channel_id):
                self.fetched_channel_id = channel_id
                return FakeChannel()

        fake_bot = FakeBot()

        asyncio.run(bot.WhitelistBot.send_whitelist_log(fake_bot, "hello world"))

        self.assertEqual(fake_bot.channel_id, 12345)
        self.assertEqual(messages, ["hello world"])


if __name__ == "__main__":
    unittest.main()