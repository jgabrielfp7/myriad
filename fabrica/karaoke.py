"""Karaokê palavra-a-palavra em .ass, no estilo do video1 (modelo Myriad):
serif bold creme, uma palavra por vez, centralizada em (540, KARAOKE_Y).
Regras anti-defeito do parceiro: palavra fica até a próxima começar (sem
buraco preto) e nenhuma palavra fica menos de 0,12s na tela."""
import re
import unicodedata
from pathlib import Path

from PIL import ImageFont

from .gabarito import KARAOKE_Y

MINIMO = 0.12
RESPIRO_FINAL = 0.6
CORPO = 78                   # medido dos vídeos reais (~75-80px de glifo)
COR_NORMAL = "&H00C0FEFF"    # BGR de #FFFEC0 (amarelo-creme do CapCut do operador)
COR_DESTAQUE = "&H006AC4E9"  # BGR de #E9C46A (dourado)


def _norm(p: str) -> str:
    s = unicodedata.normalize("NFD", p.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def _t(segundos: float) -> str:
    h = int(segundos // 3600)
    m = int(segundos % 3600 // 60)
    s = segundos % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _nome_fonte(dir_fontes: Path) -> str:
    """O .ass referencia a fonte pelo nome de FAMÍLIA interno do .ttf (o libass
    não olha o nome do arquivo) — lê do arquivo pra nunca divergir."""
    arq = Path(dir_fontes) / "KaraokeMyriad.ttf"
    if not arq.exists():
        return "Playfair Display"
    familia, estilo = ImageFont.truetype(str(arq), 40).getname()
    return familia if estilo.lower() in ("regular", "") else f"{familia} {estilo}"


BRANCO = "&H00FFFFFF"        # branco puro: a máscara do efeito de negativo


TRANSPARENTE = "&HFF000000"  # alfa FF = invisível (ASS usa &HAABBGGRR)
PRETO = "&H00000000"
TRACO = 4                    # espessura do contorno (2 sumia em fundo de tom medio)


def gerar_ass(palavras_casadas: list[dict], destaques: set[str], dir_fontes: Path,
              negativo: bool = False, contorno: bool = False) -> str:
    """O `.ass` do karaokê. Em `negativo=True` sai a MÁSCARA do efeito.

    O negativo (pedido do operador, 03/09) é feito com blend `difference`: esta
    máscara — texto branco sobre preto — vai por cima do vídeo. Onde é preta,
    |base-0| = base e nada muda; onde é branca, |base-255| = 255-base e a
    imagem inverte dentro da letra.

    Por isso a máscara é branco puro e **sem sombra**: sombra cinza inverteria
    parcialmente e deixaria um halo sujo em volta de cada palavra. O destaque
    dourado também some — no negativo não existe cor, existe inversão.
    """
    destaques_norm = {_norm(d) for d in destaques}
    fonte = _nome_fonte(dir_fontes)
    cor_normal = BRANCO if negativo else COR_NORMAL
    cor_destaque = BRANCO if negativo else COR_DESTAQUE
    sombra = 0 if negativo else 3
    cor_traco, traco = PRETO, 0
    if contorno:
        # Só o traço, sem preencher: esta passada é desenhada FORA da inversão,
        # por cima dela. Se preenchesse, taparia o efeito que ela serve pra
        # tornar legível. Existe porque palavra invertida sobre fundo de tom
        # médio some (visto no render de 03/09).
        cor_normal = cor_destaque = TRANSPARENTE
        cor_traco, traco, sombra = PRETO, TRACO, 0
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Palavra,{fonte},{CORPO},{cor_normal},{cor_normal},{cor_traco},&H80000000,-1,-1,0,0,100,100,0,0,1,{traco},{sombra},5,0,0,0,1
Style: Destaque,{fonte},{CORPO},{cor_destaque},{cor_destaque},{cor_traco},&H80000000,-1,-1,0,0,100,100,0,0,1,{traco},{sombra},5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    eventos = []
    n = len(palavras_casadas)
    fim_anterior = 0.0
    for i, p in enumerate(palavras_casadas):
        # Nunca nasce por cima da anterior: palavras muito rápidas eram
        # esticadas pelo MINIMO e ficavam DUAS na mesma posição — texto
        # sobreposto na tela (bug relatado pelo operador em 2026-08-24).
        ini = max(p["inicio"], fim_anterior)
        if i + 1 < n:
            fim = palavras_casadas[i + 1]["inicio"]  # até a próxima: sem buraco
        else:
            fim = p["fim"] + RESPIRO_FINAL
        if fim - ini < MINIMO:
            fim = ini + MINIMO
        fim_anterior = fim
        estilo = "Destaque" if _norm(p["palavra"]) in destaques_norm else "Palavra"
        texto = p["palavra"].replace("{", "").replace("}", "")
        eventos.append(
            f"Dialogue: 0,{_t(ini)},{_t(fim)},{estilo},,0,0,0,,"
            f"{{\\pos(540,{KARAOKE_Y})}}{texto}")
    return cab + "\n".join(eventos) + "\n"
