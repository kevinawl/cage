"""
The Saguaro wire protocol, as Fennec2 speaks it.

Discovery: each board multicasts "<tcp port>-SAGUARO-<MAC>" to 224.0.0.251:4210;
the sender's address is the board's IP (Fennec2: Discovery/SaguaroDiscovery.cs).

Session: the host sends "\\r<cmd>\\r" commands over TCP; the board answers with
protobuf McuToHostPacket frames separated by AA 55 0D 0A
(Fennec2: Communication/protobuf/fennec2.proto).

The schema is seven small messages, so a hand-written proto3 codec keeps the
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
ENDPOINT_TYPE_CODES = {name: code for code, name in ENDPOINT_TYPES.items()}

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


# --------------------------------------------------------------------------- encoding
# The board's side of the protocol: used by fake_saguaro.py.

def encode_packet(timestamp_ms, kind, body):
    if kind not in _ENCODERS:
        raise ValueError(kind)
    return _varint_field(1, timestamp_ms) + _ENCODERS[kind](body)


def _encode_varint(value):
    value &= UINT64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _varint_field(field, value):
    return _encode_varint(field << 3 | VARINT) + _encode_varint(value)


def _bytes_field(field, data):
    return _encode_varint(field << 3 | LENGTH) + _encode_varint(len(data)) + data


def _float_field(field, value):
    return _encode_varint(field << 3 | FIXED32) + struct.pack("<f", value)


def _encode_mcu_name(body):
    return _bytes_field(4, _bytes_field(1, body["device_name"].encode()) +
                        _bytes_field(2, body["firmware_version"].encode()))


def _encode_endpoint_info(endpoint):
    return _bytes_field(1, _varint_field(1, endpoint["sensor_id"]) +
                        (_varint_field(2, 1) if endpoint["active"] else b"") +
                        _bytes_field(3, endpoint["name"].encode()) +
                        _bytes_field(4, endpoint.get("name_type", "").encode()) +
                        _varint_field(5, ENDPOINT_TYPE_CODES[endpoint["type"]]))


def _encode_ep_man_list(endpoints):
    return _bytes_field(5, b"".join(_encode_endpoint_info(e) for e in endpoints))


def _encode_endpoint_data(reading):
    value = reading["value"]
    if isinstance(value, bool):                # before int: bool is an int in Python
        encoded = _varint_field(5, int(value))
    elif isinstance(value, float):
        encoded = _float_field(3, value)
    elif isinstance(value, int):
        encoded = _varint_field(4, value)
    else:
        encoded = _bytes_field(6, str(value).encode())
    return _bytes_field(1, _varint_field(1, reading["sensor_id"]) + _varint_field(2, 1) + encoded)


def _encode_telemetry(readings):
    return _bytes_field(2, b"".join(_encode_endpoint_data(r) for r in readings))


def _encode_ack(body):
    return _bytes_field(3, _varint_field(1, body.get("command_id", 0)) + _varint_field(2, 1))


_ENCODERS = {"mcu_name": _encode_mcu_name, "ep_man_list": _encode_ep_man_list,
             "telemetry": _encode_telemetry, "ack": _encode_ack}
