#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Gera po/pt_BR.po a partir do .pot e das traduções abaixo (make po).
import ast
import sys

T = {
 "Landscape": "Paisagem",
 "Portrait (rotated left)": "Retrato (girado à esquerda)",
 "Landscape (upside down)": "Paisagem (de cabeça para baixo)",
 "Portrait (rotated right)": "Retrato (girado à direita)",
 "At least one monitor must stay on.": "Pelo menos um monitor precisa ficar ligado.",
 "%(name)s has no resolution.": "%(name)s está sem resolução.",
 "%(name)s does not announce the mode %(mode)s.": "%(name)s não anuncia o modo %(mode)s.",
 "%(name)s does not support this orientation.": "%(name)s não aceita esta orientação.",
 "%(name)s: per-monitor scale does not exist on X11.": "%(name)s: escala por monitor não existe no X11.",
 "%(name)s: the scale must be between 1 and 3.": "%(name)s: a escala precisa ficar entre 1 e 3.",
 "%(name)s mirrors a monitor that is off or is itself a mirror.": "%(name)s espelha um monitor desligado ou que já é um espelho.",
 "%(name)s and %(source)s need the same resolution to mirror.": "%(name)s e %(source)s precisam da mesma resolução para espelhar.",
 "%(a)s and %(b)s overlap.": "%(a)s e %(b)s estão sobrepostos.",
 "The monitors must touch each other: there is a gap between them.": "Os monitores precisam se encostar: há um vão entre eles.",
 "Negative positions are not allowed.": "Posições negativas não são permitidas.",
 "The arrangement (%(w)dx%(h)d) exceeds the maximum screen size (%(mw)dx%(mh)d).": "A disposição (%(w)dx%(h)d) passa do tamanho máximo da tela (%(mw)dx%(mh)d).",
 "Only one monitor can be the primary one.": "Só um monitor pode ser o principal.",
 "%.2f Hz": "%.2f Hz",
 "unknown": "desconhecido",
 "recommended": "recomendada",
 "Could not read the monitors: %s": "Não foi possível ler os monitores: %s",
 "Profile:": "Perfil:",
 "Save as…": "Salvar como…",
 "Rename…": "Renomear…",
 "Delete": "Excluir",
 "Identify": "Identificar",
 "Shows the name of each monitor on its screen": "Mostra o nome de cada monitor na própria tela",
 "Side by side": "Lado a lado",
 "Arranges the monitors in a row, left to right, aligned at the top": "Põe os monitores em fila, da esquerda para a direita, alinhados no topo",
 "Defaults": "Padrão",
 "All monitors on, at their native resolution, side by side": "Todos os monitores ligados, na resolução nativa, lado a lado",
 "Monitor": "Monitor",
 "Monitor:": "Monitor:",
 "On": "Ligado",
 "Primary monitor": "Monitor principal",
 "Use:": "Uso:",
 "Resolution:": "Resolução:",
 "Refresh rate:": "Taxa de atualização:",
 "Scale:": "Escala:",
 "Mirror image (reflect)": "Imagem espelhada (reflexo)",
 "Orientation:": "Orientação:",
 "Position:": "Posição:",
 "Variable refresh rate (VRR / Adaptive Sync)": "Taxa de atualização variável (VRR / Adaptive Sync)",
 "VRR:": "VRR:",
 "HDR:": "HDR:",
 "Information": "Informações",
 "EDID": "EDID",
 "Reset": "Redefinir",
 "Discards the changes not yet applied": "Descarta as mudanças ainda não aplicadas",
 "Close": "Fechar",
 "Apply": "Aplicar",
 "Current configuration": "Configuração atual",
 "Defaults (all on, side by side)": "Padrão (todos ligados, lado a lado)",
 "Saved automatically": "Salvo automaticamente",
 "On Wayland, wlmaker has no configurable primary monitor: the first one in the arrangement holds the Dock.": "No Wayland o wlmaker não tem monitor principal configurável: o primeiro da disposição fica com o Dock.",
 "Panels, the Dock and new windows prefer this monitor": "Painéis, o Dock e as janelas novas preferem este monitor",
 "Extend the desktop": "Estender a área de trabalho",
 "Mirror %s": "Espelhar %s",
 "Fractional scales reach applications that support fractional-scale; the others are drawn at 1× and enlarged.": "Escalas fracionárias chegam aos aplicativos com fractional-scale; os outros são desenhados em 1× e ampliados.",
 "X11 has no per-monitor scale (xrandr --scale only stretches the picture). Use the GTK/Qt scale for larger text.": "O X11 não tem escala por monitor (o xrandr --scale só estica a imagem). Para texto maior, use a escala do GTK/Qt.",
 "This monitor's driver does not offer reflection": "O driver deste monitor não oferece reflexo",
 "The EDID declares %d–%d Hz.": "O EDID declara %d–%d Hz.",
 "FreeSync block present.": "Tem o bloco FreeSync.",
 "The driver does not report whether this output supports VRR (no vrr_capable property).": "O driver não informa se esta saída aceita VRR (sem a propriedade vrr_capable).",
 "The driver reports this output as VRR capable.": "O driver informa que esta saída aceita VRR.",
 "The driver reports this output as not VRR capable.": "O driver informa que esta saída não aceita VRR.",
 "On X11 VRR is a driver option (Option \"VariableRefresh\" in xorg.conf), not a per-monitor setting.": "No X11 o VRR é opção do driver (Option \"VariableRefresh\" no xorg.conf), não um ajuste por monitor.",
 "The compositor does not report adaptive sync (output management older than version 4).": "O compositor não informa a taxa variável (gerenciamento de saídas anterior à versão 4).",
 "off": "desligado",
 "The monitor declares HDR (%s).": "O monitor declara HDR (%s).",
 "The monitor does not declare HDR in its EDID.": "O monitor não declara HDR no EDID.",
 "No EDID: HDR capability unknown.": "Sem EDID: não se sabe se há HDR.",
 "X11 has no HDR output.": "O X11 não tem saída HDR.",
 "wlmaker does not drive HDR outputs, and output management has no HDR setting: there is nothing to turn on here.": "O wlmaker não liga saídas em HDR e o gerenciamento de saídas não tem ajuste de HDR: não há o que ligar aqui.",
 "Manufacturer": "Fabricante",
 "Model": "Modelo",
 "Serial": "Serial",
 "not informed": "não informado",
 "Connector": "Conector",
 "Native": "Nativa",
 "Current": "Atual",
 "Size": "Tamanho",
 "%d × %d mm (%.1f″)": "%d × %d mm (%.1f″)",
 "Year": "Ano",
 "EDID (%d bytes)": "EDID (%d bytes)",
 "EDID: not available": "EDID: indisponível",
 "This profile no longer fits these monitors (a mode it uses is not announced any more).": "Este perfil não serve mais para estes monitores (um modo que ele usa não é mais anunciado).",
 "Cancel": "Cancelar",
 "OK": "OK",
 "Profile name:": "Nome do perfil:",
 "Save profile": "Salvar perfil",
 "Rename profile": "Renomear perfil",
 "Delete the profile \"%s\"?": "Excluir o perfil \"%s\"?",
 "saved automatically": "salvo automaticamente",
 "The configuration was refused in the test: %s": "A configuração foi recusada no teste: %s",
 "Could not start the revert guard, nothing was changed: %s": "Não foi possível iniciar o vigia da reversão; nada foi mudado: %s",
 "Applying failed (%s); the previous configuration is back.": "Aplicar falhou (%s); a configuração anterior voltou.",
 "Revert": "Reverter",
 "Keep": "Manter",
 "The confirmation came too late; the previous configuration was restored.": "A confirmação chegou tarde demais; a configuração anterior foi restaurada.",
 "Configuration kept and saved for this set of monitors.": "Configuração mantida e salva para este conjunto de monitores.",
 "Could not restore the previous configuration automatically.": "Não foi possível restaurar a configuração anterior automaticamente.",
 "The previous configuration was restored.": "A configuração anterior foi restaurada.",
 "Off:": "Desligados:",
 "primary": "principal",
 "mirrors %s": "espelha %s",
 "Drag to place; arrows move 1 pixel (Shift: 10)": "Arraste para posicionar; as setas movem 1 pixel (Shift: 10)",
 "%s at %d, %d": "%s em %d, %d",
 # Plurais: (forma 0, forma 1) pela regra (n > 1).
 "Changes not applied yet. Apply asks for confirmation and goes back to the previous configuration after %d second without an answer.": ("Mudanças ainda não aplicadas. Aplicar pede confirmação e volta à configuração anterior depois de %d segundo sem resposta.",
  "Mudanças ainda não aplicadas. Aplicar pede confirmação e volta à configuração anterior depois de %d segundos sem resposta."),
 "%d monitor connected. No saved configuration for this monitor yet: the one you keep is restored at login and when it is plugged in.": ("%d monitor conectado. Ainda não há configuração salva para este monitor: a que você mantiver volta no login e quando ele for conectado.",
  "%d monitores conectados. Ainda não há configuração salva para este conjunto de monitores: a que você mantiver volta no login e quando eles forem conectados."),
 "%d monitor connected. This configuration is restored at login and whenever this same monitor is connected.": ("%d monitor conectado. Esta configuração volta no login e sempre que este mesmo monitor for conectado.",
  "%d monitores conectados. Esta configuração volta no login e sempre que este mesmo conjunto de monitores for conectado."),
 "Adaptive sync is on and cannot be changed: the compositor refused the change in a test of this output.": "A taxa variável está ligada e não pode mudar: o compositor recusou a troca num teste desta saída.",
 "Adaptive sync is off and cannot be changed: the compositor refused the change in a test of this output.": "A taxa variável está desligada e não pode mudar: o compositor recusou a troca num teste desta saída.",
 "Keep these display settings?": "Manter estas configurações de monitores?",
 "Reverting to the previous configuration in %d second.": ("Voltando à configuração anterior em %d segundo.",
  "Voltando à configuração anterior em %d segundos."),
 "Usage: big-wm-display-resolution [OPTION]\n\nMonitors of the X11 (Window Maker) and Wayland (wlmaker) sessions.\n\n  (none)                 open the window (or raise the open one)\n  --restore              at login: apply the profile of the connected set\n                         of monitors (no window)\n  --hotplug              the same, run by the watcher when a monitor\n                         is plugged in or out\n  --watch                hotplug watcher (replaces this process with\n                         big-wm-display-helper)\n  --show                 what is connected and the profile that applies\n  --profiles             list the profiles\n  --apply-profile NAME   apply a profile (no confirmation)\n  --version              show the version\n": "Uso: big-wm-display-resolution [OPÇÃO]\n\nMonitores das sessões X11 (Window Maker) e Wayland (wlmaker).\n\n  (nenhuma)              abre a janela (ou traz a que já está aberta)\n  --restore              no login: aplica o perfil do conjunto de\n                         monitores conectado (sem janela)\n  --hotplug              o mesmo, chamado pelo vigia quando um monitor\n                         é conectado ou desconectado\n  --watch                vigia de conexão de monitores (troca este\n                         processo pelo big-wm-display-helper)\n  --show                 o que está conectado e o perfil que vale\n  --profiles             lista os perfis\n  --apply-profile NOME   aplica um perfil (sem confirmação)\n  --version              mostra a versão\n",
 "session: %s": "sessão: %s",
 "profile: none for this set of monitors": "perfil: nenhum para este conjunto de monitores",
 "automatic": "automático",
 "profile: %s": "perfil: %s",
 "%d monitor": ("%d monitor",
  "%d monitores"),
 "the profile is not for this set of monitors": "o perfil não é deste conjunto de monitores",
 "invalid profile: %s": "perfil inválido: %s",
 "profile not found: %s": "perfil não encontrado: %s",
}


