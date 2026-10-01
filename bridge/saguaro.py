"""
Saguaro receiver boards, the way Fennec2 talks to them.

Session, over plain TCP (Fennec2: Devices/MCU/McuDevice.cs):
    "fennec2"        -> McuName        (resent until answered)
    "ep-man list"    -> EpManList      (resent until answered)
    "print protobuf", "s 1", "ping"    -> telemetry starts
    no telemetry/ack for 2 s -> "ping"; for 4 s -> reconnect
    "ep-man index <id> <0|1>" turns one endpoint's telemetry on or off.
The wire format itself is in saguaro_protocol.py.

Only boards the user connects (or has assigned to a mover or a cage point) are
opened, as in Fennec2, so this never grabs a board someone else is using by
accident. Assignments are saved to receivers.json next to this file, keyed by
MAC; cage points (measured positions a board can be placed at) beside it, in
cage_points.json.
"""

import json
import re
import socket
import threading
import time
from pathlib import Path

from saguaro_protocol import GROUP, PORT, command, decode_packet, ENDPOINT_TYPES, parse_announce, split_frames

STORE = Path(__file__).resolve().parent / "receivers.json"
POINTS_FILE = "cage_points.json"    # kept beside the receivers store

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

KEEP = ...             # ReceiverHub.update() default: leave that field as it is


# --------------------------------------------------------------------------- persistence

def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_json(path, obj):
    """Write via a temp file, so a crash never leaves half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- one board

def _endpoint_from_info(info):
    return {"name": info.get("name", f"#{info['sensor_id']}"), "unit": info.get("name_type", ""),
            "type": ENDPOINT_TYPES.get(info.get("type"), "?"), "active": info.get("active", False),
            "value": None, "t": 0}


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
        self._send_lock = threading.Lock()
        self._thread = None
        self._stage = "hello"              # within a session: hello, list, stream
        self._last_cmd = 0.0

    @property
    def streaming(self):
        return self.state == "streaming"

    # control ------------------------------------------------------------------
    def start(self):
        self._want = True
        if not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._run, daemon=True, name=f"saguaro-{self.mac}")
            self._thread.start()

    def stop(self):
        self._want = False
        self._close_socket()

    def send(self, text):
        sock = self._sock
        if sock:
            with self._send_lock:
                sock.sendall(command(text))

    def activate(self, sensor_id):
        """Switch one endpoint's telemetry on."""
        self.send(f"ep-man index {sensor_id} 1")

    def _close_socket(self):
        sock = self._sock
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    # session ------------------------------------------------------------------
    def _run(self):
        while self._want:
            address = self.hub.address_of(self.mac)
            if not address:
                self.state, self.error = "error", "Not announcing on the network"
                time.sleep(NOT_ANNOUNCING_RETRY_S)
                continue
            try:
                self.state, self.error = "connecting", None
                self._sock = self._open(*address)
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
        sock = socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT_S)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.settimeout(RECV_POLL_S)
        return sock

    def _session(self, sock):
        buf, began = b"", time.time()
        self._stage, self._last_cmd, self.state = "hello", 0.0, "handshake"
        while self._want:
            self._tick(time.time(), began)
            try:
                chunk = sock.recv(RECV_BYTES)
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
                self.send("fennec2" if self._stage == "hello" else "ep-man list")
                self._last_cmd = now
            return
        quiet = now - self.last_rx
        if quiet > SILENT_S:
            raise OSError(f"no telemetry for {SILENT_S} s")
        if quiet > PING_AFTER_S and now - self._last_cmd > PING_AFTER_S:
            self.send("ping")
            self._last_cmd = now

    def _on_packet(self, packet):
        if "mcu_name" in packet and self._stage == "hello":
            self.name = packet["mcu_name"].get("device_name") or None
            self.fw = packet["mcu_name"].get("firmware_version") or None
            self._stage, self._last_cmd = "list", 0.0
        elif "ep_man_list" in packet and self._stage == "list":
            self._start_streaming(packet["ep_man_list"].get("endpoints", []))
        elif self._stage == "stream" and ("telemetry" in packet or "ack" in packet):
            self.last_rx = time.time()
            for reading in packet.get("telemetry", {}).get("data", []):
                endpoint = self.endpoints.get(reading.get("sensor_id"))
                if endpoint is not None and "value" in reading:
                    endpoint["value"], endpoint["t"] = reading["value"], self.last_rx

    def _start_streaming(self, infos):
        self.endpoints = {info["sensor_id"]: _endpoint_from_info(info) for info in infos}
        time.sleep(STREAM_SETTLE_S)
        for text in ("print protobuf", "s 1", "ping"):
            self.send(text)
        self._stage, self._last_cmd, self.last_rx = "stream", time.time(), time.time()
        self.state = "streaming"
        self.hub.on_endpoints(self)


