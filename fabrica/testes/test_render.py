import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from fabrica import render

DIR_FONTES = Path(__file__).parents[1] / "fontes"


def _gerar_video(caminho, fonte, dur):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", fonte, "-t", str(dur),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(caminho)],
                   check=True, capture_output=True)


def _gerar_audio(caminho, dur, freq=440):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={dur}", str(caminho)],
                   check=True, capture_output=True)


def _probe(video):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=width,height", "-of", "json", str(video)],
        capture_output=True, text=True)
    return json.loads(r.stdout)


def test_ganho_da_trilha_por_medicao():
    # voz baixa + trilha alta → desconto grande; nunca ganho positivo
    assert render._ganho_trilha_db(-20.0, -8.0) == -26.0
    assert render._ganho_trilha_db(-16.0, -30.0) == 0.0   # trilha já quieta: não aumenta
    assert render._ganho_trilha_db(-20.0, -9.0) == -25.0
    assert render._ganho_trilha_db(-10.0, -60.0) == 0.0


def test_render_fumaca(tmp_path):
    # estrutura mínima: 2 edits 9:16 do harvey, 2 trilhas, áudio de 5s
    edits = tmp_path / "edits" / "harvey"
    edits.mkdir(parents=True)
    for i, fonte in enumerate(["testsrc=s=540x960:r=25", "testsrc2=s=540x960:r=25"]):
        _gerar_video(edits / f"edit{i}.mp4", fonte, 12)
    trilhas = tmp_path / "trilhas"
    trilhas.mkdir()
    _gerar_audio(trilhas / "trilha_a.mp3", 12, 220)
    _gerar_audio(trilhas / "trilha_b.mp3", 12, 330)
    audio = tmp_path / "voz.wav"
    _gerar_audio(audio, 5.0)
    (tmp_path / "saida").mkdir()

    rot = {"slug": "fumaca", "personagem": "harvey",
           "headline": "TESTE DE FUMACA DO RENDER",
           "texto_falado": "um dois tres", "destaques": {"tres"},
           "legenda": "Legenda do teste."}
    palavras = [{"palavra": "um", "inicio": 0.5, "fim": 1.0},
                {"palavra": "dois", "inicio": 1.5, "fim": 2.0},
                {"palavra": "tres", "inicio": 2.5, "fim": 3.0}]

    mp4 = render.renderizar(rot, palavras, audio, raiz=tmp_path, dir_fontes=DIR_FONTES)
    assert mp4.exists()
    info = _probe(mp4)
    stream = info["streams"][0]
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert abs(float(info["format"]["duration"]) - 5.45) < 0.3
    # legenda do post entregue junto
    assert (tmp_path / "saida" / "fumaca.txt").read_text(encoding="utf-8") == "Legenda do teste."
    # estado gravou edit e trilha pro anti-repetição
    estado = json.loads((tmp_path / "estado_fabrica.json").read_text(encoding="utf-8"))
    assert estado["ultimo_edit"] and estado["ultima_trilha"]
