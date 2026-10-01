"""
The bridge's HTTP side: the page, the event stream, and the JSON API.

GET  /                      -> redirect to the live page
GET  /<path>                -> files under web/: the page, its scripts and styles
GET  /events                -> Server-Sent Events, one JSON object per event

POST /api/receivers/<MAC>/connect | /disconnect
POST /api/receivers/<MAC>   {"xbot": 1|null, "point": "P1"|null, "endpoint": "P_out",
                             "v_endpoint": "V_out", "i_endpoint": "I_out", "label": "..."}
     puts a board on a mover or at a cage point (one or the other) and says which
     endpoints carry W, V and A.
POST /api/points            {"name", "x", "y", "z"} -> {"id": "P3"}
POST /api/points/<id>       {any of name, x, y, z}
POST /api/points/<id>/delete

POSTs are accepted only from the page itself, as the bridge served it (an Origin of
http://localhost:<port> or http://127.0.0.1:<port>),
sent as text/plain so the browser makes no CORS preflight.
"""

import json
import math
import mimetypes
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
SSE_KEEPALIVE_S = 5
MAX_BODY_BYTES = 4096
TEXT_MAX = 64              # endpoint names, labels, point names
COORD_MAX_MM = 10000       # the cage is 3000, the room is not much bigger

MAC = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
POINT_ID = re.compile(r"^P[0-9]{1,6}$")
RECEIVER_TEXT_FIELDS = ("endpoint", "v_endpoint", "i_endpoint", "label")
STATIC_TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml"}


# --------------------------------------------------------------------------- validation

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_mm(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and abs(value) <= COORD_MAX_MM)


def point_fields(body, need_xyz):
    """Validated {name, x, y, z} from a request body, or an error string."""
    fields = {}
    if "name" in body:
        if not isinstance(body["name"], str):
            return "name must be a string"
        fields["name"] = body["name"].strip()[:TEXT_MAX]
    for axis in ("x", "y", "z"):
        if axis not in body:
            if need_xyz:
                return f"{axis} is required"
            continue
        if not _is_mm(body[axis]):
            return f"{axis} must be a number of mm within +/-{COORD_MAX_MM}"
        fields[axis] = round(float(body[axis]), 1)
    return fields


def receiver_fields(body, points):
    """Validated ReceiverHub.update() keywords from a request body, or an error string."""
    fields = {}
    if "xbot" in body:
        if body["xbot"] is not None and not _is_int(body["xbot"]):
            return "xbot must be an integer or null"
        fields["xbot"] = body["xbot"]
    if "point" in body:
        if body["point"] is not None and body["point"] not in points:
            return "no such point"
        fields["point"] = body["point"]
    for key in RECEIVER_TEXT_FIELDS:
        if key in body:
            if body[key] is not None and not isinstance(body[key], str):
                return f"{key} must be a string or null"
            fields[key] = body[key][:TEXT_MAX] if body[key] else None
    return fields


def static_file(path):
    """The file under WEB_ROOT a request path names, or None (missing, or outside it).

    Anything that could leave web/ is refused before touching the file system:
    resolving a Windows UNC path (two backslashes, a host, a share) alone would connect to that host."""
    if "\\" in path or ":" in path or ".." in path.split("/"):
        return None
    target = (WEB_ROOT / path.lstrip("/")).resolve()
    if WEB_ROOT not in target.parents or not target.is_file():
        return None
    return target


# --------------------------------------------------------------------------- handler

