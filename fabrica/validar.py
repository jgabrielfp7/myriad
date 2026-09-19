"""Regras de coerência do operador — validadas ANTES de renderizar.
Regra que não é teste automático não existe (lição do parceiro)."""
from pathlib import Path

from . import alinhar, gabarito

TAXA_MINIMA = 0.8


def validar_tudo(rot: dict, palavras_whisper: list[dict], taxa: float,
                 dir_edits: Path, dir_fontes: Path) -> list[str]:
    """Lista de erros; vazia = aprovado pra render."""
    erros = []

    # 1. áudio ↔ roteiro/headline
    if taxa < TAXA_MINIMA:
        faltando = alinhar.nao_casadas(palavras_whisper, rot["texto_falado"])
        erros.append(
            f"áudio não confirma o roteiro: só {taxa:.0%} das palavras casaram "
            f"(mínimo 80%). Não confirmadas: {' '.join(faltando[:20])}"
            + (" …" if len(faltando) > 20 else ""))

    # 2. voz ↔ personagem: o fundo sai SÓ dos edits do personagem declarado
    pasta = Path(dir_edits) / rot["personagem"]
    edits = list(pasta.glob("*.mp4")) if pasta.exists() else []
    if not edits:
        erros.append(
            f"nenhum edit de '{rot['personagem']}' em {pasta} — "
            f"jogue os edits 9:16 dele lá")

    # 3. headline cabe no gabarito
    try:
        gabarito.desenhar_moldura(rot["headline"], dir_fontes)
    except gabarito.HeadlineNaoCabe as e:
        erros.append(str(e))

    return erros
