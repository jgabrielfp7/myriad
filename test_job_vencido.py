# -*- coding: utf-8 -*-
"""Guardrail de job zumbi (28/08, aprendido com o reel59): catch-up vale pra
atraso do MESMO dia; job agendado há mais de max_atraso_horas NUNCA posta
sozinho — vira status "vencido" na fila e espera decisão humana."""
import csv
from datetime import datetime, timedelta

import postador


def _monta_fila(tmp_path, monkeypatch, quando: datetime):
    arq = tmp_path / "fila.csv"
    with arq.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=postador.CAMPOS_FILA)
        w.writeheader()
        w.writerow({"conta": "exemplo.social", "arquivo": "reelX.mp4",
                    "quando": quando.strftime("%Y-%m-%d %H:%M"),
                    "status": "pendente", "resultado": "", "postado_em": "",
                    "views": ""})
    monkeypatch.setattr(postador, "ARQ_FILA", arq)
    monkeypatch.setattr(postador, "ARQ_LOG", tmp_path / "log.csv")
    monkeypatch.setattr(postador, "ARQ_ESTADO", tmp_path / "estado.json")
    return arq


def _le_status(arq):
    with arq.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))[0]


def test_job_de_dois_dias_atras_vira_vencido_e_nao_posta(tmp_path, monkeypatch):
    arq = _monta_fila(tmp_path, monkeypatch, datetime.now() - timedelta(days=2))
    # se o guard falhar e o fluxo avançar, resolver_conexao explode o teste
    monkeypatch.setattr(postador, "resolver_conexao",
                        lambda cfg: (_ for _ in ()).throw(AssertionError("tentou postar job vencido")))
    postador.processar_fila({"max_atraso_horas": 6})
    linha = _le_status(arq)
    assert linha["status"] == "vencido"
    assert "remarca" in linha["resultado"]


def test_atraso_do_mesmo_dia_segue_no_catch_up(tmp_path, monkeypatch):
    """2h de atraso (notebook dormiu): NÃO vira vencido — segue o fluxo normal
    (aqui interceptado no pode_postar_agora pra não ir longe)."""
    arq = _monta_fila(tmp_path, monkeypatch, datetime.now() - timedelta(hours=2))
    monkeypatch.setattr(postador, "pode_postar_agora",
                        lambda cfg, fila, conta: (False, "teste: para aqui"))
    postador.processar_fila({"max_atraso_horas": 6})
    assert _le_status(arq)["status"] == "pendente"


def test_limite_configuravel(tmp_path, monkeypatch):
    """max_atraso_horas do config manda: 1h de atraso com limite 0.5h vence."""
    arq = _monta_fila(tmp_path, monkeypatch, datetime.now() - timedelta(hours=1))
    postador.processar_fila({"max_atraso_horas": 0.5})
    assert _le_status(arq)["status"] == "vencido"
