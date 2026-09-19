# -*- coding: utf-8 -*-
"""Testes do agendador manual.

Decisão do operador (03/09): a fábrica sai do caminho — ele produz os vídeos e o
robô só posta. Então o buraco a fechar é: largar o .mp4 numa pasta com o nome
da conta e o robô agendar sozinho, sem ninguém editar fila.csv na mão (editar
CSV à mão já custou post perdido antes).
"""
from datetime import datetime
from pathlib import Path

import pytest

import agendar


CFG = {"max_posts_dia": 3, "intervalo_minimo_min": 60, "jitter_max_min": 7,
       "janela_inicio": "09:00", "janela_fim": "21:00"}


def _video_pronto(pasta: Path, nome: str, legenda: str = "legenda") -> Path:
    """Um vídeo 'pronto' é mp4 + .txt de mesmo nome — o postador lê a legenda
    do .txt irmão."""
    pasta.mkdir(parents=True, exist_ok=True)
    mp4 = pasta / f"{nome}.mp4"
    mp4.write_bytes(b"video")
    (pasta / f"{nome}.txt").write_text(legenda, encoding="utf-8")
    return mp4


# ------------------------------------------------------------ nome da conta

def test_slug_da_conta_vira_prefixo_curto():
    assert agendar.slug_conta("exemplo.group") == "group"
    assert agendar.slug_conta("exemplo.mind") == "mind"


def test_slug_aceita_conta_sem_ponto():
    assert agendar.slug_conta("minhaconta") == "minhaconta"


# --------------------------------------------------------- achar os prontos

def test_so_entra_video_que_tem_legenda(tmp_path):
    """Sem o .txt o postador publica sem legenda — melhor não agendar e avisar."""
    pasta = tmp_path / "videos" / "exemplo.group"
    _video_pronto(pasta, "com-legenda")
    (pasta / "sem-legenda.mp4").write_bytes(b"video")

    prontos = agendar.descobrir_prontos(tmp_path / "videos", "exemplo.group")

    assert [p.name for p in prontos] == ["com-legenda.mp4"]


def test_pasta_de_conta_inexistente_nao_e_erro(tmp_path):
    assert agendar.descobrir_prontos(tmp_path / "videos", "exemplo.mind") == []


# ---------------------------------------------------- nome final no postador

def test_nome_final_ganha_o_prefixo_da_conta():
    """O postador procura o arquivo direto em videos/, então o arquivo sai da
    pasta da conta. O prefixo mantém a rastreabilidade (já era a convenção:
    group-reel68.mp4)."""
    assert agendar.nome_no_postador("exemplo.group", "aula1.mp4", set()) == "group-aula1.mp4"


def test_nome_final_desvia_de_colisao():
    usados = {"group-aula1.mp4", "group-aula1-2.mp4"}
    assert agendar.nome_no_postador("exemplo.group", "aula1.mp4", usados) == "group-aula1-3.mp4"


# ------------------------------------------------------------- horários

def test_horarios_respeitam_o_intervalo_minimo():
    hs = agendar.horarios_do_dia(datetime(2026, 9, 4), 3, CFG, semente="x")
    assert len(hs) == 3
    for antes, depois in zip(hs, hs[1:]):
        assert (depois - antes).total_seconds() / 60 >= CFG["intervalo_minimo_min"]


def test_horarios_ficam_dentro_da_janela():
    hs = agendar.horarios_do_dia(datetime(2026, 9, 4), 3, CFG, semente="x")
    assert all(datetime(2026, 9, 4, 9) <= h <= datetime(2026, 9, 4, 21) for h in hs)


def test_horarios_variam_entre_contas_no_mesmo_dia():
    """Três contas postando no mesmo minuto, todo dia, é padrão de robô."""
    a = agendar.horarios_do_dia(datetime(2026, 9, 4), 3, CFG, semente="group")
    b = agendar.horarios_do_dia(datetime(2026, 9, 4), 3, CFG, semente="mind")
    assert a != b


# --------------------------------------------------------------- planejar

