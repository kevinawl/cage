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
    {"type":"status", "connected":bool, "source":"pmc"|"mock",
     "pmc":"PMC_FULLCTRL"|null, "master":bool|null, "error":str|null,
     "layout":{"cols":4, "rows":1, "tile":240,
               "flyways":[{"id":1, "col":0, "row":0, "sn":"9777-366"}, ...]}|null}

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
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "index.html"
TILE_MM = 240          # S3 flyway, 240 x 240 mm; the config XML carries no size


def parse_layout(xml_text):
    lay = ET.fromstring(xml_text).find("flw/layout")
    cols = [int(v.text) for v in lay.findall("mapping/col/value")]
    rows = [int(v.text) for v in lay.findall("mapping/row/value")]
    return {"cols": int(lay.findtext("mcol")), "rows": int(lay.findtext("mrow")), "tile": TILE_MM,
            "flyways": [{"id": i + 1, "col": c, "row": r} for i, (c, r) in enumerate(zip(cols, rows))]}


class Hub:
    """Latest pose + status, handed to every connected browser."""

    def __init__(self):
        self.cond = threading.Condition()
        self.seq = 0
        self.pose = None
        self.tele = None
        self.status = {"type": "status", "connected": False, "source": None,
                       "pmc": None, "master": None, "error": "starting"}

    def publish_pose(self, pose):
        with self.cond:
            self.pose = pose
            self.seq += 1
            self.cond.notify_all()

    def publish_tele(self, tele):
        with self.cond:
            self.tele = tele
            self.seq += 1
            self.cond.notify_all()

    def publish_status(self, **kw):
        with self.cond:
            self.status = {**self.status, **kw}
            self.seq += 1
            self.cond.notify_all()

    def wait(self, seq, timeout):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != seq, timeout)
            return self.seq, self.pose, self.tele, dict(self.status)


# --------------------------------------------------------------------------- sources

class PmcSource:
    def __init__(self, args):
        # Imported here so --mock works on a machine without the library.
        from pmclib import pmc_commands as pmc
        from pmclib import pmc_types as pm
        self.pmc, self.pm, self.args = pmc, pm, args

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
        t0 = time.perf_counter()
        info = self.pmc.get_all_xbot_info(option)
        return (t0 + time.perf_counter()) / 2, {b.xbot_id: b for b in (info.all_xbot_info_list or [])}

    def read(self):
        o = self.pm.ALLXBOTSFEEDBACKOPTION
        tp, pos = self._all(o.POSITION)
        tr, ref = self._all(o.REFERENCE)
        prev, self._prev_ref = getattr(self, "_prev_ref", None), (tr, ref)
        out = []
        for i, b in pos.items():
            err = None
            r = ref.get(i)
            if r is not None:
                rx, ry, rz = r.x_pos, r.y_pos, r.z_pos
                if prev and i in prev[1] and tr > prev[0]:          # shift ref back to tp
                    k = (tr - tp) / (tr - prev[0]); q = prev[1][i]
                    rx, ry, rz = rx - (rx - q.x_pos) * k, ry - (ry - q.y_pos) * k, rz - (rz - q.z_pos) * k
                err = [(b.x_pos - rx) * 1e6, (b.y_pos - ry) * 1e6, (b.z_pos - rz) * 1e6]
            out.append({
                "id": i,
                "x": b.x_pos * 1000, "y": b.y_pos * 1000, "z": b.z_pos * 1000,
                "rx": math.degrees(b.rx_pos), "ry": math.degrees(b.ry_pos),
                "rz": math.degrees(b.rz_pos), "err": err,
                "state": b.xbot_state.name, "kind": b.xbot_type.name,
            })
        return out

    def telemetry(self, xbot_ids):
        fl = []
        for fid in getattr(self, "flyway_ids", []):
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


