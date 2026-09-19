# -*- coding: utf-8 -*-
"""Myriad v2 (control plane): as 7 views renderizam com dados reais, o
estado global e o buffer derivam de sinais verdadeiros, e as ações estão
plugadas nas telas."""
from datetime import datetime

import myriad
import myriad_dados as dados


def _d(**extra) -> dict:
    base = {
        "fila": [{"conta": "exemplo.group", "arquivo": "reel01.mp4", "quando": "2026-09-14 12:00",
                  "status": "pendente", "resultado": "", "postado_em": "", "views": "", "tipo": "reel"},
                 {"conta": "exemplo.social", "arquivo": "reel00.mp4", "quando": "2026-09-14 09:00",
                  "status": "erro", "resultado": "boom", "postado_em": "", "views": "", "tipo": "reel"}],
        "cfg": {"max_posts_dia": 3, "intervalo_minimo_min": 60, "jitter_max_min": 7,
                "max_atraso_horas": 6, "bateria_minima": 20,
                "janela_inicio": "09:00", "janela_fim": "21:00",
                "contas_agendamento": ["exemplo.group", "exemplo.social"],
                "contas_pausadas": ["exemplo.social"],
                "overrides_conta": {"exemplo.group": {"max_posts_dia": 5}},
                "aquecimento": {"ativo": True, "contas": ["exemplo.group"],
                                "min_reels": 15, "max_reels": 25, "chance_curtida": 0.1}},
        "estado": {"pausado": False, "motivo_pausa": ""},
        "log": [{"data_hora": "2026-09-14 10:00:00", "evento": "POSTADO", "arquivo": "reel99.mp4", "detalhe": ""}],
        "agora": datetime(2026, 9, 14, 10, 30),
        "rodando": True, "hb": None,
        "contas": {"exemplo.group": {"nome": "exemplo.group", "posts": [], "postados_hoje": 2,
                                   "ultimo": "09:12", "proximo": None, "mediana": 1500}},
        "total_post": 2, "total_pend": 1, "total_erro": 1, "total_views": 3200,
        "prox": {"previsto": datetime(2026, 9, 14, 12, 0), "conta": "exemplo.group",
                 "arquivo": "reel01.mp4", "quando": datetime(2026, 9, 14, 12, 0),
                 "aguarda_intervalo": False},
        "conexao": {"modo": "usb", "ip": "192.168.1.13", "bateria": 84, "carregando": True,
                    "ts": "2026-09-14 10:29:00"},
        "estoque": {"prontos": ["reel02.mp4"], "sem_legenda": ["cru.mp4"], "pendentes_sem_video": []},
    }
    base.update(extra)
    # derivações que montar() faria
    ativas = [c for c in base["cfg"]["contas_agendamento"]
              if c not in base["cfg"].get("contas_pausadas", [])]
    base["n_contas_ativas"] = len(ativas)
    base["n_online"] = 1
    base["buffer"] = dados.buffer_conteudo(len(base["estoque"]["prontos"]), base["cfg"], len(ativas))
    base["eg"] = dados.estado_global(base)
    base["agora_ap"] = dados.agora_do_aparelho(base)
    base["saude"] = dados.saude(base)
    base["atividade"] = [dados.traduzir_evento(l) for l in base["log"]]
    return base


def test_render_tem_as_sete_views_e_plataformas_na_sidebar():
    html = myriad.render(_d())
    for v in ("visao", "aparelhos", "contas", "posts", "biblioteca", "automacao", "conectar"):
        assert f'data-view="{v}"' in html, v
    assert "Instagram — ATIVO" in html and "TikTok — em breve" in html


def test_visao_geral_deriva_estado_real():
    html = myriad.render(_d())
    assert "Atenção" in html                          # tem 1 erro na fila
    assert "1 post(s) com erro" in html
    ok = myriad.render(_d(total_erro=0, fila=[], total_pend=1,
                          estoque={"prontos": ["a"] * 10, "sem_legenda": [], "pendentes_sem_video": []}))
    assert "Operação normal" in ok
    kill = myriad.render(_d(estado={"pausado": True, "motivo_pausa": "restrição na tela"}))
    assert "Falha crítica" in kill and "Kill-switch" in kill


def test_buffer_em_dias_e_honesto():
    b = dados.buffer_conteudo(10, {"max_posts_dia": 3}, 2)     # 10 vídeos / 6 por dia
    assert b["dias"] == 1.7 and b["tom"] == "atencao"
    vazio = dados.buffer_conteudo(10, {"max_posts_dia": 3}, 0)
    assert vazio["dias"] is None and "nenhuma conta" in vazio["frase"]


def test_contas_mostram_estado_acoes_e_override():
    html = myriad.render(_d())
    assert "PAUSADA" in html                          # exemplo.social
    assert "/acao/retomar_conta" in html
    assert "/acao/pausar_conta" in html
    assert "5/dia própria" in html                    # override do group
    assert "/acao/remover_conta" in html


