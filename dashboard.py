# -*- coding: utf-8 -*-
"""
Dashboard local do Postador Myriad — lê a fila/logs REAIS ao vivo.

Uso:
    python dashboard.py           # abre em http://127.0.0.1:8777
    (ou duplo clique em dashboard.bat)

Sem dependências: usa só a biblioteca padrão. A página se atualiza sozinha.
"""

import csv
import json
import sys
import webbrowser
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

RAIZ = Path(__file__).parent
ARQ_FILA = RAIZ / "fila.csv"
ARQ_CONFIG = RAIZ / "config.json"
ARQ_ESTADO = RAIZ / "estado.json"
ARQ_LOG = RAIZ / "logs" / "log.csv"
ARQ_HEARTBEAT = RAIZ / "logs" / "heartbeat.txt"
ARQ_STATUS_CONEXAO = RAIZ / "logs" / "status_conexao.json"
PASTA_VIDEOS = RAIZ / "videos"
PASTA_SAIDA_FABRICA = RAIZ / "fabrica" / "saida"

PORTA = 8777

STATUS_INFO = {
    "postado":   ("Postado",   "ok"),
    "pendente":  ("Pendente",  "pend"),
    "erro":      ("Erro",      "err"),
    "cancelado": ("Cancelado", "mut"),
}


# ---------- leitura dos dados ----------

