import unittest
from unittest.mock import patch

from app.api.v1.endpoints.voice import voice_token_is_allowed
from app.core.config import settings
from app.core.security import create_access_token


class VoiceAuthTests(unittest.TestCase):
    def test_local_bypass_allows_missing_token(self):
        with patch.object(settings, "ALLOW_UNAUTHENTICATED_VOICE", True):
            self.assertTrue(voice_token_is_allowed(None))

    def test_secure_mode_rejects_missing_token(self):
        with patch.object(settings, "ALLOW_UNAUTHENTICATED_VOICE", False):
            self.assertFalse(voice_token_is_allowed(None))

    def test_secure_mode_accepts_valid_token(self):
        token = create_access_token(subject="voice-user")

        with patch.object(settings, "ALLOW_UNAUTHENTICATED_VOICE", False):
            self.assertTrue(voice_token_is_allowed(token))

    def test_secure_mode_rejects_invalid_token(self):
        with patch.object(settings, "ALLOW_UNAUTHENTICATED_VOICE", False):
            self.assertFalse(voice_token_is_allowed("not-a-jwt"))


if __name__ == "__main__":
    unittest.main()
