"""The HTTP routes, against a real server on a random port. No real boards, no PMC."""

import http.client
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import _bridge_path  # noqa: F401
from events import EventHub
from http_api import point_fields, receiver_fields, make_handler
from saguaro import ReceiverHub

MAC = "02:00:00:5A:67:01"


class Validation(unittest.TestCase):
    def test_point_fields(self):
        self.assertEqual(point_fields({"name": "  TX ", "x": 1, "y": -2.25, "z": 3}, True),
                         {"name": "TX", "x": 1.0, "y": -2.2, "z": 3.0})
        self.assertEqual(point_fields({"x": 5}, False), {"x": 5.0})
        self.assertEqual(point_fields({"x": 1, "y": 2}, True), "z is required")
        for bad in (True, "1", float("nan"), 10001):
            self.assertIsInstance(point_fields({"x": bad}, False), str, bad)
        self.assertIsInstance(point_fields({"name": 3}, False), str)

    def test_receiver_fields(self):
        points = {"P1"}
        self.assertEqual(receiver_fields({"xbot": 1, "label": ""}, points), {"xbot": 1, "label": None})
        self.assertEqual(receiver_fields({"point": "P1"}, points), {"point": "P1"})
        self.assertEqual(receiver_fields({"point": "P2"}, points), "no such point")
        self.assertIsInstance(receiver_fields({"xbot": True}, points), str)
        self.assertIsInstance(receiver_fields({"endpoint": 3}, points), str)
        self.assertEqual(len(receiver_fields({"label": "x" * 100}, points)["label"]), 64)


class Server(unittest.TestCase):
    receivers_enabled = True

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.events = EventHub()
        self.receivers = None
        if self.receivers_enabled:
            self.receivers = ReceiverHub(log=lambda m: None, store=Path(self._dir.name) / "receivers.json")
            patcher = mock.patch.object(self.receivers, "connect")
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.server.RequestHandlerClass = make_handler(self.events, self.receivers, self.port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://localhost:{self.port}"

    def request(self, method, path, body=None, origin=...):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "text/plain"}
        if origin is ...:
            origin = self.origin
        if origin is not None:
            headers["Origin"] = origin
        data = body if isinstance(body, bytes) else None if body is None else json.dumps(body).encode()
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        conn.close()
        return response, payload


class Pages(Server):
    def test_root_redirects_to_the_live_view(self):
        response, _ = self.request("GET", "/")
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"), "/index.html?bridge=same&view=fly")

    def test_page_and_its_modules(self):
        response, body = self.request("GET", "/index.html")
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("text/html"))
        self.assertIn(b'<script type="module" src="js/main.js">', body)
        for path, kind in (("/js/main.js", "text/javascript"), ("/styles.css", "text/css")):
            response, _ = self.request("GET", path)
            self.assertEqual((response.status, response.getheader("Content-Type").split(";")[0]), (200, kind), path)

    def test_nothing_outside_web_is_served(self):
        for path in ("/../bridge/pmc_bridge.py", "/%2e%2e/README.md", "/nope.js", "/js",
                     r"/..\bridge\pmc_bridge.py", "/C:/Windows/win.ini", r"/\\localhost\c$\x"):
            self.assertEqual(self.request("GET", path)[0].status, 404, path)

    def test_events_start_with_the_status(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/events")
        response = conn.getresponse()
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
        line = response.fp.readline()
        conn.close()
        self.assertEqual(json.loads(line[len(b"data: "):])["type"], "status")


class Api(Server):
    def test_other_sites_may_not_post(self):
        response, _ = self.request("POST", "/api/points", {"x": 0, "y": 0, "z": 0}, origin="https://example.com")
        self.assertEqual(response.status, 403)

    def test_opaque_origins_may_not_post(self):
        # Origin: null is what a sandboxed iframe on any website sends.
        for origin in ("null", None):
            response, _ = self.request("POST", "/api/points", {"x": 0, "y": 0, "z": 0}, origin=origin)
            self.assertEqual(response.status, 403, origin)

    def test_point_lifecycle(self):
        response, body = self.request("POST", "/api/points", {"name": "TX", "x": -1500, "y": 0, "z": 1500})
        self.assertEqual(response.status, 200)
        pid = json.loads(body)["id"]
        self.assertEqual(self.request("POST", f"/api/points/{pid}", {"z": 1200})[0].status, 200)
        self.assertEqual(self.receivers.points.as_list()[0]["z"], 1200.0)
        self.assertEqual(self.events.rx["points"][0]["z"], 1200.0)          # pushed to the page at once
        self.assertEqual(self.request("POST", f"/api/points/{pid}/delete")[0].status, 200)
        self.assertEqual(self.request("POST", f"/api/points/{pid}/delete")[0].status, 404)

    def test_bad_requests(self):
        self.assertEqual(self.request("POST", "/api/points", b"{not json")[0].status, 400)
        self.assertEqual(self.request("POST", "/api/points", {"x": 1})[0].status, 400)
        self.assertEqual(self.request("POST", "/api/points/X1")[0].status, 404)
        self.assertEqual(self.request("POST", "/api/receivers/not-a-mac/connect")[0].status, 404)
        self.assertEqual(self.request("POST", f"/api/receivers/{MAC}", {"point": "P9"})[0].status, 400)
        self.assertEqual(self.request("POST", f"/api/receivers/{MAC}/explode")[0].status, 404)

    def test_assign_a_receiver(self):
        pid = self.receivers.points.add("P", 0, 0, 0)
        response, _ = self.request("POST", f"/api/receivers/{MAC}", {"point": pid, "endpoint": "P_out"})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.receivers.assign[MAC], {"point": pid, "xbot": None, "endpoint": "P_out"})
        self.assertEqual(self.request("POST", f"/api/receivers/{MAC}/connect")[0].status, 200)


class ReceiversDisabled(Server):
    receivers_enabled = False

    def test_api_says_so(self):
        response, body = self.request("POST", "/api/points", {"x": 0, "y": 0, "z": 0})
        self.assertEqual((response.status, json.loads(body)["error"]), (503, "receivers disabled"))

    def test_unknown_routes_are_still_404(self):
        self.assertEqual(self.request("POST", "/api/foo")[0].status, 404)


if __name__ == "__main__":
    unittest.main()