def _ler_csv(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _ler_json(caminho: Path, padrao: dict) -> dict:
    if not caminho.exists():
        return padrao
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def _parse_dt(txt: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(txt.strip(), fmt)
    except Exception:
        return None


def _views_int(l: dict) -> int | None:
    v = (l.get("views") or "").strip().replace(".", "").replace(",", "").replace(" ", "")
    return int(v) if v.isdigit() else None


def _fmt_views(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f} mil".replace(".0 ", " ").replace(".", ",")
    return str(n)


def prever_proximos(fila: list[dict], cfg: dict, agora: datetime) -> dict:
    """Previsão do próximo post por conta, do jeito que o postador decide:
    max(horário agendado, último post da conta + intervalo mínimo, agora).
    Sempre aproximada (~): jitter de até 7 min + duração do fluxo de post.
    Devolve {conta: {"arquivo", "quando", "previsto", "aguarda_intervalo"}}."""
    intervalo = timedelta(minutes=cfg.get("intervalo_minimo_min", 90))
    ultimo: dict[str, datetime] = {}
    pendente: dict[str, tuple[datetime, dict]] = {}
    for l in fila:
        conta = l.get("conta", "").strip() or "(sem conta)"
        if l["status"] == "postado" and l.get("postado_em"):
            dt = _parse_dt(l["postado_em"], "%Y-%m-%d %H:%M")
            if dt and (conta not in ultimo or dt > ultimo[conta]):
                ultimo[conta] = dt
        elif l["status"] == "pendente":
            dt = _parse_dt(l["quando"], "%Y-%m-%d %H:%M")
            if dt and (conta not in pendente or dt < pendente[conta][0]):
                pendente[conta] = (dt, l)
    prev = {}
    for conta, (quando, l) in pendente.items():
        livre = ultimo[conta] + intervalo if conta in ultimo else agora
        previsto = max(quando, livre, agora)
        prev[conta] = {"arquivo": l["arquivo"], "quando": quando,
                       "previsto": previsto,
                       "aguarda_intervalo": livre > max(quando, agora)}
    return prev


def coletar() -> dict:
    fila = _ler_csv(ARQ_FILA)
    cfg = _ler_json(ARQ_CONFIG, {"max_posts_dia": 5, "intervalo_minimo_min": 90})
    estado = _ler_json(ARQ_ESTADO, {"pausado": False, "motivo_pausa": ""})
    log = _ler_csv(ARQ_LOG)
    agora = datetime.now()
    hoje = date.today()

    # heartbeat → rodando?
    hb_txt = ARQ_HEARTBEAT.read_text(encoding="utf-8").strip() if ARQ_HEARTBEAT.exists() else ""
    hb = _parse_dt(hb_txt, "%Y-%m-%d %H:%M:%S")
    rodando = bool(hb and (agora - hb).total_seconds() < 150)

    conexao_st = _ler_json(ARQ_STATUS_CONEXAO, {
        "modo": None, "ip": None, "bateria": None, "carregando": False})

    # por conta
    contas = {}
    for l in fila:
        c = l.get("conta", "").strip() or "(sem conta)"
        contas.setdefault(c, {"nome": c, "posts": [], "postados_hoje": 0,
                              "ultimo": None, "proximo": None})
        contas[c]["posts"].append(l)

    for c, d in contas.items():
        postados_hoje = []
        for l in d["posts"]:
            if l["status"] == "postado" and l.get("postado_em"):
                dt = _parse_dt(l["postado_em"], "%Y-%m-%d %H:%M")
                if dt and dt.date() == hoje:
                    postados_hoje.append(dt)
        d["postados_hoje"] = len(postados_hoje)
        d["ultimo"] = max(postados_hoje).strftime("%H:%M") if postados_hoje else None
        # alcance: mediana da conta (sobre todos os posts com views registrados)
        vs = sorted(v for v in (_views_int(l) for l in d["posts"]
                                if l["status"] == "postado") if v is not None)
        d["mediana"] = vs[len(vs) // 2] if vs else None

    # totais do dia
    total_post = sum(c["postados_hoje"] for c in contas.values())
    total_pend = sum(1 for l in fila if l["status"] == "pendente")
    total_erro = sum(1 for l in fila if l["status"] == "erro")
    total_views = 0
    for l in fila:
        if l["status"] == "postado":
            dt = _parse_dt(l.get("postado_em", ""), "%Y-%m-%d %H:%M")
            v = _views_int(l)
            if dt and dt.date() == hoje and v:
                total_views += v

    # próximo post: previsão real (agendado × intervalo mínimo), por conta e geral
    previsoes = prever_proximos(fila, cfg, agora)
    for conta, p in previsoes.items():
        if conta in contas:
            contas[conta]["proximo"] = {**p, "atrasado": p["quando"] < agora}
    prox = None
    for c in contas.values():
        p = c.get("proximo")
        if p and (prox is None or p["previsto"] < prox["previsto"]):
            prox = {**p, "conta": c["nome"]}

    estoque = inventariar_estoque(fila, PASTA_VIDEOS, PASTA_SAIDA_FABRICA)

    return {
        "fila": fila, "cfg": cfg, "estado": estado, "log": log[-16:][::-1],
        "agora": agora, "rodando": rodando, "hb": hb, "contas": contas,
        "total_post": total_post, "total_pend": total_pend, "total_erro": total_erro,
        "total_views": total_views, "prox": prox, "conexao": conexao_st,
        "estoque": estoque,
    }


def inventariar_estoque(fila: list[dict], pasta_videos: Path,
                        pasta_saida: Path | None = None) -> dict:
    """Inventário do estoque de vídeos: o que está PRONTO pra agendar (mp4 +
    legenda .txt, ainda sem linha na fila), o que está sem legenda, e quais
    linhas PENDENTES apontam pra vídeo que ainda não existe na pasta (o robô
    vai ADIAR até o arquivo chegar). O estoque conta as duas casas do vídeo:
    videos/ (entregue ao postador) e fabrica/saida (renderizado, não entregue)."""
    fontes: dict[str, Path] = {}
    for pasta in (pasta_videos, pasta_saida):
        if pasta and pasta.exists():
            for p in pasta.glob("*.mp4"):
                fontes.setdefault(p.name, p)  # videos/ tem prioridade
    usados = {(l.get("arquivo") or "").strip() for l in fila
              if l.get("status") in ("postado", "pendente")}
    livres = sorted(n for n in fontes if n not in usados)
    prontos = [n for n in livres
               if (fontes[n].parent / (Path(n).stem + ".txt")).exists()]
    sem_legenda = [n for n in livres if n not in prontos]
    mp4s_postador = ({p.name for p in pasta_videos.glob("*.mp4")}
                     if pasta_videos.exists() else set())
    pendentes_sem_video = sorted((l.get("arquivo") or "").strip() for l in fila
                                 if l.get("status") == "pendente"
                                 and (l.get("arquivo") or "").strip() not in mp4s_postador)
    return {"prontos": prontos, "sem_legenda": sem_legenda,
            "pendentes_sem_video": pendentes_sem_video}


# ---------- render ----------

CSS = """
:root{
  --bg:#0B0B0D; --strip:#0E0E11; --surface:#131316; --surface2:#1A1A1F;
  --border:#26262C; --hair:#1F1F24;
  --text:#F4F4F5; --sec:#A6A6AF; --muted:#6E6E78; --faint:#4A4A54; --claro:#D8D8DC;
  --accent:#EC1B2E; --ok:#3ECF8E; --pend:#C9CCD4; --err:#FF3B47; --amber:#F5A623;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);line-height:1.5;
  font-family:'Archivo',system-ui,-apple-system,sans-serif;
  background-image:radial-gradient(640px 300px at 50% -120px,rgba(236,27,46,.05),transparent)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#26262C;border-radius:999px;border:2px solid var(--bg)}
::-webkit-scrollbar-track{background:transparent}
.mono{font-family:'JetBrains Mono',Consolas,ui-monospace,monospace;
  font-variant-numeric:tabular-nums}
.topbar{display:flex;align-items:center;gap:10px;padding:16px 20px 13px;
  border-bottom:1px solid var(--hair)}
.brand{width:30px;height:30px;border-radius:8px;background:var(--accent);
  display:grid;place-items:center;font-weight:800;font-size:15px;color:#fff}
.bname{font-weight:700;font-size:15px;letter-spacing:.2px}
.bsub{font-size:11px;color:var(--muted);letter-spacing:.6px;text-transform:uppercase}
.spacer{flex:1}
.pill{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:600;
  color:var(--claro);padding:7px 12px;border-radius:999px;
  border:1px solid var(--border);background:var(--surface)}
.dot{width:7px;height:7px;border-radius:50%}
.dot.live{background:var(--ok);box-shadow:0 0 8px rgba(62,207,142,.7);animation:pulse 1.8s infinite}
.dot.off{background:var(--faint)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(62,207,142,.5)}70%{box-shadow:0 0 0 8px rgba(62,207,142,0)}100%{box-shadow:0 0 0 0 rgba(62,207,142,0)}}
.strip{display:flex;align-items:center;gap:14px;padding:10px 20px;flex-wrap:wrap;
  border-bottom:1px solid var(--hair);background:var(--strip);font-size:12px}
.strip .rot{font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--faint)}
.strip .item{display:inline-flex;align-items:center;gap:6px;font-weight:600;color:var(--claro)}
.strip .sub{color:var(--muted);font-weight:400}
.wrap{max-width:1180px;margin:0 auto;padding:18px 20px 40px;
  display:flex;flex-direction:column;gap:22px}
.banner{padding:14px 16px;border-radius:14px;font-weight:600;border:1px solid;
  display:flex;gap:11px;align-items:center;font-size:13.5px}
.banner.kill{background:rgba(255,59,71,.08);border-color:rgba(255,59,71,.4);color:#FF9AA1}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px}
.hero{display:flex;flex-direction:column;gap:14px;padding:18px;
  border-top:2px solid var(--accent)}
.hero .num{font-size:46px;font-weight:800;letter-spacing:-2px;line-height:1}
.hero .l1{font-size:13px;font-weight:600;color:var(--claro)}
.hero .l2{font-size:12px;color:var(--muted)}
.barra{height:6px;border-radius:999px;background:var(--surface2);overflow:hidden}
.barra>span{display:block;height:100%;border-radius:999px;background:var(--accent)}
.prox{display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:10px;
  background:var(--surface2);font-size:12.5px;flex-wrap:wrap}
.prox .lb{color:var(--sec)}
.prox .arq{color:var(--muted)}
.prox .ct{font-weight:700;color:var(--accent);margin-left:auto;font-size:12px}
.prox .ct.tarde{color:var(--amber)}
h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);
  font-weight:700;margin:0 0 10px 2px}
.lista{display:flex;flex-direction:column;overflow:hidden}
.slot{display:flex;align-items:center;gap:12px;padding:12px 14px;
  border-bottom:1px solid var(--hair)}
.slot:last-child{border-bottom:none}
.slot.destaque{background:rgba(236,27,46,.05)}
.slot .hora{font-size:12.5px;font-weight:600;color:var(--sec);width:44px;flex-shrink:0}
.slot .meio{display:flex;flex-direction:column;gap:1px;flex:1;min-width:0}
.slot .arqs{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.slot .det{font-size:11.5px;color:var(--muted)}
.slot .st{font-size:11px;font-weight:700;letter-spacing:.4px;flex-shrink:0}
.slot.futuro .arqs{font-weight:500;color:var(--sec)}
.slot.futuro .hora{color:var(--muted)}
.contas{display:flex;flex-direction:column;gap:12px}
.conta{display:flex;flex-direction:column;gap:12px;padding:16px}
.conta .hd{display:flex;align-items:center;gap:10px}
.conta .pt{width:9px;height:9px;border-radius:50%}
.conta .nm{font-size:14px;font-weight:700}
.conta .cap{font-size:12px;color:var(--sec);margin-left:auto}
.conta .mini{display:flex;gap:20px}
.conta .mini .b{display:flex;flex-direction:column;gap:1px}
.conta .mini .k{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}
.conta .mini .v{font-size:13px;font-weight:600}
.conta .mini .v.na{color:var(--muted);font-weight:500}
.rolagem{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.6px;padding:12px 12px 9px}
td{padding:11px 12px;border-top:1px solid var(--hair);vertical-align:middle;white-space:nowrap}
tr:hover td{background:rgba(255,255,255,.02)}
.tag{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;font-weight:600;
  padding:3px 9px;border-radius:999px}
.tag.ok{background:rgba(62,207,142,.12);color:#6EE7B7}
.tag.pend{background:rgba(201,204,212,.10);color:var(--pend)}
.tag.err{background:rgba(255,59,71,.14);color:#FF8B93}
.tag.mut{background:rgba(91,91,100,.16);color:var(--sec)}
.tag.late{background:rgba(245,166,35,.14);color:#FCD34D}
.reach{font-weight:600}
.reach.low{color:var(--accent)}
.reach .flag{font-size:11px;font-weight:600;color:var(--accent);margin-left:6px}
.reach.na{color:var(--faint);font-weight:400}
.acc-chip{font-size:12px;color:var(--muted)}
.evt{display:flex;align-items:center;gap:10px;padding:10px 14px;
  border-bottom:1px solid var(--hair);font-size:12px}
.evt:last-child{border-bottom:none}
.evt .h{color:var(--muted);width:40px;flex-shrink:0;font-size:11.5px}
.evt .n{font-weight:700;font-size:11px;letter-spacing:.3px;width:96px;flex-shrink:0}
.evt .d{color:var(--sec);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.n.POSTADO{color:var(--ok)}.n.ERRO,.n.KILL_SWITCH{color:#FF8B93}
.n.ADIADO,.n.RETENTATIVA{color:var(--amber)}.n.ARMADO_WIFI{color:var(--claro)}
.foot{color:var(--faint);font-size:11.5px;text-align:center}
.colunas{display:flex;flex-direction:column;gap:22px}
@media(min-width:980px){
  .colunas{display:grid;grid-template-columns:2fr 1fr;gap:16px;align-items:start}
  .hero .num{font-size:52px}
}

/* ---- movimento (uma vez por visita; a troca silenciosa de dados não replay) ---- */
.card{transition:border-color .22s ease,transform .22s ease,box-shadow .22s ease}
.card:hover{border-color:#33333B;transform:translateY(-1px);
  box-shadow:0 10px 28px rgba(0,0,0,.38)}
.slot,.evt{transition:background .15s ease}
.slot:hover,.evt:hover{background:rgba(255,255,255,.025)}
.slot.destaque{animation:respirar 3.2s ease-in-out infinite}
.barra>span{transition:width .6s cubic-bezier(.22,1,.36,1)}
@keyframes entrar{from{opacity:0;transform:translateY(14px)}}
@keyframes surgir{from{opacity:0}}
@keyframes crescer{from{width:0}}
@keyframes respirar{0%,100%{background:rgba(236,27,46,.04)}50%{background:rgba(236,27,46,.09)}}
@media(prefers-reduced-motion:no-preference){
  html:not([data-atualizado]) .sec{
    animation:entrar .6s cubic-bezier(.22,1,.36,1) both;
    animation-delay:calc(var(--i,0)*80ms)}
  html:not([data-atualizado]) .topbar,
  html:not([data-atualizado]) .strip{animation:surgir .5s ease-out both}
  html:not([data-atualizado]) .barra>span{
    animation:crescer .9s cubic-bezier(.22,1,.36,1) both;
    animation-delay:calc(var(--i,0)*80ms + 250ms)}
  html:not([data-atualizado]) .hero .num{
    display:inline-block;animation:entrar .7s cubic-bezier(.22,1,.36,1) both}
}
@media(prefers-reduced-motion:reduce){
  .slot.destaque{animation:none;background:rgba(236,27,46,.05)}
  .dot.live{animation:none}
}
"""


def _pill_status(status: str, atrasado: bool = False) -> str:
    if status == "pendente" and atrasado:
        return '<span class="tag late">Atrasado</span>'
    rotulo, cls = STATUS_INFO.get(status, (status, "mut"))
    return f'<span class="tag {cls}">{rotulo}</span>'


# ---------- ícones (SVG inline, traço 16px — nada de emoji no painel) ----------

def _ic_check(cor: str, px: int = 15) -> str:
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 16 16" fill="none" stroke="{cor}" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
            f'<circle cx="8" cy="8" r="6.4"></circle><path d="M5.4 8.2 7.2 10l3.4-3.8"></path></svg>')


def _ic_relogio(cor: str, px: int = 15) -> str:
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 16 16" fill="none" stroke="{cor}" '
            f'stroke-width="1.7" stroke-linecap="round">'
            f'<circle cx="8" cy="8" r="6.4"></circle><path d="M8 4.8V8l2.2 1.4"></path></svg>')


def _ic_agendado(px: int = 15) -> str:
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 16 16" fill="none" stroke="#4A4A54" '
            f'stroke-width="1.7" stroke-linecap="round">'
            f'<circle cx="8" cy="8" r="6.4" stroke-dasharray="2.4 2.6"></circle></svg>')


