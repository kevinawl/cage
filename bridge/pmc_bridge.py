"""
PMC -> browser bridge.

Polls the Planar Motor controller for every xBot's pose and streams it to
index.html as Server-Sent Events. Standard library only, apart from pmclib.

    .venv\\Scripts\\python.exe bridge\\pmc_bridge.py                 # PMC at 192.168.17.150
    .venv\\Scripts\\python.exe bridge\\pmc_bridge.py --ip 10.0.0.5
    .venv\\Scripts\\python.exe bridge\\pmc_bridge.py --mock          # no hardware

Then open http://localhost:8765 - the bridge serves index.html itself and
the page opens on the Flyway view, connected.

Read-only by default: it connects and polls, it never gains mastership and
never commands motion, so it can run next to whatever is driving the rig.

Wire format, one JSON object per event, units mm and degrees:
    {"type":"pose", "t":<unix s>, "hz":<poll rate>,
     "xbots":[{"id":1, "x":.., "y":.., "z":.., "rx":.., "ry":.., "rz":..,
               "err":[ex, ey, ez] (um, position minus reference),
               "state":"XBOT_IDLE", "kind":"M306"}, ...]}          20 Hz
    {"type":"telemetry", "t":<unix s>,
     "flyways":[{"id":1, "w":91.5, "cpu":41.7, "amp":42.2, "motor":38.0}, ...],
     "force":{"1":[fx, fy, fz, tx, ty, tz]}}   (N, N m)             2 Hz
    {"type":"receivers", "boards":[{"mac", "ip", "state", "name", "fw",
     "endpoints":[{id, name, unit, type, active, value}], "power_ep", "volt_ep", "curr_ep",
     "power", "voltage", "current", "xbot", "point", "label"}, ...],
     "points":[{"id":"P1", "name", "x", "y", "z"}, ...]}   Saguaro receiver boards
     (saguaro.py) and the cage points they can be placed at      5 Hz
    {"type":"status", "connected":bool, "source":"pmc"|"mock",
     "pmc":"PMC_FULLCTRL"|null, "master":bool|null, "error":str|null,
     "layout":{"cols":4, "rows":1, "tile":240,
               "flyways":[{"id":1, "col":0, "row":0, "sn":"9777-366"}, ...]}|null}

Receivers: POST /api/receivers/<MAC>/connect | /disconnect, and
POST /api/receivers/<MAC> {"xbot": 1|null, "point": "P1"|null, "endpoint": "P_out",
"v_endpoint": "V_out", "i_endpoint": "I_out", "label": "..."} to put a board on a mover
or at a cage point (one or the other) and say which endpoints carry W, V and A.
Assignments persist in bridge/receivers.json.

Cage points, mm, origin at the centre of the cage floor, Z up:
POST /api/points {"name", "x", "y", "z"} -> {"id": "P3"};  POST /api/points/<id>
{any of name, x, y, z};  POST /api/points/<id>/delete. Kept in bridge/cage_points.json.

Positions are the PMC's own coordinates: origin at the outer corner of the
flyway in column 0, row 0. The layout comes from the PMC's configuration
(save_pmc_config_xml_file), read once per connection.

Tracking error needs two reads (position, then reference) a few ms apart. At
speed that skew alone looks like millimetres of error, so the reference is
shifted back to the position's sample time using the reference's own velocity
between polls. At rest the correction is zero.
"""

import argparse
import json
import math
import os
import re
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from saguaro import ReceiverHub

PAGE = Path(__file__).resolve().parent.parent / "index.html"
TILE_MM = 240          # S3 flyway, 240 x 240 mm; the config XML carries no size

TELEMETRY_PERIOD_S = .5    # power, temperatures, force: 2 Hz
META_PERIOD_S = 2          # controller status is slow-moving
RETRY_S = 2                # after the PMC connection fails
RECEIVERS_PERIOD_S = .2    # receivers + points to the page: 5 Hz
SSE_KEEPALIVE_S = 5
MAX_BODY_BYTES = 4096
TEXT_MAX = 64              # endpoint names, labels, point names

M_TO_MM, M_TO_UM = 1000, 1e6


def parse_layout(xml_text):
    lay = ET.fromstring(xml_text).find("flw/layout")
    cols = [int(v.text) for v in lay.findall("mapping/col/value")]
    rows = [int(v.text) for v in lay.findall("mapping/row/value")]
    return {"cols": int(lay.findtext("mcol")), "rows": int(lay.findtext("mrow")), "tile": TILE_MM,
            "flyways": [{"id": i + 1, "col": c, "row": r} for i, (c, r) in enumerate(zip(cols, rows))]}


