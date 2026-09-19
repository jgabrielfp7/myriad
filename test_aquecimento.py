# -*- coding: utf-8 -*-
"""Aquecimento de conta (spec 2026-08-28): sorteio do plano diário, sessão
com aparelho falso e integração no ciclo do postador."""
import csv
import random
from datetime import datetime, timedelta

import aquecimento
import postador
import driver_instagram as ig


AGORA = datetime(2026, 8, 28, 10, 0)


# ---------- montar_plano ----------

def test_plano_evita_zona_morta_dos_posts():
    slots = [datetime(2026, 8, 28, 15, 0)]
    plano = aquecimento.montar_plano(["a", "b", "c"], slots, AGORA,
                                     random.Random(1))
    for s in plano["sessoes"].values():
        alvo = datetime.strptime(f"2026-08-28 {s['quando']}", "%Y-%m-%d %H:%M")
        assert abs((alvo - slots[0]).total_seconds()) >= 20 * 60


def test_plano_espaca_sessoes_entre_contas():
    plano = aquecimento.montar_plano(["a", "b", "c"], [], AGORA,
                                     random.Random(7))
    horarios = sorted(
        datetime.strptime(f"2026-08-28 {s['quando']}", "%Y-%m-%d %H:%M")
        for s in plano["sessoes"].values())
    for h1, h2 in zip(horarios, horarios[1:]):
        assert (h2 - h1).total_seconds() >= 45 * 60


def test_plano_so_sorteia_horario_futuro_e_dentro_da_janela():
    tarde = datetime(2026, 8, 28, 21, 50)
    plano = aquecimento.montar_plano(["a", "b", "c"], [], tarde,
                                     random.Random(3))
    for s in plano["sessoes"].values():
        alvo = datetime.strptime(f"2026-08-28 {s['quando']}", "%Y-%m-%d %H:%M")
        assert alvo >= tarde + timedelta(minutes=10)
        assert alvo <= datetime(2026, 8, 28, 22, 30)


def test_conta_sem_vaga_fica_fora_em_vez_de_colidir():
    quase_fim = datetime(2026, 8, 28, 22, 10)
    plano = aquecimento.montar_plano(["a", "b", "c"], [], quase_fim,
                                     random.Random(5))
    # janela restante (22:20-22:30) só comporta 1 sessão com piso de 45 min
    assert len(plano["sessoes"]) <= 1


def test_plano_do_dia_reusa_mesma_data_e_replaneja_data_nova(tmp_path, monkeypatch):
    monkeypatch.setattr(aquecimento, "ARQ_PLANO", tmp_path / "aq.json")
    aq = {"ativo": True, "contas": ["a"], "min_reels": 15, "max_reels": 25,
          "chance_curtida": 0.1}
    p1 = aquecimento.plano_do_dia(aq, [], AGORA, random.Random(1))
    p1["sessoes"]["a"]["feito"] = True
    aquecimento.salvar_plano(p1)
    p2 = aquecimento.plano_do_dia(aq, [], AGORA + timedelta(hours=2))
    assert p2["sessoes"]["a"]["feito"] is True  # mesmo dia: memória preservada
    p3 = aquecimento.plano_do_dia(aq, [], AGORA + timedelta(days=1))
    assert p3["data"] != p1["data"]
    assert p3["sessoes"]["a"]["feito"] is False  # dia novo: replanejado


# ---------- sessão (aparelho falso) ----------

class SelFalso:
    def __init__(self, existe=True):
        self.exists = existe
        self.cliques = 0

    def wait(self, timeout=0):
        return self.exists

    def click(self):
        self.cliques += 1


class AparelhoFalso:
    def __init__(self):
        self.sels = {}
        self.swipes = 0
        self.likes = SelFalso(existe=True)

    def __call__(self, **kw):
        rid = kw.get("resourceId", "")
        if rid.endswith("like_button"):
            return self.likes
        return self.sels.setdefault(rid or str(kw), SelFalso())

    def screen_on(self): pass
    def unlock(self): pass
    def app_start(self, pacote, stop=False): pass
    def press(self, tecla): pass

    def screen_off(self):
        self.tela_apagada = True

    def swipe(self, *a, **kw):
        self.swipes += 1


def _sessao_rapida(monkeypatch, chance, rng):
    d = AparelhoFalso()
    monkeypatch.setattr(ig, "garantir_conta", lambda *a, **k: None)
    monkeypatch.setattr(ig, "_fechar_popups", lambda dd: None)
    monkeypatch.setattr(ig, "_checar_bloqueio", lambda dd: None)
    monkeypatch.setattr(aquecimento.time, "sleep", lambda s: None)
    aq = {"min_reels": 10, "max_reels": 10, "chance_curtida": chance}
    stats = aquecimento.sessao(d, "exemplo.social", aq, tmp_logs, rng=rng)
    return d, stats


tmp_logs = None  # setado no fixture abaixo


