# -*- coding: utf-8 -*-
"""Agenda vídeos prontos SEM ninguém editar a fila na mão.

Decisão de projeto (03/09/2026): a fábrica sai do caminho. Ele produz os vídeos
(os manuais dele saem em 30 fps e 12 Mbps; os da fábrica saíam em 25 fps e
2,7–4,4 Mbps) e o robô só publica.

Fluxo dele:
  1. joga o `.mp4` + um `.txt` de mesmo nome (a legenda) em
     `videos/<conta>/` — ex.: `videos/exemplo.group/aula1.mp4`
  2. roda `agendar.bat`
  3. o robô move pra `videos/`, batiza com o prefixo da conta
     (`group-aula1.mp4`, convenção que já existia) e escreve as linhas
     pendentes na fila, respeitando os guardrails POR CONTA.

Editar `fila.csv` à mão já custou post perdido — por isso este módulo existe.

Uso:  python agendar.py            (mostra o plano e pergunta antes de aplicar)
      python agendar.py --sim      (aplica direto)
"""
from __future__ import annotations

import csv
import json
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PASTA_VIDEOS = RAIZ / "videos"
ARQ_FILA = RAIZ / "fila.csv"
ARQ_CONFIG = RAIZ / "config.json"

CAMPOS_FILA = ["conta", "arquivo", "quando", "status", "resultado",
               "postado_em", "views", "tipo"]

JANELA_INICIO = "09:00"
JANELA_FIM = "21:00"


class VideoSumiu(RuntimeError):
    """O arquivo existia ao planejar e sumiu antes de aplicar."""


def slug_conta(conta: str) -> str:
    """`exemplo.group` -> `group`. É o prefixo do arquivo no postador."""
    return conta.split(".")[-1].strip()


def descobrir_prontos(pasta_videos: Path, conta: str) -> list[Path]:
    """Os `.mp4` de `videos/<conta>/` que têm legenda `.txt` irmã.

    Sem o `.txt` o postador publicaria sem legenda: melhor deixar de fora e
    avisar do que postar torto.
    """
    pasta = pasta_videos / conta
    if not pasta.is_dir():
        return []
    return sorted(p for p in pasta.glob("*.mp4")
                  if (p.parent / (p.stem + ".txt")).exists())


def nome_no_postador(conta: str, arquivo: str, usados: set[str]) -> str:
    """Nome final dentro de `videos/`, com o prefixo da conta e sem colidir."""
    caule = Path(arquivo).stem
    ext = Path(arquivo).suffix or ".mp4"
    base = f"{slug_conta(conta)}-{caule}"
    nome = f"{base}{ext}"
    n = 2
    while nome in usados:
        nome = f"{base}-{n}{ext}"
        n += 1
    return nome


def _hhmm(txt: str) -> tuple[int, int]:
    h, m = txt.split(":")
    return int(h), int(m)