class Hub:
    """Latest pose, telemetry, receivers and status, handed to every connected browser."""

    def __init__(self):
        self.cond = threading.Condition()
        self.seq = 0
        self.pose = None
        self.tele = None
        self.rx = None
        self.status = {"type": "status", "connected": False, "source": None,
                       "pmc": None, "master": None, "error": "starting"}

    def _publish(self, **latest):
        with self.cond:
            for k, v in latest.items():
                setattr(self, k, v)
            self.seq += 1
            self.cond.notify_all()

    def publish_pose(self, pose): self._publish(pose=pose)
    def publish_tele(self, tele): self._publish(tele=tele)
    def publish_rx(self, rx): self._publish(rx=rx)
    def publish_status(self, **kw):
        with self.cond:                    # merge under the lock (it's reentrant)
            self._publish(status={**self.status, **kw})

    def wait(self, seq, timeout):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != seq, timeout)
            return self.seq, self.pose, self.tele, self.rx, dict(self.status)


# --------------------------------------------------------------------------- sources

class PmcSource:
    def __init__(self, args):
        # Imported here so --mock works on a machine without the library.
        from pmclib import pmc_commands as pmc
        from pmclib import pmc_types as pm
        self.pmc, self.pm, self.args = pmc, pm, args
        self.flyway_ids = []
        self._prev_ref = None              # (sample time, {id: reference}) from the last poll

    def connect(self):
        a = self.args
        ok = (self.pmc.auto_search_and_connect_to_pmc() if a.ip == "auto"
              else self.pmc.connect_to_specific_pmc(a.ip))
        if not ok:
            raise ConnectionError(f"no PMC answered at {a.ip}")
        if a.gain_mastership:
            self.pmc.gain_mastership()

    def alive(self):
        return self.pmc.check_tcp_connection()

    def meta(self):
        return {"pmc": self.pmc.get_pmc_status().name, "master": self.pmc.is_master()}

    def layout(self):
        fd, path = tempfile.mkstemp(suffix=".xml"); os.close(fd)
        try:
            self.pmc.save_pmc_config_xml_file(path)
            lay = parse_layout(Path(path).read_text(encoding="latin-1"))
        finally:
            os.remove(path)
        for f in lay["flyways"]:
            try:
                sn = self.pmc.get_flyway_serial_number(f["id"])
                f["sn"] = f"{sn.serial_number_high}-{sn.serial_number_low}"
            except Exception:
                pass
        self.flyway_ids = [f["id"] for f in lay["flyways"]]
        return lay

    def _all(self, option):
        """Every xBot's info, stamped with the middle of the call."""
        t0 = time.perf_counter()
        info = self.pmc.get_all_xbot_info(option)
        return (t0 + time.perf_counter()) / 2, {b.xbot_id: b for b in (info.all_xbot_info_list or [])}

    def _reference_at(self, xbot_id, ref, t_ref, t_pos, prev):
        """The reference shifted back from its own sample time to the position's."""
        x, y, z = ref.x_pos, ref.y_pos, ref.z_pos
        if prev and xbot_id in prev[1] and t_ref > prev[0]:
            k = (t_ref - t_pos) / (t_ref - prev[0]); q = prev[1][xbot_id]
            x, y, z = x - (x - q.x_pos) * k, y - (y - q.y_pos) * k, z - (z - q.z_pos) * k
        return x, y, z

    def read(self):
        o = self.pm.ALLXBOTSFEEDBACKOPTION
        t_pos, pos = self._all(o.POSITION)
        t_ref, ref = self._all(o.REFERENCE)
        prev, self._prev_ref = self._prev_ref, (t_ref, ref)
        out = []
        for i, b in pos.items():
            err = None
            if i in ref:
                rx, ry, rz = self._reference_at(i, ref[i], t_ref, t_pos, prev)
                err = [(b.x_pos - rx) * M_TO_UM, (b.y_pos - ry) * M_TO_UM, (b.z_pos - rz) * M_TO_UM]
            out.append({
                "id": i,
                "x": b.x_pos * M_TO_MM, "y": b.y_pos * M_TO_MM, "z": b.z_pos * M_TO_MM,
                "rx": math.degrees(b.rx_pos), "ry": math.degrees(b.ry_pos),
                "rz": math.degrees(b.rz_pos), "err": err,
                "state": b.xbot_state.name, "kind": b.xbot_type.name,
            })
        return out

    def telemetry(self, xbot_ids):
        fl = []
        for fid in self.flyway_ids:
            ph = self.pmc.get_flyway_physical_status(fid)
            fl.append({"id": fid, "w": ph.power_consumption_w, "cpu": ph.cpu_temp_c,
                       "amp": ph.amplifier_temp_c, "motor": ph.motor_temp_c})
        force = {}
        for i in xbot_ids:
            st = self.pmc.get_xbot_status(i, self.pm.FEEDBACKOPTION.FORCE)
            force[str(i)] = [float(v) for v in st.feedback_position_si]
        return {"type": "telemetry", "t": time.time(), "flyways": fl, "force": force}

    def close(self):
        try:
            if self.args.gain_mastership:
                self.pmc.release_mastership()
            self.pmc.disconnect_from_pmc()
        except Exception:
            pass


