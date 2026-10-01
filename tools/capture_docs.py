"""
Regenerate the screenshots in docs/images/ (used by the README and the Confluence manual).

    .venv\\Scripts\\python.exe tools\\capture_docs.py

Starts its own bridge (--mock, on a spare port, with throwaway receivers/points files)
and two fake Saguaro boards, drives headless Microsoft Edge over the DevTools protocol,
and saves one PNG per feature. Nothing touches bridge/receivers.json or a bridge already
running on 8765.

The flyway pictures show the mock controller. The cage plots use a simulated walk of a
receiver along the bars (the fake boards' power doesn't depend on where they are), so
the heat map and power-vs-distance plots look like a real mapping run. Captions should
say so.

Standard library only. Windows: needs Edge (or set EDGE to a Chromium-based browser).
"""

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
PYTHON = sys.executable
EDGE = os.environ.get("EDGE", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BRIDGE_PORT, DEVTOOLS_PORT = 8790, 9334
VIEWPORT = (1440, 900)

POINTS = {"P1": {"name": "P1", "x": 1500.0, "y": -1500.0, "z": 1500.0},
          "P2": {"name": "TX", "x": -1500.0, "y": 0.0, "z": 1500.0}}
RECEIVERS = {"02:00:00:5A:67:01": {"point": "P1", "xbot": None, "label": "RX A"},
             "02:00:00:5A:67:02": {"xbot": 1, "point": None, "label": "RX B"}}

# A mapping run, simulated: RX A walked along the bars, 15 s per 250 mm stop, power falling off
# with distance from the TX point. Replaces the cage recording; flyway readings stay as recorded.
SIMULATED_CAGE_RUN = r"""
(async () => {
  const {rec} = await import('/js/recorder.js');
  const TX = {x:-1500, y:0, z:1500}, MAC = '02:00:00:5A:67:01';
  const noise = a => 1 + (Math.random() - .5) * a;
  const model = (x, y, z) => { const d = Math.hypot(x-TX.x, y-TX.y, z-TX.z), p = 3.2/(1+Math.pow(d/1100, 2.2)), v = 4.2+p/(p+.4); return {p, v, i:p/v}; };
  const walk = [];
  for (let j = -1500; j <= 1500; j += 250) walk.push([j, -1500, 1500]);
  for (let j = -1500; j <= 1500; j += 250) walk.push([1500, j, 1500]);
  for (let j = 1500; j >= 0; j -= 250) walk.push([1500, 1500, j]);
  for (let j = 1500; j >= -1500; j -= 250) walk.push([j, 1500, 0]);
  for (let j = 0; j <= 3000; j += 250) walk.push([-1500, 1500, j]);
  for (let j = -1500; j <= 1500; j += 250) walk.push([j, 0, 3000]);
  const STOP = 75, t0 = Date.now() - walk.length * STOP * 200, cage = [];
  for (let k = 0; k < walk.length * STOP; k++){
    const [x, y, z] = walk[Math.floor(k / STOP)], m = model(x, y, z), n = noise(.06);
    cage.push({t:t0 + k*200, mac:MAC, rig:'cage', place:'P1', x, y, z, p:m.p*n, v:m.v*noise(.01), i:m.i*n, sent:null});
  }
  rec.on = false;
  rec.samples = cage.concat(rec.samples.filter(s => s.rig === 'fly'));
  rec.nameOf[MAC] = 'RX A';
  return rec.samples.length;
})()
"""


class DevTools:
    """Just enough of the Chrome DevTools protocol, over a hand-rolled WebSocket."""

    def __init__(self, url):
        host, path = url[len("ws://"):].split("/", 1)
        self.sock = socket.create_connection(tuple([host.split(":")[0], int(host.split(":")[1])]))
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self.buf, self.next_id, self.errors = buf.split(b"\r\n\r\n", 1)[1], 0, []

    def _read(self, n):
        while len(self.buf) < n:
            self.buf += self.sock.recv(1 << 20)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _message(self):
        data = b""
        while True:
            first, second = self._read(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            data += self._read(length)
            if first & 0x80:
                return json.loads(data)

    def call(self, method, **params):
        self.next_id += 1
        payload, mask = json.dumps({"id": self.next_id, "method": method, "params": params}).encode(), os.urandom(4)
        n = len(payload)
        header = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
                                  if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        while True:
            message = self._message()
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})
            if message.get("method") == "Runtime.exceptionThrown":
                self.errors.append(message["params"]["exceptionDetails"].get("exception", {}).get("description", "?"))

    def js(self, expression):
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")

    def click(self, selector):
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def shot(self, name, clip_selector=None, pause=1.0):
        time.sleep(pause)
        params = {"format": "png"}
        if clip_selector:
            r = self.js(f"(r => ({{x:r.left, y:r.top, width:r.width, height:r.height}}))"
                        f"(document.querySelector({json.dumps(clip_selector)}).getBoundingClientRect())")
            params["clip"] = {**r, "scale": 1}
        (OUT / name).write_bytes(base64.b64decode(self.call("Page.captureScreenshot", **params)["data"]))
        print("  ", name)