def _ic_alerta(cor: str, px: int = 15) -> str:
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 16 16" fill="none" stroke="{cor}" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="M8 2.2 14.6 13.4H1.4Z"></path><path d="M8 6.6v3"></path>'
            f'<circle cx="8" cy="11.6" r="0.4" fill="{cor}" stroke="none"></circle></svg>')


def _ic_wifi(cor: str, px: int = 14) -> str:
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 16 16" fill="none" stroke="{cor}" '
            f'stroke-width="1.6" stroke-linecap="round"><path d="M2 6.5a9 9 0 0 1 12 0"></path>'
            f'<path d="M4.3 9a5.6 5.6 0 0 1 7.4 0"></path>'
            f'<circle cx="8" cy="12" r="1" fill="{cor}" stroke="none"></circle></svg>')


def _ic_usb(cor: str, px: int = 14) -> str:
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 16 16" fill="none" stroke="{cor}" '
            f'stroke-width="1.5" stroke-linecap="round"><path d="M8 1.5v9"></path>'
            f'<path d="M8 10.5 5 8.2V6.8"></path><path d="M8 9.2 11 7.4V5.8"></path>'
            f'<circle cx="8" cy="12.6" r="1.6"></circle><circle cx="5" cy="5.4" r="1.1"></circle>'
            f'<rect x="10" y="4" width="2" height="2"></rect></svg>')


