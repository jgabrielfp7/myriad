# -*- coding: utf-8 -*-
"""Aquecimento de conta: 1 sessão diária de consumo casual por conta — rolar o
feed de Reels, assistir 3-12s por reel, curtir ~10% pelo botão de coração.

Decisão registrada: a group ENTRA (revoga o "95k 100% manual" de 21/08).

O que este módulo NUNCA faz: comentar, seguir, compartilhar, abrir perfil,
tocar em link, double-tap. Cap DURO de 1 sessão por conta por dia — nem o
config sobe isso.
"""
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import driver_instagram as ig

RAIZ = Path(__file__).resolve().parent
ARQ_PLANO = RAIZ / "logs" / "aquecimento_hoje.json"

# Janela do dia em que uma sessão pode ser sorteada.
JANELA_INICIO = "09:00"
JANELA_FIM = "22:30"
EXCLUSAO_POST_MIN = 20   # zona morta ao redor de cada slot pendente da fila
ESPACO_SESSOES_MIN = 45  # piso entre sessões de contas diferentes

PADRAO = {"ativo": False, "contas": [], "min_reels": 15, "max_reels": 25,
          "chance_curtida": 0.10}


def cfg_aquecimento(cfg: dict) -> dict:
    """Bloco `aquecimento` do config com defaults seguros (ausente = inativo)."""
    aq = dict(PADRAO)
    aq.update(cfg.get("aquecimento") or {})
    return aq


# ---------- plano do dia (funções puras, testáveis) ----------

def _hm(base: datetime, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return base.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def montar_plano(contas: list[str], slots_pendentes: list[datetime],
                 agora: datetime, rng: random.Random) -> dict:
    """Sorteia 1 horário FUTURO por conta, evitando ±EXCLUSAO_POST_MIN de cada
    slot pendente e mantendo ESPACO_SESSOES_MIN entre sessões. Conta sem vaga
    hoje fica fora do plano (melhor pular que forçar colisão)."""
    inicio = max(agora + timedelta(minutes=10), _hm(agora, JANELA_INICIO))
    fim = _hm(agora, JANELA_FIM)

    candidatos = []
    t = inicio.replace(second=0, microsecond=0)
    while t <= fim:
        livre = all(abs((t - s).total_seconds()) >= EXCLUSAO_POST_MIN * 60
                    for s in slots_pendentes)
        if livre:
            candidatos.append(t)
        t += timedelta(minutes=5)

    sessoes = {}
    escolhidos: list[datetime] = []
    for conta in contas:
        vagas = [c for c in candidatos
                 if all(abs((c - e).total_seconds()) >= ESPACO_SESSOES_MIN * 60
                        for e in escolhidos)]
        if not vagas:
            continue
        alvo = rng.choice(vagas)
        escolhidos.append(alvo)
        sessoes[conta] = {"quando": f"{alvo:%H:%M}", "feito": False,
                          "reels": 0, "curtidas": 0}
    return {"data": f"{agora:%Y-%m-%d}", "sessoes": sessoes}


def carregar_plano() -> dict | None:
    try:
        return json.loads(ARQ_PLANO.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def salvar_plano(plano: dict) -> None:
    ARQ_PLANO.parent.mkdir(exist_ok=True)
    ARQ_PLANO.write_text(json.dumps(plano, ensure_ascii=False, indent=2),
                         encoding="utf-8")


def plano_do_dia(aq: dict, slots_pendentes: list[datetime],
                 agora: datetime, rng: random.Random | None = None) -> dict:
    """Plano de hoje: reusa o gravado se for da mesma data, senão sorteia e
    grava. Sessão já feita nunca é re-sorteada (o arquivo é a memória)."""
    plano = carregar_plano()
    if plano and plano.get("data") == f"{agora:%Y-%m-%d}":
        return plano
    plano = montar_plano(list(aq["contas"]), slots_pendentes, agora,
                         rng or random.Random())
    salvar_plano(plano)
    return plano


# ---------- a sessão em si (dirige o aparelho) ----------

def _abrir_reels_do_feed(d) -> None:
    """Feed de Reels da barra inferior (clips_tab). Aqui ele é o DESTINO —
    o coletor de views o evita porque lá o alvo é o perfil."""
    aba = d(resourceId=f"{ig.PACOTE_IG}:id/clips_tab")
    if not aba.wait(timeout=15):
        raise ig.FalhaNoFluxo("Aba de Reels (clips_tab) não apareceu")
    aba.click()
    time.sleep(4)


def _curtir_visivel(d) -> bool:
    """Curte o reel na tela APENAS pelo botão de coração (nunca double-tap).
    Retorna True se curtiu. Se o botão não for encontrado, segue sem curtir."""
    for rid in ("like_button", "clips_like_button"):
        b = d(resourceId=f"{ig.PACOTE_IG}:id/{rid}")
        if b.exists:
            b.click()
            time.sleep(1)
            return True
    return False


def _proximo_reel(d, rng: random.Random) -> None:
    """Swipe vertical com posição/duração levemente variadas."""
    x = 0.5 + rng.uniform(-0.06, 0.06)
    d.swipe(x, 0.72 + rng.uniform(-0.04, 0.04), x, 0.20 + rng.uniform(-0.04, 0.04),
            duration=rng.uniform(0.08, 0.2))


def sessao(d, conta: str, aq: dict, pasta_logs: Path,
           rng: random.Random | None = None) -> dict:
    """Roda UMA sessão de aquecimento na conta. Levanta FalhaNoFluxo /
    BloqueioDetectado (mesma semântica do postar_reel)."""
    rng = rng or random.Random()
    d.screen_on(); time.sleep(1)
    d.unlock(); time.sleep(1)
    d.app_start(ig.PACOTE_IG, stop=True)
    time.sleep(6)
    (d(resourceId=f"{ig.PACOTE_IG}:id/feed_tab").wait(timeout=25)
     or d(resourceId=f"{ig.PACOTE_IG}:id/profile_tab").wait(timeout=5))
    ig._fechar_popups(d)
    ig._checar_bloqueio(d)

    ig.garantir_conta(d, conta, pasta_logs)

    # do perfil (onde garantir_conta termina) pro feed, e daí pros Reels
    d(resourceId=f"{ig.PACOTE_IG}:id/feed_tab").click()
    time.sleep(2)
    _abrir_reels_do_feed(d)

    n_reels = rng.randint(int(aq["min_reels"]), int(aq["max_reels"]))
    curtidas = 0
    for i in range(n_reels):
        time.sleep(rng.uniform(3, 12))          # "assistindo"
        if rng.random() < float(aq["chance_curtida"]):
            if _curtir_visivel(d):
                curtidas += 1
        if i % 6 == 5:                           # checagens periódicas
            ig._checar_bloqueio(d)
            ig._fechar_popups(d)
        _proximo_reel(d, rng)
        time.sleep(rng.uniform(0.5, 1.5))

    d.press("home")
    ig.apagar_tela(d)
    return {"reels": n_reels, "curtidas": curtidas}
