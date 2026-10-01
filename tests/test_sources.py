import threading
import time
import unittest
from types import SimpleNamespace

import _bridge_path  # noqa: F401
from events import EventHub
from pmc_sources import MOCK_XML, MockSource, PmcSource, parse_layout


class Layout(unittest.TestCase):
    def test_parse(self):
        layout = parse_layout(MOCK_XML)
        self.assertEqual((layout["cols"], layout["rows"], layout["tile"]), (4, 1, 240))
        self.assertEqual(layout["flyways"][3], {"id": 4, "col": 3, "row": 0})


class Mock(unittest.TestCase):
    def test_shapes_match_the_wire_format(self):
        source = MockSource()
        xbots = source.read()
        self.assertEqual({"id", "x", "y", "z", "rx", "ry", "rz", "err", "state", "kind"}, set(xbots[0]))
        tele = source.telemetry([b["id"] for b in xbots])
        self.assertEqual(tele["type"], "telemetry")
        self.assertEqual(len(tele["flyways"]), 4)
        self.assertEqual(set(tele["force"]), {"1", "2"})

    def test_a_mover_adds_its_draw_to_the_flyway_under_it(self):
        flyways = MockSource().telemetry([])["flyways"]
        self.assertGreater(flyways[0]["w"], 50)             # xBot 2 sits at x = 120 mm, on flyway 1
        self.assertGreater(flyways[0]["w"], min(f["w"] for f in flyways) + 50)


class ReferenceSkew(unittest.TestCase):
    def test_reference_is_shifted_back_to_the_position_time(self):
        pose = lambda x: SimpleNamespace(x_pos=x, y_pos=0.0, z_pos=0.0)
        prev = (0.0, {1: pose(0.0)})                       # 1 m/s along X
        x, _, _ = PmcSource._reference_at(1, pose(1.0), t_ref=1.0, t_pos=0.99, prev=prev)
        self.assertAlmostEqual(x, 0.99)

    def test_no_history_no_shift(self):
        ref = SimpleNamespace(x_pos=1.0, y_pos=2.0, z_pos=3.0)
        self.assertEqual(PmcSource._reference_at(1, ref, 1.0, 0.9, None), (1.0, 2.0, 3.0))


class Events(unittest.TestCase):
    def test_wait_wakes_on_publish_and_status_merges(self):
        events = EventHub()
        seq = events.wait(-1, 0)[0]
        threading.Timer(.05, lambda: events.publish_status(connected=True)).start()
        started = time.time()
        new_seq, _, _, _, status = events.wait(seq, 2)
        self.assertLess(time.time() - started, 1)
        self.assertNotEqual(new_seq, seq)
        self.assertTrue(status["connected"])
        self.assertEqual(status["error"], "starting")       # untouched keys survive the merge


if __name__ == "__main__":
    unittest.main()
