# SPDX-License-Identifier: GPL-2.0-or-later
import json
import os

from conftest import fake_state, head

from bigwmdisplay import backend, model, store


def layout_from(tmp_path, heads, session="wayland"):
    p = fake_state(tmp_path / ("state-%d.json" % len(heads)), heads)
    return backend.FakeBackend(str(p), session).query()


TWO = [head("DP-1", "LG", "ULTRAWIDE", "AAA", modes=((3440, 1440, 59973, True), (2560, 1080, 60000, False))),
       head("HDMI-A-1", "Dell", "P2419H", "BBB", x=3440)]


def test_save_load_roundtrip_and_format(cfg, tmp_path):
    lay = layout_from(tmp_path, TWO)
    st = store.Store()
    prof = st.remember(lay)
    st.save()
    data = json.loads(open(st.path).read())
    assert data["format"] == "big-wm-display-resolution" and data["version"] == 1
    assert os.stat(st.path).st_mode & 0o777 == 0o600
    st2 = store.Store()
    assert st2.get(prof["id"])["outputs"][0]["identity"]["serial"] == "AAA"
    assert st2.best_for(lay, "wayland")["id"] == prof["id"]


def test_backup_is_last_good_and_used_when_main_breaks(cfg, tmp_path):
    lay = layout_from(tmp_path, TWO)
    st = store.Store()
    st.add(lay, "um")
    st.save()
    st.add(lay, "dois")
    st.save()
    backup = json.loads(open(st.backup).read())
    assert [p["name"] for p in backup["profiles"]] == ["um"]
    with open(st.path, "w") as f:
        f.write("{quebrado")
    st3 = store.Store()
    assert st3.loaded_from == st.backup
    assert [p["name"] for p in st3.profiles] == ["um"]


def test_unknown_future_version_is_not_loaded(cfg):
    st = store.Store()
    os.makedirs(st.dir)
    with open(st.path, "w") as f:
        json.dump({"format": "big-wm-display-resolution", "version": 99, "profiles": []}, f)
    assert not store.Store().load()


def test_profile_follows_identity_not_connector(cfg, tmp_path):
    lay = layout_from(tmp_path, TWO)
    lay.get("DP-1").mode = model.find_mode(lay.get("DP-1").modes, 2560, 1080, 60000)
    lay.get("HDMI-A-1").x = 2560
    st = store.Store()
    prof = st.add(lay, "trabalho")
    # Os cabos trocaram de porta: os conectores mudam, os monitores não.
    swapped = [dict(TWO[0], name="HDMI-A-2"), dict(TWO[1], name="DP-3")]
    lay2 = layout_from(tmp_path, swapped)
    new = store.apply_profile(prof, lay2)
    assert new is not None
    assert new.get("HDMI-A-2").mode.size == (2560, 1080)
    assert new.get("DP-3").x == 2560


def test_profile_never_applies_to_other_set(cfg, tmp_path):
    three = TWO + [head("DP-2", "LG", "HDR WFHD", "CCC", x=5360)]
    lay3 = layout_from(tmp_path, three)
    st = store.Store()
    prof = st.remember(lay3)
    lay1 = layout_from(tmp_path, TWO[:1])
    assert store.apply_profile(prof, lay1) is None
    assert st.best_for(lay1, "wayland") is None
    lay2 = layout_from(tmp_path, TWO)
    assert st.best_for(lay2, "wayland") is None


def test_profile_with_unannounced_mode_is_refused(cfg, tmp_path):
    lay = layout_from(tmp_path, TWO)
    st = store.Store()
    prof = st.add(lay, "x")
    prof["outputs"][0]["mode"]["width"] = 1234
    assert store.apply_profile(prof, lay) is None


def test_sessions_have_separate_auto_profiles(cfg, tmp_path):
    lay = layout_from(tmp_path, TWO)
    st = store.Store()
    w = st.remember(lay, session="wayland")
    x = st.remember(lay, session="x11")
    assert w["id"] != x["id"]
    assert st.best_for(lay, "x11")["id"] == x["id"]
    # Lembrar de novo substitui o automático (não duplica).
    st.remember(lay, session="x11")
    assert len([p for p in st.profiles if p["kind"] == "auto"]) == 2


def test_last_applied_wins(cfg, tmp_path):
    lay = layout_from(tmp_path, TWO)
    st = store.Store()
    st.remember(lay)
    custom = st.add(lay, "apresentação")
    assert st.best_for(lay, "wayland")["kind"] == "auto"
    st.mark_applied(lay, custom)
    assert st.best_for(lay, "wayland")["id"] == custom["id"]


def test_rename_delete(cfg, tmp_path):
    lay = layout_from(tmp_path, TWO)
    st = store.Store()
    p = st.add(lay, "a")
    st.mark_applied(lay, p)
    assert st.rename(p["id"], "  novo  ") and st.get(p["id"])["name"] == "novo"
    assert not st.rename(p["id"], "   ")
    assert st.delete(p["id"]) and st.get(p["id"]) is None
    assert st.data["last_applied"] == {}


def test_mirror_and_scale_survive(cfg, tmp_path):
    heads = [head("DP-1", "A", "M", "1"), head("DP-2", "B", "N", "2", x=1920)]
    lay = layout_from(tmp_path, heads)
    lay.get("DP-2").mirror_of = "DP-1"
    lay.get("DP-1").scale = 1.25
    lay.get("DP-2").scale = 1.25
    model.sync_mirrors(lay)
    st = store.Store()
    p = st.add(lay, "espelho")
    new = store.apply_profile(p, layout_from(tmp_path, heads))
    assert new.get("DP-2").mirror_of == "DP-1" and new.get("DP-1").scale == 1.25
    assert model.validate(new) == []
