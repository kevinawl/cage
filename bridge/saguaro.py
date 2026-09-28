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

Only boards the user connects (or has assigned to a mover) are opened, as in
Fennec2, so this never grabs a board someone else is using by accident.
Assignments are saved to receivers.json next to this file, keyed by MAC.
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
FRESH_S = 3.5          # boards announce about once a second; allow two or three missed packets
FORGET_S = 120         # drop a silent board's address after this long
POWER_NAME = re.compile(r"pow|watt|(^|[^a-z])p(_?out|_?rx|_?in)?($|[^a-z])", re.I)


# --------------------------------------------------------------------------- protobuf
# The schema is seven small messages; a hand-rolled proto3 codec keeps the bridge stdlib-only.

def _varint(b, i):
    v = s = 0
    while True:
        c = b[i]; i += 1
        v |= (c & 0x7F) << s; s += 7
        if c < 0x80:
            return v, i


def _fields(b):
    i, n = 0, len(b)
    while i < n:
        key, i = _varint(b, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = _varint(b, i)
        elif w == 1:
            v, i = b[i:i + 8], i + 8
        elif w == 2:
            ln, i = _varint(b, i); v, i = b[i:i + ln], i + ln
        elif w == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type {w}")
        if i > n:
            raise ValueError("truncated")
        yield f, w, v


def _i32(v):                                  # int32 is sign-extended to 64 bits on the wire
    v &= (1 << 64) - 1
    return v - (1 << 64) if v >= 1 << 63 else v


def _msg(b, spec):
    """spec: {field: (name, kind)} with kind in int, uint, bool, float, str, bytes, or a sub-spec."""
    out = {}
    for f, w, v in _fields(b):
        if f not in spec:
            continue
        name, kind = spec[f][0], spec[f][1]
        rep = len(spec[f]) > 2
        if kind == "int" and w == 0:
            val = _i32(v)
        elif kind in ("uint", "enum") and w == 0:
            val = v
        elif kind == "bool" and w == 0:
            val = bool(v)
        elif kind == "float" and w == 5:
            val = struct.unpack("<f", v)[0]
        elif kind == "str" and w == 2:
            val = bytes(v).decode("utf-8", "replace")
        elif isinstance(kind, dict) and w == 2:
            val = _msg(v, kind)
        else:
            continue                                  # wire-type mismatch: skip, like protobuf
        if rep:
            out.setdefault(name, []).append(val)
        else:
            out[name] = val
    for f, sp in spec.items():                        # proto3 omits defaults: put them back
        name, kind = sp[0], sp[1]
        if name not in out and name != "value" and isinstance(kind, str) and kind in _DEFAULT and len(sp) == 2:
            out[name] = _DEFAULT[kind]
    return out


_DEFAULT = {"int": 0, "uint": 0, "enum": 0, "bool": False, "float": 0.0, "str": ""}


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
TYPES = {1: "float", 2: "int", 3: "bool", 4: "string"}


def decode_packet(frame):
    """McuToHostPacket -> dict, or None for anything that isn't one (console text)."""
    try:
        p = _msg(frame, PACKET)
    except (ValueError, IndexError):
        return None
    return p if any(k in p for k in ("telemetry", "ack", "mcu_name", "ep_man_list")) else None


def split_frames(buf):
    """Frames are the bytes between AA 55 0D 0A markers. Returns (frames, leftover)."""
    parts = buf.split(DELIM)
    return [p for p in parts[:-1] if p], parts[-1]


# encoder, used by fake_saguaro.py and the self-test
def _ev(v):
    v &= (1 << 64) - 1
    out = bytearray()
    while True:
        c = v & 0x7F; v >>= 7
        out.append(c | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _fv(f, v): return _ev(f << 3) + _ev(v)
def _fb(f, b): return _ev(f << 3 | 2) + _ev(len(b)) + b
def _ff(f, x): return _ev(f << 3 | 5) + struct.pack("<f", x)


def encode_packet(ts, kind, body):
    if kind == "mcu_name":
        inner = _fb(1, body["device_name"].encode()) + _fb(2, body["firmware_version"].encode())
        return _fv(1, ts) + _fb(4, inner)
    if kind == "ep_man_list":
        inner = b"".join(_fb(1, _fv(1, e["sensor_id"]) + (_fv(2, 1) if e["active"] else b"") +
                             _fb(3, e["name"].encode()) + _fb(4, e.get("name_type", "").encode()) +
                             _fv(5, {"float": 1, "int": 2, "bool": 3, "string": 4}[e["type"]]))
                         for e in body)
        return _fv(1, ts) + _fb(5, inner)
    if kind == "telemetry":
        def one(d):
            v = d["value"]
            val = (_ff(3, v) if isinstance(v, float) else _fv(5, int(v)) if isinstance(v, bool)
                   else _fv(4, v) if isinstance(v, int) else _fb(6, str(v).encode()))
            return _fb(1, _fv(1, d["sensor_id"]) + _fv(2, 1) + val)
        return _fv(1, ts) + _fb(2, b"".join(one(d) for d in body))
    if kind == "ack":
        return _fv(1, ts) + _fb(3, _fv(1, body.get("command_id", 0)) + _fv(2, 1))
    raise ValueError(kind)


# --------------------------------------------------------------------------- one board

class Board:
    """TCP session to one Saguaro board, run on its own thread (Fennec2's state machine)."""

    def __init__(self, mac, hub):
        self.mac, self.hub = mac, hub
        self.name = self.fw = None
        self.state = "idle"                # idle, connecting, handshake, streaming, error
        self.error = None
        self.endpoints = {}                # sensor_id -> {name, type, active, value, t}
        self.last_rx = 0.0
        self._want = False
        self._sock = None
        self._lock = threading.Lock()
        self._thread = None

    # control ------------------------------------------------------------------
    def start(self):
        self._want = True
        if not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._run, daemon=True, name=f"saguaro-{self.mac}")
            self._thread.start()

    def stop(self):
        self._want = False
        s = self._sock
        if s:
            try: s.close()
            except OSError: pass

    def send(self, cmd):
        s = self._sock
        if s:
            with self._lock:
                s.sendall(("\r" + cmd + "\r").encode("ascii"))

    def set_active(self, sensor_id, on):
        self.send(f"ep-man index {sensor_id} {1 if on else 0}")

    # session ------------------------------------------------------------------
    def _run(self):
        while self._want:
            seen = self.hub.seen.get(self.mac)
            if not seen:
                self.state, self.error = "error", "Not announcing on the network"
                time.sleep(1); continue
            try:
                self.state, self.error = "connecting", None
                s = socket.create_connection((seen["ip"], seen["port"]), timeout=1.5)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                s.settimeout(.1); self._sock = s
                self._session(s)
            except OSError as e:
                if self._want:
                    self.state, self.error = "error", f"{type(e).__name__}: {e}"
            finally:
                if self._sock:
                    try: self._sock.close()
                    except OSError: pass
                self._sock = None
            if self._want:
                time.sleep(1.5)
        self.state = "idle"

    def _session(self, s):
        buf, stage, last_cmd, began = b"", "hello", 0.0, time.time()
        self.state = "handshake"
        while self._want:
            now = time.time()
            if stage != "stream" and now - began > 5:              # accepts TCP but never answers
                raise OSError("no answer to the handshake in 5 s")
            if stage == "hello" and now - last_cmd > .6:
                self.send("fennec2"); last_cmd = now
            elif stage == "list" and now - last_cmd > .6:
                self.send("ep-man list"); last_cmd = now
            elif stage == "stream":
                quiet = now - self.last_rx
                if quiet > 4:
                    raise OSError("no telemetry for 4 s")
                if quiet > 2 and now - last_cmd > 2:
                    self.send("ping"); last_cmd = now
            try:
                chunk = s.recv(4096)
                if not chunk:
                    raise OSError("board closed the connection")
                buf += chunk
            except socket.timeout:
                continue
            frames, buf = split_frames(buf)
            for fr in frames:
                p = decode_packet(fr)
                if p is None:
                    continue                                   # console text from the firmware
                if "mcu_name" in p and stage == "hello":
                    self.name = p["mcu_name"].get("device_name") or None
                    self.fw = p["mcu_name"].get("firmware_version") or None
                    stage, last_cmd = "list", 0.0
                elif "ep_man_list" in p and stage == "list":
                    self.endpoints = {e["sensor_id"]: {"name": e.get("name", f"#{e['sensor_id']}"),
                                                       "type": TYPES.get(e.get("type"), "?"),
                                                       "active": e.get("active", False), "value": None, "t": 0}
                                      for e in p["ep_man_list"].get("endpoints", [])}
                    time.sleep(.5)
                    for c in ("print protobuf", "s 1", "ping"):
                        self.send(c)
                    stage, last_cmd, self.last_rx = "stream", time.time(), time.time()
                    self.state = "streaming"
                    self.hub.on_endpoints(self)
                elif stage == "stream" and ("telemetry" in p or "ack" in p):
                    self.last_rx = time.time()
                    for d in p.get("telemetry", {}).get("data", []):
                        ep = self.endpoints.get(d.get("sensor_id"))
                        if ep is not None and "value" in d:
                            ep["value"], ep["t"] = d["value"], self.last_rx


# --------------------------------------------------------------------------- all boards

class ReceiverHub:
    def __init__(self, log=print, store=STORE):
        self.log, self.store = log, Path(store)
        self.seen = {}                     # mac -> {ip, port, t}
        self.boards = {}                   # mac -> Board
        self.assign = self._load()         # mac -> {label, xbot, endpoint}
        self._lock = threading.Lock()

    # persistence --------------------------------------------------------------
    def _load(self):
        try:
            return json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.assign, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.store)

    # discovery ----------------------------------------------------------------
    def start(self):
        threading.Thread(target=self._listen, daemon=True, name="saguaro-discovery").start()
        for mac, a in self.assign.items():             # assigned boards reconnect by themselves
            if a.get("xbot") is not None:
                self._board(mac).start()

    def _listen(self):
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
        self.log(f"[receivers] listening for Saguaro boards on {GROUP}:{PORT}")
        while True:
            try:
                data, (ip, _) = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(1); continue
            m = ANNOUNCE.match(data.decode("ascii", "replace").strip("\x00\r\n\t "))
            if not m:
                continue
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

    def update(self, mac, xbot=..., endpoint=..., label=...):
        a = dict(self.assign.get(mac, {}))
        if xbot is not ...: a["xbot"] = xbot
        if endpoint is not ...: a["endpoint"] = endpoint
        if label is not ...: a["label"] = label
        self.assign[mac] = a
        self._save()
        b = self.boards.get(mac)
        if b and endpoint not in (..., None):
            self._ensure_active(b)
        if xbot not in (..., None):
            self.connect(mac)

    def on_endpoints(self, board):
        a = self.assign.setdefault(board.mac, {})
        if not a.get("endpoint"):                      # first contact: guess the power endpoint
            guess = [e["name"] for e in board.endpoints.values()
                     if e["type"] == "float" and POWER_NAME.search(e["name"])]
            if guess:
                a["endpoint"] = guess[0]; self._save()
        self._ensure_active(board)

    def _ensure_active(self, board):
        name = self.assign.get(board.mac, {}).get("endpoint")
        for sid, e in board.endpoints.items():
            if e["name"] == name and not e["active"]:
                try:
                    board.set_active(sid, True); e["active"] = True
                except OSError:
                    pass

    # snapshot for the page ----------------------------------------------------
    def snapshot(self):
        """Only boards reachable right now: announced within FRESH_S, or streaming to us.
        Anything else is left out, including assigned boards, whose assignment is kept
        so they reappear and reconnect by themselves when they come back."""
        now, out = time.time(), []
        for mac in [m for m, v in list(self.seen.items()) if now - v["t"] > FORGET_S]:
            if not (self.boards.get(mac) and self.boards[mac].state == "streaming"):
                self.seen.pop(mac, None)
        for mac in sorted(set(self.seen) | set(self.boards)):
            seen, b, a = self.seen.get(mac), self.boards.get(mac), self.assign.get(mac, {})
            fresh = seen is not None and now - seen["t"] <= FRESH_S
            if not (fresh or (b is not None and b.state == "streaming")):
                continue
            eps = [] if not b else [{"id": sid, "name": e["name"], "type": e["type"], "active": e["active"],
                                     "value": e["value"]} for sid, e in sorted(b.endpoints.items())]
            pe = next((e for e in eps if e["name"] == a.get("endpoint")), None)
            stale = b is not None and b.state == "streaming" and pe is not None and \
                now - b.endpoints.get(pe["id"], {}).get("t", 0) > 2
            out.append({
                "mac": mac, "ip": seen and seen["ip"], "port": seen and seen["port"],
                "seen_s": None if not seen else round(now - seen["t"], 1),
                "state": b.state if b else "idle", "error": b.error if b else None,
                "name": b.name if b else None, "fw": b.fw if b else None,
                "endpoints": eps, "power_ep": a.get("endpoint"),
                "power": None if (pe is None or stale or not isinstance(pe["value"], (int, float))) else pe["value"],
                "xbot": a.get("xbot"), "label": a.get("label"),
            })
        return out
