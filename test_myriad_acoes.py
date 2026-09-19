# -*- coding: utf-8 -*-
"""As ações do Myriad e o alicerce delas: o lock da fila + merge por linha.
O cenário que justifica tudo: o robô demora minutos postando; o painel
mexe na fila nesse meio tempo; NINGUÉM pode esmagar a mudança do outro."""
import json
from datetime import datetime
from pathlib import Path

import pytest

import myriad_acoes
import postador


@pytest.fixture(autouse=True)
def _mundo_isolado(tmp_path, monkeypatch):
    """Redireciona TODOS os arquivos de estado pro tmp."""
    for mod in (postador, myriad_acoes):
        monkeypatch.setattr(mod, "ARQ_FILA", tmp_path / "fila.csv", raising=False)
        monkeypatch.setattr(mod, "PASTA_VIDEOS", tmp_path / "videos", raising=False)
    monkeypatch.setattr(postador, "ARQ_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(postador, "ARQ_ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(postador, "ARQ_LOG", tmp_path / "logs" / "log.csv")
    monkeypatch.setattr(postador, "PASTA_LOGS", tmp_path / "logs")
    monkeypatch.setattr(postador, "ARQ_FILA_LOCK", tmp_path / "logs" / "fila.lock")
    monkeypatch.setattr(postador, "RAIZ", tmp_path)
    (tmp_path / "videos").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "config.json").write_text(json.dumps({
        "max_posts_dia": 3, "intervalo_minimo_min": 60,
        "contas_agendamento": ["a", "b"], "aquecimento": {"contas": ["a"]},
    }), encoding="utf-8")


def _linha(**kw):
    base = {"conta": "a", "arquivo": "v1.mp4", "quando": "2026-09-14 10:00",
            "status": "pendente", "resultado": "", "postado_em": "", "views": "", "tipo": "reel"}
    return {**base, **kw}


def test_testar_conexao_e_so_leitura_nunca_manda_comando_ao_aparelho(monkeypatch):
    """Regressão 18/09: a versão antiga re-armava o Wi-Fi e mandava `shell`
    de bateria — com o motor postando, o adb serializa e o painel TRAVAVA por
    minutos. O teste garante que só `adb devices` é chamado (nada de tcpip,
    connect ou shell)."""
    import conexao
    chamadas = []

    def _fake_adb(args, timeout=30, bin=None):
        chamadas.append(list(args))
        if args and args[0] == "devices":
            return "List of devices attached\n192.168.1.13:5555\tdevice\n"
        return ""

    monkeypatch.setattr(conexao, "executar_adb", _fake_adb)
    msg = myriad_acoes.testar_conexao()
    assert "Conectado" in msg and "192.168.1.13:5555" in msg
    assert chamadas == [["devices"]]                     # SÓ devices, mais nada
    proibidos = {"tcpip", "connect", "shell"}
    assert not any(set(c) & proibidos for c in chamadas)


def test_reiniciar_instagram_e_pedido_nao_toca_o_adb_direto(monkeypatch):
    """Regressão 18/09: reiniciar o IG pelo painel mandava force-stop na hora
    (disputa o adb com o motor). Agora é PEDIDO consumido pelo motor."""
    import conexao
    monkeypatch.setattr(conexao, "executar_adb",
                        lambda *a, **k: pytest.fail("o painel não pode tocar o adb aqui"))
    postador.salvar_estado({"pausado": False})
    msg = myriad_acoes.reiniciar_instagram()
    assert "pedido" in msg.lower()
    assert postador.carregar_estado().get("reiniciar_ig_pedido") is True
    # segundo clique não duplica
    assert "já pedido" in myriad_acoes.reiniciar_instagram().lower()
    # pausado: recusa
    postador.salvar_estado({"pausado": True})
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.reiniciar_instagram()


def test_merge_por_linha_preserva_mudanca_do_painel_durante_o_post():
    # o robô leu a fila com v1 e v2...
    postador.salvar_fila([_linha(), _linha(arquivo="v2.mp4")])
    copia_do_robo = postador.ler_fila()
    # ...enquanto postava v1, o painel REAGENDOU v2
    myriad_acoes.reagendar("a", "v2.mp4", "2026-09-15 09:00")
    # o robô terminou v1 e salva SÓ a linha dele
    copia_do_robo[0].update(status="postado", postado_em="2026-09-14 10:05", resultado="ok")
    postador.atualizar_linha_fila(copia_do_robo[0])
    fila = postador.ler_fila()
    assert fila[0]["status"] == "postado"                     # desfecho do robô entrou
    assert fila[1]["quando"] == "2026-09-15 09:00"            # e a mudança do painel SOBREVIVEU


def test_linha_removida_pelo_painel_reaparece_se_o_desfecho_importa():
    postador.salvar_fila([_linha()])
    copia = postador.ler_fila()
    myriad_acoes.remover_post("a", "v1.mp4")
    copia[0].update(status="postado", resultado="ok")
    postador.atualizar_linha_fila(copia[0])                   # histórico não se perde
    assert postador.ler_fila()[0]["status"] == "postado"