# --------------------------------------------------------------------------- cage points

def _point_order(pid):
    """P1, P2, ... P10 in numeric order; anything else after them."""
    return (0, int(pid[1:])) if pid[1:].isdigit() else (1, pid)


class CagePoints:
    """Measured positions a board can sit at: "P1" -> {name, x, y, z}, mm, cage coordinates."""

    def __init__(self, path):
        self.path = path
        self._points = load_json(path)
        self._lock = threading.Lock()

    def __contains__(self, pid):
        return pid in self._points

    def add(self, name, x, y, z):
        with self._lock:
            n = 1 + max([int(pid[1:]) for pid in self._points if pid[1:].isdigit()] or [0])
            pid = f"P{n}"
            self._points[pid] = {"name": name or pid, "x": x, "y": y, "z": z}
            save_json(self.path, self._points)
        return pid

    def edit(self, pid, **fields):
        with self._lock:
            if pid not in self._points:
                return False
            if "name" in fields and not fields["name"]:
                fields["name"] = pid
            self._points[pid].update(fields)
            save_json(self.path, self._points)
        return True

    def remove(self, pid):
        with self._lock:
            if self._points.pop(pid, None) is None:
                return False
            save_json(self.path, self._points)
        return True

    def as_list(self):
        with self._lock:
            return [{"id": pid, **self._points[pid]} for pid in sorted(self._points, key=_point_order)]


# --------------------------------------------------------------------------- all boards