def _ic_bateria(nivel, carregando: bool) -> str:
    pct = 0 if nivel is None else max(0, min(100, nivel))
    largura = round(6.6 * pct / 100, 1)
    cor = "#3ECF8E" if carregando or pct >= 40 else ("#F5A623" if pct >= 20 else "#FF3B47")
    barra = (f'<rect x="2.6" y="6.1" width="{largura}" height="3.8" rx="1" fill="{cor}" '
             f'stroke="none"></rect>') if pct else ""
    raio = (f'<svg width="10" height="12" viewBox="0 0 10 14" fill="#F5A623">'
            f'<path d="M5.8 0 1 8h3l-1 6 5.4-8.5H5z"></path></svg>') if carregando else ""
    return (f'<svg width="15" height="14" viewBox="0 0 17 16" fill="none" stroke="#A6A6AF" '
            f'stroke-width="1.4" stroke-linecap="round"><rect x="1" y="4.5" width="12" height="7" '
            f'rx="2"></rect><path d="M15 7v2"></path>{barra}</svg>{raio}')


ICONE_EVENTO = {
    "POSTADO": lambda: _ic_check("#3ECF8E", 13),
    "ERRO": lambda: _ic_alerta("#FF8B93", 13),
    "KILL_SWITCH": lambda: _ic_alerta("#FF8B93", 13),
    "ADIADO": lambda: _ic_relogio("#F5A623", 13),
    "RETENTATIVA": lambda: _ic_relogio("#F5A623", 13),
    "ARMADO_WIFI": lambda: _ic_wifi("#A6A6AF", 13),
}