def test_plano_respeita_o_teto_diario_e_empurra_o_resto(tmp_path):
    pasta = tmp_path / "videos" / "exemplo.group"
    for i in range(5):
        _video_pronto(pasta, f"v{i}")

    plano = agendar.planejar({"exemplo.group": agendar.descobrir_prontos(
        tmp_path / "videos", "exemplo.group")}, [], CFG,
        agora=datetime(2026, 9, 4, 8, 0))

    dias = [linha["quando"][:10] for linha in plano]
    assert len(plano) == 5
    assert dias.count("2026-09-04") == 3       # teto do dia
    assert dias.count("2026-09-05") == 2       # o resto vai pro dia seguinte


def test_plano_respeita_override_da_conta(tmp_path):
    """O painel dá limite próprio por conta (Semana 1: group a 4/dia com
    global 3); o agendador tem que enxergar o mesmo override do motor."""
    pasta = tmp_path / "videos" / "exemplo.group"
    for i in range(5):
        _video_pronto(pasta, f"v{i}")
    cfg = {**CFG, "overrides_conta": {"exemplo.group": {"max_posts_dia": 4}}}

    plano = agendar.planejar({"exemplo.group": agendar.descobrir_prontos(
        tmp_path / "videos", "exemplo.group")}, [], cfg,
        agora=datetime(2026, 9, 4, 8, 0))

    dias = [linha["quando"][:10] for linha in plano]
    assert dias.count("2026-09-04") == 4       # teto próprio da conta
    assert dias.count("2026-09-05") == 1


def test_plano_nunca_agenda_no_passado(tmp_path):
    pasta = tmp_path / "videos" / "exemplo.group"
    _video_pronto(pasta, "v0")

    plano = agendar.planejar({"exemplo.group": agendar.descobrir_prontos(
        tmp_path / "videos", "exemplo.group")}, [], CFG,
        agora=datetime(2026, 9, 4, 20, 45))     # janela do dia praticamente no fim

    assert plano[0]["quando"] > "2026-09-04 20:45"


def test_plano_conta_o_que_a_conta_ja_tem_agendado_hoje(tmp_path):
    """Se já existem 2 pendentes hoje, só cabe mais 1 antes de virar o dia."""
    pasta = tmp_path / "videos" / "exemplo.group"
    for i in range(3):
        _video_pronto(pasta, f"v{i}")
    fila = [{"conta": "exemplo.group", "arquivo": "x.mp4", "quando": "2026-09-04 10:00",
             "status": "pendente", "resultado": "", "postado_em": "", "views": "", "tipo": "reel"},
            {"conta": "exemplo.group", "arquivo": "y.mp4", "quando": "2026-09-04 12:00",
             "status": "pendente", "resultado": "", "postado_em": "", "views": "", "tipo": "reel"}]

    plano = agendar.planejar({"exemplo.group": agendar.descobrir_prontos(
        tmp_path / "videos", "exemplo.group")}, fila, CFG,
        agora=datetime(2026, 9, 4, 8, 0))

    dias = [l["quando"][:10] for l in plano]
    assert dias.count("2026-09-04") == 1
    assert dias.count("2026-09-05") == 2


def test_plano_isola_as_contas_uma_da_outra(tmp_path):
    """Guardrail é POR CONTA: a group estar cheia não pode empurrar a mind."""
    for conta in ("exemplo.group", "exemplo.mind"):
        for i in range(3):
            _video_pronto(tmp_path / "videos" / conta, f"v{i}")
    prontos = {c: agendar.descobrir_prontos(tmp_path / "videos", c)
               for c in ("exemplo.group", "exemplo.mind")}

    plano = agendar.planejar(prontos, [], CFG, agora=datetime(2026, 9, 4, 8, 0))

    por_conta = {}
    for l in plano:
        por_conta.setdefault(l["conta"], []).append(l["quando"][:10])
    assert por_conta["exemplo.group"].count("2026-09-04") == 3
    assert por_conta["exemplo.mind"].count("2026-09-04") == 3


# ---------------------------------------------------------------- aplicar

def test_aplicar_move_video_e_legenda_pra_pasta_do_postador(tmp_path):
    videos = tmp_path / "videos"
    _video_pronto(videos / "exemplo.group", "aula1", legenda="minha legenda")
    plano = agendar.planejar({"exemplo.group": agendar.descobrir_prontos(videos, "exemplo.group")},
                             [], CFG, agora=datetime(2026, 9, 4, 8, 0))
    arq_fila = tmp_path / "fila.csv"

    agendar.aplicar(plano, videos, arq_fila)

    assert (videos / "group-aula1.mp4").exists()
    assert (videos / "group-aula1.txt").read_text(encoding="utf-8") == "minha legenda"
    assert not (videos / "exemplo.group" / "aula1.mp4").exists()   # saiu da pasta de entrada


