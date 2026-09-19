# -*- coding: utf-8 -*-
"""Testes do executar_adb reescrito (bug do pipe herdado pelo daemon do adb).

O cenário fatal (travou o postador por 4h em 24/08 e 1h+ em 25/08): o comando
adb auto-inicia o daemon, o daemon herda o pipe de stdout, e o communicate()
do subprocess.run pós-timeout bloqueia até o daemon morrer. Aqui simulamos o
daemon com um neto que herda o stdout e fica vivo — a chamada tem que voltar
IMEDIATAMENTE com a saída que o filho direto produziu."""
import subprocess
import sys
import time

from conexao import executar_adb

PYTHON = sys.executable


def test_comando_normal_devolve_saida():
    out = executar_adb(["-c", "print('oi adb')"], timeout=15, bin=PYTHON)
    assert "oi adb" in out


def test_timeout_de_filho_pendurado_levanta_rapido():
    ini = time.monotonic()
    try:
        executar_adb(["-c", "import time; time.sleep(60)"], timeout=2, bin=PYTHON)
        assert False, "devia ter levantado TimeoutExpired"
    except subprocess.TimeoutExpired:
        pass
    assert time.monotonic() - ini < 20  # segundos, nunca minutos/horas


def test_neto_orfao_segurando_o_pipe_nao_trava():
    """Filho imprime e SAI; neto (herda o stdout) fica vivo 30s.
    Com subprocess.run(capture_output) isso bloqueia ~30s; aqui tem que
    voltar em poucos segundos COM a saída do filho, sem matar o neto."""
    codigo = ("import subprocess, sys;"
              "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
              "print('filho terminou')")
    ini = time.monotonic()
    out = executar_adb(["-c", codigo], timeout=15, bin=PYTHON)
    assert "filho terminou" in out
    assert time.monotonic() - ini < 10
