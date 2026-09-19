# -*- coding: utf-8 -*-
"""Testes da lógica pura do vigia (idade do heartbeat e decisão de reinício)."""
from datetime import datetime

from vigia import LIMITE_MIN, deve_reiniciar, idade_heartbeat_min

AGORA = datetime(2026, 8, 25, 15, 0, 0)


def test_idade_normal():
    assert idade_heartbeat_min("2026-08-25 14:50:00", AGORA) == 10.0


def test_heartbeat_ilegivel_vira_none():
    assert idade_heartbeat_min("", AGORA) is None
    assert idade_heartbeat_min("lixo", AGORA) is None
    assert idade_heartbeat_min(None, AGORA) is None


def test_nao_reinicia_dentro_do_limite():
    assert deve_reiniciar(10.0) is False
    assert deve_reiniciar(LIMITE_MIN) is False  # exatamente no limite: espera


def test_reinicia_acima_do_limite():
    assert deve_reiniciar(LIMITE_MIN + 1) is True
    assert deve_reiniciar(69.0) is True  # o travamento de hoje (13:53→15:02)


def test_sem_heartbeat_nunca_mata():
    assert deve_reiniciar(None) is False


def test_limite_cobre_silencio_legitimo_de_um_post():
    # jitter 7 + fluxo ~10 + retries ~4 = ~21 min de silêncio legítimo
    assert deve_reiniciar(21.0) is False