def test_pausar_e_retomar_conta_mexem_no_config_e_no_rodizio_do_agendador():
    import agendar
    assert "pausada" in myriad_acoes.pausar_conta("a")
    cfg = postador.carregar_config()
    assert cfg["contas_pausadas"] == ["a"]
    assert agendar._contas_do_config(cfg) == ["b"]            # agendador não enxerga pausada
    assert "retomada" in myriad_acoes.retomar_conta("a")
    assert postador.carregar_config()["contas_pausadas"] == []


def test_motor_pula_linha_de_conta_pausada():
    postador.salvar_fila([_linha(quando="2020-01-01 00:00")])
    myriad_acoes.pausar_conta("a")
    postador.processar_fila(postador.carregar_config(), serial="fake")
    assert postador.ler_fila()[0]["status"] == "pendente"     # nem tentou (nem virou vencido)


def test_publicar_agora_reagendar_cancelar_retry_remover():
    postador.salvar_fila([_linha(), _linha(arquivo="v2.mp4", status="erro", resultado="x")])
    assert "próximo ciclo" in myriad_acoes.publicar_agora("a", "v1.mp4")
    assert postador.ler_fila()[0]["quando"] >= datetime.now().strftime("%Y-%m-%d")
    assert "voltou pra fila" in myriad_acoes.tentar_de_novo("a", "v2.mp4")
    assert postador.ler_fila()[1]["status"] == "pendente"
    assert "cancelado" in myriad_acoes.cancelar_post("a", "v2.mp4")
    assert "removido" in myriad_acoes.remover_post("a", "v2.mp4")
    assert len(postador.ler_fila()) == 1
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.publicar_agora("a", "nao-existe.mp4")


def test_publicado_nao_cancela_nem_remove():
    postador.salvar_fila([_linha(status="postado")])
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.cancelar_post("a", "v1.mp4")
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.remover_post("a", "v1.mp4")


def test_agendar_video_da_biblioteca_exige_legenda_e_recusa_duplicado():
    (postador.PASTA_VIDEOS / "novo.mp4").write_bytes(b"x")
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.agendar_video("novo.mp4", "a", "2026-09-15 10:00")
    (postador.PASTA_VIDEOS / "novo.txt").write_text("legenda", encoding="utf-8")
    assert "agendado" in myriad_acoes.agendar_video("novo.mp4", "a", "2026-09-15 10:00")
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.agendar_video("novo.mp4", "b", "2026-09-16 10:00")


def test_excluir_video_recusa_com_job_pendente_e_leva_a_legenda_junto():
    (postador.PASTA_VIDEOS / "v1.mp4").write_bytes(b"x")
    (postador.PASTA_VIDEOS / "v1.txt").write_text("l", encoding="utf-8")
    postador.salvar_fila([_linha()])
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.excluir_video("v1.mp4")
    myriad_acoes.cancelar_post("a", "v1.mp4")
    assert "excluído" in myriad_acoes.excluir_video("v1.mp4")
    assert not (postador.PASTA_VIDEOS / "v1.mp4").exists()
    assert not (postador.PASTA_VIDEOS / "v1.txt").exists()


def test_override_por_conta_vale_no_motor():
    myriad_acoes.override_conta("a", 1)
    cfg = postador.carregar_config()
    assert cfg["overrides_conta"]["a"]["max_posts_dia"] == 1
    hoje = datetime.now().strftime("%Y-%m-%d 08:00")
    fila = [_linha(status="postado", postado_em=hoje),
            _linha(arquivo="v2.mp4", quando="2020-01-01 00:00")]
    postador.salvar_fila(fila)
    postador.processar_fila(cfg, serial="fake")               # cap 1 da conta já estourou
    assert postador.ler_fila()[1]["status"] in ("pendente", "vencido")
    assert "herdar" in myriad_acoes.override_conta("a", None)


def test_regras_globais_editaveis_com_validacao():
    assert "60" not in myriad_acoes.editar_regra("intervalo_minimo_min", "90")
    assert postador.carregar_config()["intervalo_minimo_min"] == 90
    assert "Janela" in myriad_acoes.editar_regra("janela", "08:30-22:00")
    cfg = postador.carregar_config()
    assert cfg["janela_inicio"] == "08:30" and cfg["janela_fim"] == "22:00"
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.editar_regra("max_posts_dia", "99")
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.editar_regra("hackear", "1")


def test_remover_conta_cancela_pendentes_e_preserva_historico():
    postador.salvar_fila([_linha(), _linha(arquivo="v0.mp4", status="postado")])
    msg = myriad_acoes.remover_conta("a")
    assert "1 post(s) pendente(s)" in msg
    fila = postador.ler_fila()
    assert fila[0]["status"] == "cancelado"
    assert fila[1]["status"] == "postado"                     # histórico fica
    cfg = postador.carregar_config()
    assert "a" not in cfg["contas_agendamento"]
    assert "a" not in cfg["aquecimento"]["contas"]


