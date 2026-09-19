"""Composição final: um trecho contínuo de um EDIT do personagem (fundo
inteiro, 9:16, ritmo original preservado) + tarja/headline + karaokê + voz +
trilha → MP4 1080×1920 pronto pro postador.

Receitas que ficaram do parceiro:
- duração = duração MEDIDA do arquivo de áudio (ffprobe) + 0,45s — nunca soma
- edit e trilha giram por sorteio semeado pelo slug, sem repetir os do render
  anterior (estado_fabrica.json)
- trilha: graves cortados a 90Hz, volume fixo por medição de loudness
  (sem ducking — decisão do operador em 2026-08-24), -14 LUFS no fim
"""
import json
import random
import re
import subprocess
import tempfile
from pathlib import Path

from . import gabarito, karaoke

RAIZ = Path(__file__).parent
CAUDA = 0.45
MARGEM_EDIT = 1.0  # o trecho sorteado não encosta no fim do edit
DIF_TRILHA_LU = 14  # trilha fica 14 LU ABAIXO da voz


def _loudness(arquivo: Path) -> float:
    """Loudness integrado (LUFS) medido com ebur128 — as trilhas do operador são
    músicas masterizadas em volumes muito diferentes entre si; sem medir,
    qualquer ganho fixo acerta numa e soterra a voz na outra."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(arquivo), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+)\s+LUFS", r.stderr)
    if not m:
        return -23.0  # fallback conservador
    return float(m[-1])


def _ganho_trilha_db(voz_lufs: float, trilha_lufs: float) -> float:
    """Ganho que põe a trilha DIF_TRILHA_LU abaixo da voz, limitado a ±0/-40."""
    ganho = (voz_lufs - DIF_TRILHA_LU) - trilha_lufs
    return max(-40.0, min(0.0, round(ganho, 1)))


def _duracao(arquivo: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(arquivo)], capture_output=True, text=True)
    return float(r.stdout.strip())


FPS = 60          # a origem (os edits) é 60 fps: reamostrar joga fora movimento


def filtros_video(ass: Path, dir_fontes: Path, negativo: bool = False,
                  ass_contorno: Path | None = None) -> list[str]:
    """A cadeia de vídeo: fundo → moldura → legenda.

    **Por que 60 fps** (corrigido em 03/09): estava `fps=25` cravado aqui, com
    os edits de origem em 60. Além de descartar metade do movimento, 60/25 =
    2,4 — queda IRREGULAR, que faz o vídeo engasgar. Os manuais do operador saem
    em 30 (60/30 = 2 exato) e por isso ficam fluidos. Ficar em 60 não descarta
    nada.

    **Negativo**: a legenda é desenhada branca sobre uma cópia PRETA do quadro
    e entra por `blend=difference`. Onde a máscara é preta, |base-0| = base e
    a imagem passa intacta; dentro da letra, |base-255| = 255-base e inverte.
    """
    fundo = ("[0:v]fps=" + str(FPS) + ",scale=1080:1920:"
             "force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[fundo]")
    moldura = "[fundo][3:v]overlay=0:0[v1]"
    legenda = (f"subtitles=filename='{_escapar_filtro(ass)}':"
               f"fontsdir='{_escapar_filtro(dir_fontes)}'")
    if not negativo:
        return [fundo, moldura, f"[v1]{legenda},format=yuv420p[vout]"]
    return [
        fundo,
        moldura,
        "[v1]split=2[base][canvas]",
        # gbrp = RGB planar. Em YUV o "preto" da máscara é luma 16 / croma 128,
        # e o difference subtraía 128 do croma do quadro INTEIRO: a 1ª tentativa
        # (03/09) saiu com a tela toda verde. Em RGB o preto é 0,0,0 mesmo, então
        # |base-0| = base fora da letra e |base-255| = 255-base dentro dela.
        f"[canvas]drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill,{legenda},"
        "format=gbrp[mascara]",
        "[base]format=gbrp[basergb]",
        # O contorno é a ÚLTIMA coisa: ele desenha o traço por cima da letra já
        # invertida. Sem ele, palavra sobre fundo de tom médio some (o invertido
        # de cinza médio continua cinza médio).
        "[basergb][mascara]blend=all_mode=difference," + (
            f"subtitles=filename='{_escapar_filtro(ass_contorno)}':"
            f"fontsdir='{_escapar_filtro(dir_fontes)}'," if ass_contorno else ""
        ) + "format=yuv420p[vout]",
    ]


def args_encoder() -> list[str]:
    """Os argumentos do libx264.

    **Sem `-crf`** (corrigido em 03/09): com CRF e `-b:v` juntos, o CRF ganha e
    o bitrate vira decoração. O código pedia 12 Mbps e entregava 2,7–4,4 —
    um terço do que os vídeos manuais do operador entregam.
    """
    return ["-c:v", "libx264", "-profile:v", "high", "-preset", "medium",
            "-b:v", "12M", "-maxrate", "14M", "-bufsize", "24M",
            "-r", str(FPS), "-pix_fmt", "yuv420p"]


def _escapar_filtro(caminho: Path) -> str:
    return str(caminho).replace("\\", "/").replace(":", "\\:")


def _carregar_estado(raiz: Path) -> dict:
    arq = raiz / "estado_fabrica.json"
    if arq.exists():
        return json.loads(arq.read_text(encoding="utf-8"))
    return {}


def _salvar_estado(raiz: Path, estado: dict) -> None:
    (raiz / "estado_fabrica.json").write_text(
        json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


def _sortear_edit(dir_edits: Path, dur: float, semente: str,
                  ultimo: str) -> tuple[Path, float]:
    """Escolhe um edit com fôlego pro trecho e um offset aleatório dentro dele.
    Nunca o mesmo edit do render anterior (se houver outro)."""
    todos = sorted(p for p in dir_edits.glob("*.mp4"))
    candidatos = [(p, _duracao(p)) for p in todos]
    candidatos = [(p, d) for p, d in candidatos if d >= dur + MARGEM_EDIT]
    if not candidatos:
        raise FileNotFoundError(
            f"Nenhum edit em {dir_edits} com pelo menos {dur + MARGEM_EDIT:.0f}s")
    rnd = random.Random(semente)
    sem_ultimo = [(p, d) for p, d in candidatos if p.name != ultimo]
    escolha, dur_edit = rnd.choice(sem_ultimo or candidatos)
    offset = rnd.uniform(0, dur_edit - dur - MARGEM_EDIT)
    return escolha, round(offset, 2)


def _sortear_trilha(dir_trilhas: Path, semente: str, ultima: str) -> Path:
    # .mp4 também: o o operador baixa trilha em vídeo — só o áudio é usado
    trilhas = sorted(p for p in dir_trilhas.iterdir()
                     if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4"))
    if not trilhas:
        raise FileNotFoundError(f"Nenhuma trilha em {dir_trilhas}")
    rnd = random.Random(semente)
    candidatas = [t for t in trilhas if t.name != ultima] or trilhas
    return candidatas[rnd.randrange(len(candidatas))]


def renderizar(rot: dict, palavras_casadas: list[dict], audio: Path,
               raiz: Path = RAIZ, dir_fontes: Path = None,
               negativo: bool = False, contorno: bool = False) -> Path:
    dir_fontes = dir_fontes or (raiz / "fontes")
    estado = _carregar_estado(raiz)
    dur = round(_duracao(audio) + CAUDA, 2)

    edit, offset = _sortear_edit(raiz / "edits" / rot["personagem"], dur,
                                 rot["slug"], estado.get("ultimo_edit", ""))
    trilha = _sortear_trilha(raiz / "trilhas", rot["slug"], estado.get("ultima_trilha", ""))

    saida_dir = raiz / "saida"
    saida_dir.mkdir(exist_ok=True)
    saida = saida_dir / f"{rot['slug']}.mp4"

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        moldura = td / "moldura.png"
        gabarito.desenhar_moldura(rot["headline"], dir_fontes).save(moldura)
        ass = td / "karaoke.ass"
        ass.write_text(karaoke.gerar_ass(palavras_casadas, rot["destaques"], dir_fontes,
                                        negativo=negativo),
                       encoding="utf-8")
        ass_contorno = None
        # Desligado por padrão: o o operador assistiu os 21 e pediu a legenda em
        # negativo LIMPA (03/09). O traço resolvia legibilidade em fundo de
        # tom médio, mas o custo visual não compensou.
        if negativo and contorno:
            ass_contorno = td / "contorno.ass"
            ass_contorno.write_text(
                karaoke.gerar_ass(palavras_casadas, rot["destaques"], dir_fontes,
                                  contorno=True), encoding="utf-8")

        fc = filtros_video(ass, dir_fontes, negativo=negativo,
                           ass_contorno=ass_contorno)
        ganho = _ganho_trilha_db(_loudness(audio), _loudness(trilha))
        fade_out = max(dur - 1.6, 0)
        fc.append(f"[2:a]atrim=duration={dur},highpass=f=90,volume={ganho}dB,"
                  f"afade=t=in:d=1.2,afade=t=out:st={fade_out}:d=1.6[tr]")
        # SEM ducking (decisão do operador, 2026-08-24): a mixagem por loudness já
        # deixa a trilha no volume certo — o sidechain fazia a música "respirar"
        # a cada fala e incomodava mais do que ajudava.
        fc.append("[1:a][tr]amix=inputs=2:duration=longest:normalize=0,"
                  "loudnorm=I=-14:TP=-1.5[aout]")

        cmd = (["ffmpeg", "-y",
                "-ss", str(offset), "-t", str(dur), "-i", str(edit),   # 0: edit (sem áudio dele)
                "-i", str(audio),                                       # 1: voz
                "-i", str(trilha),                                      # 2: trilha
                "-i", str(moldura),                                     # 3: moldura
                "-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
                "-t", str(dur)] + args_encoder() + [
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-movflags", "+faststart", str(saida)])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg falhou ({r.returncode}):\n{' '.join(cmd)}\n\n{r.stderr[-2000:]}")

    (saida_dir / f"{rot['slug']}.txt").write_text(rot["legenda"], encoding="utf-8")
    estado.update(ultimo_edit=edit.name, ultima_trilha=trilha.name)
    _salvar_estado(raiz, estado)
    print(f"🎬 {saida.name}  {dur:.1f}s  fundo: {edit.name} @{offset:.0f}s  "
          f"trilha: {trilha.name} ({ganho:+.1f}dB)")
    return saida
