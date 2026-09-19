# -*- coding: utf-8 -*-
"""
Derivações da Visão Geral do Myriad (spec 14/09): estado global, buffer de
conteúdo em DIAS, "agora" por aparelho, saúde por componente e eventos
traduzidos pra gente. Tudo derivado de sinais REAIS — nada de verde
inventado: sem sinal = "sem dados", nunca "ok".
"""
from __future__ import annotations

from datetime import datetime, timedelta

# tradução dos eventos do log.csv pra frase humana (Atividade recente)
EVENTOS_HUMANOS = {
    "POSTADO": ("✅", "Reel publicado"),
    "VIEWS": ("👁", "Views coletadas"),
    "ADIADO": ("⏸", "Post adiado"),
    "VENCIDO": ("⚠", "Post venceu (precisa remarcar)"),
    "ERRO": ("🔴", "Falha ao postar"),
    "RETENTATIVA": ("🔁", "Conexão caiu — vai tentar de novo"),
    "KILL_SWITCH": ("🛑", "Kill-switch: Instagram mostrou restrição"),
    "CONECTADO": ("🔌", "Aparelho conectado"),
    "COLETA_INICIO": ("👁", "Coleta de views iniciada"),
    "COLETA_ERRO": ("⚠", "Falha na coleta de views"),
    "AGUARDANDO_JITTER": ("🕐", "Aguardando variação de horário"),
    "VIGIA_REINICIO": ("🩺", "Robô travado — vigia reiniciou"),
    "CONTA_PAUSADA": ("⏸", "Conta pausada pelo painel"),
    "CONTA_RETOMADA": ("▶", "Conta retomada"),
    "PUBLICAR_AGORA": ("🚀", "Publicação imediata pedida"),
    "REAGENDADO": ("📅", "Post reagendado"),
    "CANCELADO": ("✖", "Post cancelado"),
    "RETRY": ("🔁", "Post devolvido pra fila"),
    "AGENDADO_PELO_PAINEL": ("📅", "Vídeo agendado pelo painel"),
    "MIDIA_EXCLUIDA": ("🗑", "Vídeo excluído da biblioteca"),
    "REGRA_EDITADA": ("⚙", "Regra de automação editada"),
    "AUTOMACAO_PAUSADA": ("⏸", "Automação pausada"),
    "AUTOMACAO_RETOMADA": ("▶", "Automação retomada"),
    "IG_REINICIADO": ("🔄", "Instagram reiniciado no aparelho"),
    "CONTA_REMOVIDA": ("🗑", "Conta removida"),
    "RODIZIO": ("🔀", "Rodízio alterado"),
    "OVERRIDE_CONTA": ("⚙", "Regra da conta ajustada"),
    "REMOVIDO_DA_FILA": ("✖", "Post removido da fila"),
    # eventos do dia a dia real do motor (vistoria 14/09: ERRO_CICLO tinha
    # 5.857 ocorrências despejando comando adb cru na tela)
    "ERRO_CICLO": ("📡", "Robô não alcançou o aparelho — vai tentar de novo"),
    "AQUECIMENTO_ADIADO": ("🔥", "Aquecimento adiado"),
    "AQUECIMENTO_ERRO": ("🔥", "Falha no aquecimento"),
    "AQUECEU": ("🔥", "Sessão de aquecimento feita"),
    "INICIADO": ("▶", "Robô iniciado"),
    "ARMADO_WIFI": ("📶", "Modo sem fio armado"),
    "DRY_RUN_INICIO": ("🧪", "Teste sem postar iniciado"),
    "DRY_RUN_OK": ("🧪", "Teste sem postar concluído"),
    "VIGIA_LANCOU": ("🩺", "Vigia subiu o robô"),
    "VIGIA_RELANCA": ("🩺", "Vigia religou o robô"),
}

_TECNICO = ("adb", "Command", "Traceback", "\\\\", "platform-tools")


