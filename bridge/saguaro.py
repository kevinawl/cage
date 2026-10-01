"""
Saguaro receiver boards, the way Fennec2 talks to them.

Discovery: each board multicasts "<tcp port>-SAGUARO-<MAC>" to 224.0.0.251:4210;
the sender's address is the board's IP (Fennec2: Discovery/SaguaroDiscovery.cs).

Session, over plain TCP to ip:port (Fennec2: Devices/MCU/McuDevice.cs):
    host sends "\\r<cmd>\\r" commands; the board answers with protobuf
    McuToHostPacket frames separated by AA 55 0D 0A (Communication/protobuf/fennec2.proto).
    "fennec2"        -> McuName        (resent until answered)
    "ep-man list"    -> EpManList      (resent until answered)
    "print protobuf", "s 1", "ping"    -> telemetry starts
    no telemetry/ack for 2 s -> "ping"; for 4 s -> reconnect
    "ep-man index <id> <0|1>" turns one endpoint's telemetry on or off.

Only boards the user connects (or has assigned to a mover or a cage point) are
opened, as in Fennec2, so this never grabs a board someone else is using by accident.
Assignments are saved to receivers.json next to this file, keyed by MAC. Cage
points (measured positions a board can be placed at) are saved next to it, in
cage_points.json.
"""

import json
import re
import socket
import struct
import threading
import time
from pathlib import Path

GROUP, PORT, TAG = "224.0.0.251", 4210, "SAGUARO"
DELIM = b"\xaa\x55\x0d\x0a"
ANNOUNCE = re.compile(r"^([0-9]{1,5})-SAGUARO-((?:[0-9A-F]{2}:){5}[0-9A-F]{2})$")
STORE = Path(__file__).resolve().parent / "receivers.json"
POINTS = "cage_points.json"    # kept beside STORE

FRESH_S = 3.5          # boards announce about once a second; allow two or three missed packets
FORGET_S = 120         # drop a silent board's address after this long
READING_STALE_S = 2    # a value older than this is shown as no reading

CONNECT_TIMEOUT_S = 1.5
RECONNECT_S = 1.5      # pause between attempts after a session ends
NOT_ANNOUNCING_RETRY_S = 1
RECV_POLL_S = .1       # socket timeout, so timers run between reads
HANDSHAKE_TIMEOUT_S = 5    # some boards accept TCP but never answer
RESEND_S = .6          # handshake commands are resent until answered
PING_AFTER_S = 2       # quiet this long while streaming: ping
SILENT_S = 4           # quiet this long while streaming: reconnect
STREAM_SETTLE_S = .5   # the firmware needs a moment after listing before it streams
RECV_BYTES = 4096
ANNOUNCE_BYTES = 2048

POWER_NAME = re.compile(r"pow|watt|(^|[^a-z])p(_?out|_?rx|_?in)?($|[^a-z])", re.I)
VOLT_NAME = re.compile(r"volt|(^|[^a-z])v(_?out|_?rx|_?in|_?bus)?($|[^a-z])", re.I)
CURR_NAME = re.compile(r"curr|amp|(^|[^a-z])i(_?out|_?rx|_?in)?($|[^a-z])", re.I)
# The three readings a receiver is shown by: assignment key, unit the board reports, name fallback.
QUANTITIES = (("endpoint", "W", POWER_NAME), ("v_endpoint", "V", VOLT_NAME), ("i_endpoint", "A", CURR_NAME))
NUMERIC = ("float", "int")


# --------------------------------------------------------------------------- protobuf
# The schema is seven small messages; a hand-rolled proto3 codec keeps the bridge stdlib-only.

VARINT, FIXED64, LENGTH, FIXED32 = 0, 1, 2, 5          # protobuf wire types
UINT64 = (1 << 64) - 1


def _varint(b, i):
    v = shift = 0
    while True:
        c = b[i]; i += 1
        v |= (c & 0x7F) << shift; shift += 7
        if c < 0x80:
            return v, i


