# SPDX-License-Identifier: GPL-2.0-or-later
"""Barras de rolagem no padrão WINGs: imagens e CSS (sem display)."""
import re
import struct
import zlib
from urllib.parse import unquote

from bigwmdisplay import nextscroll
from bigwmdisplay.ui import CSS, PALETTES


def decode(data):
    """PNG RGBA 8 bits sem filtro (o que nextscroll.png grava) -> linhas de pixels."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    pos, idat = 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        if kind == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = 1 + 4 * w
    return [[tuple(raw[y * stride + 1 + 4 * x:y * stride + 5 + 4 * x]) for x in range(w)] for y in range(h)]


def opaque(rows):
    return ["".join("#" if px[3] else "." for px in row) for row in rows]


def test_arrows_point_the_right_way(tmp_path):
    imgs = nextscroll.Images(str(tmp_path), "t")
    urls = nextscroll.arrows(PALETTES["light"], imgs)
    shapes = {}
    for d in ("up", "down", "left", "right"):
        with open(unquote(urls[(d, "normal")][len("file://"):]), "rb") as f:
            shapes[d] = opaque(decode(f.read()))
    # cima: ponta na primeira linha, base cheia na última
    assert shapes["up"][0].count("#") == 1 and shapes["up"][-1].count("#") == 9
    assert shapes["down"] == shapes["up"][::-1]
    # esquerda: ponta na primeira coluna
    assert [r[0] for r in shapes["left"]].count("#") == 1
    assert [r[-1] for r in shapes["left"]].count("#") == 9
    assert shapes["right"] == [r[::-1] for r in shapes["left"]]


def test_css_both_palettes(tmp_path):
    for mode, pal in PALETTES.items():
        css = nextscroll.css(pal, mode, str(tmp_path))
        # todas as imagens existem e são PNG válidos
        urls = re.findall(r'url\("file://([^"]+)"\)', css)
        assert len(urls) >= 14
        for u in urls:
            with open(unquote(u), "rb") as f:
                decode(f.read())
        # vertical: setas juntas embaixo; horizontal: juntas à esquerda (WINGs)
        vert = css[css.index("#bwmdr scrollbar.vertical {"):]
        vert = vert[:vert.index("}")]
        assert "has-backward-stepper: false" in vert and "has-secondary-backward-stepper: true" in vert
        assert "has-forward-stepper: true" in vert and "has-secondary-forward-stepper: false" in vert
        horiz = css[css.index("#bwmdr scrollbar.horizontal {"):]
        horiz = horiz[:horiz.index("}")]
        assert "has-backward-stepper: true" in horiz and "has-secondary-forward-stepper: true" in horiz
        assert "has-forward-stepper: false" in horiz and "has-secondary-backward-stepper: false" in horiz
        # nada de hover diferente (o WINGs não tem), pressionado sim
        assert "scrollbar button:active" in css


def test_generic_button_rule_is_overridden():
    """A regra genérica "#bwmdr button" (padding 2px 8px) é a causa dos botões
    largos e soltos da calha: as regras da barra precisam ser mais específicas
    e zerar padding/margem."""
    assert "padding: 2px 8px" in CSS
    css = nextscroll.CSS
    block = css[css.index("#bwmdr scrollbar button, #bwmdr scrollbar button:hover {{"):]
    block = block[:block.index("}}")]
    assert "padding: 0" in block and "margin: 0" in block


def test_dark_arrows_are_light(tmp_path):
    """No tema escuro a seta usa a cor do texto (clara); no claro, preto."""
    for mode, expect_light in (("dark", True), ("light", False)):
        imgs = nextscroll.Images(str(tmp_path), mode)
        url = nextscroll.arrows(PALETTES[mode], imgs)[("up", "normal")]
        with open(unquote(url[len("file://"):]), "rb") as f:
            rows = decode(f.read())
        r, g, b, a = rows[1][4]          # corpo da seta ('#')
        assert a == 255 and ((r + g + b) / 3 > 128) == expect_light
