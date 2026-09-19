# -*- coding: utf-8 -*-
"""
MYRIAD — central de comando do postador (v2, spec 14/09).

Regra de UX do spec: SE EU VEJO, EU ADMINISTRO DALI. Cada tela responde:
o que está acontecendo · o que vem depois · o que eu posso fazer.

Dados: coletar() do dashboard (lógica testada) + derivações do
myriad_dados. Ações: myriad_acoes (lock da fila, frases humanas).
Views: Visão Geral · Aparelhos · Contas · Posts · Biblioteca · Automação
· Conectar. Toast via ?msg=; destrutivas confirmam no navegador.

Uso:
    python myriad.py        # http://127.0.0.1:8776
"""

import html as _html
import re
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import dashboard
import myriad_acoes as acoes
import myriad_dados as dados
from dashboard import coletar, montar_slots

RAIZ = Path(__file__).parent
PORTA = 8776
VERDE = "#41C46E"

esc = lambda s: _html.escape(str(s if s is not None else ""))

# ---------- SVGs ----------

LOGO = f"""<svg viewBox="0 0 48 48" fill="none" width="26" height="26">
<path d="M8 38V14L18 28L24 16L30 28L40 14V38" stroke="{VERDE}" stroke-width="2.6"
 stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="8" cy="14" r="3" fill="#0B0E0B" stroke="{VERDE}" stroke-width="2"/>
<circle cx="24" cy="16" r="3" fill="#0B0E0B" stroke="{VERDE}" stroke-width="2"/>
<circle cx="40" cy="14" r="3" fill="#0B0E0B" stroke="{VERDE}" stroke-width="2"/>
<circle cx="8" cy="38" r="2.2" fill="{VERDE}"/>
<circle cx="40" cy="38" r="2.2" fill="{VERDE}"/>
</svg>"""

IG = """<svg viewBox="0 0 24 24" width="20" height="20"><defs>
<linearGradient id="ig" x1="0" y1="1" x2="1" y2="0">
<stop offset="0" stop-color="#FFD600"/><stop offset=".5" stop-color="#FF0169"/>
<stop offset="1" stop-color="#7638FA"/></linearGradient></defs>
<rect x="2" y="2" width="20" height="20" rx="6" fill="url(#ig)"/>
<circle cx="12" cy="12" r="4.6" fill="none" stroke="#fff" stroke-width="1.8"/>
<circle cx="17.2" cy="6.8" r="1.3" fill="#fff"/></svg>"""

TIKTOK = """<svg viewBox="0 0 24 24" width="20" height="20"><rect x="2" y="2" width="20" height="20" rx="6" fill="#111"/><path d="M15 6.5c.6 1.3 1.7 2.2 3.1 2.4v2.3c-1.2 0-2.3-.4-3.1-1v4.6a4.4 4.4 0 11-3.6-4.3v2.4a2 2 0 101.4 1.9V5.5H15v1z" fill="#fff"/></svg>"""
YT = """<svg viewBox="0 0 24 24" width="20" height="20"><rect x="2" y="5" width="20" height="14" rx="4" fill="#FF0000"/><path d="M10.5 9l5 3-5 3z" fill="#fff"/></svg>"""
FB = """<svg viewBox="0 0 24 24" width="20" height="20"><rect x="2" y="2" width="20" height="20" rx="6" fill="#1877F2"/><path d="M15.5 8.5h-1.6c-.4 0-.8.4-.8.9v1.6h2.3l-.4 2.3h-1.9V20h-2.4v-6.7H9v-2.3h1.7V9.2c0-1.8 1.1-2.9 2.8-2.9h2v2.2z" fill="#fff"/></svg>"""

_I = {
    "visao": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
    "aparelhos": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M10.5 18.5h3"/></svg>',
    "contas": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="3.4"/><path d="M5 20c.8-3.6 3.6-5.4 7-5.4s6.2 1.8 7 5.4"/></svg>',
    "posts": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 3L10.5 13.5M21 3l-7 18-3.5-7.5L3 10z"/></svg>',
    "biblioteca": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 4h5l2 3h9v12H4z"/></svg>',
    "automacao": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.2 2.2M16.9 16.9l2.2 2.2M19.1 4.9l-2.2 2.2M7.1 16.9l-2.2 2.2"/></svg>',
    "conectar": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 7L5 12l4 5M15 7l4 5-4 5"/></svg>',
}

MENU = [("visao", "Visão Geral"), ("aparelhos", "Aparelhos"), ("contas", "Contas"),
        ("posts", "Posts"), ("biblioteca", "Biblioteca"), ("automacao", "Automação"),
        ("conectar", "Conectar aparelho")]