class MockSource:
    """Two movers over a 4 x 1 flyway (960 x 240 mm), like the bench rig."""

    def __init__(self, args):
        self.t0 = time.time()

    def connect(self): pass
    def alive(self): return True
    def meta(self): return {"pmc": "PMC_FULLCTRL", "master": False}
    def layout(self):
        lay = parse_layout(MOCK_XML)
        for f in lay["flyways"]: f["sn"] = f"9777-{300 + f['id']}"
        return lay

    def telemetry(self, xbot_ids):
        """Idle draw ~11 W per flyway plus ~80 W for each mover it carries."""
        t = time.time() - self.t0
        bots = self.read()
        fl = []
        for fid in range(1, 5):
            x0 = (fid - 1) * 240
            share = sum(max(0.0, min(x0 + 240, b["x"] + 60) - max(x0, b["x"] - 60)) / 120 for b in bots)
            w = 10.8 + .6 * math.sin(t * .3 + fid) + 80 * share + (6 * share * abs(math.sin(t * .5)))
            fl.append({"id": fid, "w": w, "cpu": 35 + .06 * w + .4 * math.sin(t * .1 + fid),
                       "amp": 28.5 + .15 * w, "motor": 28 + .11 * w})
        force = {str(b["id"]): [-.4 + .3 * math.sin(t), -.5 + .2 * math.cos(t * .8), 15.76 + .15 * math.sin(t * 3.1),
                                .026, -.026, .015] for b in bots}
        return {"type": "telemetry", "t": time.time(), "flyways": fl, "force": force}
    def close(self): pass

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


def poll_loop(hub, args, stop):
    src_name = "mock" if args.mock else "pmc"
    period = 1.0 / args.hz
    while not stop.is_set():
        try:
            src = MockSource(args) if args.mock else PmcSource(args)
            src.connect()
            try:
                layout = src.layout()
            except Exception as e:                         # page falls back to a bare grid
                print(f"[bridge] could not read layout: {e}", flush=True); layout = None
            hub.publish_status(connected=True, source=src_name, error=None, layout=layout, **src.meta())
            print(f"[bridge] connected to {src_name}", flush=True)
            last_meta = last_tele = time.time()
            while not stop.is_set():
                t = time.time()
                bots = src.read()
                hub.publish_pose({"type": "pose", "t": t, "hz": args.hz, "xbots": bots})
                if t - last_tele >= .5:                    # power, temperatures, force: 2 Hz
                    hub.publish_tele(src.telemetry([b["id"] for b in bots]))
                    last_tele = t
                if t - last_meta > 2:                      # status is slow-moving
                    if not src.alive():
                        raise ConnectionError("TCP connection to PMC dropped")
                    hub.publish_status(**src.meta())
                    last_meta = t
                stop.wait(max(0.0, period - (time.time() - t)))
        except Exception as e:                             # keep retrying; the page shows why
            msg = f"{type(e).__name__}: {e}"
            print(f"[bridge] {msg} - retrying in 2 s", flush=True)
            hub.publish_status(connected=False, source=src_name, error=msg)
            try: src.close()
            except Exception: pass
            stop.wait(2)


# --------------------------------------------------------------------------- http

def make_handler(hub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":                                 # open http://localhost:8765 -> live view
                self.send_response(302); self.send_header("Location", "/index.html?bridge=same&view=fly")
                self.end_headers(); return
            if path == "/index.html":
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")   # always the file on disk
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            if path != "/events":
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")   # index.html opens from file://
            self.end_headers()
            seq, sent_status, sent_tele = -1, None, None
            try:
                while True:
                    seq, pose, tele, status = hub.wait(seq, 5)
                    if status != sent_status:
                        self._send(status); sent_status = status
                    if tele is not None and tele is not sent_tele and status.get("connected"):
                        self._send(tele); sent_tele = tele
                    if pose is not None and status.get("connected"):
                        self._send(pose)
                    else:
                        self.wfile.write(b": keepalive\n\n"); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _send(self, obj):
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default="192.168.17.150", help='PMC address, or "auto" to search')
    ap.add_argument("--port", type=int, default=8765, help="HTTP port the page connects to")
    ap.add_argument("--hz", type=float, default=20, help="poll rate")
    ap.add_argument("--gain-mastership", action="store_true",
                    help="take mastership on connect (only if reads fail without it)")
    ap.add_argument("--mock", action="store_true", help="fake movers, no hardware")
    args = ap.parse_args()

    hub, stop = Hub(), threading.Event()
    threading.Thread(target=poll_loop, args=(hub, args, stop), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(hub))
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