def _fields(b):
    i, n = 0, len(b)
    while i < n:
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        if wire == VARINT:
            v, i = _varint(b, i)
        elif wire == FIXED64:
            v, i = b[i:i + 8], i + 8
        elif wire == LENGTH:
            ln, i = _varint(b, i); v, i = b[i:i + ln], i + ln
        elif wire == FIXED32:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type {wire}")
        if i > n:
            raise ValueError("truncated")
        yield field, wire, v


def _i32(v):                                  # int32 is sign-extended to 64 bits on the wire
    v &= UINT64
    return v - (1 << 64) if v >= 1 << 63 else v


_SKIP = object()


def _value(kind, wire, raw):
    """One field's value by its schema kind, or _SKIP on a wire-type mismatch (as protobuf does)."""
    if wire == VARINT:
        if kind == "int": return _i32(raw)
        if kind in ("uint", "enum"): return raw
        if kind == "bool": return bool(raw)
    elif wire == FIXED32 and kind == "float":
        return struct.unpack("<f", raw)[0]
    elif wire == LENGTH:
        if kind == "str": return bytes(raw).decode("utf-8", "replace")
        if isinstance(kind, dict): return _msg(raw, kind)
    return _SKIP


_DEFAULT = {"int": 0, "uint": 0, "enum": 0, "bool": False, "float": 0.0, "str": ""}


def _fill_defaults(out, spec):
    """proto3 omits default values on the wire: put them back (not for repeated or oneof "value")."""
    for field_spec in spec.values():
        name, kind, repeated = field_spec[0], field_spec[1], len(field_spec) > 2
        if name not in out and name != "value" and not repeated and isinstance(kind, str) and kind in _DEFAULT:
            out[name] = _DEFAULT[kind]


def _msg(b, spec):
    """spec: {field: (name, kind[, repeated])} with kind in int, uint, enum, bool, float, str, or a sub-spec."""
    out = {}
    for field, wire, raw in _fields(b):
        if field not in spec:
            continue
        name, kind, repeated = spec[field][0], spec[field][1], len(spec[field]) > 2
        val = _value(kind, wire, raw)
        if val is _SKIP:
            continue
        if repeated:
            out.setdefault(name, []).append(val)
        else:
            out[name] = val
    _fill_defaults(out, spec)
    return out


ENDPOINT_DATA = {1: ("sensor_id", "int"), 2: ("active", "bool"), 3: ("value", "float"),
                 4: ("value", "int"), 5: ("value", "bool"), 6: ("value", "str")}
ENDPOINT_INFO = {1: ("sensor_id", "int"), 2: ("active", "bool"), 3: ("name", "str"),
                 4: ("name_type", "str"), 5: ("type", "enum")}
PACKET = {
    1: ("timestamp_ms", "uint"),
    2: ("telemetry", {1: ("data", ENDPOINT_DATA, True)}),
    3: ("ack", {1: ("command_id", "uint"), 2: ("success", "bool"), 3: ("message", "str")}),
    4: ("mcu_name", {1: ("device_name", "str"), 2: ("firmware_version", "str")}),
    5: ("ep_man_list", {1: ("endpoints", ENDPOINT_INFO, True)}),
}
PACKET_KINDS = ("telemetry", "ack", "mcu_name", "ep_man_list")
TYPES = {1: "float", 2: "int", 3: "bool", 4: "string"}
TYPE_CODES = {name: code for code, name in TYPES.items()}


def decode_packet(frame):
    """McuToHostPacket -> dict, or None for anything that isn't one (console text)."""
    try:
        p = _msg(frame, PACKET)
    except (ValueError, IndexError):
        return None
    return p if any(k in p for k in PACKET_KINDS) else None


