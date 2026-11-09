# SPDX-License-Identifier: GPL-2.0-or-later
from conftest import make_edid

from bigwmdisplay import edid, model


def out(name, w=1920, h=1080, x=0, y=0, make="", modelname="", serial="", refreshes=(60000,), **kw):
    modes = [model.Mode(w, h, r, preferred=(i == 0)) for i, r in enumerate(refreshes)]
    modes.append(model.Mode(1280, 720, 60000))
    o = model.Output(name, make, modelname, serial, modes)
    o.mode = modes[0]
    o.x, o.y = x, y
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def lay(*outs, backend="wayland"):
    return model.Layout(backend, list(outs))


# -- EDID ------------------------------------------------------------------

def test_edid_identity_like_libdisplay_info():
    e = edid.Edid(make_edid(name="LG HDR WFHD", serial_number=0x01010101))
    assert e.valid
    assert e.vendor == "GSM"
    assert e.make in ("LG Electronics", "GSM")       # nome do hwdata, se instalado
    assert e.model == "LG HDR WFHD"
    assert e.serial == "0x01010101"
    assert (e.width_cm, e.height_cm) == (60, 34)
    assert e.native[:2] == (2560, 1080)
    assert e.vrr_range == (40, 75)


def test_edid_serial_text_and_model_fallback():
    e = edid.Edid(make_edid(name="", serial_text="306AZBZ48517", product=0x1234))
    assert e.serial == "306AZBZ48517"
    assert e.model in ("0x1234", "")  or e.model == "0x1234"


def test_edid_hdr_block():
    e = edid.Edid(make_edid(hdr=True))
    assert e.hdr and "PQ (HDR10)" in e.hdr_eotfs and "SDR" in e.hdr_eotfs
    assert not edid.Edid(make_edid()).hdr


def test_edid_invalid():
    assert not edid.Edid(b"\x00" * 128).valid
    bad = bytearray(make_edid())
    bad[20] ^= 0xFF
    assert not edid.Edid(bytes(bad)).valid
    assert not edid.from_hex("zz").valid


# -- Identidade -------------------------------------------------------------

def test_identity_is_edid_not_connector():
    a = out("DP-1", make="LG", modelname="ULTRAWIDE", serial="123")
    b = out("HDMI-A-1", make="LG", modelname="ULTRAWIDE", serial="123")
    assert a.identity() == b.identity()
    assert model.set_key([a]) == model.set_key([b])


def test_identical_monitors_without_serial_use_connector():
    a = out("DP-1", make="Dell", modelname="P2419H")
    b = out("DP-2", make="Dell", modelname="P2419H")
    ids = model.identities([a, b])
    assert ids["DP-1"] != ids["DP-2"]


def test_virtual_outputs_use_connector():
    assert out("HEADLESS-1").identity() == "connector:HEADLESS-1"


# -- Validação ------------------------------------------------------------

def test_valid_side_by_side():
    assert model.validate(lay(out("A"), out("B", x=1920))) == []


def test_overlap_and_gap():
    errs = model.validate(lay(out("A"), out("B", x=1000)))
    assert errs[0][0] == "overlap"
    errs = model.validate(lay(out("A"), out("B", x=2000)))
    assert errs[0][0] == "gap"


def test_needs_one_enabled():
    a = out("A", enabled=False)
    assert model.validate(lay(a))[0][0] == "no-output"


def test_mode_must_be_announced():
    a = out("A")
    a.mode = model.Mode(1366, 768, 60000)
    assert model.validate(lay(a))[0][0] == "bad-mode"


def test_scale_rules():
    a = out("A", scale=1.5)
    assert model.validate(lay(a)) == []
    assert model.validate(lay(a, backend="x11"))[0][0] == "no-scale"
    a.scale = 0.5
    assert model.validate(lay(a))[0][0] == "bad-scale"


def test_portrait_uses_rotated_size():
    a = out("A")
    b = out("B", x=1920, transform=1)
    assert b.logical_size() == (1080, 1920)
    assert model.validate(lay(a, b)) == []


def test_mirror_needs_same_size():
    a = out("A")
    b = out("B", mirror_of="A")
    layout = lay(a, b)
    model.sync_mirrors(layout)
    assert model.validate(layout) == []
    b.mode = b.modes[-1]
    assert model.validate(layout)[0][0] == "mirror-size"


def test_transform_must_be_supported():
    a = out("A", transform=4)
    a.transforms = [0, 1, 2, 3]
    assert model.validate(lay(a))[0][0] == "bad-transform"


def test_too_big_for_x11_screen():
    layout = lay(out("A"), out("B", x=1920), backend="x11")
    layout.caps["max_size"] = (3000, 3000)
    assert model.validate(layout)[0][0] == "too-big"


# -- Encaixe ---------------------------------------------------------------

def test_snap_to_edge_and_alignment():
    assert model.snap((1925, 7, 100, 100), [(0, 0, 1920, 1080)], 32) == (1920, 0)
    assert model.snap((500, 500, 100, 100), [(0, 0, 1920, 1080)], 32) == (500, 500)


def test_attach_moves_to_nearest_touching_position():
    x, y = model.attach((2100, 50, 1920, 1080), [(0, 0, 1920, 1080)])
    assert (x, y) == (1920, 50)
    x, y = model.attach((900, 300, 1920, 1080), [(0, 0, 1920, 1080)])
    r = (x, y, 1920, 1080)
    assert model.touches(r, (0, 0, 1920, 1080)) and not model.overlaps(r, (0, 0, 1920, 1080))


def test_normalize_and_default_layout():
    a, b = out("HDMI-A-1", x=500, y=300), out("eDP-1", x=2420, y=300)
    layout = lay(a, b, backend="x11")
    model.normalize(layout)
    assert (a.x, a.y) == (0, 0)
    d = model.default_layout(layout)
    edp = d.get("eDP-1")
    assert (edp.x, edp.y) == (0, 0) and edp.primary
    assert d.get("HDMI-A-1").x == 1920


def test_same_config():
    a = lay(out("A"), out("B", x=1920))
    b = a.copy()
    assert model.same_config(a, b)
    b.get("B").y = 10
    assert not model.same_config(a, b)


def test_find_mode_tolerance():
    modes = [model.Mode(1920, 1080, 59940), model.Mode(1920, 1080, 144000)]
    assert model.find_mode(modes, 1920, 1080, 60000).refresh == 59940
    assert model.find_mode(modes, 1920, 1080, 0).refresh == 144000
    assert model.find_mode(modes, 1920, 1080, 75000) is None
