# -*- coding: utf-8 -*-
"""Agenda carrosséis prontos: 2/dia pra conta alvo, à tarde (os Reels da
Semana 1 ocupam 09h-13h30; carrossel entra 15h30/17h30 pra espalhar o dia).

Pronto = pasta em videos/carrosseis/<nome>/ com slide-*.png + legenda.txt e
sem linha na fila. Uso: python agendar_carrosseis.py [--sim] [--conta X]
"""
import random
import sys
from datetime import datetime, timedelta

import postador

BASES = ["15:30", "17:30"]          # slots-alvo por dia
FOLGA_CARROSSEL = 65                # distância mínima entre CARROSSÉIS
FOLGA_QUALQUER = 12                 # só pra não cair no mesmo minuto de um reel
IGNORAR = {"social-quem-pergunta"}  # parece ser da exemplo.social — o operador decide


def _prontos(fila: list[dict]) -> list[str]:
    usados = {l["arquivo"] for l in fila if (l.get("tipo") or "") == "carrossel"}
    prontos = []
    for pasta in sorted(postador.PASTA_CARROSSEIS.iterdir() if postador.PASTA_CARROSSEIS.is_dir() else []):
        if not pasta.is_dir() or pasta.name in usados or pasta.name in IGNORAR:
            continue
        if list(pasta.glob("slide-*.png")) and (pasta / "legenda.txt").exists():
            prontos.append(pasta.name)
    return prontos


def _posts_do_dia(fila: list[dict], conta: str, dia: str,
                  tipo: str | None = None) -> list[datetime]:
    ts = []
    for l in fila:
        if (l.get("conta") == conta and l.get("status") in ("pendente", "postado")
                and (l.get("quando") or "").startswith(dia)
                and (tipo is None or (l.get("tipo") or "reel") == tipo)):
            try:
                ts.append(datetime.strptime(l["quando"], "%Y-%m-%d %H:%M"))
            except ValueError:
                pass
    return ts


def planejar(prontos: list[str], fila: list[dict], cfg: dict, conta: str,
             agora: datetime) -> list[dict]:
    cap = int(cfg.get("max_carrosseis_dia", 1))
    jitter = int(cfg.get("jitter_max_min", 7))
    fim_h, fim_m = map(int, cfg.get("janela_fim", "21:00").split(":"))
    plano, virtual = [], list(fila)
    dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    rnd = random.Random(f"carrossel|{conta}")
    restantes = list(prontos)
    while restantes:
        chave = f"{dia:%Y-%m-%d}"
        fim = dia.replace(hour=fim_h, minute=fim_m)
        ja = sum(1 for l in virtual if l.get("conta") == conta
                 and (l.get("tipo") or "") == "carrossel"
                 and l.get("status") in ("pendente", "postado")
                 and (l.get("quando") or "").startswith(chave))
        for base in BASES[ja:cap]:
            if not restantes:
                break
            h, m = map(int, base.split(":"))
            t = dia.replace(hour=h, minute=m) + timedelta(minutes=rnd.randint(0, jitter))
            irmaos = _posts_do_dia(virtual, conta, chave, tipo="carrossel")
            outros = _posts_do_dia(virtual, conta, chave)
            while (t <= agora + timedelta(minutes=10)
                   or any(abs((t - o).total_seconds()) / 60 < FOLGA_CARROSSEL for o in irmaos)
                   or any(abs((t - o).total_seconds()) / 60 < FOLGA_QUALQUER for o in outros)):
                t += timedelta(minutes=35)
            if t > fim - timedelta(minutes=5):
                continue                      # não coube hoje — fica pro dia seguinte
            linha = {"conta": conta, "arquivo": restantes.pop(0),
                     "quando": f"{t:%Y-%m-%d %H:%M}", "status": "pendente",
                     "resultado": "", "postado_em": "", "views": "",
                     "tipo": "carrossel"}
            plano.append(linha)
            virtual.append(linha)
        dia += timedelta(days=1)
    return plano


def main() -> int:
    args = sys.argv[1:]
    conta = args[args.index("--conta") + 1] if "--conta" in args else "exemplo.group"
    cfg = postador.carregar_config()
    with postador.fila_travada():
        fila = postador.ler_fila()
        prontos = _prontos(fila)
        if not prontos:
            print("Nenhum carrossel novo (pasta com slide-*.png + legenda.txt).")
            return 0
        plano = planejar(prontos, fila, cfg, conta, datetime.now())
        for l in plano:
            print(f"  {l['quando']}  {l['conta']:14} {l['arquivo']}")
        if "--sim" not in args:
            resp = input("Aplicar? [s/N] ").strip().lower()
            if resp not in ("s", "sim"):
                print("Cancelado.")
                return 1
        fila.extend(plano)
        postador.salvar_fila(fila)
        postador.logar("AGENDADO_CARROSSEL", detalhe=f"{len(plano)} pra @{conta}")
    print(f"PRONTO: {len(plano)} carrossel(is) na fila.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