def _detalhe_limpo(detalhe: str) -> tuple[str, str]:
    """(resumo humano, técnico completo). Log bruto NUNCA vai pra tela de
    operação — vira tooltip (spec: técnico só sob demanda)."""
    d = (detalhe or "").strip()
    if not d:
        return "", ""
    if any(t in d for t in _TECNICO):
        resumo = "sem resposta do aparelho (timeout)" if "timed out" in d else "detalhe técnico"
        return resumo, d[:400]
    return d[:110], ""


def traduzir_evento(l: dict) -> dict:
    ev = (l.get("evento") or "").strip()
    icone, frase = EVENTOS_HUMANOS.get(ev, ("·", ev.replace("_", " ").capitalize() or "Evento"))
    resumo, tecnico = _detalhe_limpo(l.get("detalhe", ""))
    detalhe = " · ".join(x for x in (l.get("arquivo", ""), resumo) if x)
    return {"quando": l.get("data_hora", ""), "icone": icone, "frase": frase,
            "detalhe": detalhe[:110], "tecnico": tecnico, "bruto": ev}


def agrupar_atividade(log: list[dict], max_itens: int = 12) -> list[dict]:
    """Traduz e AGRUPA repetições consecutivas do mesmo evento (o robô
    tentando reconectar gera dezenas de linhas iguais — vira UMA com ×N).
    Espera o log do mais recente pro mais antigo."""
    saida: list[dict] = []
    for l in log:
        e = traduzir_evento(l)
        if saida and saida[-1]["bruto"] == e["bruto"] and saida[-1]["frase"] == e["frase"]:
            saida[-1]["vezes"] += 1
            saida[-1]["desde"] = e["quando"]      # o mais antigo do grupo
            continue
        e["vezes"] = 1
        e["desde"] = e["quando"]
        saida.append(e)
        if len(saida) > max_itens:
            break
    return saida[:max_itens]


