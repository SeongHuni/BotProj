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

    def test_whitelist_add_includes_server_address_in_confirmation(self):
        sent_messages = []
        logged_messages = []

        class FakeResponse:
            async def defer(self, ephemeral=False):
                self.ephemeral = ephemeral

        class FakeFollowup:
            async def send(self, content, ephemeral=False):
                sent_messages.append((content, ephemeral))

        class FakeUser:
            def __init__(self):
                self.id = 42
                self.mention = "<@42>"
                self.guild_permissions = type("Permissions", (), {"manage_guild": True})()

        class FakeBot:
            def __init__(self):
                self.settings = type(
                    "Settings",
                    (),
                    {"minecraft_server_ip": "mc.example.com", "minecraft_server_port": 25565},
                )()
                self.log = bot.logging.getLogger("test")

            async def add_to_whitelist(self, username):
                self.username = username
                return "whitelist updated"

            async def send_whitelist_log(self, content):
                logged_messages.append(content)

        class FakeInteraction:
            def __init__(self):
                self.user = FakeUser()
                self.response = FakeResponse()
                self.followup = FakeFollowup()

        original_bot = bot.bot
        fake_bot = FakeBot()
        bot.bot = fake_bot
        try:
            asyncio.run(bot.whitelist_add(FakeInteraction(), "Steve"))
        finally:
            bot.bot = original_bot

        self.assertEqual(fake_bot.username, "Steve")
        self.assertTrue(sent_messages)
        self.assertIn("서버 주소: `mc.example.com:25565`", sent_messages[0][0])
        self.assertTrue(sent_messages[0][1])
        self.assertTrue(logged_messages)
        self.assertIn("서버 주소: `mc.example.com:25565`", logged_messages[0])

    def test_server_address_command_returns_configured_address(self):
        sent_messages = []

        class FakeResponse:
            async def send_message(self, content, ephemeral=False):
                sent_messages.append((content, ephemeral))

        class FakeInteraction:
            def __init__(self):
                self.response = FakeResponse()

        original_bot = bot.bot

        class FakeBot:
            def __init__(self):
                self.settings = type(
                    "Settings",
                    (),
                    {"minecraft_server_ip": "mc.example.com", "minecraft_server_port": 25565},
                )()

        bot.bot = FakeBot()
        try:
            asyncio.run(bot.server_address(FakeInteraction()))
        finally:
            bot.bot = original_bot

        self.assertEqual(sent_messages, [("Minecraft 서버 주소: `mc.example.com:25565`", True)])

    def test_submit_verification_allows_second_nickname(self):
        messages = []

        class FakeStore:
            def list_by_discord_id(self, discord_id):
                return [
                    {"minecraft_name": "Steve"},
                ]

            def get_by_minecraft_name(self, minecraft_name):
                return None

            def get_by_discord_id(self, discord_id):
                return {"minecraft_name": "Steve"}

            def add_verified_user(self, **kwargs):
                self.saved = kwargs

        class FakeBot:
            def __init__(self):
                self.settings = type(
                    "Settings",
                    (),
                    {
                        "require_admin_approval": False,
                        "discord_guild_id": None,
                        "minecraft_server_ip": "mc.example.com",
                        "minecraft_server_port": 25565,
                    },
                )()
                self.store = FakeStore()
                self.log = bot.logging.getLogger("test")

            async def add_to_whitelist(self, username):
                self.username = username
                return "whitelist updated"

            async def send_whitelist_log(self, content):
                messages.append(content)

            async def assign_verified_role(self, member):
                self.assigned_member = member

        class FakeUser:
            def __init__(self):
                self.id = 42
                self.mention = "<@42>"
                self.name = "DiscordUser"

            def __str__(self):
                return self.name

        fake_bot = FakeBot()
        ok, message = asyncio.run(
            bot.submit_verification(fake_bot, discord_user=FakeUser(), username="Alex")
        )

        self.assertTrue(ok)
        self.assertIn("등록 완료", message)
        self.assertEqual(fake_bot.username, "Alex")
        self.assertTrue(messages)

    def test_submit_verification_rejects_third_nickname(self):
        class FakeStore:
            def list_by_discord_id(self, discord_id):
                return [{"minecraft_name": "Steve"}, {"minecraft_name": "Alex"}]

            def get_by_minecraft_name(self, minecraft_name):
                return None

        class FakeBot:
            def __init__(self):
                self.settings = type(
                    "Settings",
                    (),
                    {
                        "require_admin_approval": False,
                        "discord_guild_id": None,
                        "minecraft_server_ip": "mc.example.com",
                        "minecraft_server_port": 25565,
                    },
                )()
                self.store = FakeStore()
                self.log = bot.logging.getLogger("test")

        class FakeUser:
            def __init__(self):
                self.id = 42
                self.name = "DiscordUser"

            def __str__(self):
                return self.name

        ok, message = asyncio.run(
            bot.submit_verification(FakeBot(), discord_user=FakeUser(), username="Herobrine")
        )

        self.assertFalse(ok)
        self.assertIn("최대 2개", message)


if __name__ == "__main__":
    unittest.main()