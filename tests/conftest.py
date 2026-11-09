# SPDX-License-Identifier: GPL-2.0-or-later
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def make_edid(vendor="GSM", product=0x5B7F, serial_number=0x01010101, name="TEST MONITOR",
              serial_text=None, size_cm=(60, 34), native=(2560, 1080, 148500), hdr=False, vrr=(40, 75)):
    """EDID 1.4 sintético (bloco base + extensão CTA opcional com HDR)."""
    b = bytearray(128)
    b[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    v = 0
    for ch in vendor:
        v = (v << 5) | (ord(ch) - 64)
    b[8], b[9] = v >> 8, v & 0xFF
    b[10], b[11] = product & 0xFF, product >> 8
    b[12:16] = serial_number.to_bytes(4, "little")
    b[16], b[17] = 1, 30
    b[18], b[19] = 1, 4
    b[21], b[22] = size_cm
    w, h, clock_khz = native
    hblank, vblank = 160, 31
    d = bytearray(18)
    clk = clock_khz // 10
    d[0], d[1] = clk & 0xFF, clk >> 8
    d[2], d[3] = w & 0xFF, hblank & 0xFF
    d[4] = ((w >> 8) << 4) | (hblank >> 8)
    d[5], d[6] = h & 0xFF, vblank & 0xFF
    d[7] = ((h >> 8) << 4) | (vblank >> 8)
    b[54:72] = d

    def text_desc(tag, text):
        t = bytearray(18)
        t[3] = tag
        raw = text.encode()[:13]
        raw += b"\x0a" if len(raw) < 13 else b""
        raw = raw.ljust(13, b" ")
        t[5:18] = raw
        return t
    b[72:90] = text_desc(0xFC, name)
    if serial_text:
        b[90:108] = text_desc(0xFF, serial_text)
    else:
        r = bytearray(18)
        r[3] = 0x10
        b[90:108] = r
    lim = bytearray(18)
    lim[3] = 0xFD
    lim[5], lim[6] = vrr
    b[108:126] = lim
    b[126] = 1 if hdr else 0
    b[127] = (256 - sum(b[:127]) % 256) % 256
    out = bytes(b)
    if hdr:
        e = bytearray(128)
        e[0], e[1] = 0x02, 0x03
        blk = bytes([0xE0 | 3, 0x06, 0x05, 0x01])   # HDR static metadata: SDR + PQ
        e[4:4 + len(blk)] = blk
        e[2] = 4 + len(blk)
        e[127] = (256 - sum(e[:127]) % 256) % 256
        out += bytes(e)
    return out


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    (tmp_path / "home").mkdir()
    return tmp_path


def fake_state(path, heads, **extra):
    data = {"backend": "wayland", "serial": 1, "manager_version": 4, "heads": heads}
    data.update(extra)
    path.write_text(json.dumps(data))
    return path


def head(name, make="", model="", serial="", modes=((1920, 1080, 60000, True),), x=0, y=0, enabled=True,
         current=None, scale=1.0, transform=0, vrr=0):
    modes = [list(m) for m in modes]
    cur = current or modes[0][:3]
    return {"name": name, "description": "", "make": make, "model": model, "serial": serial,
            "physical": [600, 340], "enabled": enabled, "x": x, "y": y, "transform": transform,
            "scale": scale, "adaptive_sync": vrr, "current": cur if enabled else None, "modes": modes}
