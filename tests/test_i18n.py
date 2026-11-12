# SPDX-License-Identifier: GPL-2.0-or-later
"""Tradução: po/POTFILES completo, .pot em dia com o código, pt_BR gerado
pelo po/make-pt_BR.py sem diferença, catálogos válidos e o resultado em
execução (pt_BR, en_US e es_ES sem catálogo, que cai no inglês).

Falha alto quando falta a lista de fontes ou um arquivo dela: um teste que
pula em silêncio por olhar o diretório errado não guarda nada."""

import gettext
import os
import re
import shutil
import subprocess
import sys

import pytest
from conftest import ROOT, fake_state, head

PO = os.path.join(ROOT, "po")
POT = os.path.join(PO, "big-wm-display-resolution.pot")
LAUNCHER = os.path.join(ROOT, "big-wm-display-resolution")
DOMAIN = "big-wm-display-resolution"
HAVE_GETTEXT = all(shutil.which(t) for t in ("xgettext", "msgfmt", "msgcmp"))
needs_gettext = pytest.mark.skipif(not HAVE_GETTEXT, reason="sem gettext (xgettext, msgfmt, msgcmp)")


def potfiles():
    path = os.path.join(PO, "POTFILES")
    assert os.path.isfile(path), "po/POTFILES não existe em %s" % ROOT
    files = [line.strip() for line in open(path, encoding="utf-8") if line.strip() and not line.startswith("#")]
    assert files, "po/POTFILES vazio"
    return files


def linguas():
    path = os.path.join(PO, "LINGUAS")
    assert os.path.isfile(path), "po/LINGUAS não existe"
    langs = [w for line in open(path, encoding="utf-8") if not line.startswith("#") for w in line.split()]
    assert langs
    return langs


def xgettext_args():
    """As palavras-chave do alvo "make po", lidas do Makefile (uma fonte só)."""
    text = open(os.path.join(ROOT, "Makefile"), encoding="utf-8").read()
    m = re.search(r"^XGETTEXT_ARGS\s*=\s*((?:.*\\\n)*.*)$", text, re.M)
    assert m, "XGETTEXT_ARGS sumiu do Makefile"
    return m.group(1).replace("\\\n", " ").split()


def test_potfiles_exist_and_cover_the_sources():
    files = potfiles()
    for f in files:
        assert os.path.isfile(os.path.join(ROOT, f)), "%s (po/POTFILES) não existe" % f
    marked = []
    for name in sorted(os.listdir(os.path.join(ROOT, "bigwmdisplay"))):
        if name.endswith(".py"):
            src = open(os.path.join(ROOT, "bigwmdisplay", name), encoding="utf-8").read()
            if re.search(r"(?<![\w.])(_|N_|P_|ngettext)\(\s*[\"']", src):
                marked.append("bigwmdisplay/" + name)
    assert marked, "nenhum fonte com _(): o teste está olhando o lugar errado"
    assert sorted(set(marked) - set(files)) == [], "fontes com texto marcado fora do po/POTFILES"


def test_no_raw_gtk_labels():
    """Rótulo, título, dica ou botão do GTK com texto cru (sem _())."""
    src = open(os.path.join(ROOT, "bigwmdisplay", "ui.py"), encoding="utf-8").read()
    raw = re.findall(r"(?:Gtk\.(?:Label|Button|CheckButton|Frame|Expander)\((?:label=)?|set_label\(|"
                     r"set_tooltip_text\(|set_title\(|add_button\()\"([^\"]*[A-Za-z]{2}[^\"]*)\"", src)
    assert raw == []


@needs_gettext
def test_pot_is_up_to_date(tmp_path):
    fresh = tmp_path / "fresh.pot"
    subprocess.run(["xgettext"] + xgettext_args() + ["-f", "po/POTFILES", "-o", str(fresh)],
                   cwd=ROOT, check=True)
    assert len(re.findall(r"^msgid ", fresh.read_text(encoding="utf-8"), re.M)) > 100
    for a, b in ((POT, fresh), (fresh, POT)):
        r = subprocess.run(["msgcmp", "--use-untranslated", "--use-fuzzy", str(a), str(b)],
                           capture_output=True, text=True)
        assert r.returncode == 0, "po/%s.pot desatualizado; rode 'make po':\n%s" % (DOMAIN, r.stderr[:800])


