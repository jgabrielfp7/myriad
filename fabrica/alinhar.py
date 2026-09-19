"""Alinhamento palavra-a-palavra: faster-whisper transcreve o áudio do operador e
`casar` mapeia os tempos pras palavras do ROTEIRO (a grafia do roteiro manda —
é ela que vai pro karaokê). Palavra que o whisper não ouviu herda tempo
interpolado dos vizinhos: o karaokê nunca fica sem palavra."""
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

MODELO = "small"


def _normalizar(palavra: str) -> str:
    s = unicodedata.normalize("NFD", palavra.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def transcrever(audio: Path) -> list[dict]:
    """Roda o whisper local com timestamps por palavra. Lento na 1ª vez
    (baixa o modelo ~460MB); depois é rápido."""
    from faster_whisper import WhisperModel
    modelo = WhisperModel(MODELO, device="cpu", compute_type="int8")
    segmentos, _ = modelo.transcribe(str(audio), language="pt", word_timestamps=True)
    palavras = []
    for seg in segmentos:
        for w in seg.words or []:
            palavras.append({"palavra": w.word.strip(), "inicio": round(w.start, 3),
                             "fim": round(w.end, 3)})
    return palavras


def casar(palavras_whisper: list[dict], texto_roteiro: str) -> tuple[list[dict], float]:
    """Retorna ([{palavra do ROTEIRO, inicio, fim}], taxa de casamento 0..1)."""
    roteiro = texto_roteiro.split()
    norm_r = [_normalizar(p) for p in roteiro]
    norm_w = [_normalizar(p["palavra"]) for p in palavras_whisper]

    casadas: list[dict | None] = [None] * len(roteiro)
    iguais = 0
    sm = SequenceMatcher(a=norm_r, b=norm_w, autojunk=False)
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            for i, j in zip(range(a0, a1), range(b0, b1)):
                w = palavras_whisper[j]
                casadas[i] = {"palavra": roteiro[i], "inicio": w["inicio"], "fim": w["fim"]}
                iguais += 1

    taxa = iguais / len(roteiro) if roteiro else 0.0

    # interpola as não casadas entre os vizinhos casados
    for i, c in enumerate(casadas):
        if c is not None:
            continue
        ant = next((casadas[k] for k in range(i - 1, -1, -1) if casadas[k]), None)
        prox = next((casadas[k] for k in range(i + 1, len(casadas)) if casadas[k]), None)
        ini = ant["fim"] if ant else 0.0
        fim = prox["inicio"] if prox else ini + 0.4
        if fim <= ini:
            fim = ini + 0.15
        casadas[i] = {"palavra": roteiro[i], "inicio": round(ini, 3), "fim": round(fim, 3)}

    return casadas, round(taxa, 3)


def nao_casadas(palavras_whisper: list[dict], texto_roteiro: str) -> list[str]:
    """Palavras do roteiro que o whisper não confirmou — pro diff da reprova."""
    roteiro = texto_roteiro.split()
    norm_r = [_normalizar(p) for p in roteiro]
    norm_w = [_normalizar(p["palavra"]) for p in palavras_whisper]
    sm = SequenceMatcher(a=norm_r, b=norm_w, autojunk=False)
    confirmadas = set()
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            confirmadas.update(range(a0, a1))
    return [roteiro[i] for i in range(len(roteiro)) if i not in confirmadas]