CSS = """
:root{--bg:#0A0B0A;--side:#0C0E0C;--card:#131614;--card2:#1B1F1C;
 --verde:#30D158;--verde-esc:rgba(48,209,88,.12);--text:#F2F5F2;--sec:#98A29A;
 --mut:#5C665E;--err:#FF6961;--amber:#FFB340;--azul:#64B5FF}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);display:flex;min-height:100vh;
 font:14px/1.55 -apple-system,'SF Pro Text','Segoe UI',system-ui,sans-serif;
 -webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.mono{font-family:ui-monospace,'SF Mono',Consolas,monospace;font-variant-numeric:tabular-nums}
.side{width:220px;background:var(--side);padding:22px 14px;flex-shrink:0;display:flex;flex-direction:column;gap:2px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;padding:2px 10px 22px}
.brand b{font-size:16px;letter-spacing:-.01em;font-weight:700}
.mi{display:flex;align-items:center;gap:11px;padding:8px 12px;border-radius:11px;color:var(--sec);font-weight:500;font-size:13.5px;cursor:pointer;transition:color .12s}
.mi:hover{color:var(--text)}
.mi.on{background:var(--verde-esc);color:var(--verde);font-weight:600}
.plats{margin-top:auto;display:flex;gap:10px;padding:12px;align-items:center}
.plats .breve{filter:grayscale(1);opacity:.25}
.plats svg{width:16px;height:16px}
main{flex:1;padding:34px 40px;min-width:0;max-width:1180px}
h1{font-size:26px;letter-spacing:-.03em;margin-bottom:3px;font-weight:700}
.sub{color:var(--mut);font-size:13px;margin-bottom:26px}
.sub b{color:var(--sec);font-weight:600}
.view{display:none}.view.on{display:block;animation:vista .22s ease}
@keyframes vista{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
.faixa{display:flex;align-items:center;gap:12px;border-radius:16px;padding:14px 20px;margin-bottom:22px;font-weight:600;font-size:14.5px}
.faixa small{font-weight:400;opacity:.75;font-size:13px}
.f-ok{background:var(--verde-esc);color:var(--verde)}
.f-atencao{background:rgba(255,179,64,.1);color:var(--amber)}
.f-pausado{background:rgba(152,162,154,.08);color:var(--sec)}
.f-critico{background:rgba(255,105,97,.1);color:var(--err)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
.tile{background:var(--card);border:1px solid rgba(255,255,255,.055);border-radius:18px;padding:18px 20px;
 transition:transform .16s ease,border-color .16s ease;animation:sobe .34s ease both}
.tile:nth-child(2){animation-delay:.05s}.tile:nth-child(3){animation-delay:.1s}.tile:nth-child(4){animation-delay:.15s}
.tile:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.12)}
.tile .v{font-size:28px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tile .k{font-size:11px;color:var(--mut);margin-top:2px}
.tile.ok .v{color:var(--verde)}.tile.err .v{color:var(--err)}.tile.amber .v{color:var(--amber)}
.duas{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:1100px){.duas{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid rgba(255,255,255,.055);border-radius:18px;padding:18px 22px;margin-bottom:14px;overflow-x:auto;
 transition:border-color .16s ease}
.card:hover{border-color:rgba(255,255,255,.1)}
@keyframes sobe{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.gcard{overflow:hidden}
.g7{width:100%;height:auto;display:block}
.glegenda{display:flex;gap:16px;font-size:11px;margin-bottom:6px}
.lg-p{color:var(--verde)}.lg-v{color:var(--azul)}
.g7 .gb{fill:var(--verde);opacity:.85;transform-origin:bottom;animation:cresce .6s cubic-bezier(.2,.7,.3,1) both}
.g7 .gb:hover{opacity:1}
.g7 .ga{fill:url(#gv)}
.g7 .gl{fill:none;stroke:var(--azul);stroke-width:2;stroke-linecap:round;stroke-linejoin:round;
 filter:drop-shadow(0 0 5px rgba(100,181,255,.55));stroke-dasharray:1200;stroke-dashoffset:1200;animation:desenha 1.1s ease-out .25s forwards}
.g7 .gd{fill:var(--azul);filter:drop-shadow(0 0 6px rgba(100,181,255,.9));opacity:0;animation:aparece .3s ease 1.2s forwards}
.g7 .gt{fill:var(--mut);font-size:10px;text-anchor:middle}
@keyframes cresce{from{transform:scaleY(0)}to{transform:scaleY(1)}}
@keyframes desenha{to{stroke-dashoffset:0}}
@keyframes aparece{to{opacity:1}}
.card h3{margin-bottom:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.08em;font-weight:600;font-size:11px}
.card table{min-width:520px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.07em;text-align:left;padding:5px 8px}
td{padding:9px 10px;border-top:1px solid rgba(255,255,255,.05);vertical-align:middle}
.tag{font-size:12px;font-weight:600;white-space:nowrap}
.t-ok{color:var(--verde)}
.t-pend{color:var(--sec)}
.t-err{color:var(--err)}
.t-amber{color:var(--amber)}
.t-azul{color:var(--azul)}
button{font:inherit;cursor:pointer}
.acao{background:var(--verde);color:#06130A;font-weight:600;border:0;border-radius:99px;padding:9px 18px;font-size:13.5px}
.acao.vermelho{background:rgba(255,105,97,.14);color:var(--err)}
.mini{background:none;border:0;color:var(--azul);padding:4px 8px;font-size:13px;font-weight:500;border-radius:8px}
.mini:hover{background:rgba(255,255,255,.05)}
.mini.v{color:var(--verde)}.mini.r{color:var(--err)}
input,select{background:var(--card2);border:0;border-radius:10px;color:var(--text);font:inherit;padding:8px 12px}
input:focus,select:focus{outline:2px solid rgba(48,209,88,.4)}
.busca{width:260px;margin-bottom:14px}
.distrib{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--card);border:1px solid rgba(255,255,255,.055);border-radius:14px;padding:10px 14px;margin-bottom:14px;font-size:13px}
.distrib .chip{display:inline-flex;align-items:center;gap:6px;background:var(--card2);border-radius:99px;padding:5px 12px;cursor:pointer;color:var(--sec)}
.distrib .chip:has(input:checked){background:var(--verde-esc);color:var(--verde)}
.distrib-dica{color:var(--mut);font-size:11.5px}
.marca{accent-color:var(--verde);width:15px;height:15px;cursor:pointer}
.abas{display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap;background:var(--card);border-radius:99px;padding:4px;width:fit-content}
.aba{padding:6px 15px;border-radius:99px;border:0;background:none;color:var(--sec);font-size:13px;font-weight:500}
.aba.on{background:var(--card2);color:var(--text);font-weight:600}
.saude{display:grid;gap:9px}
.saude .item{display:flex;gap:10px;align-items:baseline;font-size:13.5px}
.saude .led{width:8px;height:8px;border-radius:50%;flex-shrink:0;position:relative;top:1px}
.led-ok{background:var(--verde)}.led-erro{background:var(--err)}
.led-atencao{background:var(--amber)}.led-sem_dados{background:var(--mut)}
.saude .nm{font-weight:600;min-width:100px}
.saude .fr{color:var(--sec)}
.ativ{display:grid;gap:10px;font-size:13.5px}
.ativ .lin{display:flex;gap:12px;align-items:baseline}
.ativ .q{color:var(--mut);font-size:11.5px;min-width:70px;flex-shrink:0}
.ativ .d{color:var(--mut);font-size:12px;margin-top:1px}
.sinal-velho{color:var(--err);font-weight:600}
.vazio{color:var(--mut);padding:16px 0;text-align:center;font-size:13px}
.frota{display:grid;grid-template-columns:repeat(auto-fill,minmax(460px,1fr));gap:18px;max-width:1040px}
.cel-linha{display:flex;gap:20px;background:var(--card);border-radius:20px;padding:20px}
.tela{position:relative;width:100px;aspect-ratio:9/19;border-radius:16px;background:#000;box-shadow:0 0 0 2px #262B27,0 0 0 5px #14171A;padding:10px 6px;display:flex;flex-direction:column;align-items:center;overflow:hidden;flex-shrink:0}
.tela::before{content:"";position:absolute;top:5px;left:50%;transform:translateX(-50%);width:28px;height:7px;border-radius:5px;background:#15191B}
.tela::after{content:"";position:absolute;inset:0;background:radial-gradient(70px 90px at 50% 60%,rgba(48,209,88,.09),transparent)}
.dock{display:flex;gap:5px;margin-top:12px;z-index:1}
.dock .off{filter:grayscale(1);opacity:.25}
.dock svg{width:13px;height:13px}
.miolo{flex:1;display:grid;place-items:center;z-index:1}
.miolo svg{width:32px;height:32px;opacity:.85}
.statusled{position:absolute;bottom:8px;right:9px;width:8px;height:8px;border-radius:50%;z-index:2}
.led-on{background:var(--verde);box-shadow:0 0 8px rgba(48,209,88,.8);animation:pulso 2.6s ease-in-out infinite}
@keyframes pulso{0%,100%{box-shadow:0 0 6px rgba(48,209,88,.55)}50%{box-shadow:0 0 12px rgba(48,209,88,.95)}}
.led-off{background:#39413B}
.cel-info{flex:1;min-width:0}
.cel-info h4{font-size:15px;font-weight:600}
.cel-info .est{margin:4px 0 10px;font-size:12.5px;display:flex;gap:12px}
.cel-info .kv{font-size:13px;color:var(--sec);display:grid;grid-template-columns:auto 1fr;gap:3px 12px}
.cel-info .kv b{color:var(--mut);font-weight:500;font-size:12px}
.cel-acoes{margin-top:12px;display:flex;flex-wrap:wrap;gap:4px}
#toast{position:fixed;bottom:22px;right:24px;max-width:400px;background:var(--card2);border:1px solid rgba(255,255,255,.08);color:var(--text);border-radius:14px;padding:13px 18px;font-size:13.5px;box-shadow:0 14px 44px rgba(0,0,0,.65);z-index:99;display:none;
 animation:toastin .28s cubic-bezier(.2,.9,.3,1.15)}
@keyframes toastin{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
.inline-form{display:inline}
.regras td form{display:flex;gap:8px}
.regras input{width:100px}
details.menu{position:relative;display:inline-block}
details.menu>summary{list-style:none;cursor:pointer;color:var(--sec);padding:2px 10px;border-radius:8px;font-weight:700;font-size:15px}
details.menu>summary::-webkit-details-marker{display:none}
details.menu>summary:hover{background:rgba(255,255,255,.06);color:var(--text)}
details.menu[open]>summary{color:var(--text)}
details.menu>.itens{position:absolute;right:0;top:26px;background:var(--card2);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:6px;min-width:190px;z-index:20;box-shadow:0 14px 40px rgba(0,0,0,.55);display:grid;
 animation:menupop .13s cubic-bezier(.2,.9,.3,1.2)}
@keyframes menupop{from{opacity:0;transform:translateY(-4px) scale(.97)}to{opacity:1;transform:none}}
details.menu .itens form{display:block}
details.menu .itens button{display:block;width:100%;text-align:left;background:none;border:0;color:var(--text);padding:8px 12px;border-radius:9px;font-size:13px}
details.menu .itens button:hover{background:rgba(255,255,255,.06)}
details.menu .itens button.r{color:var(--err)}
details.menu .itens .grupo{padding:8px 12px}
@media(max-width:980px){
  .side{width:62px;padding:16px 8px}
  .side .mi span,.side .brand b,.side .plats{display:none}
  .side .mi{justify-content:center;padding:10px}
  main{padding:18px 14px}
  .duas{grid-template-columns:1fr}
  .busca{width:100%}
}
"""