@needs_gettext
def test_catalogs_check_and_are_generated(tmp_path):
    for lang in linguas():
        po = os.path.join(PO, lang + ".po")
        assert os.path.isfile(po), "po/%s.po (LINGUAS) não existe" % lang
        # Um catálogo por chamada: vários juntos se fundem e acusam duplicatas.
        r = subprocess.run(["msgfmt", "--check", "--statistics", "-o", "/dev/null", po],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "não traduzidas" not in r.stderr and "untranslated" not in r.stderr, r.stderr
        assert "fuzzy" not in r.stderr and "aproximadas" not in r.stderr, r.stderr
    gen = tmp_path / "pt_BR.po"
    subprocess.run([sys.executable, "-I", os.path.join(PO, "make-pt_BR.py"), POT, str(gen)], check=True)
    assert gen.read_text(encoding="utf-8") == open(os.path.join(PO, "pt_BR.po"), encoding="utf-8").read(), \
        "po/pt_BR.po difere do que o make-pt_BR.py gera; rode 'make po'"


@pytest.fixture(scope="module")
def localedir(tmp_path_factory):
    if not shutil.which("msgfmt"):
        pytest.skip("sem msgfmt")
    d = tmp_path_factory.mktemp("locale")
    for lang in linguas():
        out = d / lang / "LC_MESSAGES"
        out.mkdir(parents=True)
        subprocess.run(["msgfmt", "-c", "-o", str(out / (DOMAIN + ".mo")), os.path.join(PO, lang + ".po")],
                       check=True)
    return d


def _env(localedir, lang, tmp_path):
    env = dict(os.environ, LANG=lang, BIGWM_DISPLAY_LOCALEDIR=str(localedir),
               XDG_CONFIG_HOME=str(tmp_path / "config"), HOME=str(tmp_path))
    for k in ("LANGUAGE", "LC_ALL", "LC_MESSAGES"):
        env.pop(k, None)
    return env


@pytest.mark.parametrize("lang, word", [("pt_BR.UTF-8", "Uso:"), ("en_US.UTF-8", "Usage:"),
                                        ("es_ES.UTF-8", "Usage:")])
def test_help_in_the_user_language(localedir, tmp_path, lang, word):
    out = subprocess.run([sys.executable, LAUNCHER, "--help"], capture_output=True, text=True,
                         env=_env(localedir, lang, tmp_path))
    assert out.returncode == 0 and out.stdout.startswith(word), out.stdout[:200]
    # Opções e comandos não se traduzem.
    for opt in ("--restore", "--show", "--profiles", "--apply-profile", "big-wm-display-resolution"):
        assert opt in out.stdout


def test_show_in_pt_br(localedir, tmp_path):
    fake = fake_state(tmp_path / "monitores.json", [head("DP-1", "LG", "A", "1")])
    env = _env(localedir, "pt_BR.UTF-8", tmp_path)
    env["BIGWM_DISPLAY_FAKE"] = str(fake)
    out = subprocess.run([sys.executable, LAUNCHER, "--show"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "sessão: " in out.stdout and "perfil: nenhum para este conjunto de monitores" in out.stdout


def test_plural_forms_pt_br(localedir):
    """(n > 1): 0 e 1 no singular, como no GTK e no coreutils instalados."""
    t = gettext.translation(DOMAIN, str(localedir), languages=["pt_BR"])
    one, many = ("Reverting to the previous configuration in %d second.",
                 "Reverting to the previous configuration in %d seconds.")
    assert t.ngettext(one, many, 1) % 1 == "Voltando à configuração anterior em 1 segundo."
    assert t.ngettext(one, many, 15) % 15 == "Voltando à configuração anterior em 15 segundos."
    assert t.ngettext("%d monitor", "%d monitors", 0) % 0 == "0 monitor"
    assert t.ngettext("%d monitor", "%d monitors", 2) % 2 == "2 monitores"
    assert t.gettext("Keep these display settings?") == "Manter estas configurações de monitores?"
    header = t._info  # noqa: SLF001 - cabeçalho do .mo
    assert header.get("plural-forms") == "nplurals=2; plural=(n > 1);"
