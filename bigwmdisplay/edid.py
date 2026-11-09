# SPDX-License-Identifier: GPL-2.0-or-later
"""Leitura do EDID: identidade do monitor e o que ele declara saber fazer.

A identidade (fabricante, modelo, serial) segue as mesmas regras da
libdisplay-info, que o wlroots usa para o make/model/serial do Wayland:
assim um perfil gravado no X11 casa com o mesmo monitor no Wayland.

  fabricante  nome do código PNP (hwdata), senão as três letras
  modelo      o descritor "nome do monitor", senão "0x%04X" do código do produto
  serial      o descritor "serial", senão "0x%08X" do número de série (se não for 0)
"""

import os

PNP_IDS = ("/usr/share/hwdata/pnp.ids", "/usr/share/misc/pnp.ids")
_pnp_cache = None


def _pnp_names():
    global _pnp_cache
    if _pnp_cache is None:
        _pnp_cache = {}
        for path in PNP_IDS:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        code, _, name = line.rstrip("\n").partition("\t")
                        if len(code) == 3 and name:
                            _pnp_cache.setdefault(code, name.strip())
            except OSError:
                continue
            break
    return _pnp_cache


class Edid:
    """Campos do EDID que interessam. `valid` é False para dados quebrados."""

    def __init__(self, data):
        self.raw = bytes(data or b"")
        self.valid = False
        self.vendor = ""
        self.make = ""
        self.model = ""
        self.serial = ""
        self.product_code = 0
        self.serial_number = 0
        self.year = None
        self.width_cm = 0
        self.height_cm = 0
        self.native = None          # (largura, altura, mHz) do timing preferido
        self.vrr_range = None       # (mín Hz, máx Hz) do descritor de limites
        self.hdr = False            # bloco HDR Static Metadata na extensão CTA
        self.hdr_eotfs = []         # "SDR", "HDR", "PQ (HDR10)", "HLG"
        self.freesync = False       # bloco específico da AMD (FreeSync)
        self._parse()

    def _parse(self):
        d = self.raw
        if len(d) < 128 or d[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
            return
        if sum(d[:128]) % 256 != 0:
            return
        self.valid = True
        v = (d[8] << 8) | d[9]
        self.vendor = "".join(chr(((v >> s) & 0x1F) + 64) for s in (10, 5, 0))
        self.product_code = d[10] | (d[11] << 8)
        self.serial_number = d[12] | (d[13] << 8) | (d[14] << 16) | (d[15] << 24)
        if d[17]:
            self.year = 1990 + d[17]
        self.width_cm, self.height_cm = d[21], d[22]
        name = serial = None
        for i in range(4):
            block = d[54 + 18 * i:72 + 18 * i]
            if block[0] or block[1]:
                if i == 0 or self.native is None:
                    timing = _detailed_timing(block)
                    if timing and self.native is None:
                        self.native = timing
                continue
            tag = block[3]
            if tag == 0xFC:
                name = _descriptor_text(block)
            elif tag == 0xFF:
                serial = _descriptor_text(block)
            elif tag == 0xFD:
                self.vrr_range = (block[5], block[6])
        self.make = _pnp_names().get(self.vendor, self.vendor)
        self.model = name if name else "0x%04X" % self.product_code
        if serial:
            self.serial = serial
        elif self.serial_number:
            self.serial = "0x%08X" % self.serial_number
        for ext in range(1, min(d[126], 7) + 1):
            block = d[128 * ext:128 * (ext + 1)]
            if len(block) == 128 and block[0] == 0x02:
                self._parse_cta(block)

    def _parse_cta(self, b):
        dtd_start = b[2]
        i = 4
        end = dtd_start if 4 <= dtd_start <= 127 else 4
        while i < end:
            tag, length = b[i] >> 5, b[i] & 0x1F
            payload = b[i + 1:i + 1 + length]
            if tag == 7 and payload:
                ext_tag = payload[0]
                if ext_tag == 6 and len(payload) >= 2:
                    self.hdr = True
                    eotf = payload[1]
                    names = ("SDR", "HDR", "PQ (HDR10)", "HLG")
                    self.hdr_eotfs = [n for bit, n in enumerate(names) if eotf & (1 << bit)]
            elif tag == 3 and len(payload) >= 3:
                oui = payload[0] | (payload[1] << 8) | (payload[2] << 16)
                if oui == 0x00001A:     # AMD: FreeSync
                    self.freesync = True
            i += 1 + length

    @property
    def diagonal_inches(self):
        if not self.width_cm or not self.height_cm:
            return None
        return ((self.width_cm ** 2 + self.height_cm ** 2) ** 0.5) / 2.54

    def hex(self):
        return self.raw.hex()


def _descriptor_text(block):
    text = block[5:18].split(b"\x0a", 1)[0]
    return text.decode("cp437", errors="replace").strip()


def _detailed_timing(b):
    clock = (b[0] | (b[1] << 8)) * 10000          # Hz
    if not clock:
        return None
    hact = b[2] | ((b[4] & 0xF0) << 4)
    hblank = b[3] | ((b[4] & 0x0F) << 8)
    vact = b[5] | ((b[7] & 0xF0) << 4)
    vblank = b[6] | ((b[7] & 0x0F) << 8)
    total = (hact + hblank) * (vact + vblank)
    if not total or not hact or not vact:
        return None
    return (hact, vact, round(clock * 1000 / total))


def from_hex(text):
    try:
        return Edid(bytes.fromhex("".join(text.split())))
    except ValueError:
        return Edid(b"")


def sysfs_edid(connector, root="/sys/class/drm"):
    """EDID do conector DRM (ex.: DP-1, HDMI-A-1), como o kernel o leu."""
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in sorted(names):
        card, _, conn = name.partition("-")
        if conn == connector and card.startswith("card"):
            try:
                with open(os.path.join(root, name, "edid"), "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if data:
                return data
    return None