def conexao_fresca(cx: dict, agora: datetime) -> bool:
    """O aparelho está MESMO conectado: modo válido E sinal recente. Sinal
    de 2 dias atrás não é 'online' (vistoria 14/09 pegou o painel mentindo)."""
    if cx.get("modo") in (None, "", "sem_conexao"):
        return False
    try:
        ts = datetime.strptime(cx.get("ts", ""), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return False
    return (agora - ts) < timedelta(minutes=30)


def idade_sinal(cx: dict, agora: datetime) -> str:
    try:
        ts = datetime.strptime(cx.get("ts", ""), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return "nunca"
    s = (agora - ts).total_seconds()
    if s < 90:
        return "agora"
    if s < 3600:
        return f"há {int(s // 60)} min"
    if s < 86400:
        return f"há {int(s // 3600)} h"
    return f"há {int(s // 86400)} dia(s)"


def buffer_conteudo(prontos: int, cfg: dict, contas_ativas: int) -> dict:
    """Buffer em DIAS = vídeos prontos / ritmo diário real (posts/dia por
    conta × contas ativas). Sem contas ativas não existe ritmo — diz isso."""
    ritmo = cfg.get("max_posts_dia", 0) * contas_ativas
    if ritmo <= 0:
        return {"dias": None, "ritmo": 0,
                "frase": "Buffer indisponível — nenhuma conta ativa no rodízio."}
    dias = prontos / ritmo
    tom = "ok" if dias >= 2 else ("atencao" if dias >= 1 else "critico")
    return {"dias": round(dias, 1), "ritmo": ritmo, "tom": tom,
            "frase": f"≈ {dias:.1f} dia(s) de conteúdo no ritmo atual ({ritmo} post(s)/dia)"}


def estado_global(d: dict) -> dict:
    """O topo da Visão Geral: uma frase que resume a operação. A ordem
    importa: falha crítica > pausado > atenção > normal."""
    est = d["estado"]
    motivo = (est.get("motivo_pausa") or "").lower()
    if est.get("pausado") and ("bloque" in motivo or "restri" in motivo or "kill" in motivo):
        return {"tom": "critico", "rotulo": "Falha crítica",
                "frase": "Kill-switch disparado — o Instagram mostrou restrição. Nada posta até você destravar."}
    if est.get("pausado"):
        return {"tom": "pausado", "rotulo": "Operação pausada",
                "frase": est.get("motivo_pausa") or "Pausada pelo painel."}
    atencoes = []
    if d["total_erro"]:
        atencoes.append(f"{d['total_erro']} post(s) com erro")
    vencidos = sum(1 for l in d["fila"] if l.get("status") == "vencido")
    if vencidos:
        atencoes.append(f"{vencidos} vencido(s) esperando remarcação")
    if not d["rodando"]:
        atencoes.append("robô parado (sem heartbeat)")
    if not conexao_fresca(d["conexao"], d["agora"]):
        atencoes.append("aparelho desconectado")
    buf = d.get("buffer") or {}
    if buf.get("tom") == "critico":
        atencoes.append("estoque de conteúdo acabando")
    if atencoes:
        return {"tom": "atencao", "rotulo": "Atenção", "frase": " · ".join(atencoes)}
    return {"tom": "ok", "rotulo": "Operação normal",
            "frase": "Robô de pé, aparelho conectado, fila andando."}


def agora_do_aparelho(d: dict) -> dict:
    """O que o aparelho está fazendo NESTE momento, derivado dos sinais que
    existem (heartbeat + último evento do log + previsão). O motor não emite
    etapa fina ainda — dizemos o que dá pra afirmar, sem inventar."""
    if not conexao_fresca(d["conexao"], d["agora"]):
        sub = ("o robô está de pé tentando reconectar" if d["rodando"]
               else "plugue o cabo uma vez pra armar")
        return {"led": "off", "titulo": "Aparelho desconectado",
                "sub": f"{sub} · último sinal {idade_sinal(d['conexao'], d['agora'])}"}
    if not d["rodando"]:
        return {"led": "off", "titulo": "Robô parado",
                "sub": "sem heartbeat há mais de 2 min e meio"}
    ult = d["log"][0] if d.get("log") else {}
    ev = (ult.get("evento") or "").strip()
    if ev == "AGUARDANDO_JITTER":
        return {"led": "on", "titulo": "Quase postando",
                "sub": f"variação de horário antes de {ult.get('arquivo', '')}"}
    prox = d.get("prox")
    if prox:
        return {"led": "on", "titulo": "Aguardando próximo slot",
                "sub": f"@{prox['conta']} · {prox['arquivo']} ~{prox['previsto']:%H:%M}"}
    return {"led": "on", "titulo": "De vigia",
            "sub": "nada agendado pra agora"}


def saude(d: dict, agora: datetime | None = None) -> list[dict]:
    """Checklist de componentes com sinal REAL. Sem sinal = 'sem dados'."""
    agora = agora or d["agora"]
    itens = []

    def add(nome, ok, frase):
        itens.append({"nome": nome, "estado": ok, "frase": frase})

    add("Robô (worker)", "ok" if d["rodando"] else "erro",
        "heartbeat fresco" if d["rodando"] else "sem heartbeat — rode iniciar.bat")
    cx = d["conexao"]
    ts = cx.get("ts", "")
    fresco = False
    try:
        fresco = (agora - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")) < timedelta(minutes=30)
    except (TypeError, ValueError):
        pass
    if cx.get("modo") not in (None, "sem_conexao"):
        add("Aparelho", "ok" if fresco else "sem_dados",
            f"{cx.get('modo')} · bateria {cx.get('bateria')}%" if fresco
            else "último sinal é antigo — estado incerto")
    else:
        add("Aparelho", "erro", "sem conexão registrada")
    add("Agendador", "ok" if d["total_pend"] else "atencao",
        f"{d['total_pend']} post(s) na fila" if d["total_pend"]
        else "fila vazia — rode agendar.bat ou solte vídeos na biblioteca")
    buf = d.get("buffer") or {}
    add("Estoque", {"ok": "ok", "atencao": "atencao", "critico": "erro"}.get(buf.get("tom"), "sem_dados"),
        buf.get("frase", "sem dados"))
    kill = d["estado"].get("pausado") and "restri" in (d["estado"].get("motivo_pausa") or "").lower()
    add("Instagram", "erro" if kill else ("ok" if d["total_post"] else "sem_dados"),
        "restrição detectada" if kill else
        (f"{d['total_post']} post(s) publicados hoje" if d["total_post"] else "nenhum post hoje ainda"))
    return itens