MOCK_FLYWAYS = 4
MOCK_MOVER_MM = 120        # M3-06 footprint
MOCK_IDLE_W = 10.8         # an empty flyway's draw
MOCK_CARRY_W = 80          # extra draw for the flyway carrying a mover


class MockSource:
    """Two movers over a 4 x 1 flyway (960 x 240 mm), like the bench rig."""

    def __init__(self, args):
        self.t0 = time.time()

    def connect(self): pass
    def alive(self): return True
    def meta(self): return {"pmc": "PMC_FULLCTRL", "master": False}
    def close(self): pass

    def layout(self):
        lay = parse_layout(MOCK_XML)
        for f in lay["flyways"]: f["sn"] = f"9777-{300 + f['id']}"
        return lay

    @staticmethod
    def _share(fid, bots):
        """How much of each mover's footprint lies over this flyway, summed over movers."""
        x0, half = (fid - 1) * TILE_MM, MOCK_MOVER_MM / 2
        return sum(max(0.0, min(x0 + TILE_MM, b["x"] + half) - max(x0, b["x"] - half)) / MOCK_MOVER_MM for b in bots)

    def telemetry(self, xbot_ids):
        """Idle draw ~11 W per flyway plus ~80 W for each mover it carries."""
        t = time.time() - self.t0
        bots = self.read()
        fl = []
        for fid in range(1, MOCK_FLYWAYS + 1):
            share = self._share(fid, bots)
            w = MOCK_IDLE_W + .6 * math.sin(t * .3 + fid) + MOCK_CARRY_W * share + (6 * share * abs(math.sin(t * .5)))
            fl.append({"id": fid, "w": w, "cpu": 35 + .06 * w + .4 * math.sin(t * .1 + fid),
                       "amp": 28.5 + .15 * w, "motor": 28 + .11 * w})
        force = {str(b["id"]): [-.4 + .3 * math.sin(t), -.5 + .2 * math.cos(t * .8), 15.76 + .15 * math.sin(t * 3.1),
                                .026, -.026, .015] for b in bots}
        return {"type": "telemetry", "t": time.time(), "flyways": fl, "force": force}

    def read(self):
        t = time.time() - self.t0
        return [
            {"id": 1, "x": 540 + 340 * math.sin(t * .5), "y": 120 + 50 * math.sin(t * .77 + .6),
             "z": 1.0 + .2 * math.sin(t * 2), "rx": .3 * math.sin(t * 1.3),
             "ry": .3 * math.cos(t * 1.1), "rz": 25 * math.sin(t * .4),
             "err": [14 * math.sin(t * 1.9), 9 * math.cos(t * 2.3), 1.5 * math.sin(t * 5)],
             "state": "XBOT_MOTION", "kind": "M306"},
            {"id": 2, "x": 120, "y": 120, "z": 1.0,
             "rx": 0, "ry": 0, "rz": 0, "err": [.9 * math.sin(t * 7), -1.4, .6 * math.cos(t * 6)],
             "state": "XBOT_IDLE", "kind": "M306"},
        ]


MOCK_XML = """<planarmotorconfiguration><flw><layout><mcol>4</mcol><mrow>1</mrow>
<mapping><col><value>0</value><value>1</value><value>2</value><value>3</value></col>
<row><value>0</value><value>0</value><value>0</value><value>0</value></row></mapping>
</layout></flw></planarmotorconfiguration>"""


def _connect_source(hub, args, src_name):
    src = MockSource(args) if args.mock else PmcSource(args)
    src.connect()
    try:
        layout = src.layout()
    except Exception as e:                             # page falls back to a bare grid
        print(f"[bridge] could not read layout: {e}", flush=True); layout = None
    hub.publish_status(connected=True, source=src_name, error=None, layout=layout, **src.meta())
    print(f"[bridge] connected to {src_name}", flush=True)
    return src