def _reading(board, endpoints, name, now):
    """The named endpoint's value, or None if unset, not a number, or older than READING_STALE_S."""
    endpoint = next((e for e in endpoints if e["name"] == name), None)
    if endpoint is None or board is None or not board.streaming:
        return None
    value = endpoint["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if now - board.endpoints.get(endpoint["id"], {}).get("t", 0) > READING_STALE_S:
        return None
    return value


class ReceiverHub:
    """Discovery, one Board per MAC, and where each board is placed.

    Discovery, board threads and HTTP requests all touch the shared dicts, so
    every read-modify-write of `seen`, `boards` and `assign` holds `_lock`.
    """

    def __init__(self, log=print, store=STORE):
        self.log, self.store = log, Path(store)
        self.points = CagePoints(self.store.parent / POINTS_FILE)
        self.seen = {}                     # mac -> {ip, port, t}
        self.boards = {}                   # mac -> Board
        self.assign = load_json(self.store)    # mac -> {label, xbot, point, endpoint, v_endpoint, i_endpoint}
        self._lock = threading.RLock()

    def _save(self):
        save_json(self.store, self.assign)

    # discovery ----------------------------------------------------------------
    def start(self):
        threading.Thread(target=self._listen, daemon=True, name="saguaro-discovery").start()
        with self._lock:
            placed = [mac for mac, a in self.assign.items()
                      if a.get("xbot") is not None or a.get("point") is not None]
        for mac in placed:                              # assigned boards reconnect by themselves
            self.connect(mac)

    @staticmethod
    def _discovery_socket():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", PORT))
        interfaces = {"0.0.0.0"}
        try:
            interfaces |= {ai[4][0] for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
        except OSError:
            pass
        for ip in interfaces:                           # join on every interface: boards may be on WiFi
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                socket.inet_aton(GROUP) + socket.inet_aton(ip))
            except OSError:
                pass
        sock.settimeout(1)
        return sock

    def _listen(self):
        sock = self._discovery_socket()
        self.log(f"[receivers] listening for Saguaro boards on {GROUP}:{PORT}")
        while True:
            try:
                data, (ip, _) = sock.recvfrom(ANNOUNCE_BYTES)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(1)
                continue
            self.on_announce(data, ip)

    def on_announce(self, data, ip):
        announced = parse_announce(data)
        if not announced:
            return
        mac, port = announced
        with self._lock:
            new = mac not in self.seen
            self.seen[mac] = {"ip": ip, "port": port, "t": time.time()}
        if new:
            self.log(f"[receivers] found Saguaro {mac} at {ip}:{port}")

    def address_of(self, mac):
        """(ip, port) the board last announced, or None."""
        with self._lock:
            seen = self.seen.get(mac)
            return (seen["ip"], seen["port"]) if seen else None

    def _board(self, mac):
        with self._lock:
            if mac not in self.boards:
                self.boards[mac] = Board(mac, self)
            return self.boards[mac]

    # actions from the page ----------------------------------------------------
    def connect(self, mac):
        self._board(mac).start()

    def disconnect(self, mac):
        board = self.boards.get(mac)
        if board:
            board.stop()

    def update(self, mac, xbot=KEEP, point=KEEP, endpoint=KEEP, v_endpoint=KEEP, i_endpoint=KEEP, label=KEEP):
        """A board is in one place: riding an xBot or clamped at a cage point, not both."""
        endpoints = {"endpoint": endpoint, "v_endpoint": v_endpoint, "i_endpoint": i_endpoint}
        with self._lock:
            assignment = dict(self.assign.get(mac, {}))
            if xbot is not KEEP:
                assignment["xbot"] = xbot
                if xbot is not None:
                    assignment["point"] = None
            if point is not KEEP:
                assignment["point"] = point
                if point is not None:
                    assignment["xbot"] = None
            assignment.update({k: v for k, v in endpoints.items() if v is not KEEP})
            if label is not KEEP:
                assignment["label"] = label
            self.assign[mac] = assignment
            self._save()
        board = self.boards.get(mac)
        if board and any(v not in (KEEP, None) for v in endpoints.values()):
            self._ensure_active(board)
        if xbot not in (KEEP, None) or point not in (KEEP, None):
            self.connect(mac)

    def remove_point(self, pid):
        """Delete a cage point; boards placed there are unplaced, not forgotten."""
        if not self.points.remove(pid):
            return False
        with self._lock:
            for assignment in self.assign.values():
                if assignment.get("point") == pid:
                    assignment["point"] = None
            self._save()
        return True

    # endpoints ------------------------------------------------------------------
    def on_endpoints(self, board):
        """First contact: guess power, voltage and current endpoints that aren't set yet,
        by the unit the board reports for them, else by name (P_out, V_out, I_out)."""
        numeric = [e for e in board.endpoints.values() if e["type"] in NUMERIC]
        guessed = False
        with self._lock:
            assignment = self.assign.setdefault(board.mac, {})
            for key, unit, name_pattern in QUANTITIES:
                if assignment.get(key):
                    continue
                by_unit = [e["name"] for e in numeric if e.get("unit", "").strip().upper() == unit]
                by_name = [e["name"] for e in numeric if e["type"] == "float" and name_pattern.search(e["name"])]
                guesses = by_unit or by_name
                if guesses:
                    assignment[key] = guesses[0]
                    guessed = True
            if guessed:
                self._save()
        self._ensure_active(board)

    def _ensure_active(self, board):
        with self._lock:
            assignment = self.assign.get(board.mac, {})
            wanted = {assignment.get(key) for key, _, _ in QUANTITIES} - {None}
        for sensor_id, endpoint in board.endpoints.items():
            if endpoint["name"] in wanted and not endpoint["active"]:
                try:
                    board.activate(sensor_id)
                    endpoint["active"] = True
                except OSError:
                    pass

    # snapshot for the page ----------------------------------------------------
    def snapshot(self):
        """Only boards reachable right now: announced within FRESH_S, or streaming to us.
        Anything else is left out, including assigned boards, whose assignment is kept
        so they reappear and reconnect by themselves when they come back."""
        now = time.time()
        with self._lock:
            self._forget_silent(now)
            macs = sorted(set(self.seen) | set(self.boards))
            return [self._board_view(mac, now) for mac in macs if self._reachable(mac, now)]

    def _streaming(self, mac):
        board = self.boards.get(mac)
        return board is not None and board.streaming

    def _forget_silent(self, now):
        for mac in [m for m, seen in self.seen.items() if now - seen["t"] > FORGET_S]:
            if not self._streaming(mac):
                del self.seen[mac]

    def _reachable(self, mac, now):
        seen = self.seen.get(mac)
        fresh = seen is not None and now - seen["t"] <= FRESH_S
        return fresh or self._streaming(mac)

    def _board_view(self, mac, now):
        seen, board, assignment = self.seen.get(mac), self.boards.get(mac), self.assign.get(mac, {})
        endpoints = [] if not board else [
            {"id": sid, "name": e["name"], "unit": e.get("unit", ""), "type": e["type"],
             "active": e["active"], "value": e["value"]}
            for sid, e in sorted(board.endpoints.items())]
        return {
            "mac": mac, "ip": seen and seen["ip"], "port": seen and seen["port"],
            "seen_s": None if not seen else round(now - seen["t"], 1),
            "state": board.state if board else "idle", "error": board.error if board else None,
            "name": board.name if board else None, "fw": board.fw if board else None,
            "endpoints": endpoints, "power_ep": assignment.get("endpoint"),
            "volt_ep": assignment.get("v_endpoint"), "curr_ep": assignment.get("i_endpoint"),
            "power": _reading(board, endpoints, assignment.get("endpoint"), now),
            "voltage": _reading(board, endpoints, assignment.get("v_endpoint"), now),
            "current": _reading(board, endpoints, assignment.get("i_endpoint"), now),
            "xbot": assignment.get("xbot"), "point": assignment.get("point"), "label": assignment.get("label"),
        }