def _ic_evento(ev: str) -> str:
    fabrica = ICONE_EVENTO.get(ev)
    if fabrica:
        return fabrica()
    return ('<svg width="13" height="13" viewBox="0 0 16 16" fill="none">'
            '<circle cx="8" cy="8" r="3" fill="#6E6E78"></circle></svg>')


# ---------- linha do dia ----------

def montar_slots(fila: list[dict], agora: datetime) -> list[dict]:
    """Agrupa a fila de HOJE por horário agendado (cada slot = o par corp+mind).
    Estado do slot: erro > postado > atrasado > proximo (1º pendente) > agendado."""
    hoje = agora.date()
    slots: dict[str, dict] = {}
    for l in fila:
        dt = _parse_dt(l.get("quando", ""), "%Y-%m-%d %H:%M")
        if not dt or dt.date() != hoje:
            continue
        s = slots.setdefault(dt.strftime("%H:%M"),
                             {"hora": dt.strftime("%H:%M"), "dt": dt, "itens": []})
        s["itens"].append(l)
    ordenados = sorted(slots.values(), key=lambda s: s["dt"])
    proximo_marcado = False
    for s in ordenados:
        sts = [l["status"] for l in s["itens"]]
        if "erro" in sts:
            s["estado"] = "erro"
        elif sts and all(x == "postado" for x in sts):
            s["estado"] = "postado"
        elif "pendente" in sts and s["dt"] < agora:
            s["estado"] = "atrasado"
            proximo_marcado = True  # o atrasado É o próximo a sair
        elif "pendente" in sts and not proximo_marcado:
            s["estado"] = "proximo"
            proximo_marcado = True
        else:
            s["estado"] = "agendado"
    return ordenados


COR_CONTA = {"exemplo.corp": "#EC1B2E", "exemplo.mind": "#C9CCD4", "exemplo.es": "#9BB8E0"}


