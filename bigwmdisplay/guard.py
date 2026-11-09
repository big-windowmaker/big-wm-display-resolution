# SPDX-License-Identifier: GPL-2.0-or-later
"""Vigia da reversão: um processo separado, numa sessão própria, que volta
à configuração anterior se não receber a confirmação a tempo.

A interface inicia o vigia ANTES de aplicar a configuração nova, passando
a configuração anterior num arquivo. Depois, pela entrada padrão do vigia:

  "keep"     o usuário manteve: o vigia sai sem mexer em nada
  "revert"   o usuário pediu para voltar (ou a contagem acabou na janela)

Sem resposta até o prazo (a interface travou) ou com a entrada fechada (a
interface morreu), o vigia reverte sozinho. Ele não depende do GTK nem da
janela: só do backend (xrandr ou o helper do Wayland).

Enquanto vive, o vigia mantém o arquivo de trava (apply.lock): o vigia de
hotplug não aplica perfis no meio de uma confirmação.
"""

import json
import os
import select
import signal
import subprocess
import sys
import time

from . import backend as backendmod
from . import model, store

CONFIRM_SECONDS = 15
GRACE_SECONDS = 3


def lock_path():
    return os.path.join(store.runtime_dir(), "apply.lock")


def lock_active():
    """Há uma aplicação esperando confirmação (vigia vivo)?"""
    try:
        with open(lock_path(), encoding="utf-8") as f:
            pid = int(f.read().strip() or 0)
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def launcher():
    env = os.environ.get("BIGWM_DISPLAY_LAUNCHER")
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (os.path.join(root, "big-wm-display-resolution"), "/usr/bin/big-wm-display-resolution"):
        if os.path.isfile(p):
            return p
    return "big-wm-display-resolution"


class Guard:
    """O lado da interface: inicia o vigia e manda a resposta."""

    def __init__(self, previous, timeout=CONFIRM_SECONDS + GRACE_SECONDS):
        rd = store.runtime_dir()
        os.makedirs(rd, mode=0o700, exist_ok=True)
        self.state = os.path.join(rd, "guard-%d-%d.json" % (os.getpid(), int(time.time() * 1000)))
        prof = store.layout_to_profile(previous, "previous", kind="guard")
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"profile": prof, "timeout": timeout, "session": previous.backend}, f)
        cmd = [sys.executable, "-I", launcher(), "--guard", self.state]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                     start_new_session=True, close_fds=True)
        # O vigia avisa quando está pronto (trava gravada).
        ready = self.proc.stdout.readline().strip()
        if ready != "ready":
            raise RuntimeError("o vigia da reversão não iniciou")

    def _send(self, word):
        try:
            self.proc.stdin.write(word + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def keep(self):
        self._send("keep")
        return self._wait()

    def revert(self):
        self._send("revert")
        return self._wait()

    def _wait(self):
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            out = self.proc.stdout.read().strip()
            self.proc.wait(timeout=60)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            out = ""
        return out.splitlines()[-1] if out else ""


def run_guard(state_path):
    """O processo vigia (big-wm-display-resolution --guard ARQUIVO)."""
    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGPIPE):
        signal.signal(sig, signal.SIG_IGN)
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        print("error: %s" % e, flush=True)
        return 2
    rd = store.runtime_dir()
    os.makedirs(rd, mode=0o700, exist_ok=True)
    with open(lock_path(), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    print("ready", flush=True)
    deadline = time.monotonic() + float(state.get("timeout", CONFIRM_SECONDS + GRACE_SECONDS))
    answer = None
    buf = ""
    fd = sys.stdin.fileno()
    while answer is None:
        left = deadline - time.monotonic()
        if left <= 0:
            answer = "timeout"
            break
        r, _, _ = select.select([fd], [], [], left)
        if not r:
            continue
        chunk = os.read(fd, 256).decode(errors="replace")
        if not chunk:
            answer = "eof"
            break
        buf += chunk
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            if line.strip() in ("keep", "revert"):
                answer = line.strip()
                break
    result = "kept"
    if answer != "keep":
        result = "reverted" if revert(state) else "revert-failed"
        _log("reversão (%s): %s" % (answer, result))
    try:
        os.unlink(state_path)
    except OSError:
        pass
    try:
        if open(lock_path(), encoding="utf-8").read().strip() == str(os.getpid()):
            os.unlink(lock_path())
    except OSError:
        pass
    try:
        print(result, flush=True)
    except (BrokenPipeError, OSError):
        pass
    return 0 if result != "revert-failed" else 1


def revert(state):
    try:
        be = backendmod.get_backend()
        current = be.query()
    except Exception as e:  # noqa: BLE001 - o vigia nunca pode cair sem tentar
        _log("reversão: sem o estado atual: %s" % e)
        return False
    target = store.apply_profile(state["profile"], current)
    if target is None:
        _log("reversão: os monitores mudaram durante a confirmação; nada revertido")
        return False
    if model.same_config(target, current):
        return True
    ok, msg = be.apply(target)
    if not ok:
        _log("reversão falhou: %s" % msg)
    return ok


def _log(text):
    try:
        subprocess.run(["logger", "-t", "big-wm-display-resolution", "--", text], timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass
    print(text, file=sys.stderr, flush=True)