def entries(pot):
    """(msgid, msgid_plural ou None, comentários) de cada entrada do .pot."""
    cur, key, out, comments = {}, None, [], []
    for line in open(pot, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("msgid "):
            cur, key = {"id": [ast.literal_eval(line[6:])]}, "id"
        elif line.startswith("msgid_plural "):
            cur["plural"], key = [ast.literal_eval(line[13:])], "plural"
        elif line.startswith("msgstr"):
            if key in ("id", "plural"):
                out.append(("".join(cur["id"]), "".join(cur["plural"]) if "plural" in cur else None, comments))
                comments = []
            key = "str"
        elif line.startswith('"') and key in ("id", "plural"):
            cur[key].append(ast.literal_eval(line))
        elif line.startswith("#"):
            comments.append(line)
    return out


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


pot, dest = sys.argv[1], sys.argv[2]
missing = []
with open(dest, "w", encoding="utf-8") as f:
    f.write('# Big WM Display Resolution: português do Brasil.\n# SPDX-License-Identifier: GPL-2.0-or-later\n'
            'msgid ""\nmsgstr ""\n"Project-Id-Version: big-wm-display-resolution\\n"\n'
            '"PO-Revision-Date: 2026-11-09 12:00-0300\\n"\n"Last-Translator: Big WindowMaker\\n"\n'
            '"Language-Team: Portuguese (Brazil)\\n"\n"Language: pt_BR\\n"\n"MIME-Version: 1.0\\n"\n"Content-Type: text/plain; charset=UTF-8\\n"\n'
            '"Content-Transfer-Encoding: 8bit\\n"\n"Plural-Forms: nplurals=2; plural=(n > 1);\\n"\n')
    for msgid, plural, comments in entries(pot):
        if not msgid:
            continue
        tr = T.get(msgid)
        # Plural: (singular, plural) pela regra (n > 1) do cabeçalho; 0 e 1
        # usam a primeira forma.
        if tr is None or (plural is not None) != isinstance(tr, tuple):
            missing.append(msgid)
            tr = None
        flags = [c for c in comments if c.startswith("#,")]
        f.write("\n" + "".join(c + "\n" for c in flags))
        if plural is None:
            f.write("msgid %s\nmsgstr %s\n" % (q(msgid), q(tr or "")))
        else:
            tr = tr or ("", "")
            f.write("msgid %s\nmsgid_plural %s\nmsgstr[0] %s\nmsgstr[1] %s\n"
                    % (q(msgid), q(plural), q(tr[0]), q(tr[1])))
if missing:
    sys.exit("sem tradução: %r" % missing)
