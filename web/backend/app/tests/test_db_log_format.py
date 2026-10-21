import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPushLogFormat(unittest.TestCase):
    def test_event_kept_clean_payload_separate(self):
        import db
        was_enabled = db._enabled
        db._enabled = True
        try:
            q = db._log_queue
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
            db.push_log(42, "info", "charging_progress", {"battery": 80.5, "remaining_sec": 9})
            _, _, _, event, payload_json = q.get_nowait()
            self.assertEqual(event, "charging_progress")
            self.assertIn('"remaining_sec": 9', payload_json)
            self.assertNotIn("charging_progress", payload_json)
        finally:
            db._enabled = was_enabled

    def test_loki_line_still_combined(self):
        import db
        q = db._loki_queue
        while not q.empty():
            try:
                q.get_nowait()
            except Exception:
                break
        db.push_log(7, "info", "charging_start", {"battery": 12.0})
        _, _, _, line = q.get_nowait()
        self.assertTrue(line.startswith("charging_start "))


if __name__ == '__main__':
    unittest.main()