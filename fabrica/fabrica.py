"""Fábrica de Reels da Myriad — CLI.

Contrato: roteiro (modelo MYRIAD) + áudio entram → vídeo pronto sai.

    python -m fabrica.fabrica --video meu-reel        # renderiza entrada/meu-reel.*
    python -m fabrica.fabrica --lote                  # tudo que ainda não tem saída
    python -m fabrica.fabrica --prova                 # PNG do 1º quadro de cada saída
    python -m fabrica.fabrica --entregar meu-reel exemplo.corp "2026-08-24 12:00"
"""
import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import alinhar, render, roteiro, validar

RAIZ = Path(__file__).parent
DIR_ENTRADA = RAIZ / "entrada"
DIR_SAIDA = RAIZ / "saida"
DIR_VIDEOS = RAIZ.parent / "videos"
ARQ_FILA = RAIZ.parent / "fila.csv"
EXT_AUDIO = (".mp3", ".wav", ".m4a", ".flac", ".ogg")


def _achar_audio(slug: str) -> Path:
    for ext in EXT_AUDIO:
        c = DIR_ENTRADA / f"{slug}{ext}"
        if c.exists():
            return c
    raise FileNotFoundError(
        f"Áudio de '{slug}' não achado em {DIR_ENTRADA} (extensões: {EXT_AUDIO})")


def produzir(slug: str, negativo: bool = False, contorno: bool = False) -> Path | None:
    """Pipeline de 1 vídeo: parse → transcreve → valida → renderiza."""
    rot = roteiro.carregar(DIR_ENTRADA / f"{slug}.txt")
    audio = _achar_audio(slug)

    print(f"🎙  transcrevendo {audio.name} (1ª vez demora: baixa o modelo)…")
    palavras_whisper = alinhar.transcrever(audio)
    casadas, taxa = alinhar.casar(palavras_whisper, rot["texto_falado"])
    print(f"   {len(palavras_whisper)} palavras ouvidas, casamento {taxa:.0%}")

    erros = validar.validar_tudo(rot, palavras_whisper, taxa,
                                 RAIZ / "edits", RAIZ / "fontes")
    if erros:
        print(f"🛑 {slug} REPROVADO — nada renderizado:")
        for e in erros:
            print(f"   • {e}")
        return None

    return render.renderizar(rot, casadas, audio, negativo=negativo,
                             contorno=contorno)


def lote(negativo: bool = False) -> None:
    roteiros = sorted(DIR_ENTRADA.glob("*.txt"))
    pendentes = [r.stem for r in roteiros if not (DIR_SAIDA / f"{r.stem}.mp4").exists()]
    if not pendentes:
        print("Nada a fazer: toda entrada já tem saída.")
        return
    ok = 0
    for slug in pendentes:
        try:
            if produzir(slug, negativo=negativo):
                ok += 1
        except Exception as e:
            print(f"🛑 {slug}: {e}")
    print(f"✅ lote: {ok}/{len(pendentes)} renderizado(s). Confira com --prova.")


def prova() -> None:
    dir_prova = DIR_SAIDA / "prova"
    dir_prova.mkdir(exist_ok=True)
    videos = sorted(DIR_SAIDA.glob("*.mp4"))
    if not videos:
        print("Nenhum vídeo em saida/ ainda.")
        return
    for v in videos:
        png = dir_prova / f"{v.stem}.png"
        subprocess.run(["ffmpeg", "-y", "-i", str(v), "-frames:v", "1", str(png)],
                       check=True, capture_output=True)
    print(f"👀 {len(videos)} quadro(s) de prova em {dir_prova} — bata o olho no "
          f"enquadramento antes de entregar.")


def entregar(slug: str, conta: str, quando: str,
             dir_saida: Path = DIR_SAIDA, dir_videos: Path = DIR_VIDEOS,
             arq_fila: Path = ARQ_FILA) -> None:
    """Copia mp4+txt pra videos/ do postador (sem sobrescrever) e agenda na fila."""
    datetime.strptime(quando, "%Y-%m-%d %H:%M")  # valida o formato — lição do dia 22
    mp4 = dir_saida / f"{slug}.mp4"
    txt = dir_saida / f"{slug}.txt"
    if not mp4.exists():
        raise FileNotFoundError(f"{mp4} não existe — rode --video {slug} antes")

    nome = f"{slug}.mp4"
    n = 2
    while (dir_videos / nome).exists():
        nome = f"{slug}-{n}.mp4"
        n += 1
    shutil.copy2(mp4, dir_videos / nome)
    if txt.exists():
        shutil.copy2(txt, dir_videos / f"{Path(nome).stem}.txt")

    conteudo = arq_fila.read_text(encoding="utf-8")
    if not conteudo.endswith("\n"):
        conteudo += "\n"
    conteudo += f"{conta},{nome},{quando},pendente,,,\n"
    arq_fila.write_text(conteudo, encoding="utf-8")
    print(f"📬 {nome} entregue: {conta} @ {quando} (fila atualizada)")


def main() -> None:
    p = argparse.ArgumentParser(description="Fábrica de Reels da Myriad")
    p.add_argument("--video", metavar="SLUG", help="produz 1 vídeo da entrada/")
    p.add_argument("--contorno", action="store_true",
                   help="traco preto em volta da legenda (padrao: sem traco)")
    p.add_argument("--negativo", action="store_true",
                   help="legenda em NEGATIVO (inverte o fundo dentro das letras)")
    p.add_argument("--lote", action="store_true", help="produz toda a entrada pendente")
    p.add_argument("--prova", action="store_true", help="PNG do 1º quadro de cada saída")
    p.add_argument("--entregar", nargs=3, metavar=("SLUG", "CONTA", "QUANDO"),
                   help='ex.: --entregar meu-reel exemplo.corp "2026-08-24 12:00"')
    args = p.parse_args()
    if args.video:
        produzir(args.video, negativo=args.negativo, contorno=args.contorno)
    elif args.lote:
        lote(negativo=args.negativo)
    elif args.prova:
        prova()
    elif args.entregar:
        entregar(*args.entregar)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
