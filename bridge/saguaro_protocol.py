"""
The Saguaro wire protocol, as Fennec2 speaks it.

Discovery: each board multicasts "<tcp port>-SAGUARO-<MAC>" to 224.0.0.251:4210;
the sender's address is the board's IP (Fennec2: Discovery/SaguaroDiscovery.cs).

Session: the host sends "\\r<cmd>\\r" commands over TCP; the board answers with
protobuf McuToHostPacket frames separated by AA 55 0D 0A
(Fennec2: Communication/protobuf/fennec2.proto).

The schema is seven small messages, so a hand-written proto3 decoder keeps the
bridge standard-library only. It was checked against the official protobuf
library compiled from Fennec2's .proto, in both directions.
"""

import re
import struct

GROUP, PORT = "224.0.0.251", 4210
DELIM = b"\xaa\x55\x0d\x0a"
ANNOUNCE = re.compile(r"^([0-9]{1,5})-SAGUARO-((?:[0-9A-F]{2}:){5}[0-9A-F]{2})$")


def parse_announce(data):
    """(mac, tcp port) from a discovery datagram, or None if it isn't one."""
    match = ANNOUNCE.match(data.decode("ascii", "replace").strip("\x00\r\n\t "))
    return (match.group(2), int(match.group(1))) if match else None


def command(text):
    """A console command as the board expects it on the wire."""
    return ("\r" + text + "\r").encode("ascii")


def split_frames(buf):
    """Frames are the bytes between AA 55 0D 0A markers. Returns (frames, leftover)."""
    parts = buf.split(DELIM)
    return [p for p in parts[:-1] if p], parts[-1]


# --------------------------------------------------------------------------- decoding

VARINT, FIXED64, LENGTH, FIXED32 = 0, 1, 2, 5          # protobuf wire types
UINT64 = (1 << 64) - 1

# Message specs: {field number: (name, kind[, repeated])}, kind being a scalar
# name below or a nested spec.
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
ENDPOINT_TYPES = {1: "float", 2: "int", 3: "bool", 4: "string"}

_DEFAULTS = {"int": 0, "uint": 0, "enum": 0, "bool": False, "float": 0.0, "str": ""}
_SKIP = object()


def decode_packet(frame):
    """McuToHostPacket -> dict, or None for anything that isn't one (console text)."""
    try:
        packet = _decode_message(frame, PACKET)
    except (ValueError, IndexError):
        return None
    return packet if any(kind in packet for kind in PACKET_KINDS) else None


def _read_varint(buf, i):
    value = shift = 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, i


def _fields(buf):
    """(field number, wire type, raw value) for every field in a message."""
    i, end = 0, len(buf)
    while i < end:
        key, i = _read_varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == VARINT:
            raw, i = _read_varint(buf, i)
        elif wire == FIXED64:
            raw, i = buf[i:i + 8], i + 8
        elif wire == LENGTH:
            length, i = _read_varint(buf, i)
            raw, i = buf[i:i + length], i + length
        elif wire == FIXED32:
            raw, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type {wire}")
        if i > end:
            raise ValueError("truncated")
        yield field, wire, raw


def _as_int32(value):
    """int32 is sign-extended to 64 bits on the wire."""
    value &= UINT64
    return value - (1 << 64) if value >= 1 << 63 else value


def _decode_value(kind, wire, raw):
    """One field's value by its schema kind, or _SKIP on a wire-type mismatch (as protobuf does)."""
    if wire == VARINT:
        if kind == "int":
            return _as_int32(raw)
        if kind in ("uint", "enum"):
            return raw
        if kind == "bool":
            return bool(raw)
    elif wire == FIXED32 and kind == "float":
        return struct.unpack("<f", raw)[0]
    elif wire == LENGTH:
        if kind == "str":
            return bytes(raw).decode("utf-8", "replace")
        if isinstance(kind, dict):
            return _decode_message(raw, kind)
    return _SKIP


def _decode_message(buf, spec):
    out = {}
    for field, wire, raw in _fields(buf):
        if field not in spec:
            continue
        name, kind, repeated = spec[field][0], spec[field][1], len(spec[field]) > 2
        value = _decode_value(kind, wire, raw)
        if value is _SKIP:
            continue
        if repeated:
            out.setdefault(name, []).append(value)
        else:
            out[name] = value
    _fill_defaults(out, spec)
    return out


def _fill_defaults(out, spec):
    """proto3 omits default values on the wire: put them back (not for repeated or the oneof "value")."""
    for field_spec in spec.values():
        name, kind, repeated = field_spec[0], field_spec[1], len(field_spec) > 2
        scalar = isinstance(kind, str)                  # nested messages have no default
        if name not in out and name != "value" and not repeated and scalar and kind in _DEFAULTS:
            out[name] = _DEFAULTS[kind]
