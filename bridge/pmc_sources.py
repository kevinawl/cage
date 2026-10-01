"""
Where xBot poses and flyway telemetry come from: the real PMC, or a mock.

Both sources have the same interface:
    connect(), alive(), meta(), layout(), read(), telemetry(xbot_ids), close()

Positions are the PMC's own coordinates: origin at the outer corner of the
flyway in column 0, row 0. The layout comes from the PMC's configuration
(save_pmc_config_xml_file), read once per connection.

Tracking error needs two reads (position, then reference) a few ms apart. At
speed that skew alone looks like millimetres of error, so the reference is
shifted back to the position's sample time using the reference's own velocity
between polls. At rest the correction is zero.
"""

import math
import os
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

TILE_MM = 240          # S3 flyway, 240 x 240 mm; the config XML carries no size
M_TO_MM, M_TO_UM = 1000, 1e6


def parse_layout(xml_text):
    """The flyway grid from a PMC configuration XML: {cols, rows, tile, flyways: [{id, col, row}]}."""
    layout = ET.fromstring(xml_text).find("flw/layout")
    cols = [int(v.text) for v in layout.findall("mapping/col/value")]
    rows = [int(v.text) for v in layout.findall("mapping/row/value")]
    return {"cols": int(layout.findtext("mcol")), "rows": int(layout.findtext("mrow")), "tile": TILE_MM,
            "flyways": [{"id": i + 1, "col": c, "row": r} for i, (c, r) in enumerate(zip(cols, rows))]}


def telemetry_event(flyways, force):
    return {"type": "telemetry", "t": time.time(), "flyways": flyways, "force": force}


class PmcSource:
    """Read-only client for the Planar Motor controller, through pmclib."""

    def __init__(self, args):
        # Imported here so --mock works on a machine without the library.
        from pmclib import pmc_commands as pmc
        from pmclib import pmc_types as pm
        self.pmc, self.pm, self.args = pmc, pm, args
        self.flyway_ids = []
        self._prev_ref = None              # (sample time, {id: reference}) from the last poll

    def connect(self):
        ip = self.args.ip
        ok = self.pmc.auto_search_and_connect_to_pmc() if ip == "auto" else self.pmc.connect_to_specific_pmc(ip)
        if not ok:
            raise ConnectionError(f"no PMC answered at {ip}")
        if self.args.gain_mastership:
            self.pmc.gain_mastership()

    def alive(self):
        return self.pmc.check_tcp_connection()

    def meta(self):
        return {"pmc": self.pmc.get_pmc_status().name, "master": self.pmc.is_master()}

    def layout(self):
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            self.pmc.save_pmc_config_xml_file(path)
            layout = parse_layout(Path(path).read_text(encoding="latin-1"))
        finally:
            os.remove(path)
        for flyway in layout["flyways"]:
            try:
                sn = self.pmc.get_flyway_serial_number(flyway["id"])
                flyway["sn"] = f"{sn.serial_number_high}-{sn.serial_number_low}"
            except Exception:              # the serial number is a nicety; the layout is what matters
                pass
        self.flyway_ids = [f["id"] for f in layout["flyways"]]
        return layout

    def _all_xbots(self, option):
        """Every xBot's info, stamped with the middle of the call."""
        t0 = time.perf_counter()
        info = self.pmc.get_all_xbot_info(option)
        return (t0 + time.perf_counter()) / 2, {b.xbot_id: b for b in (info.all_xbot_info_list or [])}

    @staticmethod
    def _reference_at(xbot_id, ref, t_ref, t_pos, prev):
        """The reference shifted back from its own sample time to the position's."""
        x, y, z = ref.x_pos, ref.y_pos, ref.z_pos
        if prev and xbot_id in prev[1] and t_ref > prev[0]:
            k = (t_ref - t_pos) / (t_ref - prev[0])
            before = prev[1][xbot_id]
            x, y, z = x - (x - before.x_pos) * k, y - (y - before.y_pos) * k, z - (z - before.z_pos) * k
        return x, y, z

    def read(self):
        option = self.pm.ALLXBOTSFEEDBACKOPTION
        t_pos, positions = self._all_xbots(option.POSITION)
        t_ref, references = self._all_xbots(option.REFERENCE)
        prev, self._prev_ref = self._prev_ref, (t_ref, references)
        xbots = []
        for xbot_id, b in positions.items():
            err = None
            if xbot_id in references:
                rx, ry, rz = self._reference_at(xbot_id, references[xbot_id], t_ref, t_pos, prev)
                err = [(b.x_pos - rx) * M_TO_UM, (b.y_pos - ry) * M_TO_UM, (b.z_pos - rz) * M_TO_UM]
            xbots.append({
                "id": xbot_id,
                "x": b.x_pos * M_TO_MM, "y": b.y_pos * M_TO_MM, "z": b.z_pos * M_TO_MM,
                "rx": math.degrees(b.rx_pos), "ry": math.degrees(b.ry_pos), "rz": math.degrees(b.rz_pos),
                "err": err, "state": b.xbot_state.name, "kind": b.xbot_type.name,
            })
        return xbots

    def telemetry(self, xbot_ids):
        flyways = []
        for fid in self.flyway_ids:
            status = self.pmc.get_flyway_physical_status(fid)
            flyways.append({"id": fid, "w": status.power_consumption_w, "cpu": status.cpu_temp_c,
                            "amp": status.amplifier_temp_c, "motor": status.motor_temp_c})
        force = {}
        for xbot_id in xbot_ids:
            status = self.pmc.get_xbot_status(xbot_id, self.pm.FEEDBACKOPTION.FORCE)
            force[str(xbot_id)] = [float(v) for v in status.feedback_position_si]
        return telemetry_event(flyways, force)

    def close(self):
        try:
            if self.args.gain_mastership:
                self.pmc.release_mastership()
            self.pmc.disconnect_from_pmc()
        except Exception:                  # closing a dead connection: nothing left to do
            pass


