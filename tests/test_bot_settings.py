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


if __name__ == "__main__":
    unittest.main()