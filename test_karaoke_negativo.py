# -*- coding: utf-8 -*-
"""Testes da legenda em NEGATIVO (pedido do operador, 03/09).

O efeito inverte o que passa atrás das letras. Ele é feito com blend
`difference`: uma camada preta com o texto BRANCO em cima do vídeo. Onde a
camada é preta, |base-0| = base (nada muda); onde é branca, |base-255| =
255-base (inverte). Por isso a camada de máscara precisa ser branco puro e
SEM sombra — sombra cinza inverteria parcialmente e sujaria a volta da letra.
"""
from pathlib import Path

from fabrica import karaoke


PALAVRAS = [{"palavra": "voce", "inicio": 0.0, "fim": 0.4},
            {"palavra": "pediu", "inicio": 0.4, "fim": 0.9}]
FONTES = Path("fabrica/fontes")


def test_no_negativo_as_duas_cores_viram_branco_puro():
    ass = karaoke.gerar_ass(PALAVRAS, {"pediu"}, FONTES, negativo=True)
    estilos = [l for l in ass.splitlines() if l.startswith("Style:")]
    assert estilos, "sem linhas de estilo no .ass"
    for linha in estilos:
        assert "&H00FFFFFF" in linha, f"cor nao e branca: {linha}"
    # e a cor creme/dourada do modo normal nao pode sobrar
    assert karaoke.COR_NORMAL not in ass
    assert karaoke.COR_DESTAQUE not in ass


def test_no_negativo_a_sombra_e_zerada():
    """Sombra cinza vira inversao parcial: borra a letra inteira."""
    ass = karaoke.gerar_ass(PALAVRAS, set(), FONTES, negativo=True)
    for linha in [l for l in ass.splitlines() if l.startswith("Style:")]:
        campos = linha.split(",")
        outline, shadow = campos[16].strip(), campos[17].strip()
        assert outline == "0", f"outline deveria ser 0: {linha}"
        assert shadow == "0", f"shadow deveria ser 0: {linha}"


def test_modo_normal_continua_creme_e_dourado():
    """Regressão: o vídeo antigo não pode mudar de cara sem pedido."""
    ass = karaoke.gerar_ass(PALAVRAS, {"pediu"}, FONTES)
    assert karaoke.COR_NORMAL in ass
    assert karaoke.COR_DESTAQUE in ass


def test_negativo_mantem_os_tempos_das_palavras():
    """O efeito é de cor. A sincronia do karaokê não pode mudar."""
    normal = karaoke.gerar_ass(PALAVRAS, set(), FONTES)
    neg = karaoke.gerar_ass(PALAVRAS, set(), FONTES, negativo=True)
    tempos = lambda a: [l.split(",")[1:3] for l in a.splitlines() if l.startswith("Dialogue:")]
    assert tempos(normal) == tempos(neg)


# ------------------------------------------- contorno de legibilidade

def test_contorno_tem_preenchimento_transparente_e_traco_opaco():
    """No negativo, palavra sobre fundo de tom MÉDIO some: invertido de cinza
    médio continua cinza médio (medido no render de 03/09, palavra 'quiser'
    sobre uma camisa azul). O contorno é uma segunda passada, desenhada FORA
    da inversão: só o traço, sem preencher — senão taparia o efeito."""
    ass = karaoke.gerar_ass(PALAVRAS, set(), FONTES, contorno=True)
    for linha in [l for l in ass.splitlines() if l.startswith("Style:")]:
        campos = linha.split(",")
        primaria, outline_cor, outline = campos[3], campos[5], campos[16]
        assert primaria.upper().startswith("&HFF"), f"preenchimento nao e transparente: {linha}"
        assert outline_cor.upper() == "&H00000000", f"traco deveria ser preto opaco: {linha}"
        assert int(outline) > 0, f"sem espessura de traco: {linha}"


def test_contorno_mantem_os_mesmos_tempos():
    base = karaoke.gerar_ass(PALAVRAS, set(), FONTES, negativo=True)
    cont = karaoke.gerar_ass(PALAVRAS, set(), FONTES, contorno=True)
    tempos = lambda a: [l.split(",")[1:3] for l in a.splitlines() if l.startswith("Dialogue:")]
    assert tempos(base) == tempos(cont)