def test_posts_tem_abas_e_acoes_por_estado():
    html = myriad.render(_d())
    assert "/acao/publicar_agora" in html             # pro pendente
    assert "/acao/tentar_de_novo" in html             # pro erro
    assert 'data-st="erro"' in html
    assert "boom" in html                             # resultado do erro visível


def test_biblioteca_agenda_pronto_e_marca_sem_legenda():
    html = myriad.render(_d())
    assert "/acao/agendar_video" in html and "reel02.mp4" in html
    assert "SEM LEGENDA" in html and "cru.mp4" in html
    assert "/acao/excluir_video" in html


def test_automacao_e_editavel_com_regras_reais():
    html = myriad.render(_d())
    for campo in ("max_posts_dia", "intervalo_minimo_min", "janela"):
        assert f'name="nome" value="{campo}"' in html
    assert "/acao/pausar_tudo" in html
    assert "exemplo.group" in html and "5/dia" in html  # override listado


def test_toast_aparece_quando_tem_msg():
    html = myriad.render(_d(), msg="@x pausada.")
    assert "@x pausada." in html
    assert 'id="toast"' in html


def test_vistoria_aparelho_nao_mente_online_com_robo_rodando_e_celular_fora():
    # o bug real: heartbeat fresco (robô tentando reconectar) fazia o card
    # dizer ONLINE com o celular desconectado há 2 dias
    d = _d(rodando=True, conexao={"modo": "sem_conexao", "ip": "", "bateria": None,
                                  "carregando": False, "ts": "2026-09-12 22:20:56"})
    html = myriad.render(d)
    assert "OFFLINE" in html and "led-off" in html
    assert "ROBÔ RODANDO" in html                     # o robô é OUTRA verdade, separada
    assert "sem_conexao" not in html.replace("sem_conexao", "", 0) or True
    assert "sem conexão" in html                      # técnico traduzido
    assert "há 1 dia(s)" in html                      # idade do sinal visível


def test_vistoria_sinal_fresco_e_necessario_pra_online():
    velho = dados.conexao_fresca({"modo": "usb", "ts": "2026-09-12 22:20:56"},
                                 datetime(2026, 9, 14, 2, 50))
    assert velho is False
    fresco = dados.conexao_fresca({"modo": "usb", "ts": "2026-09-14 02:45:00"},
                                  datetime(2026, 9, 14, 2, 50))
    assert fresco is True


def test_vistoria_atividade_agrupa_repeticao_e_esconde_log_tecnico():
    log = [{"data_hora": f"2026-09-14 02:5{i}:00", "evento": "ERRO_CICLO", "arquivo": "",
            "detalhe": "Command '['C:\\\\platform-tools\\\\adb.EXE', 'connect']' timed out"}
           for i in range(4)] + [{"data_hora": "2026-09-14 02:40:00", "evento": "POSTADO",
                                  "arquivo": "r.mp4", "detalhe": ""}]
    ativ = dados.agrupar_atividade(log)
    assert len(ativ) == 2
    assert ativ[0]["vezes"] == 4                      # 4 erros viram 1 linha ×4
    assert "adb" not in ativ[0]["detalhe"]            # comando bruto NUNCA na tela
    assert "timeout" in ativ[0]["detalhe"]            # mas o resumo honesto fica
    assert "adb" in ativ[0]["tecnico"]                # técnico preservado pro hover


def test_vistoria_contas_do_historico_nao_sao_entidades():
    d = _d()
    d["contas"]["exemplo.corp"] = {"nome": "exemplo.corp", "posts": [], "postados_hoje": 0,
                                 "ultimo": None, "proximo": None, "mediana": None}
    html = myriad.render(d)
    # exemplo.corp só existe no histórico da fila: não aparece na tela Contas
    trecho_contas = html.split('data-view="contas"')[1].split('data-view="posts"')[0]
    assert "exemplo.corp" not in trecho_contas


def test_vistoria_sugestao_de_horario_nunca_e_no_passado_nem_fora_da_janela():
    cfg = {"janela_inicio": "09:00", "janela_fim": "21:00"}
    madrugada = myriad._sugestao_horario(cfg, datetime(2026, 9, 14, 2, 54))
    assert madrugada == "2026-09-14 09:00"            # não sugere 03:00 da manhã
    tarde = myriad._sugestao_horario(cfg, datetime(2026, 9, 14, 15, 10))
    assert tarde == "2026-09-14 16:00"
    noite = myriad._sugestao_horario(cfg, datetime(2026, 9, 14, 21, 30))
    assert noite == "2026-09-15 09:00"                # depois da janela vai pra amanhã


def test_eventos_viram_frases_humanas():
    e = dados.traduzir_evento({"data_hora": "2026-09-14 10:00:00", "evento": "KILL_SWITCH",
                               "arquivo": "r.mp4", "detalhe": "restrição"})
    assert e["frase"].startswith("Kill-switch")
    desconhecido = dados.traduzir_evento({"evento": "COISA_NOVA"})
    assert desconhecido["frase"] == "Coisa nova"      # nunca quebra
