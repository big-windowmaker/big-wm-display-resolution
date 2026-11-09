# SPDX-License-Identifier: GPL-2.0-or-later
"""Backend X11: o estado vem do `xrandr --verbose` e a configuração vai numa
única chamada do xrandr (que calcula o tamanho da tela e distribui os CRTCs).

O EDID chega pela propriedade EDID do RandR; a identidade do monitor é a
mesma do Wayland (ver edid.py). Escala por monitor não existe no X11 (o
--scale do xrandr só redimensiona a imagem); VRR é opção do driver do Xorg
e HDR não existe no X11: a interface diz isso em vez de oferecer controles.
"""

import re
import subprocess

from . import edid as edidmod
from . import model

ROTATIONS = ("normal", "left", "inverted", "right")

_SCREEN = re.compile(r"^Screen \d+: minimum (\d+) x (\d+), current (\d+) x (\d+), maximum (\d+) x (\d+)")
_OUTPUT = re.compile(r"^(\S+) (connected|disconnected|unknown connection)\b(.*)$")
_GEOM = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")
_MODE = re.compile(r"^  (\S+) \((0x[0-9a-f]+)\)\s+([\d.]+)MHz(.*)$")
_HLINE = re.compile(r"^\s+h: width\s+(\d+)")
_VLINE = re.compile(r"^\s+v: height\s+(\d+).*clock\s+([\d.]+)Hz")
_PROP = re.compile(r"^\t([^\t:][^:]*):\s?(.*)$")


def transform_from_x(rotation, reflection):
    r = ROTATIONS.index(rotation) if rotation in ROTATIONS else 0
    if reflection == "X axis":
        return r + 4
    if reflection == "Y axis":
        return (r + 2) % 4 + 4
    if reflection == "X and Y axis":
        return (r + 2) % 4
    return r


def transform_to_x(t):
    return ROTATIONS[t % 4], ("x" if t >= 4 else "normal")


def parse_verbose(text):
    """Saída do `xrandr --verbose` -> (tela, [saídas]); cada saída é um dict."""
    screen = None
    outputs = []
    cur = None
    mode = None
    prop = None
    for line in text.splitlines():
        m = _SCREEN.match(line)
        if m:
            screen = tuple(int(v) for v in m.groups())
            continue
        m = _OUTPUT.match(line)
        if m:
            cur = _parse_output_line(m.group(1), m.group(2), m.group(3))
            outputs.append(cur)
            mode = prop = None
            continue
        if cur is None:
            continue
        m = _MODE.match(line)
        if m:
            flags = m.group(4)
            mode = {"name": m.group(1), "id": m.group(2), "width": 0, "height": 0, "refresh": 0,
                    "current": "*current" in flags, "preferred": "+preferred" in flags,
                    "interlaced": "Interlace" in flags, "clock": float(m.group(3))}
            cur["modes"].append(mode)
            prop = None
            continue
        if mode is not None:
            m = _HLINE.match(line)
            if m:
                mode["width"] = int(m.group(1))
                continue
            m = _VLINE.match(line)
            if m:
                mode["height"] = int(m.group(1))
                mode["refresh"] = int(round(float(m.group(2)) * 1000))
                continue
        m = _PROP.match(line)
        if m:
            prop = m.group(1).strip()
            cur["props"][prop] = m.group(2).strip()
            continue
        if prop and line.startswith("\t\t"):
            val = line.strip()
            if prop == "EDID" and re.fullmatch(r"[0-9a-fA-F]+", val):
                cur["props"]["EDID"] = cur["props"].get("EDID", "") + val
            elif val.startswith("supported:") or val.startswith("range:"):
                cur["props"][prop + "#" + val.split(":", 1)[0]] = val.split(":", 1)[1].strip()
    return screen, outputs


def _parse_output_line(name, status, rest):
    out = {"name": name, "connected": status == "connected", "primary": False, "geometry": None,
           "mode_id": None, "rotation": "normal", "reflection": "none", "supported": [],
           "mm": (0, 0), "modes": [], "props": {}}
    # O que está entre parênteses no fim: rotações e reflexos suportados.
    m = re.search(r"\(([^()]*)\)(?:\s+(\d+)mm x (\d+)mm)?\s*$", rest)
    head = rest
    if m:
        out["supported"] = m.group(1).split()
        if m.group(2):
            out["mm"] = (int(m.group(2)), int(m.group(3)))
        head = rest[:m.start()]
    tokens = head.split()
    i = 0
    if i < len(tokens) and tokens[i] == "primary":
        out["primary"] = True
        i += 1
    if i < len(tokens) and _GEOM.match(tokens[i]):
        g = _GEOM.match(tokens[i])
        out["geometry"] = tuple(int(v) for v in g.groups())
        i += 1
    if i < len(tokens) and re.fullmatch(r"\(0x[0-9a-f]+\)", tokens[i]):
        out["mode_id"] = tokens[i][1:-1]
        i += 1
    if i < len(tokens) and tokens[i] in ROTATIONS:
        out["rotation"] = tokens[i]
        i += 1
    refl = " ".join(tokens[i:])
    if refl in ("X axis", "Y axis", "X and Y axis"):
        out["reflection"] = refl
    return out