def _stream_source(src, hub, args, stop):
    """Poll poses at args.hz until stopped or the connection drops (raises)."""
    period = 1.0 / args.hz
    last_meta = last_tele = time.time()
    while not stop.is_set():
        t = time.time()
        bots = src.read()
        hub.publish_pose({"type": "pose", "t": t, "hz": args.hz, "xbots": bots})
        if t - last_tele >= TELEMETRY_PERIOD_S:
            hub.publish_tele(src.telemetry([b["id"] for b in bots]))
            last_tele = t
        if t - last_meta > META_PERIOD_S:
            if not src.alive():
                raise ConnectionError("TCP connection to PMC dropped")
            hub.publish_status(**src.meta())
            last_meta = t
        stop.wait(max(0.0, period - (time.time() - t)))


def poll_loop(hub, args, stop):
    src_name = "mock" if args.mock else "pmc"
    while not stop.is_set():
        src = None
        try:
            src = _connect_source(hub, args, src_name)
            _stream_source(src, hub, args, stop)
        except Exception as e:                             # keep retrying; the page shows why
            msg = f"{type(e).__name__}: {e}"
            print(f"[bridge] {msg} - retrying in {RETRY_S} s", flush=True)
            hub.publish_status(connected=False, source=src_name, error=msg)
            if src is not None:
                src.close()
            stop.wait(RETRY_S)


# --------------------------------------------------------------------------- http

def publish_receivers(hub, rxhub):
    hub.publish_rx({"type": "receivers", "boards": rxhub.snapshot(), "points": rxhub.points_list()})


def rx_loop(hub, rxhub, stop):
    while not stop.is_set():
        publish_receivers(hub, rxhub)
        stop.wait(RECEIVERS_PERIOD_S)


