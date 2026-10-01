"""
PMC + Saguaro -> browser bridge.

Polls the Planar Motor controller for every xBot's pose, reads the Saguaro
receiver boards, serves the page (web/) and streams everything to it as
Server-Sent Events. Standard library only, apart from pmclib.

    .venv\\Scripts\\python.exe bridge\\pmc_bridge.py                 # PMC at 192.168.17.150
    .venv\\Scripts\\python.exe bridge\\pmc_bridge.py --ip auto       # search the network
    .venv\\Scripts\\python.exe bridge\\pmc_bridge.py --mock          # no hardware

Then open http://localhost:8765.

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
     "points":[{"id":"P1", "name", "x", "y", "z"}, ...]}            5 Hz
    {"type":"status", "connected":bool, "source":"pmc"|"mock",
     "pmc":"PMC_FULLCTRL"|null, "master":bool|null, "error":str|null,
     "layout":{"cols":4, "rows":1, "tile":240,
               "flyways":[{"id":1, "col":0, "row":0, "sn":"9777-366"}, ...]}|null}

The HTTP routes are listed in http_api.py.
"""

import argparse
import threading
import time
from http.server import ThreadingHTTPServer

from events import EventHub
from http_api import make_handler
from pmc_sources import MockSource, PmcSource
from saguaro import ReceiverHub

TELEMETRY_PERIOD_S = .5    # power, temperatures, force: 2 Hz
META_PERIOD_S = 2          # controller status is slow-moving
RETRY_S = 2                # after the PMC connection fails
RECEIVERS_PERIOD_S = .2    # receivers + points to the page: 5 Hz


def log(message):
    print(message, flush=True)


# --------------------------------------------------------------------------- the PMC side

def _connect_source(events, args, source_name):
    source = MockSource(args) if args.mock else PmcSource(args)
    source.connect()
    try:
        layout = source.layout()
    except Exception as e:                             # the page falls back to a bare grid
        log(f"[bridge] could not read layout: {e}")
        layout = None
    events.publish_status(connected=True, source=source_name, error=None, layout=layout, **source.meta())
    log(f"[bridge] connected to {source_name}")
    return source


def _stream_source(source, events, args, stop):
    """Poll poses at args.hz until stopped or the connection drops (raises)."""
    period = 1.0 / args.hz
    last_meta = last_tele = time.time()
    while not stop.is_set():
        t = time.time()
        xbots = source.read()
        events.publish_pose({"type": "pose", "t": t, "hz": args.hz, "xbots": xbots})
        if t - last_tele >= TELEMETRY_PERIOD_S:
            events.publish_tele(source.telemetry([b["id"] for b in xbots]))
            last_tele = t
        if t - last_meta > META_PERIOD_S:
            if not source.alive():
                raise ConnectionError("TCP connection to PMC dropped")
            events.publish_status(**source.meta())
            last_meta = t
        stop.wait(max(0.0, period - (time.time() - t)))


def poll_loop(events, args, stop):
    """Connect, stream, and on any failure report it and retry, until stopped."""
    source_name = "mock" if args.mock else "pmc"
    while not stop.is_set():
        source = None
        try:
            source = _connect_source(events, args, source_name)
            _stream_source(source, events, args, stop)
        except Exception as e:                         # keep retrying; the page shows why
            message = f"{type(e).__name__}: {e}"
            log(f"[bridge] {message} - retrying in {RETRY_S} s")
            events.publish_status(connected=False, source=source_name, error=message)
            if source is not None:
                source.close()
            stop.wait(RETRY_S)


# --------------------------------------------------------------------------- the receiver side

def start_receivers(events, args, stop):
    """Discovery, assigned boards and the 5 Hz feed, unless --no-receivers."""
    if args.no_receivers:
        return None
    store = {"store": args.receivers_file} if args.receivers_file else {}
    receivers = ReceiverHub(log=log, **store)
    receivers.start()

    def feed():
        while not stop.is_set():
            events.publish_receivers(receivers)
            stop.wait(RECEIVERS_PERIOD_S)

    threading.Thread(target=feed, daemon=True, name="receivers-feed").start()
    return receivers


# --------------------------------------------------------------------------- main

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", default="192.168.17.150", help='PMC address, or "auto" to search')
    parser.add_argument("--port", type=int, default=8765, help="HTTP port the page connects to")
    parser.add_argument("--hz", type=float, default=20, help="poll rate")
    parser.add_argument("--gain-mastership", action="store_true",
                        help="take mastership on connect (only if reads fail without it)")
    parser.add_argument("--mock", action="store_true", help="fake movers, no hardware")
    parser.add_argument("--no-receivers", action="store_true", help="don't listen for Saguaro receiver boards")
    parser.add_argument("--receivers-file", default=None, metavar="PATH",
                        help="where receiver assignments are saved (default bridge/receivers.json); "
                             "cage points go to cage_points.json beside it")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    events, stop = EventHub(), threading.Event()
    threading.Thread(target=poll_loop, args=(events, args, stop), daemon=True, name="pmc-poll").start()
    receivers = start_receivers(events, args, stop)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(events, receivers, args.port))
    server.daemon_threads = True
    source = "mock" if args.mock else "PMC " + args.ip
    log(f"[bridge] open http://localhost:{args.port}  ({source}, {args.hz:g} Hz) - Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