def horarios_do_dia(dia: datetime, quantos: int, cfg: dict,
                    semente: str = "", inicio_minimo: datetime | None = None) -> list[datetime]:
    """Distribui `quantos` horários dentro da janela, com folga e jitter.

    A semente é o nome da conta: assim duas contas não caem no mesmo minuto
    todo dia — três contas postando 12h00 em ponto é assinatura de robô.
    """
    if quantos <= 0:
        return []
    hi, mi = _hhmm(cfg.get("janela_inicio", JANELA_INICIO))
    hf, mf = _hhmm(cfg.get("janela_fim", JANELA_FIM))
    inicio = dia.replace(hour=hi, minute=mi, second=0, microsecond=0)
    fim = dia.replace(hour=hf, minute=mf, second=0, microsecond=0)
    # Pedido tarde ("comece a postar hoje", 18h30 de 03/09): o dia começa AGORA,
    # não às 9h. Sem isso, o resto da janela era descartado e tudo ia pra amanhã.
    if inicio_minimo and inicio_minimo > inicio:
        inicio = inicio_minimo.replace(second=0, microsecond=0) + timedelta(minutes=5)
    if inicio >= fim:
        return []

    intervalo = int(cfg.get("intervalo_minimo_min", 60))
    jitter = int(cfg.get("jitter_max_min", 7))
    rnd = random.Random(f"{semente}|{dia:%Y-%m-%d}")

    # Espaçamento (o operador 14/09): intervalo_minimo é o PISO (30) e
    # espacamento_entre_posts é o TETO (1h30) — cada vão é SORTEADO nesse
    # miolo, pra cadência não ter assinatura de robô. Sem teto definido,
    # espalha regular na janela como antes.
    minutos_janela = int((fim - inicio).total_seconds() // 60)
    esp = int(cfg.get("espacamento_entre_posts_min") or 0)
    passo_fixo = max(intervalo, minutos_janela // max(quantos, 1))

    horarios = []
    for i in range(quantos):
        if not horarios:
            t = inicio + timedelta(minutes=rnd.randint(0, jitter))
        elif esp:
            t = horarios[-1] + timedelta(minutes=rnd.randint(intervalo, max(intervalo, esp)))
        else:
            t = horarios[-1] + timedelta(minutes=passo_fixo + rnd.randint(0, jitter))
        horarios.append(min(t, fim))
    return horarios


def _agendados_no_dia(fila: list[dict], conta: str, dia: str) -> int:
    """Quantos posts a conta já tem no dia (pendentes + já postados)."""
    n = 0
    for l in fila:
        if (l.get("conta", "").strip() == conta
                and l.get("status") in ("pendente", "postado")
                and (l.get("quando") or "").startswith(dia)):
            n += 1
    return n


def planejar(prontos: dict[str, list[Path]], fila: list[dict], cfg: dict,
             agora: datetime) -> list[dict]:
    """Monta as linhas a acrescentar na fila, sem tocar em disco.

    Guardrails são POR CONTA (o postador conta assim): o teto da `group` estar
    cheio não pode empurrar a `mind`. O que não couber hoje vai pro dia
    seguinte, e assim por diante.
    """
    teto_global = int(cfg.get("max_posts_dia", 3))
    usados = {(l.get("arquivo") or "").strip() for l in fila}
    plano: list[dict] = []

    for conta in sorted(prontos):
        ov = (cfg.get("overrides_conta") or {}).get(conta, {})
        teto = int(ov.get("max_posts_dia") or teto_global)
        arquivos = list(prontos[conta])
        dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        fila_virtual = list(fila)

        while arquivos:
            chave = f"{dia:%Y-%m-%d}"
            ja = _agendados_no_dia(fila_virtual, conta, chave)
            cabe = max(teto - ja, 0)
            if cabe:
                # No dia de hoje, a janela útil começa AGORA (o pedido pode
                # chegar às 18h30); nos dias seguintes, no horário normal.
                minimo = agora if chave == f"{agora:%Y-%m-%d}" else None
                candidatos = horarios_do_dia(dia, ja + cabe, cfg, semente=conta,
                                             inicio_minimo=minimo)
                livres = [h for h in candidatos[ja:] if h > agora]
                for h in livres:
                    if not arquivos:
                        break
                    origem = arquivos.pop(0)
                    nome = nome_no_postador(conta, origem.name, usados)
                    usados.add(nome)
                    linha = {"conta": conta, "arquivo": nome,
                             "quando": f"{h:%Y-%m-%d %H:%M}", "status": "pendente",
                             "resultado": "", "postado_em": "", "views": "",
                             "tipo": "reel"}
                    plano.append({**linha, "origem": origem})
                    fila_virtual.append(linha)
            dia += timedelta(days=1)
    return plano


def aplicar(plano: list[dict], pasta_videos: Path, arq_fila: Path) -> int:
    """Move os arquivos e acrescenta as linhas na fila. Tudo ou nada.

    Se um vídeo sumiu entre planejar e aplicar, aborta ANTES de escrever: uma
    linha pendente apontando pra arquivo inexistente faz o robô adiar pra
    sempre, em silêncio.
    """
    for item in plano:
        if not Path(item["origem"]).exists():
            raise VideoSumiu(f"o vídeo {item['origem']} não está mais lá")

    movidos = 0
    for item in plano:
        origem = Path(item["origem"])
        destino = pasta_videos / item["arquivo"]
        shutil.move(str(origem), str(destino))
        legenda = origem.parent / (origem.stem + ".txt")
        if legenda.exists():
            shutil.move(str(legenda), str(destino.parent / (destino.stem + ".txt")))
        movidos += 1

    import postador
    with postador.fila_travada():        # append sob o lock painel↔robô (14/09)
        existia = arq_fila.exists()
        with arq_fila.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS_FILA)
            if not existia:
                w.writeheader()
            for item in plano:
                w.writerow({k: item[k] for k in CAMPOS_FILA})
    return movidos


# ------------------------------------------------------------------ CLI

def _contas_do_config(cfg: dict) -> list[str]:
    """As contas em rodízio (menos as pausadas pelo painel Myriad)."""
    contas = cfg.get("contas_agendamento") or cfg.get("aquecimento", {}).get("contas", [])
    pausadas = set(cfg.get("contas_pausadas", []))
    return [c for c in contas if c not in pausadas]


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cfg = json.loads(ARQ_CONFIG.read_text(encoding="utf-8-sig"))
    contas = _contas_do_config(cfg)

    fila = []
    if ARQ_FILA.exists():
        fila = list(csv.DictReader(ARQ_FILA.open(encoding="utf-8-sig")))

    prontos, sem_legenda = {}, []
    for conta in contas:
        prontos[conta] = descobrir_prontos(PASTA_VIDEOS, conta)
        pasta = PASTA_VIDEOS / conta
        if pasta.is_dir():
            sem_legenda += [p.name for p in pasta.glob("*.mp4")
                            if not (p.parent / (p.stem + ".txt")).exists()]

    print("\n  AGENDAR VIDEOS PRONTOS\n")
    for conta in contas:
        (PASTA_VIDEOS / conta).mkdir(parents=True, exist_ok=True)
        print(f"   {conta:16} {len(prontos[conta])} pronto(s)")
    if sem_legenda:
        print("\n   SEM LEGENDA (ficaram de fora - falta o .txt do lado):")
        for n in sem_legenda:
            print(f"     - {n}")

    plano = planejar(prontos, fila, cfg, agora=datetime.now())
    if not plano:
        print("\n  Nada a agendar. Ponha os videos em videos/<conta>/ com o .txt da legenda.\n")
        return 0

    print("\n  PLANO:")
    for item in plano:
        print(f"   {item['quando']}  {item['conta']:16} {item['arquivo']}")

    if "--sim" not in argv:
        resposta = input("\n  Aplicar? [s/N] ").strip().lower()
        if resposta not in ("s", "sim"):
            print("  Cancelado. Nada foi movido.\n")
            return 1

    n = aplicar(plano, PASTA_VIDEOS, ARQ_FILA)
    print(f"\n  PRONTO: {n} video(s) na fila. O postador pega sozinho.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
