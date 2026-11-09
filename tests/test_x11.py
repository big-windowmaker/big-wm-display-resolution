# SPDX-License-Identifier: GPL-2.0-or-later
from conftest import make_edid

from bigwmdisplay import backend_x11, model


def edid_lines(data):
    h = data.hex()
    return "".join("\t\t%s\n" % h[i:i + 32] for i in range(0, len(h), 32))


VERBOSE = """Screen 0: minimum 8 x 8, current 4480 x 1440, maximum 16384 x 16384
DisplayPort-0 connected primary 2560x1440+0+0 (0x4a) normal (normal left inverted right x axis y axis) 597mm x 336mm
\tIdentifier: 0x56
\tTimestamp:  1234
\tSubpixel:   unknown
\tGamma:      1.0:1.0:1.0
\tBrightness: 1.0
\tClones:
\tCRTC:       0
\tCRTCs:      0 1 2 3
\tTransform:  1.000000 0.000000 0.000000
\t            0.000000 1.000000 0.000000
\t            0.000000 0.000000 1.000000
\t           filter:
\tEDID:
{edid1}\tvrr_capable: 1
\t\trange: (0, 1)
\tnon-desktop: 0
\t\tsupported: 0, 1
  2560x1440 (0x4a) 241.500MHz +HSync -VSync *current +preferred
        h: width  2560 start 2608 end 2640 total 2720 skew    0 clock  88.79KHz
        v: height 1440 start 1443 end 1448 total 1481           clock  59.95Hz
  2560x1440 (0x4b) 586.590MHz +HSync -VSync
        h: width  2560 start 2568 end 2600 total 2640 skew    0 clock 222.19KHz
        v: height 1440 start 1446 end 1454 total 1543           clock 144.00Hz
  1920x1080 (0x4c) 148.500MHz +HSync +VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  67.50KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  60.00Hz
  1920x1080i (0x4d) 74.250MHz +HSync +VSync Interlace
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  33.75KHz
        v: height 1080 start 1084 end 1094 total 1125           clock  60.00Hz
HDMI-A-0 connected 1080x1920+2560+0 (0x60) left X axis (normal left inverted right x axis y axis) 527mm x 296mm
\tEDID:
{edid2}\tCRTC:       1
  1920x1080 (0x60) 148.500MHz +HSync +VSync *current +preferred
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  67.50KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  60.00Hz
DisplayPort-1 disconnected (normal left inverted right x axis y axis)
\tIdentifier: 0x57
DVI-D-0 connected (normal left inverted right x axis y axis)
  1280x1024 (0x70) 108.000MHz +HSync +VSync +preferred
        h: width  1280 start 1328 end 1440 total 1688 skew    0 clock  63.98KHz
        v: height 1024 start 1025 end 1028 total 1066           clock  60.02Hz
"""


def sample():
    text = VERBOSE.replace("{edid1}", edid_lines(make_edid(name="QHD", serial_text="S1"))).replace(
        "{edid2}", edid_lines(make_edid(vendor="DEL", name="P2419H", serial_number=7)))
    screen, outs = backend_x11.parse_verbose(text)
    return backend_x11.to_layout(screen, outs)


def test_parse_outputs_modes_and_identity():
    lay = sample()
    assert [o.name for o in lay.outputs] == ["DisplayPort-0", "HDMI-A-0", "DVI-D-0"]
    dp = lay.get("DisplayPort-0")
    assert dp.primary and dp.enabled and dp.mode.id == "0x4a"
    assert dp.mode.refresh == 59950
    assert {m.refresh for m in dp.modes if m.size == (2560, 1440)} == {59950, 144000}
    assert any(m.interlaced for m in dp.modes)
    assert dp.model == "QHD" and dp.serial == "S1"
    assert dp.vrr_capable is True
    assert dp.physical == (597, 336)
    assert lay.caps["max_size"] == (16384, 16384) and not lay.caps["scale"]


def test_rotation_reflection_and_disabled():
    lay = sample()
    hdmi = lay.get("HDMI-A-0")
    assert hdmi.transform == 5              # left + X axis
    assert hdmi.logical_size() == (1080, 1920)
    assert hdmi.serial == "0x00000007"
    dvi = lay.get("DVI-D-0")
    assert not dvi.enabled and dvi.mode.size == (1280, 1024)
    assert dvi.vrr_capable is None
    assert set(dvi.transforms) == set(range(8))


def test_transform_round_trip():
    for t in range(8):
        rot, refl = backend_x11.transform_to_x(t)
        x_refl = {"x": "X axis", "normal": "none"}[refl]
        assert backend_x11.transform_from_x(rot, x_refl) == t
    assert backend_x11.transform_from_x("normal", "Y axis") == 6
    assert backend_x11.transform_from_x("left", "X and Y axis") == 3


def test_arguments_single_call():
    lay = sample()
    assert model.validate(lay) == []
    dvi = lay.get("DVI-D-0")
    dvi.enabled = True
    dvi.x, dvi.y = 3640, 0
    args = backend_x11.X11Backend.arguments(lay)
    s = " ".join(args)
    assert "--output DisplayPort-0 --mode 0x4a --rotate normal --reflect normal --pos 0x0 --primary" in s
    assert "--output HDMI-A-0 --mode 0x60 --rotate left --reflect x" in s
    assert "--output DVI-D-0 --mode 0x70" in s and "--pos 3640x0" in s


def test_mirror_and_off():
    lay = sample()
    hdmi = lay.get("HDMI-A-0")
    hdmi.enabled = False
    args = " ".join(backend_x11.X11Backend.arguments(lay))
    assert "--output HDMI-A-0 --off" in args
    lay = sample()
    dvi = lay.get("DVI-D-0")
    dvi.enabled, dvi.mirror_of = True, "DisplayPort-0"
    args = " ".join(backend_x11.X11Backend.arguments(lay))
    assert "--same-as DisplayPort-0" in args
    assert "--noprimary" not in args


def test_transform_reset_only_when_scaled():
    lay = sample()
    assert "--transform" not in backend_x11.X11Backend.arguments(lay)
    text = VERBOSE.replace("{edid1}", "").replace("{edid2}", "").replace(
        "\tTransform:  1.000000 0.000000 0.000000", "\tTransform:  1.500000 0.000000 0.000000")
    lay = backend_x11.to_layout(*backend_x11.parse_verbose(text))
    args = backend_x11.X11Backend.arguments(lay)
    assert args[args.index("DisplayPort-0") + 1:].index("--transform") >= 0


def test_xvfb_style_output():
    text = """Screen 0: minimum 1 x 1, current 1600 x 900, maximum 1600 x 900
screen connected 1600x900+0+0 (0x3a) normal (normal) 0mm x 0mm
\tIdentifier: 0x3c
  1600x900 (0x3a)  0.000MHz *current
        h: width  1600 start    0 end    0 total    0 skew    0 clock   0.00KHz
        v: height  900 start    0 end    0 total    0           clock   0.00Hz
"""
    lay = backend_x11.to_layout(*backend_x11.parse_verbose(text))
    o = lay.get("screen")
    assert o.enabled and o.mode.size == (1600, 900) and o.transforms == [0]
    assert o.identity() == "connector:screen"
