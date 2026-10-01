import unittest

import _bridge_path  # noqa: F401
from saguaro_protocol import DELIM, command, decode_packet, encode_packet, parse_announce, split_frames

ENDPOINTS = [
    {"sensor_id": 0, "name": "V_out", "type": "float", "active": True, "name_type": "V"},
    {"sensor_id": 1, "name": "P_out", "type": "float", "active": False, "name_type": "W"},
    {"sensor_id": 2, "name": "link_ok", "type": "bool", "active": True, "name_type": ""},
]


class RoundTrip(unittest.TestCase):
    def test_mcu_name(self):
        packet = decode_packet(encode_packet(42, "mcu_name", {"device_name": "RX-01", "firmware_version": "2.4.1"}))
        self.assertEqual(packet["timestamp_ms"], 42)
        self.assertEqual(packet["mcu_name"], {"device_name": "RX-01", "firmware_version": "2.4.1"})

    def test_endpoint_list_restores_proto3_defaults(self):
        packet = decode_packet(encode_packet(1, "ep_man_list", ENDPOINTS))
        endpoints = packet["ep_man_list"]["endpoints"]
        self.assertEqual([e["name"] for e in endpoints], ["V_out", "P_out", "link_ok"])
        self.assertFalse(endpoints[1]["active"])           # omitted on the wire, filled back in
        self.assertEqual(endpoints[0]["sensor_id"], 0)     # likewise
        self.assertEqual([e["type"] for e in endpoints], [1, 1, 3])

    def test_telemetry_keeps_each_value_type(self):
        readings = [{"sensor_id": 0, "value": 12.5}, {"sensor_id": 1, "value": -3},
                    {"sensor_id": 2, "value": True}, {"sensor_id": 3, "value": "ok"}]
        data = decode_packet(encode_packet(7, "telemetry", readings))["telemetry"]["data"]
        self.assertAlmostEqual(data[0]["value"], 12.5, places=5)
        self.assertEqual(data[1]["value"], -3)              # int32, sign-extended on the wire
        self.assertIs(data[2]["value"], True)
        self.assertEqual(data[3]["value"], "ok")

    def test_ack(self):
        self.assertIn("ack", decode_packet(encode_packet(0, "ack", {"command_id": 5})))

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            encode_packet(0, "nope", {})


class Framing(unittest.TestCase):
    def test_console_text_is_not_a_packet(self):
        self.assertIsNone(decode_packet(b"Saguaro boot ok\r\n"))

    def test_truncated_frame_is_not_a_packet(self):
        frame = encode_packet(1, "mcu_name", {"device_name": "RX-01", "firmware_version": "1"})
        self.assertIsNone(decode_packet(frame[:-3]))

    def test_split_keeps_the_partial_frame(self):
        one, two = encode_packet(1, "ack", {}), encode_packet(2, "ack", {})
        frames, leftover = split_frames(DELIM + one + DELIM + two[:3])
        self.assertEqual(frames, [one])
        self.assertEqual(leftover, two[:3])

    def test_command(self):
        self.assertEqual(command("s 1"), b"\rs 1\r")


class Announce(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_announce(b"62806-SAGUARO-02:00:00:5A:67:01\x00"), ("02:00:00:5A:67:01", 62806))

    def test_invalid(self):
        for data in (b"", b"hello", b"80-SAGUARO-02:00:00:5a:67:01", b"x-SAGUARO-02:00:00:5A:67:01"):
            self.assertIsNone(parse_announce(data), data)


if __name__ == "__main__":
    unittest.main()
