import unittest

from inca_voice.turns import TurnManager, TurnSettings


class TurnManagerTests(unittest.TestCase):
    def test_merges_short_acknowledgement_with_followup(self):
        manager = TurnManager(TurnSettings(min_words=2, min_chars=8, settle_ms=700, max_wait_ms=1800))

        self.assertEqual(manager.add_fragment("Ja,", now_ms=0, metadata={"reason": "vad"}), [])
        self.assertEqual(manager.drain_ready(now_ms=500), [])

        self.assertEqual(
            manager.add_fragment("ich hatte einen Unfall", now_ms=600, metadata={"reason": "end_text"}),
            [],
        )

        turns = manager.drain_ready(now_ms=1300)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].text, "Ja, ich hatte einen Unfall")
        self.assertEqual(turns[0].metadata["fragment_count"], 2)

    def test_drops_filler_only_fragment(self):
        manager = TurnManager(TurnSettings(min_words=2, min_chars=8, settle_ms=700, max_wait_ms=1800))

        manager.add_fragment("mm-hmm", now_ms=0, metadata={"reason": "vad"})

        self.assertEqual(manager.drain_ready(now_ms=2000), [])
        self.assertEqual(manager.pending_text, "")

    def test_commits_greeting_even_if_short(self):
        manager = TurnManager(TurnSettings(min_words=2, min_chars=8, settle_ms=700, max_wait_ms=1800))

        manager.add_fragment("Hallo.", now_ms=0, metadata={"reason": "vad"})

        turns = manager.drain_ready(now_ms=700)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].text, "Hallo.")


if __name__ == "__main__":
    unittest.main()
