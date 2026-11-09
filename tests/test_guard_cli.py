# SPDX-License-Identifier: GPL-2.0-or-later
"""Vigia da reversão (processo separado) e a restauração/hotplug, com o
backend de teste (arquivo JSON)."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest
from conftest import ROOT, fake_state, head

from bigwmdisplay import backend, cli, guard, model, store

LAUNCHER = os.path.join(ROOT, "big-wm-display-resolution")


@pytest.fixture
def fake(cfg, tmp_path, monkeypatch):
    p = fake_state(tmp_path / "monitores.json",
                   [head("DP-1", "LG", "A", "1"), head("DP-2", "LG", "B", "2", x=1920)])
    monkeypatch.setenv("BIGWM_DISPLAY_FAKE", str(p))
    monkeypatch.setenv("BIGWM_DISPLAY_LAUNCHER", LAUNCHER)
    return p


def positions(p):
    return {h["name"]: (h["x"], h["y"], h["enabled"]) for h in json.loads(p.read_text())["heads"]}


def change(be):
    lay = be.query()
    lay.get("DP-2").y = 300
    assert model.validate(lay) == []
    return lay


def test_keep(fake):
    be = backend.get_backend()
    before = be.query()
    g = guard.Guard(before, timeout=10)
    assert guard.lock_active()
    assert be.apply(change(be))[0]
    assert g.keep() == "kept"
    assert positions(fake)["DP-2"] == (1920, 300, True)
    assert not guard.lock_active()


def test_revert_on_request(fake):
    be = backend.get_backend()
    g = guard.Guard(be.query(), timeout=10)
    be.apply(change(be))
    assert g.revert() == "reverted"
    assert positions(fake)["DP-2"] == (1920, 0, True)


def test_revert_when_interface_hangs(fake):
    """A interface trava (não responde): o vigia reverte sozinho no prazo."""
    be = backend.get_backend()
    g = guard.Guard(be.query(), timeout=1.5)
    be.apply(change(be))
    t0 = time.monotonic()
    out = g.proc.stdout.read().strip()           # sem mandar nada
    assert out.endswith("reverted")
    assert 1.2 < time.monotonic() - t0 < 6
    assert positions(fake)["DP-2"] == (1920, 0, True)


def test_revert_when_interface_dies(fake, tmp_path):
    """A interface morre (SIGKILL): o vigia, noutra sessão, reverte na hora."""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from bigwmdisplay import backend, guard\n"
        "be = backend.get_backend(); before = be.query()\n"
        "g = guard.Guard(before, timeout=30)\n"
        "lay = be.query(); lay.get('DP-2').y = 300; be.apply(lay)\n"
        "print(g.proc.pid, flush=True)\n"
        "import time; time.sleep(60)\n" % ROOT)
    ui = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    guard_pid = int(ui.stdout.readline())
    assert positions(fake)["DP-2"] == (1920, 300, True)
    ui.send_signal(signal.SIGKILL)
    ui.wait()
    for _ in range(50):
        try:
            os.kill(guard_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    assert positions(fake)["DP-2"] == (1920, 0, True)


def test_restore_applies_matching_profile(fake):
    be = backend.get_backend()
    st = store.Store()
    st.remember(change(be))
    st.save()
    assert cli.restore(be, store.Store()) == 0
    assert positions(fake)["DP-2"] == (1920, 300, True)


def test_restore_without_profile_changes_nothing(fake):
    before = fake.read_text()
    assert cli.restore(backend.get_backend(), store.Store()) == 0
    assert fake.read_text() == before


def test_hotplug_never_applies_other_set(fake):
    be = backend.get_backend()
    st = store.Store()
    st.remember(change(be))
    st.save()
    data = json.loads(fake.read_text())
    data["heads"] = data["heads"][:1]               # DP-2 saiu
    fake.write_text(json.dumps(data))
    before = fake.read_text()
    assert cli.restore(be, store.Store(), hotplug=True) == 0
    assert fake.read_text() == before


def test_hotplug_waits_for_confirmation(fake):
    be = backend.get_backend()
    st = store.Store()
    st.remember(change(be))
    st.save()
    g = guard.Guard(be.query(), timeout=10)
    try:
        before = fake.read_text()
        assert cli.restore(be, store.Store(), hotplug=True) == 0
        assert fake.read_text() == before
    finally:
        g.keep()


def test_x11_hotplug_without_profile_extends(cfg, tmp_path, monkeypatch):
    p = fake_state(tmp_path / "x.json", [head("DP-1", "A", "A", "1"),
                                         head("HDMI-1", "B", "B", "2", enabled=False)])
    monkeypatch.setenv("BIGWM_DISPLAY_FAKE", str(p))
    monkeypatch.setenv("BIGWM_DISPLAY_FAKE_SESSION", "x11")
    assert cli.restore(backend.get_backend(), store.Store(), hotplug=True) == 0
    assert positions(p)["HDMI-1"] == (1920, 0, True)


def test_failed_apply_is_reported(fake):
    be = backend.get_backend()
    st = store.Store()
    st.remember(change(be))
    st.save()
    data = json.loads(fake.read_text())
    data["fail_apply"] = True
    fake.write_text(json.dumps(data))
    assert cli.restore(be, store.Store()) == 1


def test_cli_entry_points(fake, tmp_path):
    # Em inglês, sem os catálogos do sistema (a tradução tem o test_i18n.py).
    env = dict(os.environ, LC_ALL="C.UTF-8", BIGWM_DISPLAY_LOCALEDIR=str(tmp_path / "no-locale"))
    env.pop("LANGUAGE", None)
    out = subprocess.run([sys.executable, LAUNCHER, "--show"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "DP-1" in out.stdout and "profile: none" in out.stdout
    out = subprocess.run([sys.executable, LAUNCHER, "--bogus"], capture_output=True, text=True, env=env)
    assert out.returncode == 2