def supported_transforms(supported):
    words = " ".join(supported)
    rots = [i for i, r in enumerate(ROTATIONS) if r in supported]
    if not rots:
        rots = [0]
    result = list(rots)
    if "x axis" in words:
        result += [r + 4 for r in rots]
    return sorted(set(result))


def to_layout(screen, outputs):
    outs = []
    for d in outputs:
        if not d["connected"]:
            continue
        e = edidmod.from_hex(d["props"].get("EDID", "")) if d["props"].get("EDID") else None
        if e is not None and not e.valid:
            e = None
        o = model.Output(d["name"], e.make if e else "", e.model if e else "", e.serial if e else "")
        o.edid = e
        o.physical = d["mm"]
        seen = set()
        for md in d["modes"]:
            if not md["width"]:
                continue
            key = (md["width"], md["height"], md["refresh"], md["interlaced"])
            mo = model.Mode(md["width"], md["height"], md["refresh"], md["preferred"], md["id"], md["interlaced"])
            if key in seen and not md["current"]:
                continue
            seen.add(key)
            o.modes.append(mo)
            if md["current"]:
                o.mode = mo
        o.enabled = d["geometry"] is not None and o.mode is not None
        if o.mode is None:
            o.mode = o.native_mode()
        if d["geometry"]:
            o.x, o.y = d["geometry"][2], d["geometry"][3]
        o.transform = transform_from_x(d["rotation"], d["reflection"])
        o.transforms = supported_transforms(d["supported"])
        o.primary = d["primary"]
        o.scale = 1.0
        vrr = d["props"].get("vrr_capable")
        if vrr is not None and vrr.split()[0].isdigit():
            o.vrr_capable = vrr.split()[0] == "1"
        o.extra["x11_props"] = sorted(k for k in d["props"] if "#" not in k)
        tr = d["props"].get("Transform", "").split()
        o.extra["x11_transformed"] = bool(tr) and tr[:3] != ["1.000000", "0.000000", "0.000000"]
        outs.append(o)
    # Monitores espelhados: o mesmo lugar e o mesmo tamanho de outro.
    for o in outs:
        if not o.enabled:
            continue
        for p in outs:
            if p is o or not p.enabled or p.mirror_of:
                continue
            if (p.x, p.y) == (o.x, o.y) and p.logical_size() == o.logical_size() and outs.index(p) < outs.index(o):
                o.mirror_of = p.name
                break
    caps = {"scale": False, "primary": True, "mirror": True,
            "max_size": (screen[4], screen[5]) if screen else (32767, 32767),
            "vrr_control": False, "hdr_control": False}
    lay = model.Layout("x11", outs, caps)
    lay.extra_disconnected_active = [d["name"] for d in outputs if not d["connected"] and d["geometry"]]
    return lay


class X11Backend:
    name = "x11"

    def __init__(self, xrandr="xrandr"):
        self.xrandr = xrandr

    def query(self):
        out = subprocess.run([self.xrandr, "--verbose"], capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or "xrandr falhou")
        screen, outputs = parse_verbose(out.stdout)
        return to_layout(screen, outputs)

    @staticmethod
    def arguments(layout):
        """Argumentos do xrandr para a configuração (sem o "xrandr")."""
        args = []
        for o in layout.outputs:
            args += ["--output", o.name]
            if not o.enabled or o.mode is None:
                args.append("--off")
                continue
            m = model.find_mode(o.modes, o.mode.width, o.mode.height, o.mode.refresh) or o.mode
            args += ["--mode", m.id] if m.id else ["--mode", "%dx%d" % (m.width, m.height)]
            if not m.id and m.refresh:
                args += ["--rate", "%.3f" % m.hz]
            rot, refl = transform_to_x(o.transform)
            args += ["--rotate", rot, "--reflect", refl]
            # Só desfaz uma escala/transformação que exista: drivers sem
            # RRSetCrtcTransform recusam até a identidade.
            if o.extra.get("x11_transformed"):
                args += ["--transform", "none"]
            if o.mirror_of:
                args += ["--same-as", o.mirror_of]
            else:
                args += ["--pos", "%dx%d" % (o.x, o.y)]
            if o.primary and layout.caps.get("primary"):
                args.append("--primary")
        if not any(o.primary for o in layout.enabled()):
            args.append("--noprimary")
        for name in getattr(layout, "extra_disconnected_active", []):
            args += ["--output", name, "--off"]
        return args

    def _run(self, layout, dry):
        cmd = [self.xrandr] + (["--dryrun"] if dry else []) + self.arguments(layout)
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return out.returncode == 0, (out.stderr or out.stdout).strip()

    def test(self, layout):
        return self._run(layout, True)

    def apply(self, layout):
        return self._run(layout, False)
