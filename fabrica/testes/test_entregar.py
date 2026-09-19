import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from fabrica import fabrica

FILA_EXISTENTE = """conta,arquivo,quando,status,resultado,postado_em,views
exemplo.corp,video1.mp4,2026-08-22 11:00,postado,ok,2026-08-22 11:13,
"""


def _montar(tmp_path):
    saida = tmp_path / "saida"
    saida.mkdir()
    (saida / "meu-reel.mp4").write_bytes(b"video")
    (saida / "meu-reel.txt").write_text("Legenda.", encoding="utf-8")
    videos = tmp_path / "videos"
    videos.mkdir()
    fila = tmp_path / "fila.csv"
    fila.write_text(FILA_EXISTENTE, encoding="utf-8")
    return saida, videos, fila


def test_entregar_copia_e_agenda(tmp_path):
    saida, videos, fila = _montar(tmp_path)
    fabrica.entregar("meu-reel", "exemplo.corp", "2026-08-24 12:00",
                     dir_saida=saida, dir_videos=videos, arq_fila=fila)
    assert (videos / "meu-reel.mp4").exists()
    assert (videos / "meu-reel.txt").exists()
    linhas = fila.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 3  # cabeçalho + existente + nova
    assert linhas[1].startswith("exemplo.corp,video1.mp4")  # preservou a existente
    assert linhas[2] == "exemplo.corp,meu-reel.mp4,2026-08-24 12:00,pendente,,,"


def test_entregar_nao_sobrescreve_video_existente(tmp_path):
    saida, videos, fila = _montar(tmp_path)
    (videos / "meu-reel.mp4").write_bytes(b"antigo")
    fabrica.entregar("meu-reel", "exemplo.mind", "2026-08-24 13:00",
                     dir_saida=saida, dir_videos=videos, arq_fila=fila)
    # ganhou nome alternativo em vez de clobber
    novos = [l for l in fila.read_text(encoding="utf-8").splitlines() if "13:00" in l]
    assert len(novos) == 1
    nome = novos[0].split(",")[1]
    assert nome != "meu-reel.mp4" and (videos / nome).exists()
    assert (videos / "meu-reel.mp4").read_bytes() == b"antigo"
