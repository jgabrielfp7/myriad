import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from fabrica import validar

DIR_FONTES = Path(__file__).parents[1] / "fontes"


def _rot(**kw):
    base = {"slug": "t", "personagem": "harvey",
            "headline": "SE ELE PEDIR DESCONTO NA FRENTE DOS OUTROS",
            "texto_falado": "Olha o jogo.", "destaques": set(), "linhas": [], "legenda": "x"}
    base.update(kw)
    return base


def _edits(tmp_path, personagem, n):
    d = tmp_path / personagem
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"edit{i}.mp4").write_bytes(b"0")
    return tmp_path


def test_aprovado(tmp_path):
    erros = validar.validar_tudo(_rot(), [], 0.95, _edits(tmp_path, "harvey", 2), DIR_FONTES)
    assert erros == []


def test_taxa_baixa_reprova_com_diff(tmp_path):
    whisper = [{"palavra": "outra", "inicio": 0, "fim": 1}]
    erros = validar.validar_tudo(_rot(), whisper, 0.5, _edits(tmp_path, "harvey", 2), DIR_FONTES)
    assert any("80%" in e or "áudio" in e for e in erros)
    assert any("Olha" in e for e in erros)  # diff aponta as palavras não confirmadas


def test_sem_edits_reprova(tmp_path):
    erros = validar.validar_tudo(_rot(personagem="jane"), [], 1.0,
                                 _edits(tmp_path, "jane", 0), DIR_FONTES)
    assert any("jane" in e and "edit" in e.lower() for e in erros)


def test_headline_gigante_reprova(tmp_path):
    rot = _rot(headline="UMA HEADLINE ABSURDAMENTE COMPRIDA QUE NAO TEM COMO CABER "
                        "EM DUAS LINHAS DENTRO DA CAIXA DO TOPO DE JEITO NENHUM MESMO")
    erros = validar.validar_tudo(rot, [], 1.0, _edits(tmp_path, "harvey", 2), DIR_FONTES)
    assert any("encurte" in e for e in erros)
