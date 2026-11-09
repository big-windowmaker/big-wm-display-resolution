# SPDX-License-Identifier: GPL-2.0-or-later
"""Backend Wayland: só pelas interfaces do compositor (wlr-output-management,
pelo big-wm-display-helper). Nunca xrandr no XWayland.

O EDID (para a informação e para HDR/VRR declarados) vem do sysfs do DRM,
pelo nome do conector, que o wlroots usa igual ao do kernel.
"""

import json
import os
import shutil
import subprocess

from . import edid as edidmod
from . import model

LIBEXEC_DIRS = ("/usr/lib/big-wm-display-resolution",)


def helper_path():
    env = os.environ.get("BIGWM_DISPLAY_HELPER")
    if env:
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for d in (os.path.join(here, "build"),) + LIBEXEC_DIRS:
        p = os.path.join(d, "big-wm-display-helper")
        if os.access(p, os.X_OK):
            return p
    return shutil.which("big-wm-display-helper") or "big-wm-display-helper"


def to_layout(data, edid_reader=edidmod.sysfs_edid):
    outs = []
    for h in data.get("heads", []):
        o = model.Output(h["name"], h.get("make", ""), h.get("model", ""), h.get("serial", ""))
        o.description = h.get("description", "")
        o.physical = tuple(h.get("physical") or (0, 0))
        for w, ht, r, pref in h.get("modes", []):
            o.modes.append(model.Mode(w, ht, r, pref))
        cur = h.get("current")
        o.enabled = bool(h.get("enabled"))
        if cur:
            o.mode = model.find_mode(o.modes, cur[0], cur[1], cur[2]) if o.modes else None
            if o.mode is None:
                o.mode = model.Mode(cur[0], cur[1], cur[2])
                if not o.modes:
                    o.modes.append(o.mode)
        if o.mode is None:
            o.mode = o.native_mode()
        o.x, o.y = h.get("x", 0), h.get("y", 0)
        o.transform = int(h.get("transform", 0))
        o.scale = float(h.get("scale", 1.0))
        vrr = h.get("adaptive_sync", -1)
        o.vrr = None if vrr in (-1, None) else bool(vrr)
        raw = edid_reader(o.name) if edid_reader else None
        if raw:
            e = edidmod.Edid(raw)
            if e.valid:
                o.edid = e
        outs.append(o)
    for o in outs:
        if not o.enabled:
            continue
        for p in outs:
            if p is o or not p.enabled or p.mirror_of or outs.index(p) > outs.index(o):
                continue
            if (p.x, p.y) == (o.x, o.y) and p.logical_size() == o.logical_size():
                o.mirror_of = p.name
                break
    caps = {"scale": True, "primary": False, "mirror": True, "max_size": (32767, 32767),
            "vrr_control": int(data.get("manager_version", 0)) >= 4, "hdr_control": False}
    return model.Layout("wayland", outs, caps)


def config_lines(layout):
    lines = []
    for o in layout.outputs:
        if not o.enabled or o.mode is None:
            m = o.mode or model.Mode(0, 0, 0)
            lines.append("%s\t0\t%d\t%d\t%d\t%d\t%d\t%d\t%.4f\t-" % (o.name, m.width, m.height, m.refresh,
                                                                    o.x, o.y, o.transform, o.scale))
            continue
        vrr = "-" if o.vrr is None else ("1" if o.vrr else "0")
        lines.append("%s\t1\t%d\t%d\t%d\t%d\t%d\t%d\t%.4f\t%s" % (
            o.name, o.mode.width, o.mode.height, o.mode.refresh, o.x, o.y, o.transform, o.scale, vrr))
    return "\n".join(lines) + "\n"


class WaylandBackend:
    name = "wayland"

    def __init__(self, helper=None):
        self.helper = helper or helper_path()

    def query(self, probe_vrr=False):
        out = subprocess.run([self.helper, "wl-dump"], capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or "big-wm-display-helper falhou")
        layout = to_layout(json.loads(out.stdout))
        if probe_vrr:
            self.probe_vrr(layout)
        return layout

    def probe_vrr(self, layout):
        """VRR que dá para mudar: o compositor aceita (no teste do protocolo)
        a configuração com a taxa variável trocada."""
        if not layout.caps.get("vrr_control"):
            for o in layout.outputs:
                o.vrr_capable = False if o.vrr is None else o.vrr_capable
            return
        for o in layout.outputs:
            if not o.enabled or o.vrr is None:
                continue
            trial = layout.copy()
            t = trial.get(o.name)
            t.vrr = not o.vrr
            ok, _ = self.test(trial)
            o.vrr_capable = ok

    def _run(self, layout, test):
        cmd = [self.helper, "wl-apply"] + (["--test"] if test else [])
        out = subprocess.run(cmd, input=config_lines(layout), capture_output=True, text=True, timeout=30)
        result = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
        return out.returncode == 0 and result == "succeeded", (out.stderr.strip() or result)

    def test(self, layout):
        return self._run(layout, True)

    def apply(self, layout):
        return self._run(layout, False)
