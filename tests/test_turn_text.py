import unittest

from app import _turn_text as turn_text


class InterruptionTests(unittest.TestCase):
    def test_noise_and_backchannels_are_not_interruptions(self):
        for text in ["", ".", "Okay.", "mhm", "Yeah, yeah.", "Ja, genau.", "uh-huh"]:
            self.assertFalse(turn_text.is_interruption(text), text)

    def test_real_speech_is_an_interruption(self):
        for text in ["Stop.", "Okay, but what about tomorrow?", "Nein, warte mal."]:
            self.assertTrue(turn_text.is_interruption(text), text)


if __name__ == "__main__":
    unittest.main()
