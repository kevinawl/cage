"""
Fake Saguaro receiver boards for testing without hardware.

Speaks the real protocol over real sockets: multicasts "<port>-SAGUARO-<MAC>" to
224.0.0.251:4210 once a second and answers the TCP handshake with protobuf
frames, exactly what saguaro.py (and Fennec2) expect from a board.

    .venv\\Scripts\\python.exe bridge\\fake_saguaro.py            # two boards
    .venv\\Scripts\\python.exe bridge\\fake_saguaro.py --count 3

Board 2 starts with its power endpoint switched off, so assigning it exercises
"ep-man index <id> 1".
"""

import argparse
import math
import random
import socket
import threading
import time

from saguaro import DELIM, GROUP, PORT, encode_packet


class FakeBoard:
    def __init__(self, n):
        self.n = n
        self.mac = "02:00:00:5A:67:%02X" % n        # locally administered: never a real board's MAC
        self.name = f"SAGUARO-RX-{n:02d}"
        self.eps = [{"sensor_id": 0, "name": "V_out", "type": "float", "active": True, "name_type": "V"},
                    {"sensor_id": 1, "name": "I_out", "type": "float", "active": True, "name_type": "A"},
                    {"sensor_id": 2, "name": "P_out", "type": "float", "active": n != 2, "name_type": "W"},
                    {"sensor_id": 3, "name": "T_board", "type": "float", "active": True, "name_type": "C"},
                    {"sensor_id": 4, "name": "link_ok", "type": "bool", "active": True, "name_type": ""}]
        self.srv = socket.socket(); self.srv.bind(("", 0)); self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.t0 = time.time()

    def ts(self): return int((time.time() - self.t0) * 1000) & 0xFFFFFFFF

    def announce(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        while True:
            s.sendto(f"{self.port}-SAGUARO-{self.mac}".encode(), (GROUP, PORT))
            time.sleep(1)

    def serve(self):
        while True:
            c, addr = self.srv.accept()
            print(f"[fake {self.name}] connection from {addr[0]}", flush=True)
            try:
                self.session(c)
            except OSError as e:
                print(f"[fake {self.name}] session ended: {e}", flush=True)
            finally:
                c.close()

    def session(self, c):
        c.settimeout(.05)
        send = lambda kind, body: c.sendall(DELIM + encode_packet(self.ts(), kind, body) + DELIM)
        c.sendall(b"Saguaro boot ok\r\n" + DELIM)                   # console text, like real firmware
        buf, streaming, last = b"", False, 0.0
        while True:
            try:
                chunk = c.recv(1024)
                if not chunk:
                    return
                buf += chunk
            except socket.timeout:
                pass
            while b"\r" in buf:
                cmd, _, buf = buf.partition(b"\r")
                cmd = cmd.decode("ascii", "replace").strip()
                if not cmd:
                    continue
                if cmd == "fennec2":
                    send("mcu_name", {"device_name": self.name, "firmware_version": "2.4.1-fake"})
                elif cmd == "ep-man list":
                    send("ep_man_list", self.eps)
                elif cmd == "s 1":
                    streaming = True
                elif cmd == "s 0":
                    streaming = False
                elif cmd == "ping":
                    send("ack", {"command_id": 0})
                elif cmd.startswith("ep-man index"):
                    _, _, sid, on = cmd.split()
                    for e in self.eps:
                        if e["sensor_id"] == int(sid):
                            e["active"] = on == "1"
                    print(f"[fake {self.name}] endpoint {sid} -> {'on' if on == '1' else 'off'}", flush=True)
                    send("ack", {"command_id": 0})
            now = time.time()
            if streaming and now - last >= .1:                        # 10 Hz telemetry
                last = now
                t = now - self.t0
                p = (3.2 + self.n) * (.72 + .28 * math.sin(t * .6 + self.n)) + random.gauss(0, .04)
                v = 12.0 + .15 * math.sin(t * .9) + random.gauss(0, .01)
                vals = {0: v, 1: p / v, 2: p, 3: 31.0 + .08 * p + .2 * math.sin(t * .05), 4: True}
                send("telemetry", [{"sensor_id": e["sensor_id"], "value": vals[e["sensor_id"]]}
                                   for e in self.eps if e["active"]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=2)
    args = ap.parse_args()
    for n in range(1, args.count + 1):
        b = FakeBoard(n)
        threading.Thread(target=b.announce, daemon=True).start()
        threading.Thread(target=b.serve, daemon=True).start()
        print(f"[fake] {b.name} {b.mac} on TCP {b.port}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