def _redir_msg(msg: str) -> str:
    return "/?msg=" + urllib.parse.quote(msg)


def _apps_dock() -> str:
    return (f'<div class="dock">{IG}'
            f'<span class="off" title="em breve">{TIKTOK}</span>'
            f'<span class="off" title="em breve">{YT}</span>'
            f'<span class="off" title="em breve">{FB}</span></div>')


def _bt(rotulo: str, acao: str, campos: dict, classe: str = "mini",
        confirmar: str = "") -> str:
    hid = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">'
                  for k, v in campos.items())
    onsub = f' onsubmit="return confirm(\'{esc(confirmar)}\')"' if confirmar else ""
    return (f'<form class="inline-form" method="post" action="/acao/{acao}"{onsub}>'
            f'{hid}<button class="{classe}" type="submit">{rotulo}</button></form>')


def _grafico_7d(fila: list, agora: datetime) -> str:
    """Área de views + barras de posts dos últimos 7 dias, em SVG puro
    (sem lib): linha fina com brilho e preenchimento em gradiente — o
    gráfico se DESENHA ao carregar (stroke-dasharray no CSS)."""
    from datetime import timedelta
    dias = [(agora - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    rotulos = [(agora - timedelta(days=i)).strftime("%d/%m") for i in range(6, -1, -1)]
    posts = {d: 0 for d in dias}
    views = {d: 0 for d in dias}
    for l in fila:
        dia = (l.get("postado_em") or "")[:10]
        if l.get("status") == "postado" and dia in posts:
            posts[dia] += 1
            v = (l.get("views") or "").strip()
            views[dia] += int(v) if v.isdigit() else 0
    p = [posts[d] for d in dias]
    v = [views[d] for d in dias]
    if not any(p) and not any(v):
        return ""
    W, H, PAD = 560, 132, 26
    passo = (W - 2 * PAD) / 6
    max_p = max(max(p), 1)
    max_v = max(max(v), 1)
    barras = []
    for i, n in enumerate(p):
        x = PAD + i * passo
        h = 0 if not n else max(6, int((H - 46) * n / max_p))
        barras.append(
            f'<rect class="gb" x="{x - 7:.0f}" y="{H - 24 - h}" width="14" height="{h}" rx="4">'
            f'<title>{rotulos[i]}: {n} post(s)</title></rect>')
    pontos = []
    for i, n in enumerate(v):
        x = PAD + i * passo
        y = H - 24 - (H - 52) * n / max_v
        pontos.append(f"{x:.0f},{y:.0f}")
    linha = " ".join(pontos)
    area = f"{PAD},{H - 24} " + linha + f" {W - PAD},{H - 24}"
    rot = "".join(f'<text class="gt" x="{PAD + i * passo:.0f}" y="{H - 8}">{r}</text>'
                  for i, r in enumerate(rotulos))
    fim_x, fim_y = pontos[-1].split(",")
    tem_views = any(v)
    svg_views = (f'<polygon class="ga" points="{area}"/>'
                 f'<polyline class="gl" points="{linha}"/>'
                 f'<circle class="gd" cx="{fim_x}" cy="{fim_y}" r="3.5"/>') if tem_views else ""
    return (f'<div class="card gcard"><h3>Últimos 7 dias</h3>'
            f'<div class="glegenda"><span class="lg-p">▮ posts</span>'
            + (f'<span class="lg-v">— views</span>' if tem_views else "") + "</div>"
            f'<svg class="g7" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            f'<defs><linearGradient id="gv" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="#64B5FF" stop-opacity=".28"/>'
            f'<stop offset="1" stop-color="#64B5FF" stop-opacity="0"/></linearGradient></defs>'
            f'{"".join(barras)}{svg_views}{rot}</svg></div>')


def _menu(*itens: str) -> str:
    """O '⋯' apple-style: as ações moram num dropdown, a linha fica limpa."""
    return f'<details class="menu"><summary>⋯</summary><div class="itens">{"".join(itens)}</div></details>'


def _mi_bt(rotulo: str, acao: str, campos: dict, perigo: bool = False,
           confirmar: str = "") -> str:
    hid = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">'
                  for k, v in campos.items())
    onsub = f' onsubmit="return confirm(\'{esc(confirmar)}\')"' if confirmar else ""
    return (f'<form method="post" action="/acao/{acao}"{onsub}>{hid}'
            f'<button class="{"r" if perigo else ""}" type="submit">{rotulo}</button></form>')


# ---------- views ----------

def _v_visao(d: dict) -> str:
    eg = d["eg"]
    buf = d["buffer"]
    ag = d["agora_ap"]
    sa = d["saude"]
    slots = montar_slots(d["fila"], d["agora"])
    tags = {"postado": "t-ok", "erro": "t-err", "atrasado": "t-amber", "proximo": "t-azul"}
    prox_linhas = "".join(
        '<tr><td class="mono">' + esc(s["hora"]) + "</td><td>"
        + "<br>".join(f'@{esc(i.get("conta", ""))} · {esc(i.get("arquivo", ""))}' for i in s.get("itens", []))
        + f'</td><td><span class="tag {tags.get(s["estado"], "t-pend")}">{esc(s["estado"])}</span></td></tr>'
        for s in slots[:6])
    def _linha_ativ(e: dict) -> str:
        vezes = f' <span class="tag t-pend" title="de {esc(e["desde"][11:16])} até {esc(e["quando"][11:16])}">×{e["vezes"]}</span>' if e.get("vezes", 1) > 1 else ""
        tec = f' title="{esc(e["tecnico"])}"' if e.get("tecnico") else ""
        det = f'<div class="d"{tec}>{esc(e["detalhe"])}{" · detalhe técnico no hover" if e.get("tecnico") else ""}</div>' if (e["detalhe"] or e.get("tecnico")) else ""
        return (f'<div class="lin"><span class="q mono">{esc(e["quando"][5:16])}</span>'
                f'<div><span>{e["icone"]} {esc(e["frase"])}{vezes}</span>{det}</div></div>')

    ativ = "".join(_linha_ativ(e) for e in d["atividade"][:5])
    # saúde apple-style: só o que está MAL merece tela; o resto é uma linha de paz
    problemas = [i for i in sa if i.get("estado") != "ok"]
    saude_html = "".join(
        f'<div class="item"><span class="led led-{esc(i["estado"])}"></span>'
        f'<span class="nm">{esc(i["nome"])}</span><span class="fr">{esc(i["frase"])}</span></div>'
        for i in problemas) or '<div class="item"><span class="led led-ok"></span><span class="fr">Tudo certo — nada pede sua atenção.</span></div>'
    pausado = d["estado"].get("pausado")
    botao_global = _bt("Retomar tudo", "pausar_tudo", {"pausar": "0"}, "acao") if pausado \
        else _bt("Pausar tudo", "pausar_tudo", {"pausar": "1"}, "acao vermelho",
                 "Pausar TODA a operação? Nada posta até retomar.")
    erros_chip = f' · <span style="color:var(--vermelho)">{d["total_erro"]} com erro</span>' if d["total_erro"] else ""
    return f'''
    <h1>Visão Geral</h1>
    <div class="faixa f-{eg["tom"]}"><span>{esc(eg["rotulo"])}</span><small>{esc(eg["frase"])}</small>
      <span style="margin-left:auto">{botao_global}</span></div>
    <div class="tiles">
      <div class="tile ok"><div class="v" data-n="{d["total_post"]}">{d["total_post"]}</div><div class="k">postados hoje</div></div>
      <div class="tile"><div class="v" data-n="{d["total_pend"]}">{d["total_pend"]}</div><div class="k">na fila{erros_chip}</div></div>
      <div class="tile{" amber" if (buf.get("tom") in ("atencao", "critico")) else ""}"><div class="v">{buf["dias"] if buf.get("dias") is not None else "—"}</div><div class="k">dias de conteúdo</div></div>
      <div class="tile"><div class="v">{dashboard._fmt_views(d["total_views"]) if d["total_views"] else 0}</div><div class="k">views hoje</div></div>
    </div>
    {_grafico_7d(d["fila"], d["agora"])}
    <div class="duas">
      <div>
        <div class="card"><h3>Agora</h3>
          <div class="item" style="display:flex;gap:10px;align-items:center">
            <span class="statusled {"led-on" if ag["led"] == "on" else "led-off"}" style="position:static"></span>
            <div><b>Galaxy A03s</b> — {esc(ag["titulo"])}<div class="fr" style="color:var(--sec);font-size:12.5px">{esc(ag["sub"])}</div></div>
          </div>
        </div>
        <div class="card"><h3>Saúde</h3><div class="saude">{saude_html}</div></div>
      </div>
      <div>
        <div class="card"><h3>Próximas execuções</h3>
          <table><tbody>{prox_linhas or '<tr><td class="vazio">nada agendado hoje</td></tr>'}</tbody></table></div>
        <div class="card"><h3>Atividade</h3><div class="ativ">{ativ or '<div class="vazio">sem eventos ainda</div>'}</div></div>
      </div>
    </div>'''


def _v_aparelhos(d: dict) -> str:
    cx = d["conexao"]
    online = dados.conexao_fresca(cx, d["agora"])   # a VERDADE: conexão real e fresca
    ag = d["agora_ap"]
    detal = {"usb": "cabo USB", "wifi": "Wi-Fi", "sem_conexao": "sem conexão"}.get(
        cx.get("modo"), cx.get("modo") or "sem conexão")
    bat = f'{cx.get("bateria")}%{" ⚡" if cx.get("carregando") else ""}' if cx.get("bateria") is not None else "—"
    idade = dados.idade_sinal(cx, d["agora"])
    sinal_velho = not online and idade not in ("agora", "nunca")
    contas_chips = " ".join(f"@{esc(c)}" for c in d["cfg"].get("contas_agendamento", []))
    pausado = d["estado"].get("pausado")
    robo = "Rodando" if d["rodando"] else ("Pausado" if pausado else "Parado")
    return f'''
    <h1>Meus aparelhos</h1>
    <div class="sub"><b>1 aparelho</b> · {d["n_online"]} online · robô: <b>{robo}</b></div>
    <div class="frota">
      <div class="cel-linha">
        <div class="tela">{_apps_dock()}<div class="miolo">{LOGO.replace('width="26" height="26"', 'width="34" height="34"')}</div>
          <span class="statusled {"led-on" if online else "led-off"}"></span></div>
        <div class="cel-info">
          <h4>Aparelho 1 · Galaxy A03s</h4>
          <div class="est"><span class="tag {"t-ok" if online else "t-err"}">{"ONLINE" if online else "OFFLINE"}</span>
            <span class="tag {"t-pend" if d["rodando"] else "t-amber"}">ROBÔ {esc(robo).upper()}</span></div>
          <div class="kv">
            <b>conexão</b><span>{esc(detal)}</span>
            <b>bateria</b><span>{esc(bat)}</span>
            <b>último sinal</b><span class="mono{" sinal-velho" if sinal_velho else ""}">{esc(idade)}</span>
            <b>agora</b><span>{esc(ag["titulo"])} — {esc(ag["sub"])}</span>
            <b>rodízio</b><span>{contas_chips or "—"}</span>
          </div>
          <div class="cel-acoes">
            {_bt("Testar conexão", "testar_conexao", {}, "mini v")}
            {_menu(
                _mi_bt("Reiniciar Instagram", "reiniciar_ig", {}, confirmar="Fechar e reabrir o Instagram no aparelho?"),
                _mi_bt("Retomar tudo", "pausar_tudo", {"pausar": "0"}) if pausado
                else _mi_bt("Pausar tudo", "pausar_tudo", {"pausar": "1"}, perigo=True, confirmar="Pausar TODA a operação?"))}
          </div>
        </div>
      </div>
    </div>'''


def _v_contas(d: dict) -> str:
    cfg = d["cfg"]
    pausadas = set(cfg.get("contas_pausadas", []))
    rodizio = cfg.get("contas_agendamento", [])
    ov = cfg.get("overrides_conta", {})
    linhas = []
    # entidades operacionais = as contas do CONFIG (rodízio, pausadas, com
    # regra própria). Contas que só existem no histórico da fila NÃO são
    # administráveis — aparecem em Posts (vistoria 14/09: exemplo.corp/es/mind
    # do passado apareciam como se estivessem na operação)
    nomes = sorted(set(rodizio) | pausadas | set(ov.keys()))
    for nome in nomes:
        c = d["contas"].get(nome, {"postados_hoje": 0, "ultimo": None, "proximo": None, "mediana": None})
        if nome in pausadas:
            estado = '<span class="tag t-amber">PAUSADA</span>'
        elif nome not in rodizio:
            estado = '<span class="tag t-pend">FORA DO RODÍZIO</span>'
        else:
            estado = '<span class="tag t-ok">ATIVA</span>'
        limite = ov.get(nome, {}).get("max_posts_dia")
        regra = (f'<span class="tag t-azul" title="override desta conta">{limite}/dia própria</span>'
                 if limite else f'<span style="color:var(--mut)">{cfg.get("max_posts_dia")}/dia</span>')
        prox = c.get("proximo")
        prox_txt = f'{prox["previsto"]:%H:%M}' if prox else "—"
        menu = _menu(
            (_mi_bt("Retomar", "retomar_conta", {"conta": nome}) if nome in pausadas
             else _mi_bt("Pausar", "pausar_conta", {"conta": nome},
                         confirmar=f"Pausar @{nome}? Os posts dela ficam congelados.")),
            (_mi_bt("Tirar do rodízio", "rodizio", {"conta": nome, "entrar": "0"})
             if nome in rodizio else _mi_bt("Pôr no rodízio", "rodizio", {"conta": nome, "entrar": "1"})),
            _mi_bt("Limite de posts…", "override_prompt", {"conta": nome}),
            '<div class="grupo"></div>',
            _mi_bt("Remover conta", "remover_conta", {"conta": nome}, perigo=True,
                   confirmar=f"Remover @{nome} da operação? Pendentes serão cancelados (histórico fica)."))
        linhas.append(
            f'<tr data-busca="{esc(nome)}"><td><b>@{esc(nome)}</b></td><td>{estado}</td>'
            f'<td class="mono">{c["postados_hoje"]}</td>'
            f'<td class="mono">{prox_txt}</td>'
            f'<td>{regra}</td><td style="text-align:right">{menu}</td></tr>')
    return f'''
    <h1>Contas</h1>
    <div class="sub">{len(nomes)} conta(s)</div>
    <input class="busca" placeholder="Buscar" oninput="filtrar(this, 'tab-contas')">
    <div class="card"><table id="tab-contas"><thead><tr><th>Conta</th><th>Estado</th><th>Hoje</th>
    <th>Próximo</th><th>Limite</th><th></th></tr></thead>
    <tbody>{"".join(linhas)}</tbody></table></div>
    <form method="post" action="/acao/rodizio" style="display:flex;gap:10px;align-items:center;margin-top:14px">
      <input type="hidden" name="entrar" value="1">
      <input name="conta" placeholder="conta nova (sem @)" required style="max-width:240px">
      <button class="acao" type="submit">Adicionar</button>
    </form>'''


def _v_posts(d: dict) -> str:
    tags = {"postado": "t-ok", "pendente": "t-pend", "erro": "t-err",
            "vencido": "t-amber", "cancelado": "t-pend"}
    linhas = []
    for l in sorted(d["fila"], key=lambda x: x.get("quando", ""), reverse=True):
        st = l.get("status", "")
        conta, arq = l.get("conta", ""), l.get("arquivo", "")
        base = {"conta": conta, "arquivo": arq}
        if st in ("pendente", "vencido"):
            a = _menu(_mi_bt("Publicar agora", "publicar_agora", base),
                      _mi_bt("Reagendar…", "reagendar_prompt", base),
                      '<div class="grupo"></div>',
                      _mi_bt("Cancelar", "cancelar_post", base, perigo=True, confirmar=f"Cancelar {arq}?"))
        elif st == "erro":
            a = _menu(_mi_bt("Tentar de novo", "tentar_de_novo", base),
                      _mi_bt("Reagendar…", "reagendar_prompt", base),
                      '<div class="grupo"></div>',
                      _mi_bt("Cancelar", "cancelar_post", base, perigo=True, confirmar=f"Cancelar {arq}?"))
        elif st == "cancelado":
            a = _menu(_mi_bt("Reagendar…", "reagendar_prompt", base),
                      _mi_bt("Remover da fila", "remover_post", base, perigo=True, confirmar=f"Tirar {arq} da fila?"))
        else:
            a = ""
        erro_txt = ""
        if st in ("erro", "vencido") and l.get("resultado"):
            erro_txt = f'<div style="color:var(--mut);font-size:11.5px;max-width:320px">{esc(l["resultado"][:120])}</div>'
        views = dashboard._fmt_views(int(l["views"])) if (l.get("views") or "").strip().isdigit() else "—"
        linhas.append(
            f'<tr data-st="{esc(st)}" data-busca="{esc(conta)} {esc(arq)} {esc(st)}">'
            f'<td class="mono">{esc(l.get("quando", ""))}</td><td>@{esc(conta)}</td>'
            f'<td>{esc(arq)}{erro_txt}</td>'
            f'<td><span class="tag {tags.get(st, "t-pend")}">{esc(st)}</span></td>'
            f'<td class="mono">{views}</td>'
            f'<td style="text-align:right">{a}</td></tr>')
    abas = "".join(
        f'<button class="aba{" on" if k == "todos" else ""}" onclick="abaPosts(this, \'{k}\')">{r}</button>'
        for k, r in [("todos", "Todos"), ("pendente", "Fila"), ("postado", "Publicados"),
                     ("erro", "Erros"), ("vencido", "Vencidos"), ("cancelado", "Cancelados")])
    return f'''
    <h1>Posts</h1>
    <div class="sub">{d["total_post"]} hoje · {d["total_pend"]} na fila{f" · {d['total_erro']} erro(s)" if d["total_erro"] else ""}</div>
    <div class="abas">{abas}</div>
    <input class="busca" placeholder="Buscar" oninput="filtrar(this, 'tab-posts')">
    <div class="card"><table id="tab-posts"><thead><tr><th>Quando</th><th>Conta</th><th>Arquivo</th>
    <th>Estado</th><th>Views</th><th></th></tr></thead>
    <tbody>{"".join(linhas) or '<tr><td colspan="6" class="vazio">fila vazia</td></tr>'}</tbody></table></div>'''


def _sugestao_horario(cfg: dict, agora: datetime) -> str:
    """Próximo horário VÁLIDO: dentro da janela e no futuro (a vistoria
    pegou o campo sugerindo 02:00 da madrugada, no passado)."""
    from datetime import timedelta
    ini = cfg.get("janela_inicio", "09:00")
    fim = cfg.get("janela_fim", "21:00")
    h_ini = datetime.strptime(ini, "%H:%M").time()
    h_fim = datetime.strptime(fim, "%H:%M").time()
    prox = (agora + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    if prox.time() < h_ini:
        prox = prox.replace(hour=h_ini.hour, minute=h_ini.minute)
    elif prox.time() > h_fim:
        prox = (prox + timedelta(days=1)).replace(hour=h_ini.hour, minute=h_ini.minute)
    return prox.strftime("%Y-%m-%d %H:%M")


def _v_biblioteca(d: dict) -> str:
    est = d["estoque"]
    contas_opts = "".join(f'<option value="{esc(c)}">@{esc(c)}</option>'
                          for c in d["cfg"].get("contas_agendamento", []))
    sugestao = _sugestao_horario(d["cfg"], d["agora"])
    def _linha_video(nome, tag, tag_cls, com_acao):
        marca = (f'<input type="checkbox" class="marca" form="distrib" name="arquivos" '
                 f'value="{esc(nome)}">' if com_acao else "")
        agendar = ""
        if com_acao:
            agendar = (f'<form class="inline-form" method="post" action="/acao/agendar_video">'
                       f'<input type="hidden" name="arquivo" value="{esc(nome)}">'
                       f'<select name="conta">{contas_opts}</select> '
                       f'<input name="quando" value="{esc(sugestao)}" size="15" class="mono"> '
                       f'<button class="mini v" type="submit">Agendar</button></form>')
        dedicar = (f'<form method="post" action="/acao/dedicar_video">'
                   f'<input type="hidden" name="arquivo" value="{esc(nome)}">'
                   f'<select name="conta" style="width:100%;margin-bottom:6px">{contas_opts}</select>'
                   f'<button type="submit" title="move pra videos/&lt;conta&gt;/ — só ela recebe">Dedicar a esta conta</button></form>')
        menu = _menu(dedicar, '<div class="grupo"></div>',
                     _mi_bt("Excluir vídeo", "excluir_video", {"arquivo": nome}, perigo=True,
                            confirmar=f"Excluir {nome} da biblioteca? Não tem volta."))
        return (f'<tr data-busca="{esc(nome)}"><td style="width:26px">{marca}</td><td>{esc(nome)}</td>'
                f'<td><span class="tag {tag_cls}">{tag}</span></td>'
                f'<td>{agendar}</td><td style="text-align:right">{menu}</td></tr>')

    linhas = ([_linha_video(n, "PRONTO", "t-ok", True) for n in est["prontos"]]
              + [_linha_video(n, "SEM LEGENDA", "t-amber", False) for n in est["sem_legenda"]]
              + [_linha_video(n, "AGENDADO SEM VÍDEO", "t-err", False) for n in est["pendentes_sem_video"]])

    ded = d.get("dedicados", {})
    ded_html = ""
    for conta, itens in ded.items():
        lin = "".join(
            f'<tr data-busca="{esc(i["arquivo"])} {esc(conta)}"><td>{esc(i["arquivo"])}</td>'
            f'<td><span class="tag {"t-ok" if i["com_legenda"] else "t-amber"}">{"PRONTO" if i["com_legenda"] else "SEM LEGENDA"}</span></td>'
            f'<td style="text-align:right">{_menu(_mi_bt("Devolver à geral", "devolver_video", {"arquivo": i["arquivo"], "conta": conta}))}</td></tr>'
            for i in itens)
        ded_html += (f'<div class="card"><h3 title="só @{esc(conta)} recebe estes vídeos">Dedicados a @{esc(conta)} ({len(itens)})</h3>'
                     f'<table><thead><tr><th>Arquivo</th><th>Estado</th><th></th></tr></thead>'
                     f'<tbody>{lin}</tbody></table></div>')

    return f'''
    <h1>Biblioteca</h1>
    <div class="sub">{len(est["prontos"])} pronto(s) · {len(est["sem_legenda"])} sem legenda · {esc(d["buffer"]["frase"])}</div>
    <input class="busca" placeholder="Buscar" oninput="filtrar(this, 'tab-bib')">
    <form id="distrib" method="post" action="/acao/distribuir_videos" class="distrib">
      <b>Distribuir marcados</b>
      {"".join(f'<label class="chip"><input type="checkbox" name="contas" value="{esc(c)}"> @{esc(c)}</label>' for c in d["cfg"].get("contas_agendamento", []) if c not in d["cfg"].get("contas_pausadas", []))}
      <button class="acao" type="submit">Distribuir</button>
      <span class="distrib-dica">marca os vídeos ↓, escolhe a(s) conta(s) — o robô espalha nos próximos horários livres</span>
    </form>
    <div class="card"><h3>Geral</h3>
    <table id="tab-bib"><thead><tr><th></th><th>Arquivo</th><th>Estado</th><th></th><th></th></tr></thead>
    <tbody>{"".join(linhas) or '<tr><td colspan="5" class="vazio">biblioteca vazia — solte vídeo+legenda em videos/</td></tr>'}</tbody></table></div>
    {ded_html}'''


def _v_automacao(d: dict) -> str:
    cfg = d["cfg"]
    pausado = d["estado"].get("pausado")
    aq = cfg.get("aquecimento", {})
    regras = [
        ("max_posts_dia", "Posts por conta/dia", cfg.get("max_posts_dia")),
        ("intervalo_minimo_min", "Intervalo mínimo (min)", cfg.get("intervalo_minimo_min")),
        ("espacamento_entre_posts_min", "Espaçamento entre posts (min)", cfg.get("espacamento_entre_posts_min")),
        ("max_carrosseis_dia", "Carrosséis por conta/dia", cfg.get("max_carrosseis_dia", 1)),
        ("jitter_max_min", "Variação de horário (min)", cfg.get("jitter_max_min")),
        ("max_atraso_horas", "Atraso máx. antes de vencer (h)", cfg.get("max_atraso_horas")),
        ("bateria_minima", "Bateria mínima (%)", cfg.get("bateria_minima")),
    ]
    linhas = "".join(
        f'<tr><td>{rot}</td><td><form method="post" action="/acao/editar_regra">'
        f'<input type="hidden" name="nome" value="{n}">'
        f'<input class="mono" name="valor" value="{esc(v)}">'
        f'<button class="mini v" type="submit">Salvar</button></form></td></tr>'
        for n, rot, v in regras)
    janela = f'{cfg.get("janela_inicio", "")}-{cfg.get("janela_fim", "")}'
    ovs = cfg.get("overrides_conta", {})
    ovs_html = "".join(
        f'<div>@{esc(c)} → <b>{esc(o.get("max_posts_dia"))}/dia</b> '
        + _bt("limpar", "override_conta", {"conta": c, "max_posts_dia": ""}, "mini") + "</div>"
        for c, o in ovs.items()) or '<div class="vazio">nenhuma conta com regra própria — todas herdam o global</div>'
    return f'''
    <h1>Automação</h1>
    <div class="sub">estado: <b>{"PAUSADA" if pausado else "ATIVA"}</b>{f' — {esc(d["estado"].get("motivo_pausa", ""))}' if pausado else ""}</div>
    <div style="margin-bottom:16px">
      {_bt("Retomar tudo", "pausar_tudo", {"pausar": "0"}, "acao") if pausado else _bt("Pausar tudo", "pausar_tudo", {"pausar": "1"}, "acao vermelho", "Pausar TODA a operação?")}
    </div>
    <div class="duas">
      <div class="card regras"><h3>Regras globais</h3><table><tbody>{linhas}
        <tr><td>Janela de postagem</td><td><form method="post" action="/acao/editar_regra">
        <input type="hidden" name="nome" value="janela">
        <input class="mono" name="valor" value="{esc(janela)}" placeholder="09:00-21:00">
        <button class="mini v" type="submit">Salvar</button></form></td></tr>
      </tbody></table></div>
      <div>
        <div class="card"><h3>Overrides por conta</h3>{ovs_html}
        <form method="post" action="/acao/override_conta" style="display:flex;gap:8px;margin-top:10px">
          <input name="conta" placeholder="conta" required>
          <input name="max_posts_dia" placeholder="posts/dia" size="7" required>
          <button class="mini v" type="submit">Criar</button></form></div>
        <div class="card"><h3>Aquecimento</h3>
          <div style="font-size:13px;color:var(--sec);margin-bottom:10px">Manual — roda só quando você apertar ·
          {", ".join("@" + esc(c) for c in aq.get("contas", [])) or "—"} ·
          {esc(aq.get("min_reels"))}–{esc(aq.get("max_reels"))} reels por sessão</div>
          {_bt("Aquecer pendente…", "aquecer_agora", {}, "acao") if d["estado"].get("aquecer_pedido") else _bt("Aquecer agora", "aquecer_agora", {}, "acao")}</div>
      </div>
    </div>'''


def _v_conectar(d: dict) -> str:
    return f'''
    <h1>Conectar aparelho</h1>
    <div class="sub">colocar um celular novo na frota</div>
    <div class="card">
      <ol style="margin-left:18px;color:var(--sec)">
        <li style="margin:6px 0">Ligue a <b>Depuração USB</b> (7 toques em "Número da versão" → Opções do desenvolvedor).</li>
        <li style="margin:6px 0">Plugue o cabo e marque <b>"Sempre permitir"</b>.</li>
        <li style="margin:6px 0">Clique aqui: {_bt("Testar conexão agora", "testar_conexao", {}, "mini v")}</li>
        <li style="margin:6px 0">Deu verde? O modo sem fio arma sozinho na próxima plugada (cabo vira só carregador).</li>
      </ol>
    </div>'''


def render(d: dict, msg: str = "") -> str:
    menu = "".join(
        f'<div class="mi{" on" if chave == "visao" else ""}" data-v="{chave}">{_I[chave]}<span>{rotulo}</span></div>'
        for chave, rotulo in MENU)
    views = (
        f'<section class="view on" data-view="visao">{_v_visao(d)}</section>'
        f'<section class="view" data-view="aparelhos">{_v_aparelhos(d)}</section>'
        f'<section class="view" data-view="contas">{_v_contas(d)}</section>'
        f'<section class="view" data-view="posts">{_v_posts(d)}</section>'
        f'<section class="view" data-view="biblioteca">{_v_biblioteca(d)}</section>'
        f'<section class="view" data-view="automacao">{_v_automacao(d)}</section>'
        f'<section class="view" data-view="conectar">{_v_conectar(d)}</section>')
    return f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Myriad</title>
<link rel="icon" href="data:image/svg+xml,{LOGO.replace('#', '%23').replace('"', "'")}">
<style>{CSS}</style></head><body>
<nav class="side">
  <div class="brand">{LOGO}<b>Myriad</b></div>
  {menu}
  <div class="plats">
    <div class="ok">{IG} Instagram — ATIVO</div>
    <div class="breve">{TIKTOK} TikTok — em breve</div>
    <div class="breve">{YT} YouTube — em breve</div>
    <div class="breve">{FB} Facebook — em breve</div>
  </div>
</nav>
<main>{views}</main>
<div id="toast">{esc(msg)}</div>
<script>
// Toda ação VOLTA pra view onde nasceu (18/09 — o 303 ia pra /?msg sem o
// hash e o painel pulava pra Visão Geral a cada clique; era a sensação de
// "todos os botões bugados"). O form ganha um hidden com a view atual e o
// servidor devolve o Location com o hash.
document.addEventListener("submit", function(e) {{
  var f = e.target;
  if (!f || String(f.method).toLowerCase() !== "post") return;
  if (!f.querySelector('input[name="volta"]')) {{
    var i = document.createElement("input");
    i.type = "hidden"; i.name = "volta";
    i.value = (location.hash || "#visao").slice(1);
    f.appendChild(i);
  }}
}}, true);
document.querySelectorAll(".mi").forEach(function(m){{
  m.addEventListener("click", function(){{
    document.querySelectorAll(".mi").forEach(function(x){{x.classList.remove("on");}});
    document.querySelectorAll(".view").forEach(function(v){{v.classList.remove("on");}});
    m.classList.add("on");
    document.querySelector('.view[data-view="'+m.dataset.v+'"]').classList.add("on");
    history.replaceState(null, "", "#" + m.dataset.v);
  }});
}});
if (location.hash) {{
  var alvo = document.querySelector('.mi[data-v="'+location.hash.slice(1)+'"]');
  if (alvo) alvo.click();
}}
window.filtrar = function(inp, tabela) {{
  var q = inp.value.toLowerCase();
  document.querySelectorAll("#" + tabela + " tbody tr").forEach(function(tr) {{
    var t = (tr.dataset.busca || tr.textContent).toLowerCase();
    tr.style.display = t.indexOf(q) >= 0 ? "" : "none";
  }});
}};
window.abaPosts = function(btn, st) {{
  document.querySelectorAll(".aba").forEach(function(a){{a.classList.remove("on");}});
  btn.classList.add("on");
  document.querySelectorAll("#tab-posts tbody tr").forEach(function(tr) {{
    tr.style.display = (st === "todos" || tr.dataset.st === st) ? "" : "none";
  }});
}};
var toast = document.getElementById("toast");
if (toast.textContent.trim()) {{
  toast.style.display = "block";
  // erro (⚠) fica MUITO mais tempo na tela: aviso de 6s passava batido
  var dura = toast.textContent.indexOf("⚠") >= 0 ? 20000 : 6000;
  setTimeout(function(){{ toast.style.display = "none";
    history.replaceState(null, "", location.pathname + location.hash); }}, dura);
}}
document.addEventListener("click", function(e) {{
  document.querySelectorAll("details.menu[open]").forEach(function(m) {{
    if (!m.contains(e.target)) m.removeAttribute("open");
  }});
}});
if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {{
  document.querySelectorAll(".tile .v[data-n]").forEach(function(el) {{
    var alvo = parseInt(el.dataset.n, 10);
    if (isNaN(alvo) || alvo <= 0) return;
    var t0 = performance.now(), dur = 650;
    function passo(t) {{
      var p = Math.min((t - t0) / dur, 1);
      el.textContent = Math.round(alvo * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(passo);
    }}
    requestAnimationFrame(passo);
  }});
}}
// o reload volta pro MESMO lugar (view via hash + scroll via sessionStorage)
try {{
  var sy = sessionStorage.getItem("my_scroll");
  if (sy !== null) {{ window.scrollTo(0, parseInt(sy, 10) || 0); sessionStorage.removeItem("my_scroll"); }}
}} catch (e) {{}}
setInterval(function() {{
  // NUNCA recarrega com seleção em andamento (checkbox marcado comia a
  // distribuição em massa do operador — 15/09), menu aberto ou campo em foco
  var ocupado = document.querySelector("details.menu[open]") ||
    document.querySelector(".marca:checked") ||
    (document.activeElement && /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName));
  if (!ocupado) {{
    try {{ sessionStorage.setItem("my_scroll", String(window.scrollY)); }} catch (e) {{}}
    location.reload();
  }}
}}, 45000);
</script>
</body></html>"""


# ---------- servidor ----------

ACOES = {
    "pausar_conta": lambda c: acoes.pausar_conta(c["conta"]),
    "retomar_conta": lambda c: acoes.retomar_conta(c["conta"]),
    "rodizio": lambda c: acoes.rodizio(c["conta"], c.get("entrar") == "1"),
    "remover_conta": lambda c: acoes.remover_conta(c["conta"]),
    "override_conta": lambda c: acoes.override_conta(
        c["conta"], int(c["max_posts_dia"]) if c.get("max_posts_dia", "").strip() else None),
    "publicar_agora": lambda c: acoes.publicar_agora(c["conta"], c["arquivo"]),
    "reagendar": lambda c: acoes.reagendar(c["conta"], c["arquivo"], c["quando"]),
    "cancelar_post": lambda c: acoes.cancelar_post(c["conta"], c["arquivo"]),
    "tentar_de_novo": lambda c: acoes.tentar_de_novo(c["conta"], c["arquivo"]),
    "remover_post": lambda c: acoes.remover_post(c["conta"], c["arquivo"]),
    "agendar_video": lambda c: acoes.agendar_video(c["arquivo"], c["conta"], c["quando"]),
    "excluir_video": lambda c: acoes.excluir_video(c["arquivo"]),
    "dedicar_video": lambda c: acoes.dedicar_video(c["arquivo"], c["conta"]),
    "devolver_video": lambda c: acoes.devolver_video(c["arquivo"], c["conta"]),
    "editar_regra": lambda c: acoes.editar_regra(c["nome"], c["valor"]),
    "pausar_tudo": lambda c: acoes.pausar_tudo(c.get("pausar") == "1"),
    "reiniciar_ig": lambda c: acoes.reiniciar_instagram(),
    "testar_conexao": lambda c: acoes.testar_conexao(),
    "aquecer_agora": lambda c: acoes.aquecer_agora(),
    "distribuir_videos": lambda c: acoes.distribuir_videos(
        c.get("arquivos", "").split("\n"), c.get("contas", "").split("\n")),
}


def montar() -> dict:
    d = coletar()
    cfg = d["cfg"]
    ativas = [c for c in cfg.get("contas_agendamento", [])
              if c not in cfg.get("contas_pausadas", [])]
    d["n_contas_ativas"] = len(ativas)
    # online do APARELHO = conexão real e fresca — nunca o heartbeat do robô
    # (vistoria 14/09: o painel dizia ONLINE com o celular fora há 2 dias)
    d["n_online"] = 1 if dados.conexao_fresca(d["conexao"], d["agora"]) else 0
    d["buffer"] = dados.buffer_conteudo(len(d["estoque"]["prontos"]), cfg, len(ativas))
    d["eg"] = dados.estado_global(d)
    d["agora_ap"] = dados.agora_do_aparelho(d)
    d["saude"] = dados.saude(d)
    # atividade agrupada lê mais fundo que os 16 do coletar() — repetição vira ×N
    log_fundo = dashboard._ler_csv(dashboard.ARQ_LOG)[-250:][::-1]
    d["atividade"] = dados.agrupar_atividade(log_fundo)
    d["dedicados"] = acoes.estoque_dedicado(cfg.get("contas_agendamento", []) + cfg.get("contas_pausadas", []))
    return d


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        rota = self.path.split("#")[0]
        caminho = rota.split("?")[0]
        if caminho not in ("/", "/index.html"):
            self.send_response(404); self.end_headers(); return
        q = urllib.parse.parse_qs(urllib.parse.urlparse(rota).query)
        msg = (q.get("msg") or [""])[0]
        try:
            corpo = render(montar(), msg).encode("utf-8")
        except Exception as e:
            corpo = f"<pre>Erro ao montar o Myriad: {esc(e)}</pre>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        try:
            tam = int(self.headers.get("Content-Length") or 0)
            corpo = self.rfile.read(tam).decode("utf-8") if tam else ""
            # campo repetido (checkboxes da distribuição em massa) chega
            # como lista: vira UMA string separada por \n — ações antigas
            # (sempre valor único) não mudam nada
            campos = {k: (v[0] if len(v) == 1 else "\n".join(v))
                      for k, v in urllib.parse.parse_qs(corpo, keep_blank_values=True).items()}
            nome = self.path.split("/acao/", 1)[1] if self.path.startswith("/acao/") else ""
            # os "…prompt" pedem o dado que falta na própria página seguinte
            if nome == "reagendar_prompt":
                campos["quando"] = campos.get("quando") or ""
                if not campos["quando"]:
                    self._html_prompt_reagendar(campos); return
                nome = "reagendar"
            if nome == "override_prompt":
                self._html_prompt_override(campos); return
            fn = ACOES.get(nome)
            if not fn:
                msg = f"Ação desconhecida: {nome}"
            else:
                try:
                    msg = fn(campos)
                except acoes.AcaoInvalida as e:
                    msg = f"⚠ {e}"
                    acoes.logar("ACAO_RECUSADA", detalhe=f"{nome}: {e}"[:200])
                except Exception as e:
                    msg = f"⚠ Não deu: {str(e)[:140]}"
                    acoes.logar("ACAO_FALHOU", detalhe=f"{nome}: {e}"[:200])
        except Exception as e:
            msg = f"⚠ Erro: {str(e)[:140]}"
        volta = ""
        try:
            v = campos.get("volta", "")
            if re.fullmatch(r"[a-z]+", v or ""):
                volta = "#" + v
        except Exception:
            pass
        self.send_response(303)
        self.send_header("Location", _redir_msg(msg) + volta)
        self.end_headers()

    def _pagina_simples(self, corpo: str) -> None:
        html = (f"<!doctype html><html><head><meta charset='utf-8'><title>Myriad</title>"
                f"<style>{CSS}</style></head><body><main style='max-width:520px;margin:60px auto'>"
                f"<div class='card'>{corpo}</div></main></body></html>")
        b = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _html_prompt_reagendar(self, campos: dict) -> None:
        self._pagina_simples(
            f"<h3 style='margin-bottom:12px'>Reagendar {esc(campos.get('arquivo'))}</h3>"
            f"<form method='post' action='/acao/reagendar_prompt'>"
            f"<input type='hidden' name='conta' value='{esc(campos.get('conta'))}'>"
            f"<input type='hidden' name='arquivo' value='{esc(campos.get('arquivo'))}'>"
            f"<input type='hidden' name='volta' value='{esc(campos.get('volta') or 'posts')}'>"
            f"<input class='mono' name='quando' value='{datetime.now():%Y-%m-%d %H:%M}' size='17'> "
            f"<button class='acao' type='submit'>Reagendar</button> "
            f"<a class='mini' href='/#posts'>voltar</a></form>")

    def _html_prompt_override(self, campos: dict) -> None:
        self._pagina_simples(
            f"<h3 style='margin-bottom:12px'>Limite próprio de @{esc(campos.get('conta'))}</h3>"
            f"<form method='post' action='/acao/override_conta'>"
            f"<input type='hidden' name='conta' value='{esc(campos.get('conta'))}'>"
            f"<input type='hidden' name='volta' value='{esc(campos.get('volta') or 'contas')}'>"
            f"<input class='mono' name='max_posts_dia' placeholder='posts/dia (vazio = herdar global)' size='24'> "
            f"<button class='acao' type='submit'>Salvar</button> "
            f"<a class='mini' href='/#contas'>voltar</a></form>")

    def log_message(self, *a):
        pass


def main() -> None:
    url = f"http://127.0.0.1:{PORTA}"
    print(f"Myriad no ar: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    ThreadingHTTPServer(("127.0.0.1", PORTA), Handler).serve_forever()


if __name__ == "__main__":
    main()
