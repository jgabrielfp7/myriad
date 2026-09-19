"""Gabarito visual da Myriad — coordenadas FIXAS medidas do video1.mp4 (22/08/2026).

O fundo é o EDIT INTEIRO do operador (9:16, com o conteúdo já enquadrado por ele
abaixo de y≈424). A moldura só garante duas coisas: uma tarja preta no topo
onde mora a headline (headline NUNCA cai sobre imagem, por construção) e a
headline em caixa própria com shrink-to-fit — não coube, REPROVA em vez de
renderizar torto.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LARGURA, ALTURA = 1080, 1920
CAIXA_HEADLINE = (50, 200, 1030, 414)   # x0, y0, x1, y1 — base rente à tarja
TOPO_PRETO = 422                        # tarja preta y 0-422 (conteúdo dos edits começa ≥424)
KARAOKE_Y = 1150                        # âncora do karaokê (sobre o conteúdo)

CORPO_MAX, CORPO_MIN, CORPO_PASSO = 108, 48, 4
COR_HEADLINE = (255, 255, 255, 255)


class HeadlineNaoCabe(Exception):
    """A headline não coube em 2 linhas nem no corpo mínimo."""


def _fonte_headline(dir_fontes: Path, corpo: int) -> ImageFont.FreeTypeFont:
    for nome in ("HeadlineMyriad.ttf", "PlayfairDisplay-Italic.ttf", "PlayfairDisplay.ttf"):
        caminho = Path(dir_fontes) / nome
        if caminho.exists():
            fonte = ImageFont.truetype(str(caminho), corpo)
            try:  # fonte variável: usa o peso mais pesado disponível
                fonte.set_variation_by_axes([900])
            except OSError:
                pass
            return fonte
    raise FileNotFoundError(f"Nenhuma fonte de headline em {dir_fontes}")


def _quebrar_equilibrado(texto: str) -> list[str]:
    """Quebra em até 2 linhas no ponto de menor diferença de comprimento."""
    palavras = texto.split()
    if len(palavras) == 1:
        return [texto]
    melhor, menor_dif = None, None
    for i in range(1, len(palavras)):
        l1, l2 = " ".join(palavras[:i]), " ".join(palavras[i:])
        dif = abs(len(l1) - len(l2))
        if menor_dif is None or dif < menor_dif:
            melhor, menor_dif = [l1, l2], dif
    return melhor


def desenhar_moldura(headline: str, dir_fontes: Path) -> Image.Image:
    """Moldura 1080×1920 RGBA: transparente (o edit aparece por baixo), com a
    tarja preta do topo e a headline (shrink-to-fit) na caixa dela."""
    headline = " ".join(headline.upper().split())
    im = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, LARGURA, TOPO_PRETO), fill=(0, 0, 0, 255))

    hx0, hy0, hx1, hy1 = CAIXA_HEADLINE
    larg_max, alt_max = hx1 - hx0, hy1 - hy0
    if "/" in headline:  # quebra manual: "LINHA UM / LINHA DOIS"
        linhas = [l.strip() for l in headline.split("/") if l.strip()][:2]
    else:
        linhas = _quebrar_equilibrado(headline) if len(headline) > 22 else [headline]

    for corpo in range(CORPO_MAX, CORPO_MIN - 1, -CORPO_PASSO):
        fonte = _fonte_headline(dir_fontes, corpo)
        entrelinha = int(corpo * 1.18)
        caixas = [d.textbbox((0, 0), l, font=fonte) for l in linhas]
        largs = [c[2] - c[0] for c in caixas]
        alt_total = entrelinha * (len(linhas) - 1) + (caixas[-1][3] - caixas[-1][1])
        if max(largs) <= larg_max and alt_total <= alt_max:
            # ancorada na BASE da caixa (rente à tarja), como nos vídeos-modelo:
            # o corpo varia com o tamanho do texto, a posição de baixo não
            y = hy1 - alt_total - caixas[0][1]
            for linha, c in zip(linhas, caixas):
                x = hx0 + (larg_max - (c[2] - c[0])) // 2 - c[0]
                d.text((x, y), linha, font=fonte, fill=COR_HEADLINE)
                y += entrelinha
            return im

    raise HeadlineNaoCabe(
        f"Headline não coube em 2 linhas nem no corpo {CORPO_MIN}: “{headline}” "
        f"({len(headline)} caracteres — encurte o texto)")
