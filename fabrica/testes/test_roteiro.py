import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from fabrica import roteiro

EXEMPLO = """personagem: harvey
headline: SE ELE PEDIR DESCONTO NA FRENTE DOS OUTROS
---
Olha o que ele fez ali.
Ele não pediu desconto, pediu *plateia*.
Responda o valor com a mesma *calma* de antes.
---
Você já passou por isso numa mesa cheia?

Quem pede desconto na frente dos outros quer pressão social, não preço.
"""


def _escrever(tmp_path, conteudo, nome="teste-desconto.txt"):
    caminho = tmp_path / nome
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def test_carrega_campos(tmp_path):
    r = roteiro.carregar(_escrever(tmp_path, EXEMPLO))
    assert r["slug"] == "teste-desconto"
    assert r["personagem"] == "harvey"
    assert r["headline"] == "SE ELE PEDIR DESCONTO NA FRENTE DOS OUTROS"
    assert len(r["linhas"]) == 3
    assert "plateia" in r["destaques"] and "calma" in r["destaques"]
    assert "*" not in r["texto_falado"]
    assert "pediu plateia" in r["texto_falado"]
    assert r["legenda"].startswith("Você já passou")


def test_personagem_invalido(tmp_path):
    with pytest.raises(roteiro.RoteiroInvalido, match="personagem"):
        roteiro.carregar(_escrever(tmp_path, EXEMPLO.replace("harvey", "batman")))


def test_secao_faltando(tmp_path):
    so_cabecalho = "personagem: jane\nheadline: X\n---\nSó fala, sem legenda."
    with pytest.raises(roteiro.RoteiroInvalido, match="seç"):
        roteiro.carregar(_escrever(tmp_path, so_cabecalho))


def test_headline_vazia(tmp_path):
    with pytest.raises(roteiro.RoteiroInvalido, match="headline"):
        roteiro.carregar(_escrever(tmp_path, EXEMPLO.replace(
            "headline: SE ELE PEDIR DESCONTO NA FRENTE DOS OUTROS", "headline:")))
