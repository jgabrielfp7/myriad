# -*- coding: utf-8 -*-
"""Testes da cadeia de vídeo: 60 fps, bitrate de verdade e legenda em negativo.

Três defeitos medidos em 03/09 nos vídeos que a fábrica produziu:
  1. `fps=25` cravado, com a ORIGEM em 60 — e 60/25 = 2,4, queda irregular:
     o movimento engasga. Os manuais do operador saem 60->30 (queda exata) e ficam
     fluidos.
  2. `-crf 21` junto com `-b:v 12M`: no libx264 o CRF ganha e o bitrate é
     ignorado. O código dizia 12 Mbps e entregava 2,7-4,4.
  3. Legenda em negativo (pedido novo): `difference` sobre máscara branca.
"""
from pathlib import Path

from fabrica import render


ASS = Path("/tmp/karaoke.ass")
FONTES = Path("fabrica/fontes")


def _cadeia(negativo: bool) -> str:
    return ";".join(render.filtros_video(ASS, FONTES, negativo=negativo))


def test_a_cadeia_roda_em_60fps_e_nao_em_25():
    """60 é a taxa da origem: reamostrar pra 25 joga fora metade dos quadros
    E engasga, porque 60 não divide por 25."""
    assert "fps=60" in _cadeia(negativo=False)
    assert "fps=25" not in _cadeia(negativo=False)


def test_negativo_usa_blend_difference():
    c = _cadeia(negativo=True)
    assert "blend=all_mode=difference" in c


def test_negativo_desenha_a_legenda_numa_camada_preta_propria():
    """A máscara precisa nascer preta: no difference, preto = não mexe."""
    c = _cadeia(negativo=True)
    assert "color=black" in c or "drawbox" in c
    assert "subtitles=" in c


def test_modo_normal_continua_queimando_a_legenda_direto():
    """Regressão: sem pedido, o vídeo antigo não muda de aparência."""
    c = _cadeia(negativo=False)
    assert "subtitles=" in c
    assert "blend=" not in c


def test_a_cadeia_sempre_entrega_vout_em_yuv420p():
    """Sem yuv420p o Instagram recusa ou recomprime feio."""
    for neg in (True, False):
        c = _cadeia(negativo=neg)
        assert c.rstrip().endswith("[vout]")
        assert "format=yuv420p" in c


def test_argumentos_do_encoder_nao_tem_crf():
    """Com -crf junto, o -b:v vira decoração. Foi o bug de 2,7 Mbps."""
    args = render.args_encoder()
    assert "-crf" not in args
    assert "-b:v" in args and "12M" in args


def test_encoder_fixa_60fps_na_saida():
    args = render.args_encoder()
    i = args.index("-r")
    assert args[i + 1] == "60"


# ------------------------------------------------- o flag chega no render

def test_produzir_repassa_o_negativo_pro_render(monkeypatch, tmp_path):
    """Plumbing: sem isso o --negativo existe na CLI e nao muda nada no video."""
    from fabrica import fabrica

    recebido = {}

    def falso_renderizar(rot, casadas, audio, **kw):
        recebido.update(kw)
        return tmp_path / "saida.mp4"

    monkeypatch.setattr(fabrica.render, "renderizar", falso_renderizar)
    monkeypatch.setattr(fabrica.alinhar, "transcrever", lambda a: [{"palavra": "oi", "inicio": 0, "fim": 1}])
    monkeypatch.setattr(fabrica.alinhar, "casar", lambda w, t: (w, 1.0))
    monkeypatch.setattr(fabrica.validar, "validar_tudo", lambda *a, **k: [])
    monkeypatch.setattr(fabrica.roteiro, "carregar",
                        lambda p: {"slug": "x", "personagem": "jane", "headline": "H",
                                   "texto_falado": "oi", "destaques": set(), "legenda": "L"})
    audio = tmp_path / "x.mp3"; audio.write_bytes(b"a")
    monkeypatch.setattr(fabrica, "DIR_ENTRADA", tmp_path)
    (tmp_path / "x.txt").write_text("personagem: jane\nheadline: H\n---\noi\n---\nL\n", encoding="utf-8")

    fabrica.produzir("x", negativo=True)

    assert recebido.get("negativo") is True


def test_o_difference_acontece_em_rgb_e_nao_em_yuv():
    """Primeira tentativa saiu com o quadro INTEIRO verde (03/09).

    Em YUV, "preto" é luma 16 e croma 128 — não é zero. O difference então
    subtraía 128 do croma do quadro inteiro e destruía a cor. Em RGB (gbrp)
    preto é 0,0,0 de verdade: |base-0| = base, e só a letra (branco 255)
    inverte. A conversão pra gbrp antes do blend é o que faz o efeito existir.
    """
    c = ";".join(render.filtros_video(ASS, FONTES, negativo=True))
    assert "gbrp" in c, "o blend precisa acontecer em RGB"
    assert c.index("gbrp") < c.index("blend="), "converta ANTES de misturar"
    assert c.rstrip().endswith("[vout]") and "format=yuv420p" in c


def test_negativo_desenha_o_contorno_depois_da_inversao():
    """O traço vem POR CIMA do blend: é ele que garante a forma da letra em
    fundo de tom médio, onde a inversão nao aparece."""
    c = ";".join(render.filtros_video(ASS, FONTES, negativo=True, ass_contorno=Path("/tmp/c.ass")))
    assert c.index("blend=") < c.index("c.ass"), "contorno tem que vir depois do blend"
    assert c.rstrip().endswith("[vout]")


def test_sem_ass_de_contorno_a_cadeia_segue_valida():
    """Regressão: o contorno é opcional."""
    c = ";".join(render.filtros_video(ASS, FONTES, negativo=True))
    assert "blend=" in c and c.rstrip().endswith("[vout]")


def test_contorno_vem_desligado_por_padrao(monkeypatch, tmp_path):
    """o operador assistiu os 21 e pediu a legenda em negativo LIMPA, sem traço
    (03/09). O contorno resolvia legibilidade em fundo de tom médio, mas o
    custo visual não compensou pra ele. Fica no código, atrás de um flag."""
    from fabrica import fabrica
    recebido = {}
    monkeypatch.setattr(fabrica.render, "renderizar",
                        lambda rot, casadas, audio, **kw: recebido.update(kw) or (tmp_path/"x.mp4"))
    monkeypatch.setattr(fabrica.alinhar, "transcrever", lambda a: [{"palavra":"oi","inicio":0,"fim":1}])
    monkeypatch.setattr(fabrica.alinhar, "casar", lambda w, t: (w, 1.0))
    monkeypatch.setattr(fabrica.validar, "validar_tudo", lambda *a, **k: [])
    monkeypatch.setattr(fabrica.roteiro, "carregar",
                        lambda p: {"slug":"x","personagem":"jane","headline":"H",
                                   "texto_falado":"oi","destaques":set(),"legenda":"L"})
    monkeypatch.setattr(fabrica, "DIR_ENTRADA", tmp_path)
    (tmp_path/"x.txt").write_text("personagem: jane\nheadline: H\n---\noi\n---\nL\n", encoding="utf-8")
    (tmp_path/"x.mp3").write_bytes(b"a")

    fabrica.produzir("x", negativo=True)

    assert recebido.get("contorno") is False