def make_handler(events, receivers, port):
    """A request handler bound to the event hub and the receiver hub (None: receivers disabled)."""
    local_origins = {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        # replies ------------------------------------------------------------------
        def _reply(self, code, obj=None):
            body = json.dumps(obj if obj is not None else {"ok": code < 400}).encode()
            self.send_response(code)
            origin = self.headers.get("Origin")
            if origin in local_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code, message):
            return self._reply(code, {"error": message})

        def _changed(self, obj=None):
            """A change the page should see now, not on the next receivers tick."""
            events.publish_receivers(receivers)
            return self._reply(200, obj)

        def _body(self):
            """The request's JSON object, or None if it isn't one."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(length, MAX_BODY_BYTES)) or b"{}")
            except ValueError:
                return None
            return body if isinstance(body, dict) else None

        # POST -----------------------------------------------------------------
        def do_POST(self):
            # Only the page itself may drive the boards: no requests from other sites.
            if self.headers.get("Origin") not in local_origins:
                return self._error(403, "origin not allowed")
            parts = [unquote(p) for p in self.path.split("?")[0].strip("/").split("/")]
            if parts[:2] == ["api", "points"]:
                return self._points(parts[2:])
            if len(parts) >= 3 and parts[:2] == ["api", "receivers"] and MAC.match(parts[2]):
                return self._receiver(parts[2], parts[3] if len(parts) > 3 else None)
            return self._error(404, "unknown route")

        def _receiver(self, mac, action):
            if receivers is None:
                return self._error(503, "receivers disabled")
            if action == "connect":
                receivers.connect(mac)
                return self._reply(200)
            if action == "disconnect":
                receivers.disconnect(mac)
                return self._reply(200)
            if action is not None:
                return self._error(404, "unknown action")
            body = self._body()
            if body is None:
                return self._error(400, "bad json")
            fields = receiver_fields(body, receivers.points)
            if isinstance(fields, str):
                return self._error(400, fields)
            receivers.update(mac, **fields)
            return self._changed()

        def _points(self, rest):
            if receivers is None:
                return self._error(503, "receivers disabled")
            if len(rest) > 2 or (rest and not POINT_ID.match(rest[0])):
                return self._error(404, "unknown route")
            if not rest:
                return self._add_point()
            if len(rest) == 1:
                return self._edit_point(rest[0])
            if rest[1] != "delete":
                return self._error(404, "unknown action")
            return self._changed() if receivers.remove_point(rest[0]) else self._error(404, "no such point")

        def _add_point(self):
            body = self._body()
            if body is None:
                return self._error(400, "bad json")
            fields = point_fields(body, need_xyz=True)
            if isinstance(fields, str):
                return self._error(400, fields)
            pid = receivers.points.add(fields.get("name"), fields["x"], fields["y"], fields["z"])
            return self._changed({"ok": True, "id": pid})

        def _edit_point(self, pid):
            body = self._body()
            if body is None:
                return self._error(400, "bad json")
            fields = point_fields(body, need_xyz=False)
            if isinstance(fields, str):
                return self._error(400, fields)
            return self._changed() if receivers.points.edit(pid, **fields) else self._error(404, "no such point")

        # GET ------------------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":                                 # open http://localhost:8765 -> live view
                self.send_response(302)
                self.send_header("Location", "/index.html?bridge=same&view=fly")
                self.end_headers()
                return
            if path == "/events":
                return self._events()
            target = static_file(path)
            if target is None:
                self.send_response(404)
                self.end_headers()
                return
            self._file(target)

        def _file(self, target):
            body = target.read_bytes()
            content_type = STATIC_TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0]
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")   # always the files on disk
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self._stream()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _stream(self):
            """Each change once; pose and telemetry only while the PMC is connected."""
            seq, sent_status, sent_tele, sent_rx = -1, None, None, None
            while True:
                seq, pose, tele, rx, status = events.wait(seq, SSE_KEEPALIVE_S)
                connected = status.get("connected")
                if status != sent_status:
                    self._send(status)
                    sent_status = status
                if rx is not None and rx is not sent_rx:
                    self._send(rx)
                    sent_rx = rx
                if tele is not None and tele is not sent_tele and connected:
                    self._send(tele)
                    sent_tele = tele
                if pose is not None and connected:
                    self._send(pose)
                else:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()

        def _send(self, obj):
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()

    return Handler
