# -*- coding: utf-8 -*-
"""Babá do postador: lança o postador.py como filho e vigia o heartbeat.

Se o heartbeat envelhecer além do limite (postador travado — ex.: pipe preso,
aparelho pendurado) ou o processo morrer sozinho, mata a árvore e relança.
Um travamento nunca mais custa uma tarde: custa no máximo LIMITE_MIN minutos.

Limite de 25 min porque o silêncio legítimo do heartbeat chega a ~20 min:
ele só bate no loop externo, e jitter (até 7 min) + fluxo de post (~10 min)
+ retries de troca de conta (~4 min) acontecem DENTRO de um ciclo.

Uso: python vigia.py  (o iniciar.bat chama isto em vez do postador direto)
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
HEARTBEAT = RAIZ / "logs" / "heartbeat.txt"
LOG = RAIZ / "logs" / "log.csv"
CONSOLE_POSTADOR = RAIZ / "logs" / "console_postador.log"
LIMITE_MIN = 25
CHECAGEM_S = 120


def idade_heartbeat_min(texto: str, agora: datetime) -> float | None:
    """Idade do heartbeat em minutos; None se ilegível (aí não se mata nada)."""
    try:
        ts = datetime.strptime(texto.strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None
    return (agora - ts).total_seconds() / 60


def deve_reiniciar(idade_min: float | None, limite_min: float = LIMITE_MIN) -> bool:
    return idade_min is not None and idade_min > limite_min


def _logar(evento: str, detalhe: str) -> None:
    try:
        LOG.parent.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8", newline="") as f:
            f.write(f'{datetime.now():%Y-%m-%d %H:%M:%S},{evento},,"{detalhe}"\n')
    except Exception:
        pass


def _matar_arvore(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        pass


def main() -> None:
    print(f"Vigia rodando: relança o postador se o heartbeat passar de "
          f"{LIMITE_MIN} min. Ctrl+C para parar tudo.")
    while True:
        # stdout do postador vai pra ARQUIVO, não pro console: escrita em
        # console TRAVA o processo se a janela entrar em modo seleção
        # (clique com QuickEdit ativo) — congelou o postador em 25/08 15:23,
        # preso no print() do logar. Arquivo nunca bloqueia. `-u` = sem buffer,
        # dá pra acompanhar ao vivo com Get-Content -Wait.
        LOG.parent.mkdir(exist_ok=True)
        console = open(CONSOLE_POSTADOR, "a", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, "-u", "postador.py"],
                                cwd=RAIZ, stdin=subprocess.DEVNULL,
                                stdout=console, stderr=subprocess.STDOUT)
        console.close()  # o filho herdou o handle; o nosso pode fechar
        _logar("VIGIA_LANCOU", f"postador pid={proc.pid}")
        try:
            while True:
                time.sleep(CHECAGEM_S)
                if proc.poll() is not None:
                    _logar("VIGIA_RELANCA",
                           f"postador saiu sozinho (code={proc.returncode})")
                    break
                idade = None
                if HEARTBEAT.exists():
                    idade = idade_heartbeat_min(
                        HEARTBEAT.read_text(encoding="utf-8-sig"),
                        datetime.now())
                if deve_reiniciar(idade):
                    _logar("VIGIA_REINICIO",
                           f"heartbeat parado há {idade:.0f} min — "
                           f"matando pid={proc.pid} e relançando")
                    _matar_arvore(proc.pid)
                    try:
                        proc.wait(timeout=30)
                    except Exception:
                        pass
                    break
        except KeyboardInterrupt:
            _matar_arvore(proc.pid)
            raise
        time.sleep(5)


if __name__ == "__main__":
    main()
