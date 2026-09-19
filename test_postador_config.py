# -*- coding: utf-8 -*-
"""Config sem BOM e integração do modo sem fio (resolver_conexao, status pro
dashboard, RuntimeError sem conexão) — bug do boot em 2026-08-23 e revisão
da Task 3."""
import json

import pytest

import conexao
import postador


def test_resolver_conexao_nao_esmaga_chaves_novas_do_painel(tmp_path, monkeypatch):
    """O clobber de 14/09: o motor (boot antigo) regravava o config da memória
    e apagava overrides_conta/espacamento escritos pelo painel no meio."""
    arq = tmp_path / "config.json"
    monkeypatch.setattr(postador, "ARQ_CONFIG", arq)
    monkeypatch.setattr(postador, "ARQ_LOG", tmp_path / "log.csv")
    monkeypatch.setattr(postador, "PASTA_LOGS", tmp_path)
    cfg_memoria = {"ip_aparelho": "10.0.0.9", "max_posts_dia": 3}
    # enquanto o motor rodava, o painel escreveu uma chave nova no disco
    postador.salvar_config({"max_posts_dia": 3, "ip_aparelho": "10.0.0.1",
                            "overrides_conta": {"g": {"max_posts_dia": 4}}})
    monkeypatch.setattr(postador.conexao, "garantir_conexao",
                        lambda cfg: ("serial-x", True))
    postador.resolver_conexao(cfg_memoria)
    salvo = postador.carregar_config()
    assert salvo["overrides_conta"] == {"g": {"max_posts_dia": 4}}   # sobreviveu
    assert salvo["ip_aparelho"] == "10.0.0.9"                        # só o ip mudou


def test_salvar_config_roundtrip_sem_bom(tmp_path, monkeypatch):
    arq = tmp_path / "config.json"
    monkeypatch.setattr(postador, "ARQ_CONFIG", arq)
    cfg = {"max_posts_dia": 6, "ip_aparelho": "192.168.0.42", "acentuação": "ok"}
    postador.salvar_config(cfg)
    bruto = arq.read_bytes()
    assert not bruto.startswith(b"\xef\xbb\xbf")  # sem BOM
    assert json.loads(bruto.decode("utf-8")) == cfg


def test_resolver_conexao_persiste_config_quando_muda(tmp_path, monkeypatch):
    """cfg mudou (IP novo armado pelo USB): resolver_conexao tem que persistir
    o config sem BOM antes de devolver o serial."""
    arq = tmp_path / "config.json"
    monkeypatch.setattr(postador, "ARQ_CONFIG", arq)
    monkeypatch.setattr(postador, "ARQ_LOG", tmp_path / "log.csv")
    monkeypatch.setattr(conexao, "garantir_conexao", lambda cfg: ("SERIAL", True))
    cfg = {"ip_aparelho": "192.168.0.42"}

    serial = postador.resolver_conexao(cfg)

    assert serial == "SERIAL"
    assert json.loads(arq.read_bytes().decode("utf-8")) == cfg


def test_resolver_conexao_nao_grava_quando_cfg_nao_muda(tmp_path, monkeypatch):
    """USB já armado ou Wi-Fi direto: cfg não muda, não precisa reescrever o
    config a cada ciclo."""
    arq = tmp_path / "config.json"
    monkeypatch.setattr(postador, "ARQ_CONFIG", arq)
    monkeypatch.setattr(conexao, "garantir_conexao", lambda cfg: ("SERIAL", False))

    serial = postador.resolver_conexao({})

    assert serial == "SERIAL"
    assert not arq.exists()  # nada foi escrito


def test_gravar_status_conexao_grava_contrato_completo(tmp_path, monkeypatch):
    """Contrato de logs/status_conexao.json (a Task 4/dashboard depende dele):
    exatamente as chaves ts/modo/ip/bateria/carregando, e modo certo por tipo
    de serial (USB sem ':', Wi-Fi com ':porta', None = sem_conexao)."""
    monkeypatch.setattr(postador, "PASTA_LOGS", tmp_path)
    monkeypatch.setattr(conexao, "ler_bateria", lambda serial: (61, True))
    cfg = {"ip_aparelho": "192.168.0.42"}
    arq = tmp_path / "status_conexao.json"

    postador._gravar_status_conexao("R9X", cfg)
    dados = json.loads(arq.read_text(encoding="utf-8"))
    assert set(dados) == {"ts", "modo", "ip", "bateria", "carregando"}
    assert dados["modo"] == "usb"
    assert dados["bateria"] == 61
    assert dados["carregando"] is True

    postador._gravar_status_conexao("192.168.0.42:5555", cfg)
    dados = json.loads(arq.read_text(encoding="utf-8"))
    assert dados["modo"] == "wifi"

    postador._gravar_status_conexao(None, cfg)
    dados = json.loads(arq.read_text(encoding="utf-8"))
    assert dados["modo"] == "sem_conexao"
    assert dados["bateria"] is None
    assert dados["carregando"] is False


def test_executar_post_sem_conexao_levanta_runtime_error(tmp_path, monkeypatch):
    """Sem serial resolvido (nem USB nem Wi-Fi), executar_post não pode
    tentar conectar no driver — levanta erro claro pro operador plugar o
    cabo uma vez."""
    monkeypatch.setattr(postador, "PASTA_VIDEOS", tmp_path)
    (tmp_path / "video.mp4").write_bytes(b"x")
    (tmp_path / "video.txt").write_text("legenda", encoding="utf-8")
    monkeypatch.setattr(postador, "resolver_conexao", lambda cfg: None)

    with pytest.raises(RuntimeError, match="sem conexão"):
        postador.executar_post({}, "video.mp4")
