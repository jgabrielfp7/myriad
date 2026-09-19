# -*- coding: utf-8 -*-
"""Testes das lógicas novas do painel: linha do dia (slots) e estoque de vídeos."""
from datetime import datetime

from dashboard import inventariar_estoque, montar_slots, prever_proximos

AGORA = datetime(2026, 8, 24, 14, 32)
CFG = {"intervalo_minimo_min": 60}


def _linha(conta, arquivo, quando, status, postado_em=""):
    return {"conta": conta, "arquivo": arquivo, "quando": quando,
            "status": status, "postado_em": postado_em}


def test_slots_agrupa_pares_e_marca_estados():
    fila = [
        _linha("exemplo.corp", "a.mp4", "2026-08-24 12:00", "postado", "2026-08-24 12:07"),
        _linha("exemplo.mind", "b.mp4", "2026-08-24 12:00", "postado", "2026-08-24 12:11"),
        _linha("exemplo.corp", "c.mp4", "2026-08-24 15:00", "pendente"),
        _linha("exemplo.mind", "d.mp4", "2026-08-24 15:00", "pendente"),
        _linha("exemplo.corp", "e.mp4", "2026-08-24 16:30", "pendente"),
        _linha("exemplo.corp", "velho.mp4", "2026-08-23 12:00", "postado", "2026-08-23 12:05"),
    ]
    slots = montar_slots(fila, AGORA)
    assert [s["hora"] for s in slots] == ["12:00", "15:00", "16:30"]  # ontem fica fora
    assert len(slots[0]["itens"]) == 2
    assert [s["estado"] for s in slots] == ["postado", "proximo", "agendado"]


def test_slot_atrasado_vira_o_proximo():
    fila = [
        _linha("exemplo.corp", "a.mp4", "2026-08-24 13:30", "pendente"),  # já passou
        _linha("exemplo.corp", "b.mp4", "2026-08-24 16:30", "pendente"),
    ]
    slots = montar_slots(fila, AGORA)
    assert [s["estado"] for s in slots] == ["atrasado", "agendado"]


def test_slot_com_erro_ganha_do_resto():
    fila = [
        _linha("exemplo.corp", "a.mp4", "2026-08-24 12:00", "erro"),
        _linha("exemplo.mind", "b.mp4", "2026-08-24 12:00", "postado", "2026-08-24 12:11"),
    ]
    assert montar_slots(fila, AGORA)[0]["estado"] == "erro"


def test_previsao_respeita_intervalo_da_conta():
    # agendado pras 14:00 (já passou), mas a conta postou 14:10 → só às 15:10
    fila = [
        _linha("exemplo.corp", "a.mp4", "2026-08-24 12:30", "postado", "2026-08-24 14:10"),
        _linha("exemplo.corp", "b.mp4", "2026-08-24 14:00", "pendente"),
    ]
    p = prever_proximos(fila, CFG, AGORA)["exemplo.corp"]
    assert p["previsto"] == datetime(2026, 8, 24, 15, 10)
    assert p["aguarda_intervalo"]


def test_previsao_agendamento_futuro_manda():
    # intervalo já venceu faz tempo → vale o horário agendado
    fila = [
        _linha("exemplo.mind", "a.mp4", "2026-08-24 10:00", "postado", "2026-08-24 10:05"),
        _linha("exemplo.mind", "b.mp4", "2026-08-24 16:30", "pendente"),
    ]
    p = prever_proximos(fila, CFG, AGORA)["exemplo.mind"]
    assert p["previsto"] == datetime(2026, 8, 24, 16, 30)
    assert not p["aguarda_intervalo"]


def test_previsao_atrasado_e_livre_sai_agora():
    # slot passou e o intervalo venceu → previsto = agora
    fila = [
        _linha("exemplo.es", "a.mp4", "2026-08-24 13:00", "pendente"),
    ]
    p = prever_proximos(fila, CFG, AGORA)["exemplo.es"]
    assert p["previsto"] == AGORA
    assert not p["aguarda_intervalo"]


def test_previsao_sem_pendencias_vazia():
    fila = [
        _linha("exemplo.corp", "a.mp4", "2026-08-24 12:00", "postado", "2026-08-24 12:07"),
    ]
    assert prever_proximos(fila, CFG, AGORA) == {}


def test_previsao_pega_o_pendente_mais_cedo_de_cada_conta():
    fila = [
        _linha("exemplo.corp", "b.mp4", "2026-08-24 16:30", "pendente"),
        _linha("exemplo.corp", "a.mp4", "2026-08-24 15:00", "pendente"),
    ]
    p = prever_proximos(fila, CFG, AGORA)["exemplo.corp"]
    assert p["arquivo"] == "a.mp4"
    assert p["previsto"] == datetime(2026, 8, 24, 15, 0)


def test_estoque_separa_prontos_sem_legenda_e_faltando(tmp_path):
    (tmp_path / "pronto1.mp4").write_bytes(b"x")
    (tmp_path / "pronto1.txt").write_text("legenda", encoding="utf-8")
    (tmp_path / "semtxt.mp4").write_bytes(b"x")
    (tmp_path / "usado.mp4").write_bytes(b"x")
    fila = [
        _linha("exemplo.corp", "usado.mp4", "2026-08-24 15:00", "pendente"),
        _linha("exemplo.mind", "fantasma.mp4", "2026-08-24 16:30", "pendente"),
    ]
    est = inventariar_estoque(fila, tmp_path, tmp_path / "saida-vazia")
    assert est["prontos"] == ["pronto1.mp4"]
    assert est["sem_legenda"] == ["semtxt.mp4"]
    assert est["pendentes_sem_video"] == ["fantasma.mp4"]


def test_estoque_conta_a_saida_da_fabrica_tambem(tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    # renderizado mas ainda não entregue: conta como estoque pronto
    (saida / "novo.mp4").write_bytes(b"x")
    (saida / "novo.txt").write_text("legenda", encoding="utf-8")
    # mesmo nome nas duas casas: não conta duas vezes
    (videos / "dup.mp4").write_bytes(b"x")
    (videos / "dup.txt").write_text("legenda", encoding="utf-8")
    (saida / "dup.mp4").write_bytes(b"x")
    est = inventariar_estoque([], videos, saida)
    assert est["prontos"] == ["dup.mp4", "novo.mp4"]


def test_estoque_pasta_inexistente_nao_quebra(tmp_path):
    est = inventariar_estoque([], tmp_path / "nao-existe", tmp_path / "nem-essa")
    assert est == {"prontos": [], "sem_legenda": [], "pendentes_sem_video": []}