def test_sessao_curte_so_pelo_botao_e_na_proporcao(tmp_path, monkeypatch):
    global tmp_logs
    tmp_logs = tmp_path
    d, stats = _sessao_rapida(monkeypatch, chance=1.0, rng=random.Random(2))
    assert stats["reels"] == 10
    assert stats["curtidas"] == 10 == d.likes.cliques  # só via botão
    assert d.swipes == 10

    d2, stats2 = _sessao_rapida(monkeypatch, chance=0.0, rng=random.Random(2))
    assert stats2["curtidas"] == 0 == d2.likes.cliques


def test_sessao_apaga_a_tela_no_fim(tmp_path, monkeypatch):
    global tmp_logs
    tmp_logs = tmp_path
    d, _ = _sessao_rapida(monkeypatch, chance=0.0, rng=random.Random(4))
    assert getattr(d, "tela_apagada", False) is True


def test_sessao_propaga_bloqueio(tmp_path, monkeypatch):
    global tmp_logs
    tmp_logs = tmp_path
    monkeypatch.setattr(ig, "garantir_conta", lambda *a, **k: None)
    monkeypatch.setattr(ig, "_fechar_popups", lambda dd: None)
    monkeypatch.setattr(aquecimento.time, "sleep", lambda s: None)

    def explode(dd):
        raise ig.BloqueioDetectado("restringimos")
    monkeypatch.setattr(ig, "_checar_bloqueio", explode)

    import pytest
    with pytest.raises(ig.BloqueioDetectado):
        aquecimento.sessao(AparelhoFalso(), "x",
                           {"min_reels": 10, "max_reels": 10,
                            "chance_curtida": 0}, tmp_path,
                           rng=random.Random(1))


# ---------- integração no ciclo ----------

def _prepara_postador(tmp_path, monkeypatch, plano_quando="00:00"):
    # "00:00" e não "00:05": com 00:05, rodar a suíte entre 00:00 e 00:05
    # fazia `agora < alvo` e a sessão "vencida" ainda não tinha vencido
    # (flake real, 15/09 00:03)
    fila = tmp_path / "fila.csv"
    with fila.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=postador.CAMPOS_FILA)
        w.writeheader()
    monkeypatch.setattr(postador, "ARQ_FILA", fila)
    monkeypatch.setattr(postador, "ARQ_LOG", tmp_path / "log.csv")
    monkeypatch.setattr(postador, "ARQ_ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(aquecimento, "ARQ_PLANO", tmp_path / "aq.json")
    hoje = f"{datetime.now():%Y-%m-%d}"
    aquecimento.salvar_plano({"data": hoje, "sessoes": {
        "exemplo.social": {"quando": plano_quando, "feito": False,
                         "reels": 0, "curtidas": 0}}})
    import conexao
    monkeypatch.setattr(conexao, "ler_bateria", lambda serial: (80, True))
    monkeypatch.setattr(ig, "conectar", lambda serial: AparelhoFalso())
    cfg = {"aquecimento": {"ativo": True, "contas": ["exemplo.social"],
                           "min_reels": 10, "max_reels": 10,
                           "chance_curtida": 0}, "bateria_minima": 20}
    return cfg


def test_ciclo_executa_sessao_vencida_e_marca_feito(tmp_path, monkeypatch):
    cfg = _prepara_postador(tmp_path, monkeypatch)
    monkeypatch.setattr(aquecimento, "sessao",
                        lambda *a, **k: {"reels": 10, "curtidas": 1})
    postador.processar_aquecimento(cfg, serial="S")
    plano = aquecimento.carregar_plano()
    assert plano["sessoes"]["exemplo.social"]["feito"] is True
    assert plano["sessoes"]["exemplo.social"]["reels"] == 10


def test_ciclo_nao_roda_pausado_nem_antes_da_hora(tmp_path, monkeypatch):
    cfg = _prepara_postador(tmp_path, monkeypatch, plano_quando="23:59")
    chamou = []
    monkeypatch.setattr(aquecimento, "sessao",
                        lambda *a, **k: chamou.append(1) or {"reels": 0, "curtidas": 0})
    postador.processar_aquecimento(cfg, serial="S")  # antes da hora
    assert not chamou

    cfg2 = _prepara_postador(tmp_path, monkeypatch)
    postador.salvar_estado({"pausado": True, "motivo_pausa": "teste"})
    postador.processar_aquecimento(cfg2, serial="S")  # pausado
    assert not chamou


def test_ciclo_erro_marca_e_nao_retenta_no_dia(tmp_path, monkeypatch):
    cfg = _prepara_postador(tmp_path, monkeypatch)

    def quebra(*a, **k):
        raise RuntimeError("seletor sumiu")
    monkeypatch.setattr(aquecimento, "sessao", quebra)
    postador.processar_aquecimento(cfg, serial="S")
    assert aquecimento.carregar_plano()["sessoes"]["exemplo.social"]["feito"] == "erro"

    chamou = []
    monkeypatch.setattr(aquecimento, "sessao",
                        lambda *a, **k: chamou.append(1) or {"reels": 0, "curtidas": 0})
    postador.processar_aquecimento(cfg, serial="S")
    assert not chamou  # "erro" não é False: não retenta