def split_frames(buf):
    """Frames are the bytes between AA 55 0D 0A markers. Returns (frames, leftover)."""
    parts = buf.split(DELIM)
    return [p for p in parts[:-1] if p], parts[-1]


# encoder, used by fake_saguaro.py and the tests
def _ev(v):
    v &= UINT64
    out = bytearray()
    while True:
        c = v & 0x7F; v >>= 7
        out.append(c | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _fv(f, v): return _ev(f << 3 | VARINT) + _ev(v)
def _fb(f, b): return _ev(f << 3 | LENGTH) + _ev(len(b)) + b
def _ff(f, x): return _ev(f << 3 | FIXED32) + struct.pack("<f", x)


def _enc_mcu_name(body):
    return _fb(4, _fb(1, body["device_name"].encode()) + _fb(2, body["firmware_version"].encode()))


def _enc_endpoint_info(e):
    return _fb(1, _fv(1, e["sensor_id"]) + (_fv(2, 1) if e["active"] else b"") +
               _fb(3, e["name"].encode()) + _fb(4, e.get("name_type", "").encode()) + _fv(5, TYPE_CODES[e["type"]]))


def _enc_ep_man_list(body):
    return _fb(5, b"".join(_enc_endpoint_info(e) for e in body))


def _enc_endpoint_data(d):
    v = d["value"]
    if isinstance(v, bool):                    # before int: bool is an int in Python
        val = _fv(5, int(v))
    elif isinstance(v, float):
        val = _ff(3, v)
    elif isinstance(v, int):
        val = _fv(4, v)
    else:
        val = _fb(6, str(v).encode())
    return _fb(1, _fv(1, d["sensor_id"]) + _fv(2, 1) + val)


def _enc_telemetry(body):
    return _fb(2, b"".join(_enc_endpoint_data(d) for d in body))


def _enc_ack(body):
    return _fb(3, _fv(1, body.get("command_id", 0)) + _fv(2, 1))


_ENCODERS = {"mcu_name": _enc_mcu_name, "ep_man_list": _enc_ep_man_list,
             "telemetry": _enc_telemetry, "ack": _enc_ack}


def encode_packet(ts, kind, body):
    if kind not in _ENCODERS:
        raise ValueError(kind)
    return _fv(1, ts) + _ENCODERS[kind](body)


# --------------------------------------------------------------------------- one board

def _endpoint_from_info(e):
    return {"name": e.get("name", f"#{e['sensor_id']}"), "unit": e.get("name_type", ""),
            "type": TYPES.get(e.get("type"), "?"), "active": e.get("active", False), "value": None, "t": 0}


class Board:
    """TCP session to one Saguaro board, run on its own thread (Fennec2's state machine)."""

    def __init__(self, mac, hub):
        self.mac, self.hub = mac, hub
        self.name = self.fw = None
        self.state = "idle"                # idle, connecting, handshake, streaming, error
        self.error = None
        self.endpoints = {}                # sensor_id -> {name, unit, type, active, value, t}
        self.last_rx = 0.0
        self._want = False
        self._sock = None
        self._lock = threading.Lock()
        self._thread = None
        self._stage = "hello"              # within a session: hello, list, stream
        self._last_cmd = 0.0

    # control ------------------------------------------------------------------
    def start(self):
        self._want = True
        if not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._run, daemon=True, name=f"saguaro-{self.mac}")
            self._thread.start()

    def stop(self):
        self._want = False
        self._close_socket()

    def send(self, cmd):
        s = self._sock
        if s:
            with self._lock:
                s.sendall(("\r" + cmd + "\r").encode("ascii"))

    def activate(self, sensor_id):
        """Switch one endpoint's telemetry on."""
        self.send(f"ep-man index {sensor_id} 1")

    def _close_socket(self):
        s = self._sock
        if s:
            try: s.close()
            except OSError: pass

    # session ------------------------------------------------------------------
    def _run(self):
        while self._want:
            seen = self.hub.seen.get(self.mac)
            if not seen:
                self.state, self.error = "error", "Not announcing on the network"
                time.sleep(NOT_ANNOUNCING_RETRY_S); continue
            try:
                self.state, self.error = "connecting", None
                self._sock = self._open(seen["ip"], seen["port"])
                self._session(self._sock)
            except OSError as e:
                if self._want:
                    self.state, self.error = "error", f"{type(e).__name__}: {e}"
            finally:
                self._close_socket()
                self._sock = None
            if self._want:
                time.sleep(RECONNECT_S)
        self.state = "idle"

    @staticmethod
    def _open(ip, port):
        s = socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT_S)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.settimeout(RECV_POLL_S)
        return s

    def _session(self, s):
        buf, began = b"", time.time()
        self._stage, self._last_cmd, self.state = "hello", 0.0, "handshake"
        while self._want:
            self._tick(time.time(), began)
            try:
                chunk = s.recv(RECV_BYTES)
            except socket.timeout:
                continue
            if not chunk:
                raise OSError("board closed the connection")
            frames, buf = split_frames(buf + chunk)
            for packet in filter(None, map(decode_packet, frames)):     # None: console text from the firmware
                self._on_packet(packet)

    def _tick(self, now, began):
        """Timers between reads: resend handshake commands, ping when quiet, give up when silent."""
        if self._stage != "stream":
            if now - began > HANDSHAKE_TIMEOUT_S:
                raise OSError(f"no answer to the handshake in {HANDSHAKE_TIMEOUT_S} s")
            if now - self._last_cmd > RESEND_S:
                self.send("fennec2" if self._stage == "hello" else "ep-man list"); self._last_cmd = now
            return
        quiet = now - self.last_rx
        if quiet > SILENT_S:
            raise OSError(f"no telemetry for {SILENT_S} s")
        if quiet > PING_AFTER_S and now - self._last_cmd > PING_AFTER_S:
            self.send("ping"); self._last_cmd = now

    def _on_packet(self, p):
        if "mcu_name" in p and self._stage == "hello":
            self.name = p["mcu_name"].get("device_name") or None
            self.fw = p["mcu_name"].get("firmware_version") or None
            self._stage, self._last_cmd = "list", 0.0
        elif "ep_man_list" in p and self._stage == "list":
            self._start_streaming(p["ep_man_list"].get("endpoints", []))
        elif self._stage == "stream" and ("telemetry" in p or "ack" in p):
            self.last_rx = time.time()
            for d in p.get("telemetry", {}).get("data", []):
                ep = self.endpoints.get(d.get("sensor_id"))
                if ep is not None and "value" in d:
                    ep["value"], ep["t"] = d["value"], self.last_rx

    def _start_streaming(self, infos):
        self.endpoints = {e["sensor_id"]: _endpoint_from_info(e) for e in infos}
        time.sleep(STREAM_SETTLE_S)
        for c in ("print protobuf", "s 1", "ping"):
            self.send(c)
        self._stage, self._last_cmd, self.last_rx = "stream", time.time(), time.time()
        self.state = "streaming"
        self.hub.on_endpoints(self)


