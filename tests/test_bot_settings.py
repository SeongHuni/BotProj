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


if __name__ == "__main__":
    unittest.main()