# -*- coding: utf-8 -*-
"""Carrossel: cap por tipo, ordem reversa de envio dos slides, guardas de
pasta/quantidade. Sem tocar no aparelho real."""
import csv
from datetime import datetime, date

import postador
import driver_instagram as ig
import pytest


def _fila(linhas):
    base = {"conta": "", "arquivo": "", "quando": "", "status": "",
            "resultado": "", "postado_em": "", "views": "", "tipo": ""}
    return [{**base, **l} for l in linhas]


def test_cap_de_reel_ignora_carrossel():
    hoje = f"{date.today():%Y-%m-%d} 10:00"
    fila = _fila([
        {"conta": "c", "status": "postado", "postado_em": hoje, "tipo": "carrossel"},
        {"conta": "c", "status": "postado", "postado_em": hoje, "tipo": "reel"},
    ])
    cfg = {"max_posts_dia": 3, "intervalo_minimo_min": 0}
    ok, _ = postador.pode_postar_agora(cfg, fila, "c", agora=datetime.combine(date.today(), datetime.strptime("10:30", "%H:%M").time()))
    assert ok  # 1 reel < 3; o carrossel não conta no cap de reel


def test_cap_de_carrossel_bloqueia_segundo():
    hoje = f"{date.today():%Y-%m-%d} 10:00"
    fila = _fila([{"conta": "c", "status": "postado", "postado_em": hoje,
                   "tipo": "carrossel"}])
    cfg = {"max_carrosseis_dia": 1, "intervalo_minimo_min": 0}
    ok, motivo = postador.pode_postar_carrossel(cfg, fila, "c", agora=datetime.combine(date.today(), datetime.strptime("10:30", "%H:%M").time()))
    assert not ok and "carrossel" in motivo


def test_intervalo_minimo_conta_so_o_mesmo_tipo():
    """o operador 14/09: 'entre reels e carrossel não precisa intervalo' — reel
    recém-postado NÃO segura carrossel; carrossel recente segura carrossel."""
    agora = datetime.now()
    recente = f"{agora:%Y-%m-%d %H:%M}"
    cfg = {"max_carrosseis_dia": 2, "intervalo_minimo_min": 60}
    fila = _fila([{"conta": "c", "status": "postado", "postado_em": recente,
                   "tipo": "reel"}])
    ok, _ = postador.pode_postar_carrossel(cfg, fila, "c")
    assert ok                                     # reel não bloqueia carrossel
    fila = _fila([{"conta": "c", "status": "postado", "postado_em": recente,
                   "tipo": "carrossel"}])
    ok, motivo = postador.pode_postar_carrossel(cfg, fila, "c")
    assert not ok and "intervalo" in motivo       # carrossel bloqueia carrossel
    fila = _fila([{"conta": "c", "status": "postado", "postado_em": recente,
                   "tipo": "carrossel"}])
    cfg_reel = {"max_posts_dia": 3, "intervalo_minimo_min": 60}
    ok, _ = postador.pode_postar_agora(cfg_reel, fila, "c")
    assert ok                                     # carrossel não bloqueia reel


def test_linha_sem_tipo_conta_como_reel():
    hoje = f"{date.today():%Y-%m-%d} 10:00"
    fila = _fila([{"conta": "c", "status": "postado", "postado_em": hoje, "tipo": ""}])
    assert len(postador.posts_da_conta_hoje(fila, "c", tipo="reel")) == 1
    assert len(postador.posts_da_conta_hoje(fila, "c", tipo="carrossel")) == 0


class _Sel:
    def __init__(self, existe=True):
        self.exists = existe
    def wait(self, timeout=0): return self.exists
    def click(self): pass


class AparelhoFalso:
    def __init__(self):
        self.textos_setados = []
    def __call__(self, **kw): return _Sel(False)
    def screen_on(self): pass
    def unlock(self): pass
    def press(self, t): pass
    def app_start(self, p, stop=False): pass
    def screen_off(self): pass
    def screenshot(self, path): pass


def test_carrossel_recusa_menos_de_dois_slides(tmp_path, monkeypatch):
    (tmp_path / "slide-01.png").write_bytes(b"x")
    monkeypatch.setattr(ig, "enviar_video", lambda s, c: "/dev/null")
    with pytest.raises(ig.FalhaNoFluxo, match="2\\+ slides"):
        ig.postar_carrossel(AparelhoFalso(), "S", tmp_path, "leg", tmp_path)


def test_carrossel_usa_envio_ordenado_com_carimbo(tmp_path, monkeypatch):
    for i in range(1, 4):
        (tmp_path / f"slide-0{i}.png").write_bytes(b"x")
    recebidos = []
    monkeypatch.setattr(ig, "enviar_slides_ordenados",
                        lambda s, slides: recebidos.extend(p.name for p in slides)
                        or [f"/sd/{p.name}" for p in slides])
    # para o fluxo logo após o envio: garantir_conta explode de propósito
    monkeypatch.setattr(ig, "_fechar_popups", lambda d: None)
    monkeypatch.setattr(ig, "_checar_bloqueio", lambda d: None)
    monkeypatch.setattr(ig.time, "sleep", lambda s: None)
    monkeypatch.setattr(ig, "garantir_conta",
                        lambda *a, **k: (_ for _ in ()).throw(ig.FalhaNoFluxo("stop")))
    with pytest.raises(ig.FalhaNoFluxo):
        ig.postar_carrossel(AparelhoFalso(), "S", tmp_path, "leg", tmp_path)
    # a lista chega em ORDEM (slide-01 primeiro); o carimbo de data é quem
    # garante a ordenação na galeria (testado no aparelho via dry-run)
    assert recebidos == ["slide-01.png", "slide-02.png", "slide-03.png"]


def test_envio_ordenado_carimba_datas_decrescentes(tmp_path, monkeypatch):
    """slide-01 recebe a data mais NOVA (touch -t); scan roda do mais velho
    pro mais novo. Verifica a sequência de comandos adb."""
    for i in range(1, 4):
        (tmp_path / f"slide-0{i}.png").write_bytes(b"x")
    comandos = []

    class R:
        returncode = 0
    monkeypatch.setattr(ig.subprocess, "run",
                        lambda cmd, **kw: comandos.append(cmd) or R())
    monkeypatch.setattr(ig.time, "sleep", lambda s: None)
    slides = sorted(tmp_path.glob("slide-*.png"))
    destinos = ig.enviar_slides_ordenados("S", slides)
    assert len(destinos) == 3
    carimbos = [c[c.index("touch") + 2] for c in comandos if "touch" in c]
    assert carimbos == sorted(carimbos, reverse=True)  # 01 mais novo → decresce
    scans = [c[-1] for c in comandos if any("MEDIA_SCANNER" in str(x) for x in c)]
    assert "slide-03.png" in scans[0] and "slide-01.png" in scans[-1]