def start_rig(tmp):
    (tmp / "receivers.json").write_text(json.dumps(RECEIVERS))
    (tmp / "cage_points.json").write_text(json.dumps(POINTS))
    boards = subprocess.Popen([PYTHON, str(ROOT / "bridge" / "fake_saguaro.py")], stdout=subprocess.DEVNULL)
    bridge = subprocess.Popen([PYTHON, str(ROOT / "bridge" / "pmc_bridge.py"), "--mock", "--port", str(BRIDGE_PORT),
                               "--receivers-file", str(tmp / "receivers.json")], stdout=subprocess.DEVNULL)
    return [boards, bridge]


def start_browser(tmp):
    browser = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={DEVTOOLS_PORT}",
                                f"--user-data-dir={tmp / 'profile'}", f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}",
                                "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEVTOOLS_PORT}/json"))
            return browser, DevTools(next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"])
        except (OSError, StopIteration):
            time.sleep(.2)
    raise SystemExit("the browser did not start")


def capture(page, downloads):
    page.call("Runtime.enable")
    page.call("Browser.setDownloadBehavior", behavior="allow", downloadPath=str(downloads))
    page.call("Emulation.setDeviceMetricsOverride", width=VIEWPORT[0], height=VIEWPORT[1], deviceScaleFactor=1, mobile=False)

    page.call("Page.navigate", url=f"http://localhost:{BRIDGE_PORT}/index.html?bridge=same&view=fly")
    time.sleep(25)                                    # let the flyway recording build up from the live mock
    page.shot("01-flyway.png")
    page.click("#btnView")
    page.shot("03-view-options.png", pause=.6)
    page.js("document.body.click()")

    page.click('.sysbtn[data-sys="cage"]')
    print("   simulated cage readings:", page.js(SIMULATED_CAGE_RUN))
    page.shot("02-cage.png", pause=2)

    page.click("#btnPlot")
    for tab, name in (("heat", "04-plot-heat-map.png"), ("scatter", "05-plot-vs-position.png"),
                      ("time", "06-plot-over-time.png"), ("table", "07-plot-locations.png")):
        page.click(f'[data-pk="tab"][data-pv="{tab}"]')
        if tab == "scatter":
            page.js("""(() => { const s = document.querySelector('select[data-pk="ref"]');
                s.value = 'P2'; s.dispatchEvent(new Event('change', {bubbles:true})); })()""")
        page.shot(name, clip_selector=".plotwin", pause=1.4)

    page.click('[data-pk="tab"][data-pv="heat"]')
    time.sleep(1)
    page.click("#plotPng")                            # the Save image feature itself
    for _ in range(50):
        saved = list(downloads.glob("cage-plot-*.png"))
        if saved:
            break
        time.sleep(.2)
    if saved:
        shutil.copy(saved[0], OUT / "08-saved-graph.png")
        print("   08-saved-graph.png (the file Save image downloads)")
    else:
        print("   Save image produced no file")

    page.click('[data-pk="spots"]')
    page.click("#plotClose")
    page.shot("09-cage-spots-3d.png", pause=1.5)
    return page.errors


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="cage-docs-"))
    downloads = tmp / "downloads"
    downloads.mkdir()
    processes = start_rig(tmp)
    browser = page = None
    try:
        time.sleep(4)
        browser, page = start_browser(tmp)
        errors = capture(page, downloads)
        print("page errors:", errors or "none")
    finally:
        if page:
            try:
                page.call("Browser.close")
            except Exception:
                pass
        for p in processes + ([browser] if browser else []):
            p.kill()
        time.sleep(.5)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