def test_aplicar_acrescenta_na_fila_sem_apagar_o_que_havia(tmp_path):
    import csv
    videos = tmp_path / "videos"
    _video_pronto(videos / "exemplo.group", "aula1")
    arq_fila = tmp_path / "fila.csv"
    with arq_fila.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=agendar.CAMPOS_FILA)
        w.writeheader()
        w.writerow({"conta": "exemplo.mind", "arquivo": "antigo.mp4",
                    "quando": "2026-08-01 10:00", "status": "postado",
                    "resultado": "ok", "postado_em": "2026-08-01 10:05",
                    "views": "42", "tipo": "reel"})

    plano = agendar.planejar({"exemplo.group": agendar.descobrir_prontos(videos, "exemplo.group")},
                             [], CFG, agora=datetime(2026, 9, 4, 8, 0))
    agendar.aplicar(plano, videos, arq_fila)

    linhas = list(csv.DictReader(arq_fila.open(encoding="utf-8-sig")))
    assert [l["arquivo"] for l in linhas] == ["antigo.mp4", "group-aula1.mp4"]
    assert linhas[1]["status"] == "pendente"
    assert linhas[1]["tipo"] == "reel"


def test_aplicar_e_atomico_se_o_video_sumir_no_meio(tmp_path):
    """Se o arquivo some entre planejar e aplicar, nada entra na fila — linha
    pendente apontando pra vídeo inexistente faz o robô adiar pra sempre."""
    videos = tmp_path / "videos"
    _video_pronto(videos / "exemplo.group", "aula1")
    plano = agendar.planejar({"exemplo.group": agendar.descobrir_prontos(videos, "exemplo.group")},
                             [], CFG, agora=datetime(2026, 9, 4, 8, 0))
    (videos / "exemplo.group" / "aula1.mp4").unlink()
    arq_fila = tmp_path / "fila.csv"

    with pytest.raises(agendar.VideoSumiu):
        agendar.aplicar(plano, videos, arq_fila)

    assert not arq_fila.exists()


def test_usa_o_resto_do_dia_quando_o_pedido_chega_tarde(tmp_path):
    """Pedido do operador às 18h30 de 03/09: "comece a postar hoje". Os horários
    fixos do dia (09h, 13h, 17h) já passaram, e o plano jogava TUDO pra amanhã
    — descartando 2h30 de janela útil. Chegando tarde, o dia começa AGORA."""
    pasta = tmp_path / "videos" / "exemplo.social"
    for i in range(4):
        _video_pronto(pasta, f"v{i}")

    plano = agendar.planejar({"exemplo.social": agendar.descobrir_prontos(
        tmp_path / "videos", "exemplo.social")}, [], CFG,
        agora=datetime(2026, 9, 3, 18, 30))

    hoje = [l["quando"] for l in plano if l["quando"].startswith("2026-09-03")]
    assert len(hoje) >= 2, f"deveria caber 2+ hoje ainda: {hoje}"
    assert all(h > "2026-09-03 18:30" for h in hoje)
    assert all(h <= "2026-09-03 21:00" for h in hoje)


def test_mesmo_chegando_tarde_o_intervalo_minimo_e_respeitado(tmp_path):
    pasta = tmp_path / "videos" / "exemplo.social"
    for i in range(3):
        _video_pronto(pasta, f"v{i}")

    plano = agendar.planejar({"exemplo.social": agendar.descobrir_prontos(
        tmp_path / "videos", "exemplo.social")}, [], CFG,
        agora=datetime(2026, 9, 3, 18, 30))

    hoje = sorted(l["quando"] for l in plano if l["quando"].startswith("2026-09-03"))
    for antes, depois in zip(hoje, hoje[1:]):
        a = datetime.strptime(antes, "%Y-%m-%d %H:%M")
        d = datetime.strptime(depois, "%Y-%m-%d %H:%M")
        assert (d - a).total_seconds() / 60 >= CFG["intervalo_minimo_min"]