def test_dedicar_video_move_pra_pasta_da_conta_com_legenda_junto():
    (postador.PASTA_VIDEOS / "meu.mp4").write_bytes(b"x")
    (postador.PASTA_VIDEOS / "meu.txt").write_text("l", encoding="utf-8")
    msg = myriad_acoes.dedicar_video("meu.mp4", "exemplo.group")
    assert "dedicado a @exemplo.group" in msg and "sem legenda" not in msg
    assert (postador.PASTA_VIDEOS / "exemplo.group" / "meu.mp4").exists()
    assert (postador.PASTA_VIDEOS / "exemplo.group" / "meu.txt").exists()
    assert not (postador.PASTA_VIDEOS / "meu.mp4").exists()
    est = myriad_acoes.estoque_dedicado(["exemplo.group"])
    assert est["exemplo.group"] == [{"arquivo": "meu.mp4", "com_legenda": True}]
    assert "voltou" in myriad_acoes.devolver_video("meu.mp4", "exemplo.group")
    assert (postador.PASTA_VIDEOS / "meu.mp4").exists()


def test_dedicar_sem_legenda_avisa_e_com_job_pendente_recusa():
    (postador.PASTA_VIDEOS / "cru.mp4").write_bytes(b"x")
    assert "sem legenda" in myriad_acoes.dedicar_video("cru.mp4", "a")
    (postador.PASTA_VIDEOS / "v1.mp4").write_bytes(b"x")
    postador.salvar_fila([_linha()])
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.dedicar_video("v1.mp4", "b")


def test_distribuir_videos_em_massa_round_robin_com_teto_por_conta():
    """o operador 14/09: marcar vários vídeos e distribuir pras contas escolhidas
    sem agendar um por um. Round-robin entre contas; dentro de cada conta,
    slots automáticos respeitando o teto/dia (com override)."""
    for i in range(6):
        (postador.PASTA_VIDEOS / f"d{i}.mp4").write_bytes(b"x")
        (postador.PASTA_VIDEOS / f"d{i}.txt").write_text("l", encoding="utf-8")
    postador.salvar_fila([])
    myriad_acoes.override_conta("a", 2)           # teto próprio: 2/dia
    msg = myriad_acoes.distribuir_videos([f"d{i}.mp4" for i in range(6)], ["a", "b"])
    assert "6 vídeo(s)" in msg and "@a" in msg and "@b" in msg
    fila = postador.ler_fila()
    assert len(fila) == 6 and all(l["status"] == "pendente" for l in fila)
    de_a = [l for l in fila if l["conta"] == "a"]
    de_b = [l for l in fila if l["conta"] == "b"]
    assert len(de_a) == 3 and len(de_b) == 3      # round-robin
    from collections import Counter
    por_dia_a = Counter(l["quando"][:10] for l in de_a)
    assert max(por_dia_a.values()) <= 2           # override de @a respeitado
    # horários sempre no futuro e sem duplicar arquivo
    assert len({l["arquivo"] for l in fila}) == 6


def test_distribuir_recusa_pausada_sem_legenda_e_duplicado():
    (postador.PASTA_VIDEOS / "ok.mp4").write_bytes(b"x")
    (postador.PASTA_VIDEOS / "ok.txt").write_text("l", encoding="utf-8")
    (postador.PASTA_VIDEOS / "cru.mp4").write_bytes(b"x")
    myriad_acoes.pausar_conta("b")
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.distribuir_videos(["ok.mp4"], ["b"])          # pausada
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.distribuir_videos(["cru.mp4"], ["a"])         # sem legenda
    postador.salvar_fila([_linha(arquivo="ok.mp4")])
    with pytest.raises(myriad_acoes.AcaoInvalida):
        myriad_acoes.distribuir_videos(["ok.mp4"], ["a"])          # já na fila


def test_aquecer_agora_registra_pedido_e_o_motor_consome(monkeypatch):
    """o operador 14/09: aquecimento SÓ pelo botão. O botão registra o pedido;
    o ciclo do motor roda a sessão uma vez e limpa o pedido."""
    assert "pedido" in myriad_acoes.aquecer_agora()
    assert postador.carregar_estado()["aquecer_pedido"] is True
    assert "já pedido" in myriad_acoes.aquecer_agora()          # idempotente
    rodou = []
    monkeypatch.setattr(postador, "_aquecer_sob_demanda",
                        lambda cfg, serial: rodou.append(1) or True)
    postador.processar_aquecimento(postador.carregar_config())
    assert rodou == [1]
    assert "aquecer_pedido" not in postador.carregar_estado()   # consumido
    # sem pedido e com ativo=False, o ciclo não aquece nada
    postador.processar_aquecimento(postador.carregar_config())
    assert rodou == [1]


def test_pausar_tudo_e_o_kill_switch_do_painel():
    assert "pausada" in myriad_acoes.pausar_tudo(True)
    assert postador.carregar_estado()["pausado"] is True
    assert "retomada" in myriad_acoes.pausar_tudo(False)
    assert postador.carregar_estado()["pausado"] is False