MOCK_FLYWAYS = 4
MOCK_MOVER_MM = 120        # M3-06 footprint
MOCK_IDLE_W = 10.8         # an empty flyway's draw
MOCK_CARRY_W = 80          # extra draw for the flyway carrying a mover
MOCK_XML = """<planarmotorconfiguration><flw><layout><mcol>4</mcol><mrow>1</mrow>
<mapping><col><value>0</value><value>1</value><value>2</value><value>3</value></col>
<row><value>0</value><value>0</value><value>0</value><value>0</value></row></mapping>
</layout></flw></planarmotorconfiguration>"""


class MockSource:
    """Two movers over a 4 x 1 flyway (960 x 240 mm), like the bench rig."""

    def __init__(self, args=None):
        self.t0 = time.time()

    def connect(self):
        pass

    def alive(self):
        return True

    def meta(self):
        return {"pmc": "PMC_FULLCTRL", "master": False}

    def close(self):
        pass

    def layout(self):
        layout = parse_layout(MOCK_XML)
        for flyway in layout["flyways"]:
            flyway["sn"] = f"9777-{300 + flyway['id']}"
        return layout

    @staticmethod
    def _share(fid, xbots):
        """How much of each mover's footprint lies over this flyway, summed over movers."""
        x0, half = (fid - 1) * TILE_MM, MOCK_MOVER_MM / 2
        return sum(max(0.0, min(x0 + TILE_MM, b["x"] + half) - max(x0, b["x"] - half)) / MOCK_MOVER_MM
                   for b in xbots)

    def telemetry(self, xbot_ids):
        """Idle draw ~11 W per flyway plus ~80 W for each mover it carries."""
        t = time.time() - self.t0
        xbots = self.read()
        flyways = []
        for fid in range(1, MOCK_FLYWAYS + 1):
            share = self._share(fid, xbots)
            w = MOCK_IDLE_W + .6 * math.sin(t * .3 + fid) + MOCK_CARRY_W * share + 6 * share * abs(math.sin(t * .5))
            flyways.append({"id": fid, "w": w, "cpu": 35 + .06 * w + .4 * math.sin(t * .1 + fid),
                            "amp": 28.5 + .15 * w, "motor": 28 + .11 * w})
        force = {str(b["id"]): [-.4 + .3 * math.sin(t), -.5 + .2 * math.cos(t * .8), 15.76 + .15 * math.sin(t * 3.1),
                                .026, -.026, .015] for b in xbots}
        return telemetry_event(flyways, force)

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
