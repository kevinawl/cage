import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _bridge_path  # noqa: F401
from saguaro import READING_STALE_S, CagePoints, ReceiverHub

MAC = "02:00:00:5A:67:01"


class FakeBoard:
    """The bits of saguaro.Board the hub reads."""

    def __init__(self, mac=MAC, endpoints=None, state="streaming"):
        self.mac, self.state, self.error, self.name, self.fw = mac, state, None, "RX", "1.0"
        self.endpoints = endpoints or {}
        self.activated = []

    @property
    def streaming(self):
        return self.state == "streaming"

    def activate(self, sensor_id):
        self.activated.append(sensor_id)


def endpoint(name, unit="", kind="float", active=True, value=None, t=0.0):
    return {"name": name, "unit": unit, "type": kind, "active": active, "value": value, "t": t}


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()


class CagePointsTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.points = CagePoints(self.dir / "cage_points.json")

    def test_ids_count_up_and_sort_numerically(self):
        ids = [self.points.add(None, 0, 0, i) for i in range(11)]
        self.assertEqual(ids[0], "P1")
        self.assertEqual([p["id"] for p in self.points.as_list()][-2:], ["P10", "P11"])

    def test_unnamed_point_is_named_after_its_id(self):
        pid = self.points.add("", 1, 2, 3)
        self.assertEqual(self.points.as_list()[0]["name"], pid)
        self.points.edit(pid, name="")
        self.assertEqual(self.points.as_list()[0]["name"], pid)

    def test_persists(self):
        pid = self.points.add("TX", -1500, 0, 1500)
        self.points.edit(pid, z=1200.0)
        reloaded = CagePoints(self.dir / "cage_points.json")
        self.assertEqual(reloaded.as_list(), [{"id": pid, "name": "TX", "x": -1500, "y": 0, "z": 1200.0}])

    def test_edit_and_remove_unknown(self):
        self.assertFalse(self.points.edit("P9", x=1))
        self.assertFalse(self.points.remove("P9"))


class ReceiverHubTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.hub = ReceiverHub(log=lambda m: None, store=self.dir / "receivers.json")
        connect = mock.patch.object(self.hub, "connect")   # no board threads, no sockets
        self.connect = connect.start()
        self.addCleanup(connect.stop)

    def saved(self):
        return json.loads((self.dir / "receivers.json").read_text())

    def test_a_board_is_on_an_xbot_or_at_a_point_not_both(self):
        self.hub.update(MAC, point="P1")
        self.hub.update(MAC, xbot=2)
        self.assertEqual(self.saved()[MAC], {"xbot": 2, "point": None})
        self.hub.update(MAC, point="P1")
        self.assertEqual(self.saved()[MAC], {"xbot": None, "point": "P1"})
        self.connect.assert_called_with(MAC)

    def test_unplacing_does_not_connect(self):
        self.hub.update(MAC, point=None, label="RX A")
        self.connect.assert_not_called()
        self.assertEqual(self.saved()[MAC]["label"], "RX A")

    def test_removing_a_point_unplaces_its_boards(self):
        pid = self.hub.points.add("P", 0, 0, 0)
        self.hub.update(MAC, point=pid, label="keep me")
        self.assertTrue(self.hub.remove_point(pid))
        self.assertEqual(self.saved()[MAC], {"xbot": None, "point": None, "label": "keep me"})
        self.assertFalse(self.hub.remove_point(pid))

    def test_endpoints_guessed_by_unit_then_by_name(self):
        board = FakeBoard(endpoints={0: endpoint("Vbus", unit="V"), 1: endpoint("I_out"),
                                     2: endpoint("P_out", active=False), 3: endpoint("flag", kind="bool")})
        self.hub.on_endpoints(board)
        self.assertEqual(self.saved()[MAC], {"endpoint": "P_out", "v_endpoint": "Vbus", "i_endpoint": "I_out"})
        self.assertEqual(board.activated, [2])             # P_out was off: switched on

    def test_guess_never_overrides_a_choice(self):
        self.hub.update(MAC, endpoint="Mine")
        self.hub.on_endpoints(FakeBoard(endpoints={0: endpoint("P_out", unit="W")}))
        self.assertEqual(self.saved()[MAC]["endpoint"], "Mine")

    def test_snapshot_lists_only_reachable_boards_with_fresh_readings(self):
        now = time.time()
        self.hub.on_announce(f"5000-SAGUARO-{MAC}".encode(), "10.0.0.7")
        self.hub.seen["02:00:00:5A:67:09"] = {"ip": "10.0.0.9", "port": 1, "t": now - 60}    # gone quiet
        self.hub.boards[MAC] = FakeBoard(endpoints={
            0: endpoint("P_out", value=1.25, t=now), 1: endpoint("V_out", value=12.0, t=now - READING_STALE_S - 1)})
        self.hub.update(MAC, point="P1", endpoint="P_out", v_endpoint="V_out")
        boards = self.hub.snapshot()
        self.assertEqual([b["mac"] for b in boards], [MAC])
        self.assertEqual((boards[0]["ip"], boards[0]["port"], boards[0]["point"]), ("10.0.0.7", 5000, "P1"))
        self.assertEqual(boards[0]["power"], 1.25)
        self.assertIsNone(boards[0]["voltage"])             # stale
        self.assertIsNone(boards[0]["current"])             # not assigned

    def test_no_readings_unless_streaming(self):
        self.hub.on_announce(f"5000-SAGUARO-{MAC}".encode(), "10.0.0.7")
        self.hub.boards[MAC] = FakeBoard(state="handshake", endpoints={0: endpoint("P_out", value=1.0, t=time.time())})
        self.hub.update(MAC, endpoint="P_out")
        self.assertIsNone(self.hub.snapshot()[0]["power"])


if __name__ == "__main__":
    unittest.main()
