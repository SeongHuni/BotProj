import re
import tempfile
import unittest
from pathlib import Path

from storage import VerificationStore


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


class StorageAndValidationTests(unittest.TestCase):
    def test_minecraft_username_validation(self):
        valid = ["Steve", "Alex_123", "abc", "A" * 16]
        invalid = ["ab", "A" * 17, "nickname!", "한글닉네임", "space name"]

        for username in valid:
            self.assertIsNotNone(USERNAME_RE.fullmatch(username))
        for username in invalid:
            self.assertIsNone(USERNAME_RE.fullmatch(username))

    def test_store_finds_duplicate_minecraft_name_case_insensitive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = VerificationStore(Path(temp_dir) / "verified_users.db")
            store.add_verified_user(
                discord_id="1",
                discord_name="UserA",
                minecraft_name="Steve",
                verified_at="2026-05-24T00:00:00Z",
                approved_by=None,
                rcon_response="ok",
            )

            self.assertEqual(store.get_by_discord_id("1")["minecraft_name"], "Steve")
            self.assertEqual(store.get_by_minecraft_name("steve")["discord_id"], "1")


if __name__ == "__main__":
    unittest.main()