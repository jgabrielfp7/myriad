"""Parser do roteiro modelo MYRIAD (arquivo entrada/<slug>.txt).

Formato:
    personagem: harvey|jane
    headline: TEXTO DA HEADLINE
    ---
    linhas faladas, uma frase por linha, *palavra* = destaque dourado
    ---
    legenda do post (parágrafos livres)
"""
import re
from pathlib import Path

PERSONAGENS = {"harvey", "jane"}


class RoteiroInvalido(Exception):
    pass


def carregar(caminho: Path) -> dict:
    caminho = Path(caminho)
    texto = caminho.read_text(encoding="utf-8")
    partes = [p.strip() for p in re.split(r"^\s*---\s*$", texto, flags=re.M)]
    if len(partes) < 3:
        raise RoteiroInvalido(
            f"{caminho.name}: esperadas 3 seções separadas por '---' "
            f"(cabeçalho / texto falado / legenda), achei {len(partes)}")

    cabecalho, falado, legenda = partes[0], partes[1], "\n\n".join(partes[2:]).strip()

    campos = {}
    for linha in cabecalho.splitlines():
        if ":" in linha:
            chave, valor = linha.split(":", 1)
            campos[chave.strip().lower()] = valor.strip()

    personagem = campos.get("personagem", "").lower()
    if personagem not in PERSONAGENS:
        raise RoteiroInvalido(
            f"{caminho.name}: personagem inválido '{personagem}' — use {sorted(PERSONAGENS)}")

    headline = campos.get("headline", "")
    if not headline:
        raise RoteiroInvalido(f"{caminho.name}: headline vazia ou ausente")

    linhas = [l.strip() for l in falado.splitlines() if l.strip()]
    if not linhas:
        raise RoteiroInvalido(f"{caminho.name}: seção de texto falado vazia")
    if not legenda:
        raise RoteiroInvalido(f"{caminho.name}: seção de legenda vazia")

    destaques = {m.lower() for m in re.findall(r"\*([^*]+)\*", falado)}
    texto_falado = re.sub(r"\*([^*]+)\*", r"\1", " ".join(linhas))

    return {
        "slug": caminho.stem,
        "personagem": personagem,
        "headline": headline,
        "linhas": linhas,
        "texto_falado": texto_falado,
        "destaques": destaques,
        "legenda": legenda,
    }