MAC = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
POINT_ID = re.compile(r"^P[0-9]{1,6}$")
COORD_MAX = 10000      # mm; the cage is 3000, the room is not much bigger
RECEIVER_TEXT_FIELDS = ("endpoint", "v_endpoint", "i_endpoint", "label")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_mm(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= COORD_MAX


def point_fields(body, need_xyz):
    """Validated {name, x, y, z} from a request body, or an error string."""
    kw = {}
    if "name" in body:
        if not isinstance(body["name"], str):
            return "name must be a string"
        kw["name"] = body["name"].strip()[:TEXT_MAX]
    for k in ("x", "y", "z"):
        if k not in body:
            if need_xyz:
                return f"{k} is required"
            continue
        if not _is_mm(body[k]):
            return f"{k} must be a number of mm within +/-{COORD_MAX}"
        kw[k] = round(float(body[k]), 1)
    return kw


def receiver_fields(body, points):
    """Validated update() keywords from a request body, or an error string."""
    kw = {}
    if "xbot" in body:
        if body["xbot"] is not None and not _is_int(body["xbot"]):
            return "xbot must be an integer or null"
        kw["xbot"] = body["xbot"]
    if "point" in body:
        if body["point"] is not None and body["point"] not in points:
            return "no such point"
        kw["point"] = body["point"]
    for k in RECEIVER_TEXT_FIELDS:
        if k in body:
            if body[k] is not None and not isinstance(body[k], str):
                return f"{k} must be a string or null"
            kw[k] = (body[k] or None) and body[k][:TEXT_MAX]
    return kw


def make_handler(hub, rxhub, port):
    local = {None, "null", f"http://localhost:{port}", f"http://127.0.0.1:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        # replies ------------------------------------------------------------------
        def _reply(self, code, obj=None):
            body = json.dumps(obj if obj is not None else {"ok": code < 400}).encode()
            self.send_response(code)
            if self.headers.get("Origin") in local - {None}:     # file:// pages send Origin: null
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def _error(self, code, msg):
            return self._reply(code, {"error": msg})

        def _changed(self, obj=None):
            """A change the page should see now, not on the next receivers tick."""
            publish_receivers(hub, rxhub)
            return self._reply(200, obj)

        def _body(self):
            """The request's JSON object, or None if it isn't one."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, MAX_BODY_BYTES)) or b"{}")
            except ValueError:
                return None
            return body if isinstance(body, dict) else None

        # POST -----------------------------------------------------------------
        def do_POST(self):
            # Only the page itself may drive the boards: no requests from other sites.
            if self.headers.get("Origin") not in local:
                return self._error(403, "origin not allowed")
            parts = [unquote(x) for x in self.path.split("?")[0].strip("/").split("/")]
            if parts[:2] == ["api", "points"]:
                return self._points(parts[2:])
            if len(parts) >= 3 and parts[:2] == ["api", "receivers"] and MAC.match(parts[2]):
                return self._receiver(parts[2], parts[3] if len(parts) > 3 else None)
            return self._error(404, "unknown route")

        def _receiver(self, mac, action):
            if rxhub is None:
                return self._error(503, "receivers disabled")
            if action == "connect":
                rxhub.connect(mac); return self._reply(200)
            if action == "disconnect":
                rxhub.disconnect(mac); return self._reply(200)
            if action is not None:
                return self._error(404, "unknown action")
            body = self._body()
            if body is None:
                return self._error(400, "bad json")
            kw = receiver_fields(body, rxhub.points)
            if isinstance(kw, str):
                return self._error(400, kw)
            rxhub.update(mac, **kw)
            return self._changed()

        def _points(self, rest):
            if rxhub is None:
                return self._error(503, "receivers disabled")
            if len(rest) > 2 or (rest and not POINT_ID.match(rest[0])):
                return self._error(404, "unknown route")
            if not rest:
                return self._add_point()
            if len(rest) == 1:
                return self._edit_point(rest[0])
            if rest[1] != "delete":
                return self._error(404, "unknown action")
            return self._changed() if rxhub.remove_point(rest[0]) else self._error(404, "no such point")

        def _add_point(self):
            body = self._body()
            if body is None:
                return self._error(400, "bad json")
            kw = point_fields(body, need_xyz=True)
            if isinstance(kw, str):
                return self._error(400, kw)
            pid = rxhub.add_point(kw.get("name"), kw["x"], kw["y"], kw["z"])
            return self._changed({"ok": True, "id": pid})

        def _edit_point(self, pid):
            body = self._body()
            if body is None:
                return self._error(400, "bad json")
            kw = point_fields(body, need_xyz=False)
            if isinstance(kw, str):
                return self._error(400, kw)
            return self._changed() if rxhub.edit_point(pid, **kw) else self._error(404, "no such point")

        # GET ------------------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":                                 # open http://localhost:8765 -> live view
                self.send_response(302); self.send_header("Location", "/index.html?bridge=same&view=fly")
                self.end_headers(); return
            if path == "/index.html":
                return self._page()
            if path == "/events":
                return self._events()
            self.send_response(404); self.end_headers()

        def _page(self):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")   # always the file on disk
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")   # index.html opens from file://
            self.end_headers()
            try:
                self._stream()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _stream(self):
            """Each change once; pose and telemetry only while the PMC is connected."""
            seq, sent_status, sent_tele, sent_rx = -1, None, None, None
            while True:
                seq, pose, tele, rx, status = hub.wait(seq, SSE_KEEPALIVE_S)
                connected = status.get("connected")
                if status != sent_status:
                    self._send(status); sent_status = status
                if rx is not None and rx is not sent_rx:
                    self._send(rx); sent_rx = rx
                if tele is not None and tele is not sent_tele and connected:
                    self._send(tele); sent_tele = tele
                if pose is not None and connected:
                    self._send(pose)
                else:
                    self.wfile.write(b": keepalive\n\n"); self.wfile.flush()

        def _send(self, obj):
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()

    return Handler


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="192.168.17.150", help='PMC address, or "auto" to search')
    ap.add_argument("--port", type=int, default=8765, help="HTTP port the page connects to")
    ap.add_argument("--hz", type=float, default=20, help="poll rate")
    ap.add_argument("--gain-mastership", action="store_true",
                    help="take mastership on connect (only if reads fail without it)")
    ap.add_argument("--mock", action="store_true", help="fake movers, no hardware")
    ap.add_argument("--no-receivers", action="store_true", help="don't listen for Saguaro receiver boards")
    ap.add_argument("--receivers-file", default=None, metavar="PATH",
                    help="where receiver assignments are saved (default bridge/receivers.json)")
    return ap.parse_args(argv)


def start_receivers(hub, args, stop):
    """The Saguaro side, unless --no-receivers: discovery, assigned boards, the 5 Hz feed."""
    if args.no_receivers:
        return None
    store = {"store": args.receivers_file} if args.receivers_file else {}
    rxhub = ReceiverHub(log=lambda m: print(m, flush=True), **store)
    rxhub.start()
    threading.Thread(target=rx_loop, args=(hub, rxhub, stop), daemon=True).start()
    return rxhub


def main():
    args = parse_args()
    hub, stop = Hub(), threading.Event()
    threading.Thread(target=poll_loop, args=(hub, args, stop), daemon=True).start()
    rxhub = start_receivers(hub, args, stop)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(hub, rxhub, args.port))
    srv.daemon_threads = True
    print(f"[bridge] open http://localhost:{args.port}  "
          f"({'mock' if args.mock else 'PMC ' + args.ip}, {args.hz:g} Hz) - Ctrl+C to stop", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set(); srv.server_close()


if __name__ == "__main__":
    main()