# --------------------------------------------------------------------------- all boards

KEEP = ...             # update() default: leave that field as it is


def _point_order(pid):
    """P1, P2, ... P10 in numeric order; anything else after them."""
    return (0, int(pid[1:])) if pid[1:].isdigit() else (1, pid)


def _reading(board, eps, name, now):
    """The named endpoint's value, or None if unset, not a number, or older than READING_STALE_S."""
    e = next((x for x in eps if x["name"] == name), None)
    streaming = board is not None and board.state == "streaming"
    if e is None or not streaming or isinstance(e["value"], bool) or not isinstance(e["value"], (int, float)):
        return None
    if now - board.endpoints.get(e["id"], {}).get("t", 0) > READING_STALE_S:
        return None
    return e["value"]


class ReceiverHub:
    def __init__(self, log=print, store=STORE):
        self.log, self.store = log, Path(store)
        self.pstore = self.store.parent / POINTS
        self.seen = {}                     # mac -> {ip, port, t}
        self.boards = {}                   # mac -> Board
        self.assign = self._load(self.store)     # mac -> {label, xbot, point, endpoint, v_endpoint, i_endpoint}
        self.points = self._load(self.pstore)    # "P1" -> {name, x, y, z}, mm, cage coordinates
        self._lock = threading.Lock()

    # persistence --------------------------------------------------------------
    @staticmethod
    def _load(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write(path, obj):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def _save(self):
        self._write(self.store, self.assign)

    def _save_points(self):
        self._write(self.pstore, self.points)

    # discovery ----------------------------------------------------------------
    def start(self):
        threading.Thread(target=self._listen, daemon=True, name="saguaro-discovery").start()
        for mac, a in self.assign.items():             # assigned boards reconnect by themselves
            if a.get("xbot") is not None or a.get("point") is not None:
                self._board(mac).start()

    @staticmethod
    def _discovery_socket():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", PORT))
        ips = {"0.0.0.0"}
        try:
            ips |= {ai[4][0] for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
        except OSError:
            pass
        for ip in ips:                                  # join on every interface: boards may be on WiFi
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(GROUP) + socket.inet_aton(ip))
            except OSError:
                pass
        s.settimeout(1)
        return s

    def _listen(self):
        s = self._discovery_socket()
        self.log(f"[receivers] listening for Saguaro boards on {GROUP}:{PORT}")
        while True:
            try:
                data, (ip, _) = s.recvfrom(ANNOUNCE_BYTES)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(1); continue
            self.on_announce(data, ip)

    def on_announce(self, data, ip):
        m = ANNOUNCE.match(data.decode("ascii", "replace").strip("\x00\r\n\t "))
        if not m:
            return
        mac, port = m.group(2), int(m.group(1))
        new = mac not in self.seen
        self.seen[mac] = {"ip": ip, "port": port, "t": time.time()}
        if new:
            self.log(f"[receivers] found Saguaro {mac} at {ip}:{port}")

    def _board(self, mac):
        with self._lock:
            if mac not in self.boards:
                self.boards[mac] = Board(mac, self)
            return self.boards[mac]

    # actions from the page ----------------------------------------------------
    def connect(self, mac):
        self._board(mac).start()

    def disconnect(self, mac):
        b = self.boards.get(mac)
        if b:
            b.stop()

    def update(self, mac, xbot=KEEP, point=KEEP, endpoint=KEEP, v_endpoint=KEEP, i_endpoint=KEEP, label=KEEP):
        """A board is in one place: riding an xBot or clamped at a cage point, not both."""
        a = dict(self.assign.get(mac, {}))
        if xbot is not KEEP:
            a["xbot"] = xbot
            if xbot is not None: a["point"] = None
        if point is not KEEP:
            a["point"] = point
            if point is not None: a["xbot"] = None
        endpoints = {"endpoint": endpoint, "v_endpoint": v_endpoint, "i_endpoint": i_endpoint}
        a.update({k: v for k, v in endpoints.items() if v is not KEEP})
        if label is not KEEP: a["label"] = label
        self.assign[mac] = a
        self._save()
        b = self.boards.get(mac)
        if b and any(v not in (KEEP, None) for v in endpoints.values()):
            self._ensure_active(b)
        if xbot not in (KEEP, None) or point not in (KEEP, None):
            self.connect(mac)

    # cage points ---------------------------------------------------------------
    def add_point(self, name, x, y, z):
        with self._lock:
            n = 1 + max([int(k[1:]) for k in self.points if k[1:].isdigit()] or [0])
            pid = f"P{n}"
            self.points[pid] = {"name": name or pid, "x": x, "y": y, "z": z}
            self._save_points()
        return pid

    def edit_point(self, pid, **kw):
        with self._lock:
            if pid not in self.points:
                return False
            if "name" in kw and not kw["name"]:
                kw["name"] = pid
            self.points[pid].update(kw)
            self._save_points()
        return True

    def remove_point(self, pid):
        with self._lock:
            if self.points.pop(pid, None) is None:
                return False
            self._save_points()
        for a in self.assign.values():                 # boards placed there are unplaced, not forgotten
            if a.get("point") == pid:
                a["point"] = None
        self._save()
        return True

    def points_list(self):
        return [{"id": k, **self.points[k]} for k in sorted(self.points, key=_point_order)]

    # endpoints ------------------------------------------------------------------
    def on_endpoints(self, board):
        """First contact: guess power, voltage and current endpoints that aren't set yet,
        by the unit the board reports for them, else by name (P_out, V_out, I_out)."""
        a = self.assign.setdefault(board.mac, {})
        nums = [e for e in board.endpoints.values() if e["type"] in NUMERIC]
        for key, unit, pattern in QUANTITIES:
            if a.get(key):
                continue
            by_unit = [e["name"] for e in nums if e.get("unit", "").strip().upper() == unit]
            by_name = [e["name"] for e in nums if e["type"] == "float" and pattern.search(e["name"])]
            guess = by_unit or by_name
            if guess:
                a[key] = guess[0]; self._save()
        self._ensure_active(board)

    def _ensure_active(self, board):
        a = self.assign.get(board.mac, {})
        wanted = {a.get(key) for key, _, _ in QUANTITIES} - {None}
        for sid, e in board.endpoints.items():
            if e["name"] in wanted and not e["active"]:
                try:
                    board.activate(sid); e["active"] = True
                except OSError:
                    pass

    # snapshot for the page ----------------------------------------------------
    def snapshot(self):
        """Only boards reachable right now: announced within FRESH_S, or streaming to us.
        Anything else is left out, including assigned boards, whose assignment is kept
        so they reappear and reconnect by themselves when they come back."""
        now = time.time()
        self._forget_silent(now)
        return [self._board_view(mac, now) for mac in sorted(set(self.seen) | set(self.boards))
                if self._reachable(mac, now)]

    def _streaming(self, mac):
        b = self.boards.get(mac)
        return b is not None and b.state == "streaming"

    def _forget_silent(self, now):
        for mac in [m for m, v in list(self.seen.items()) if now - v["t"] > FORGET_S]:
            if not self._streaming(mac):
                self.seen.pop(mac, None)

    def _reachable(self, mac, now):
        seen = self.seen.get(mac)
        fresh = seen is not None and now - seen["t"] <= FRESH_S
        return fresh or self._streaming(mac)

    def _board_view(self, mac, now):
        seen, b, a = self.seen.get(mac), self.boards.get(mac), self.assign.get(mac, {})
        eps = [] if not b else [{"id": sid, "name": e["name"], "unit": e.get("unit", ""), "type": e["type"],
                                 "active": e["active"], "value": e["value"]} for sid, e in sorted(b.endpoints.items())]
        return {
            "mac": mac, "ip": seen and seen["ip"], "port": seen and seen["port"],
            "seen_s": None if not seen else round(now - seen["t"], 1),
            "state": b.state if b else "idle", "error": b.error if b else None,
            "name": b.name if b else None, "fw": b.fw if b else None,
            "endpoints": eps, "power_ep": a.get("endpoint"),
            "volt_ep": a.get("v_endpoint"), "curr_ep": a.get("i_endpoint"),
            "power": _reading(b, eps, a.get("endpoint"), now),
            "voltage": _reading(b, eps, a.get("v_endpoint"), now),
            "current": _reading(b, eps, a.get("i_endpoint"), now),
            "xbot": a.get("xbot"), "point": a.get("point"), "label": a.get("label"),
        }