def render(d: dict) -> str:
    agora = d["agora"]
    est = d["estado"]
    cap = d["cfg"].get("max_posts_dia", 5)
    estoque = d.get("estoque") or {"prontos": [], "sem_legenda": [],
                                   "pendentes_sem_video": []}
    sem_video = set(estoque["pendentes_sem_video"])

    live = ('<span class="pill"><span class="dot live"></span>Ao vivo</span>'
            if d["rodando"] else
            '<span class="pill"><span class="dot off"></span>Parado</span>')

    # faixa de telemetria do aparelho do rig
    cx = d.get("conexao") or {}
    modo = cx.get("modo")
    bat = cx.get("bateria")
    carregando = bool(cx.get("carregando"))
    bateria_minima = d["cfg"].get("bateria_minima", 20)
    if modo == "wifi":
        conexao_html = (f'<span class="item">{_ic_wifi("#3ECF8E")}Wi-Fi '
                        f'<span class="sub mono">{cx.get("ip") or ""}</span></span>')
    elif modo == "usb":
        conexao_html = f'<span class="item">{_ic_usb("#3ECF8E")}USB</span>'
    elif modo == "sem_conexao":
        conexao_html = (f'<span class="item" style="color:#FF8B93">'
                        f'{_ic_alerta("#FF8B93", 14)}Sem conexão — plugue o cabo</span>')
    else:
        conexao_html = '<span class="item sub">conexão —</span>'
    if bat is None:
        bateria_html = '<span class="item sub">bateria —</span>'
    else:
        aviso_bat = (bat < bateria_minima and not carregando)
        extra = ('<span class="sub">carregando</span>' if carregando
                 else ('<span style="color:#FF8B93;font-weight:700">baixa</span>'
                       if aviso_bat else ""))
        bateria_html = f'<span class="item">{_ic_bateria(bat, carregando)}{bat}% {extra}</span>'

    # banners de atenção
    banners = []
    if est.get("pausado"):
        banners.append(f'<div class="banner kill">{_ic_alerta("#FF8B93", 16)} '
                       f'KILL-SWITCH ATIVO — tudo pausado. {est.get("motivo_pausa", "")}. '
                       f'Veja logs/ e apague estado.json p/ destravar.</div>')
    if sem_video:
        banners.append(f'<div class="banner kill">{_ic_alerta("#FF8B93", 16)} '
                       f'{len(sem_video)} post(s) na fila SEM vídeo na pasta: '
                       f'{", ".join(sorted(sem_video))} — o robô adia até o arquivo chegar.</div>')

    # hero do dia (baseado nos slots de hoje)
    slots = montar_slots(d["fila"], agora)
    hoje_itens = [l for s in slots for l in s["itens"]]
    hoje_total = len(hoje_itens)
    hoje_post = sum(1 for l in hoje_itens if l["status"] == "postado")
    pct = round(hoje_post / hoje_total * 100) if hoje_total else 0
    erros_txt = (f'<span style="color:#FF8B93">{d["total_erro"]} erro(s)</span>'
                 if d["total_erro"] else "zero erros")

    if est.get("pausado"):
        prox_html = (f'<div class="prox">{_ic_alerta("#FF8B93", 14)}'
                     f'<span class="lb">Próximo post</span>'
                     f'<span style="color:#FF8B93;font-weight:700">pausado pelo kill-switch</span></div>')
    elif d["prox"]:
        p = d["prox"]
        mins = round((p["previsto"] - agora).total_seconds() / 60)
        ct = f'<span class="ct">em ~{mins} min</span>'
        obs = []
        if p["atrasado"]:
            obs.append(f'slot {p["quando"]:%H:%M} atrasado')
        if p.get("aguarda_intervalo"):
            obs.append("aguarda intervalo")
        if modo == "sem_conexao":
            obs.append("aguardando conexão")
        obs_html = (f'<span class="ct tarde">{" · ".join(obs)}</span>' if obs else "")
        prox_html = (f'<div class="prox">{_ic_relogio("#A6A6AF", 14)}'
                     f'<span class="lb">Próximo post</span>'
                     f'<span class="mono" style="font-weight:700">~{p["previsto"]:%H:%M}</span>'
                     f'<span class="arq">{Path(p["arquivo"]).stem} · '
                     f'{p["conta"].replace("exemplo.", "")}</span>{ct}{obs_html}</div>')
    else:
        prox_html = (f'<div class="prox">{_ic_check("#3ECF8E", 14)}'
                     f'<span class="lb">Fila do dia concluída</span></div>')

    hero = f"""<div class="card hero sec" style="--i:0">
      <div style="display:flex;align-items:flex-end;gap:10px">
        <span class="num mono">{hoje_post}</span>
        <div style="display:flex;flex-direction:column;gap:2px;padding-bottom:4px">
          <span class="l1">de {hoje_total} Reels postados hoje</span>
          <span class="l2">{len(d["contas"])} contas · {erros_txt}</span>
        </div>
      </div>
      <div class="barra"><span style="width:{pct}%"></span></div>
      {prox_html}
    </div>"""

    # linha do dia
    ESTILO_SLOT = {
        "postado": (lambda: _ic_check("#3ECF8E"), "POSTADO", "#3ECF8E", ""),
        "erro": (lambda: _ic_alerta("#FF8B93"), "ERRO", "#FF8B93", ""),
        "atrasado": (lambda: _ic_relogio("#F5A623"), "ATRASADO", "#F5A623", " destaque"),
        "proximo": (lambda: _ic_relogio("#EC1B2E"), "PRÓXIMO", "#EC1B2E", " destaque"),
        "agendado": (lambda: _ic_agendado(), "AGENDADO", "#6E6E78", " futuro"),
    }
    linhas_slot = []
    for s in slots:
        icone, rotulo, cor, cls = ESTILO_SLOT.get(s["estado"], ESTILO_SLOT["agendado"])
        arqs = " + ".join(Path(l["arquivo"]).stem for l in s["itens"])
        dets = []
        for l in s["itens"]:
            nome = l.get("conta", "").replace("exemplo.", "")
            if l["status"] == "postado" and l.get("postado_em"):
                dets.append(f"{nome} {l['postado_em'][11:]}")
            elif l["arquivo"].strip() in sem_video:
                dets.append(f"{nome}: sem vídeo na pasta")
        det = " · ".join(dets)
        linhas_slot.append(
            f'<div class="slot{cls}"><span class="hora mono">{s["hora"]}</span>{icone()}'
            f'<div class="meio"><span class="arqs">{arqs}</span>'
            + (f'<span class="det">{det}</span>' if det else "")
            + f'</div><span class="st" style="color:{cor}">{rotulo}</span></div>')
    linha_dia = (f'<div class="sec" style="--i:1"><h2>Linha do dia</h2><div class="card lista">'
                 f'{"".join(linhas_slot)}</div></div>' if linhas_slot else
                 '<div class="sec" style="--i:1"><h2>Linha do dia</h2><div class="card" '
                 'style="padding:16px;color:var(--muted);font-size:13px">'
                 'Nada agendado pra hoje ainda.</div></div>')

    # contas
    cards = []
    for c in d["contas"].values():
        pct_c = min(100, round(c["postados_hoje"] / cap * 100)) if cap else 0
        cor_c = COR_CONTA.get(c["nome"], "#6E6E78")
        med = c.get("mediana")
        alcance = (f'<span class="v mono">{_fmt_views(med)}</span>' if med
                   else '<span class="v na">aguardando coleta</span>')
        cards.append(f"""<div class="card conta">
          <div class="hd"><span class="pt" style="background:{cor_c}"></span>
            <span class="nm">{c['nome']}</span>
            <span class="cap mono">{c['postados_hoje']}/{cap} hoje</span></div>
          <div class="barra"><span style="width:{pct_c}%;background:{cor_c}"></span></div>
          <div class="mini">
            <div class="b"><span class="k">Último post</span>
              <span class="v mono">{c['ultimo'] or '—'}</span></div>
            <div class="b"><span class="k">Próximo post</span>
              <span class="v mono">{'~' + format(c['proximo']['previsto'], '%H:%M') if c.get('proximo') else '—'}</span></div>
            <div class="b"><span class="k">Alcance mediano</span>{alcance}</div>
          </div></div>""")
    contas_html = (f'<div class="sec" style="--i:2"><h2>Contas</h2>'
                   f'<div class="contas">{"".join(cards)}</div></div>')

    # estoque de vídeos
    n_prontos = len(estoque["prontos"])
    necessidade_dia = max(1, cap * max(1, len(d["contas"])))
    if n_prontos == 0:
        estoque_st = ('<span style="color:#FF8B93;font-weight:700">SEM ESTOQUE</span>'
                      ' — nenhum vídeo pronto pra agendar')
        cor_est = "#FF3B47"
    elif n_prontos < necessidade_dia:
        estoque_st = (f'<span style="color:#FCD34D;font-weight:700">ESTOQUE BAIXO</span>'
                      f' — cobre menos de 1 dia (ritmo {necessidade_dia}/dia)')
        cor_est = "#F5A623"
    else:
        dias = n_prontos // necessidade_dia
        estoque_st = f'cobre ~{dias} dia(s) no ritmo de {necessidade_dia}/dia'
        cor_est = "#3ECF8E"
    pct_est = min(100, round(n_prontos / necessidade_dia * 100))
    nomes = ", ".join(Path(n).stem for n in estoque["prontos"][:8])
    if n_prontos > 8:
        nomes += f" +{n_prontos - 8}"
    sem_leg = (f'<span style="color:#FCD34D">{len(estoque["sem_legenda"])} vídeo(s) '
               f'sem legenda (.txt)</span>' if estoque["sem_legenda"] else "")
    estoque_html = f"""<div class="sec" style="--i:3"><h2>Estoque de vídeos</h2><div class="card conta">
      <div class="hd"><span class="nm mono" style="font-size:22px">{n_prontos}</span>
        <span style="font-size:12.5px;color:var(--sec)">prontos pra agendar</span>
        <span class="cap" style="font-size:11.5px">{estoque_st}</span></div>
      <div class="barra"><span style="width:{pct_est}%;background:{cor_est}"></span></div>
      {f'<span style="font-size:11.5px;color:var(--muted)">{nomes}</span>' if nomes else ''}
      {f'<span style="font-size:11.5px">{sem_leg}</span>' if sem_leg else ''}
    </div></div>"""

    # fila completa
    trs = []
    for l in sorted(d["fila"], key=lambda l: l.get("quando", ""), reverse=True):
        dt = _parse_dt(l.get("quando", ""), "%Y-%m-%d %H:%M")
        quando_txt = dt.strftime("%d/%m %H:%M") if dt else l.get("quando", "")
        atrasado = l["status"] == "pendente" and dt is not None and dt < agora
        falta = ('<span class="tag late">sem vídeo</span>'
                 if l["status"] == "pendente" and l.get("arquivo", "").strip() in sem_video
                 else "")
        res = (l.get("resultado") or "").strip()
        res = (res[:40] + "…") if len(res) > 40 else res
        v = _views_int(l)
        if v is None:
            alc = '<span class="reach na">—</span>'
        else:
            med = d["contas"].get(l.get("conta", "").strip(), {}).get("mediana")
            baixo = med and v < 0.5 * med
            flag = '<span class="flag">baixo</span>' if baixo else ""
            alc = f'<span class="reach {"low" if baixo else ""} mono">{_fmt_views(v)}{flag}</span>'
        trs.append(f"""<tr>
          <td class="mono">{quando_txt}</td>
          <td><span class="acc-chip">{l.get('conta', '')}</span></td>
          <td class="mono">{Path(l.get('arquivo', '')).stem}</td>
          <td>{_pill_status(l['status'], atrasado)} {falta}</td>
          <td>{alc}</td>
          <td style="color:var(--muted);max-width:280px;overflow:hidden;
              text-overflow:ellipsis">{res}</td></tr>""")
    tabela = f"""<div class="sec" style="--i:5"><h2>Fila completa</h2><div class="card rolagem">
      <table><thead><tr><th>Quando</th><th>Conta</th><th>Arquivo</th>
        <th>Status</th><th>Alcance</th><th>Resultado</th></tr></thead>
      <tbody>{''.join(trs)}</tbody></table></div></div>"""

    # eventos recentes
    evts = []
    for r in d["log"][:10]:
        ev = r.get("evento", "")
        detalhe = " · ".join(x for x in (Path(r.get("arquivo", "")).stem
                                         if r.get("arquivo") else "",
                                         r.get("detalhe", "")) if x)
        evts.append(f'<div class="evt"><span class="h mono">{r.get("data_hora", "")[11:16]}</span>'
                    f'{_ic_evento(ev)}<span class="n {ev}">{ev.replace("_", " ")}</span>'
                    f'<span class="d">{detalhe}</span></div>')
    eventos = (f'<div class="sec" style="--i:4"><h2>Eventos recentes</h2>'
               f'<div class="card lista">{"".join(evts)}</div></div>' if evts else "")

    return f"""<!doctype html><html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painel Myriad</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<div id="app">
  <div class="topbar">
    <div class="brand">N</div>
    <div style="display:flex;flex-direction:column;gap:1px">
      <span class="bname">MYRIAD</span><span class="bsub">Postador</span></div>
    <div class="spacer"></div>
    {live}
  </div>
  <div class="strip">
    <span class="rot">Aparelho</span>
    {conexao_html}
    {bateria_html}
    <span class="spacer"></span>
    <span class="sub mono">{agora:%H:%M:%S}</span>
  </div>
  <div class="wrap">
    {''.join(banners)}
    {hero}
    <div class="colunas">
      {linha_dia}
      <div style="display:flex;flex-direction:column;gap:22px">
        {contas_html}
        {estoque_html}
        {eventos}
      </div>
    </div>
    {tabela}
    <div class="foot">Painel Myriad · dados ao vivo de fila.csv e logs/ ·
      cap {cap}/dia por conta · intervalo mín {d['cfg'].get('intervalo_minimo_min', 90)} min ·
      atualiza a cada 20s</div>
  </div>
</div>
<script>
// Depois da entrada, marca a página como "já animada": as trocas de dados
// abaixo substituem o conteúdo SEM replay das animações (e sem piscar).
setTimeout(function () {{ document.documentElement.setAttribute("data-atualizado", "1"); }}, 1400);
setInterval(async function () {{
  try {{
    var r = await fetch(location.href, {{ cache: "no-store" }});
    if (!r.ok) return;
    var doc = new DOMParser().parseFromString(await r.text(), "text/html");
    var novo = doc.getElementById("app");
    var atual = document.getElementById("app");
    if (novo && atual) atual.replaceWith(novo);
  }} catch (e) {{ /* rede oscilou: tenta de novo no próximo ciclo */ }}
}}, 20000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404); self.end_headers(); return
        try:
            html = render(coletar())
        except Exception as e:
            html = f"<pre>Erro ao montar o painel: {e}</pre>"
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # silencia o log de acesso no console


def main():
    url = f"http://127.0.0.1:{PORTA}"
    print(f"Dashboard do Postador Myriad em {url}  (Ctrl+C para parar)")
    # --sem-navegador: modo de inicialização automática (não abre aba a cada boot)
    if "--sem-navegador" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    HTTPServer(("127.0.0.1", PORTA), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDashboard encerrado.")
