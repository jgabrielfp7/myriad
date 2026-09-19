import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from fabrica import karaoke

DIR_FONTES = Path(__file__).parents[1] / "fontes"

PALAVRAS = [
    {"palavra": "Olha", "inicio": 0.0, "fim": 0.3},
    {"palavra": "a", "inicio": 0.3, "fim": 0.35},
    {"palavra": "plateia.", "inicio": 0.35, "fim": 0.9},
]


def test_um_evento_por_palavra_sem_buraco():
    ass = karaoke.gerar_ass(PALAVRAS, {"plateia"}, DIR_FONTES)
    eventos = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(eventos) == 3
    # palavra fica na tela até a PRÓXIMA começar (sem buraco): fim do 1º = início do 2º
    assert "0:00:00.00" in eventos[0] and "0:00:00.30" in eventos[0]
    assert "0:00:00.30" in eventos[1]


def test_minimo_e_ultima_palavra():
    ass = karaoke.gerar_ass(PALAVRAS, set(), DIR_FONTES)
    eventos = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    # "a" dura 0,05s < mínimo 0,12s → o fim exibido estica pro mínimo
    assert "0:00:00.42" in eventos[1]
    # última palavra ganha +0,6s de respiro
    assert "0:00:01.50" in eventos[2]


def _tempos(ass: str) -> list[tuple[str, str]]:
    return [(l.split(",")[1], l.split(",")[2])
            for l in ass.splitlines() if l.startswith("Dialogue:")]


def test_palavras_rapidas_nunca_se_sobrepoem():
    # rajada de palavras a 0,05s: o mínimo de 0,12s esticava cada uma por cima
    # da seguinte (mesma posição na tela = texto embolado). Agora encadeia.
    rajada = [{"palavra": f"p{i}", "inicio": i * 0.05, "fim": i * 0.05 + 0.04}
              for i in range(6)]
    ass = karaoke.gerar_ass(rajada, set(), DIR_FONTES)
    tempos = _tempos(ass)
    for (_, fim_ant), (ini, _) in zip(tempos, tempos[1:]):
        assert ini >= fim_ant, f"evento começa ({ini}) antes do anterior acabar ({fim_ant})"


def test_destaque_dourado():
    ass = karaoke.gerar_ass(PALAVRAS, {"plateia"}, DIR_FONTES)
    eventos = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert "E9C46A"[::1] not in eventos[0]  # palavra comum sem cor de destaque
    assert "6AC4E9" in eventos[2] or "Destaque" in eventos[2]  # BGR do .ass ou estilo próprio
