import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from fabrica import alinhar


def _w(palavra, inicio, fim):
    return {"palavra": palavra, "inicio": inicio, "fim": fim}


def test_casamento_perfeito():
    whisper = [_w("Olha", 0.0, 0.3), _w("o", 0.3, 0.4), _w("jogo.", 0.4, 0.9)]
    casadas, taxa = alinhar.casar(whisper, "Olha o jogo.")
    assert taxa == 1.0
    assert [c["palavra"] for c in casadas] == ["Olha", "o", "jogo."]
    assert casadas[2]["inicio"] == 0.4


def test_divergencia_reduz_taxa_e_interpola():
    # roteiro tem "calma" que o whisper não ouviu; tempos interpolados dos vizinhos
    whisper = [_w("responda", 0.0, 0.5), _w("com", 0.5, 0.7), _w("firmeza", 1.1, 1.6)]
    casadas, taxa = alinhar.casar(whisper, "Responda com calma firmeza")
    assert taxa < 1.0
    assert [c["palavra"] for c in casadas] == ["Responda", "com", "calma", "firmeza"]
    calma = casadas[2]
    assert 0.7 <= calma["inicio"] < 1.1  # entre o fim de "com" e o início de "firmeza"
    assert calma["fim"] <= 1.1


def test_acento_e_pontuacao_nao_atrapalham():
    whisper = [_w("decisão", 0.0, 0.5), _w("rápida", 0.5, 1.0)]
    casadas, taxa = alinhar.casar(whisper, "Decisão, rápida!")
    assert taxa == 1.0
    # a grafia final é a DO ROTEIRO (é ela que vai pro karaokê)
    assert [c["palavra"] for c in casadas] == ["Decisão,", "rápida!"]
