# -*- coding: utf-8 -*-
"""
As AÇÕES do Myriad — o que transforma o painel de leitura em central de
comando (spec 14/09: "se eu vejo, eu administro dali").

Toda escrita da fila passa pelo lock painel↔robô do postador
(fila_travada + merge por linha do lado do motor). Toda ação devolve uma
frase humana pro toast do painel; erro vira frase também, nunca stack.
Ações destrutivas NÃO confirmam aqui — a confirmação é da UI.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import postador
from postador import (ARQ_FILA, PASTA_VIDEOS, carregar_config, fila_travada,
                      ler_fila, logar, salvar_config, salvar_fila)

FMT = "%Y-%m-%d %H:%M"


class AcaoInvalida(ValueError):
    """Erro com frase leiga — vai direto pro toast."""


# ---------- contas ----------

def pausar_conta(conta: str) -> str:
    cfg = carregar_config()
    pausadas = cfg.setdefault("contas_pausadas", [])
    if conta in pausadas:
        return f"@{conta} já estava pausada."
    pausadas.append(conta)
    salvar_config(cfg)
    logar("CONTA_PAUSADA", detalhe=conta)
    return f"@{conta} pausada — o robô não posta nela até você retomar."


def retomar_conta(conta: str) -> str:
    cfg = carregar_config()
    pausadas = cfg.setdefault("contas_pausadas", [])
    if conta not in pausadas:
        return f"@{conta} já estava ativa."
    pausadas.remove(conta)
    salvar_config(cfg)
    logar("CONTA_RETOMADA", detalhe=conta)
    return f"@{conta} retomada."


def rodizio(conta: str, entrar: bool) -> str:
    """Entrar/sair do rodízio de AGENDAMENTO (diferente de pausar: fora do
    rodízio a conta não ganha posts novos, mas os já agendados seguem)."""
    cfg = carregar_config()
    lista = cfg.setdefault("contas_agendamento", [])
    if entrar:
        if conta in lista:
            return f"@{conta} já estava no rodízio."
        lista.append(conta)
        msg = f"@{conta} entrou no rodízio de agendamento."
    else:
        if conta not in lista:
            return f"@{conta} já estava fora do rodízio."
        lista.remove(conta)
        msg = f"@{conta} saiu do rodízio (posts já agendados continuam)."
    salvar_config(cfg)
    logar("RODIZIO", detalhe=f"{conta} {'entrou' if entrar else 'saiu'}")
    return msg


def remover_conta(conta: str) -> str:
    """Remove a conta da operação: sai do rodízio, sai das pausadas, sai do
    aquecimento e CANCELA os pendentes dela. Histórico (postados) fica."""
    cfg = carregar_config()
    for chave in ("contas_agendamento", "contas_pausadas"):
        if conta in cfg.get(chave, []):
            cfg[chave].remove(conta)
    aq = cfg.get("aquecimento", {})
    if conta in aq.get("contas", []):
        aq["contas"].remove(conta)
    salvar_config(cfg)
    canceladas = 0
    with fila_travada():
        fila = ler_fila()
        for l in fila:
            if l.get("conta") == conta and l.get("status") == "pendente":
                l["status"] = "cancelado"
                l["resultado"] = "conta removida da operação"
                canceladas += 1
        salvar_fila(fila)
    logar("CONTA_REMOVIDA", detalhe=f"{conta} ({canceladas} pendente(s) cancelado(s))")
    return f"@{conta} removida da operação ({canceladas} post(s) pendente(s) cancelado(s); histórico preservado)."


def override_conta(conta: str, max_posts_dia: int | None) -> str:
    """Override por conta do cap diário (hierarquia global → conta).
    None limpa o override (volta a herdar o global)."""
    cfg = carregar_config()
    ov = cfg.setdefault("overrides_conta", {})
    if max_posts_dia is None:
        if conta in ov:
            del ov[conta]
        msg = f"@{conta} voltou a herdar o limite global ({cfg.get('max_posts_dia')}/dia)."
    else:
        if not 1 <= max_posts_dia <= 10:
            raise AcaoInvalida("Limite por dia precisa estar entre 1 e 10.")
        ov[conta] = {"max_posts_dia": max_posts_dia}
        msg = f"@{conta} agora tem limite próprio: {max_posts_dia} post(s)/dia."
    salvar_config(cfg)
    logar("OVERRIDE_CONTA", detalhe=f"{conta} = {max_posts_dia}")
    return msg


# ---------- posts (jobs) ----------

def _achar(fila: list[dict], conta: str, arquivo: str) -> dict:
    for l in fila:
        if l.get("conta") == conta and l.get("arquivo") == arquivo:
            return l
    raise AcaoInvalida(f"Não achei o post {arquivo} de @{conta} na fila.")


def publicar_agora(conta: str, arquivo: str) -> str:
    with fila_travada():
        fila = ler_fila()
        l = _achar(fila, conta, arquivo)
        if l["status"] not in ("pendente", "vencido", "erro", "cancelado"):
            raise AcaoInvalida(f"Esse post está '{l['status']}' — não dá pra publicar agora.")
        l["status"] = "pendente"
        l["quando"] = datetime.now().strftime(FMT)
        l["resultado"] = ""
        salvar_fila(fila)
    logar("PUBLICAR_AGORA", arquivo, conta)
    return f"{arquivo} vai pro próximo ciclo do robô (respeitando intervalo e cap)."


def reagendar(conta: str, arquivo: str, quando: str) -> str:
    try:
        novo = datetime.strptime(quando.strip(), FMT)
    except ValueError:
        raise AcaoInvalida("Data/hora inválida — use AAAA-MM-DD HH:MM.")
    with fila_travada():
        fila = ler_fila()
        l = _achar(fila, conta, arquivo)
        if l["status"] == "postado":
            raise AcaoInvalida("Esse post já foi publicado.")
        l["status"] = "pendente"
        l["quando"] = novo.strftime(FMT)
        l["resultado"] = ""
        salvar_fila(fila)
    logar("REAGENDADO", arquivo, f"{conta} -> {quando}")
    return f"{arquivo} reagendado para {novo:%d/%m %H:%M}."


def cancelar_post(conta: str, arquivo: str) -> str:
    with fila_travada():
        fila = ler_fila()
        l = _achar(fila, conta, arquivo)
        if l["status"] == "postado":
            raise AcaoInvalida("Post já publicado não se cancela — arquive no histórico.")
        l["status"] = "cancelado"
        l["resultado"] = "cancelado pelo painel"
        salvar_fila(fila)
    logar("CANCELADO", arquivo, conta)
    return f"{arquivo} cancelado (o vídeo continua na biblioteca)."


def tentar_de_novo(conta: str, arquivo: str) -> str:
    with fila_travada():
        fila = ler_fila()
        l = _achar(fila, conta, arquivo)
        if l["status"] not in ("erro", "vencido"):
            raise AcaoInvalida(f"Retry é só pra erro/vencido — esse está '{l['status']}'.")
        l["status"] = "pendente"
        l["quando"] = datetime.now().strftime(FMT)
        l["resultado"] = ""
        salvar_fila(fila)
    logar("RETRY", arquivo, conta)
    return f"{arquivo} voltou pra fila — o robô tenta no próximo ciclo."


def remover_post(conta: str, arquivo: str) -> str:
    with fila_travada():
        fila = ler_fila()
        l = _achar(fila, conta, arquivo)
        if l["status"] == "postado":
            raise AcaoInvalida("Publicado fica no histórico — remova só pendente/erro/cancelado.")
        fila.remove(l)
        salvar_fila(fila)
    logar("REMOVIDO_DA_FILA", arquivo, conta)
    return f"{arquivo} removido da fila (o vídeo continua na biblioteca)."


# ---------- biblioteca ----------

def distribuir_videos(arquivos: list[str], contas: list[str]) -> str:
    """Distribuição em massa (o operador 14/09): pega VÁRIOS vídeos prontos da
    biblioteca e espalha pelas contas escolhidas — round-robin entre as
    contas, e dentro de cada conta os próximos slots livres (mesmo motor
    de horários do agendador: teto/dia com override, espaçamento sorteado
    30–90min, janela). Ninguém agenda mais um por um."""
    import agendar
    from datetime import timedelta
    contas = [c.strip() for c in contas if c.strip()]
    arquivos = [a.strip() for a in arquivos if a.strip()]
    if not arquivos:
        raise AcaoInvalida("Marque pelo menos um vídeo.")
    if not contas:
        raise AcaoInvalida("Escolha pelo menos uma conta.")
    cfg = carregar_config()
    pausadas = set(cfg.get("contas_pausadas", []))
    for c in contas:
        if c not in cfg.get("contas_agendamento", []):
            raise AcaoInvalida(f"@{c} não está no rodízio.")
        if c in pausadas:
            raise AcaoInvalida(f"@{c} está pausada — retome antes de distribuir.")
    for a in arquivos:
        if not (PASTA_VIDEOS / a).exists():
            raise AcaoInvalida(f"{a} não está em videos/.")
        if not (PASTA_VIDEOS / (Path(a).stem + ".txt")).exists():
            raise AcaoInvalida(f"{a} está sem legenda (.txt de mesmo nome).")

    por_conta: dict[str, list[str]] = {c: [] for c in contas}
    for i, a in enumerate(arquivos):
        por_conta[contas[i % len(contas)]].append(a)

    agora = datetime.now()
    with fila_travada():
        fila = ler_fila()
        for a in arquivos:
            for l in fila:
                if l.get("arquivo") == a and l.get("status") in ("pendente", "postado"):
                    raise AcaoInvalida(f"{a} já está na fila (@{l.get('conta')}, {l.get('status')}).")
        novas: list[dict] = []
        for conta, lista in por_conta.items():
            if not lista:
                continue
            ov = cfg.get("overrides_conta", {}).get(conta, {})
            teto = int(ov.get("max_posts_dia") or cfg.get("max_posts_dia", 3))
            dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
            i = 0
            while i < len(lista):
                chave = f"{dia:%Y-%m-%d}"
                ja = agendar._agendados_no_dia(fila + novas, conta, chave)
                cabe = max(teto - ja, 0)
                if cabe:
                    minimo = agora if dia.date() == agora.date() else None
                    horas = agendar.horarios_do_dia(dia, ja + cabe, cfg, semente=conta,
                                                    inicio_minimo=minimo)
                    for h in [h for h in horas[ja:] if h > agora]:
                        if i >= len(lista):
                            break
                        novas.append({"conta": conta, "arquivo": lista[i],
                                      "quando": f"{h:%Y-%m-%d %H:%M}", "status": "pendente",
                                      "resultado": "", "postado_em": "", "views": "",
                                      "tipo": "reel"})
                        i += 1
                dia += timedelta(days=1)
        fila.extend(novas)
        salvar_fila(fila)
    logar("DISTRIBUIDO", detalhe=f"{len(arquivos)} video(s) pra {', '.join('@' + c for c in contas)}")
    primeiro = min(l["quando"] for l in novas)
    ultimo = max(l["quando"] for l in novas)
    return (f"{len(arquivos)} vídeo(s) distribuído(s) pra {', '.join('@' + c for c in contas)} — "
            f"do dia {primeiro[5:16]} até {ultimo[5:16]}.")


def agendar_video(arquivo: str, conta: str, quando: str) -> str:
    """Cria um job manual pra um vídeo PRONTO da biblioteca (mp4+legenda),
    no formato que o robô consome."""
    try:
        novo = datetime.strptime(quando.strip(), FMT)
    except ValueError:
        raise AcaoInvalida("Data/hora inválida — use AAAA-MM-DD HH:MM.")
    origem = PASTA_VIDEOS / arquivo
    if not origem.exists():
        origem_fabrica = postador.RAIZ / "fabrica" / "saida" / arquivo
        if origem_fabrica.exists():
            import shutil
            shutil.move(str(origem_fabrica), str(origem))
            legenda_f = origem_fabrica.parent / (origem_fabrica.stem + ".txt")
            if legenda_f.exists():
                shutil.move(str(legenda_f), str(PASTA_VIDEOS / legenda_f.name))
        else:
            raise AcaoInvalida(f"{arquivo} não está em videos/ nem na saída da fábrica.")
    if not (PASTA_VIDEOS / (Path(arquivo).stem + ".txt")).exists():
        raise AcaoInvalida(f"{arquivo} está sem legenda (.txt de mesmo nome).")
    with fila_travada():
        fila = ler_fila()
        for l in fila:
            if l.get("arquivo") == arquivo and l.get("status") in ("pendente", "postado"):
                raise AcaoInvalida(f"{arquivo} já está na fila (@{l.get('conta')}, {l.get('status')}).")
        fila.append({"conta": conta, "arquivo": arquivo, "quando": novo.strftime(FMT),
                     "status": "pendente", "resultado": "", "postado_em": "", "views": "",
                     "tipo": "reel"})
        salvar_fila(fila)
    logar("AGENDADO_PELO_PAINEL", arquivo, f"{conta} {quando}")
    return f"{arquivo} agendado pra @{conta} em {novo:%d/%m %H:%M}."


def dedicar_video(arquivo: str, conta: str) -> str:
    """Dedica um vídeo da biblioteca geral a UMA conta: move mp4+legenda pra
    videos/<conta>/ — dali só o agendador daquela conta o pega (é o fluxo
    que o agendar.bat já usa; o painel só dá o botão)."""
    import shutil
    if not conta.strip():
        raise AcaoInvalida("Escolha a conta.")
    origem = PASTA_VIDEOS / arquivo
    if not origem.exists():
        origem = postador.RAIZ / "fabrica" / "saida" / arquivo
    if not origem.exists():
        raise AcaoInvalida(f"{arquivo} não está na biblioteca.")
    fila = ler_fila()
    for l in fila:
        if l.get("arquivo") == arquivo and l.get("status") == "pendente":
            raise AcaoInvalida(f"{arquivo} já tem post agendado — cancele antes de dedicar.")
    destino = PASTA_VIDEOS / conta
    destino.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino / origem.name))
    legenda = origem.parent / (origem.stem + ".txt")
    tem_legenda = legenda.exists()
    if tem_legenda:
        shutil.move(str(legenda), str(destino / legenda.name))
    logar("VIDEO_DEDICADO", arquivo, conta)
    aviso = "" if tem_legenda else " ⚠ Está sem legenda — o agendador vai pular até você criar o .txt."
    return f"{arquivo} dedicado a @{conta} — o agendar.bat agenda só pra ela.{aviso}"


def devolver_video(arquivo: str, conta: str) -> str:
    """Desfaz a dedicação: volta o vídeo (e a legenda) pra biblioteca geral."""
    import shutil
    origem = PASTA_VIDEOS / conta / arquivo
    if not origem.exists():
        raise AcaoInvalida(f"{arquivo} não está no estoque de @{conta}.")
    shutil.move(str(origem), str(PASTA_VIDEOS / arquivo))
    legenda = origem.parent / (origem.stem + ".txt")
    if legenda.exists():
        shutil.move(str(legenda), str(PASTA_VIDEOS / legenda.name))
    logar("VIDEO_DEVOLVIDO", arquivo, conta)
    return f"{arquivo} voltou pra biblioteca geral."


def estoque_dedicado(contas: list[str]) -> dict[str, list[dict]]:
    """O que cada conta tem guardado em videos/<conta>/ (com ou sem legenda)."""
    saida: dict[str, list[dict]] = {}
    for conta in contas:
        pasta = PASTA_VIDEOS / conta
        if not pasta.is_dir():
            continue
        itens = [{"arquivo": p.name,
                  "com_legenda": (pasta / (p.stem + ".txt")).exists()}
                 for p in sorted(pasta.glob("*.mp4"))]
        if itens:
            saida[conta] = itens
    return saida


def excluir_video(arquivo: str) -> str:
    """Exclui a MÍDIA (não linhas da fila). Recusa se houver job pendente."""
    fila = ler_fila()
    for l in fila:
        if l.get("arquivo") == arquivo and l.get("status") == "pendente":
            raise AcaoInvalida(f"{arquivo} tem post agendado — cancele o post antes de excluir o vídeo.")
    alvo = PASTA_VIDEOS / arquivo
    if not alvo.exists():
        alvo = postador.RAIZ / "fabrica" / "saida" / arquivo
    if not alvo.exists():
        raise AcaoInvalida(f"{arquivo} não encontrado.")
    alvo.unlink()
    legenda = alvo.parent / (alvo.stem + ".txt")
    if legenda.exists():
        legenda.unlink()
    logar("MIDIA_EXCLUIDA", arquivo)
    return f"{arquivo} excluído da biblioteca."


# ---------- automação / regras globais ----------

REGRAS_EDITAVEIS = {
    "max_posts_dia": (int, 1, 10, "posts por conta/dia"),
    "intervalo_minimo_min": (int, 15, 360, "intervalo mínimo (min)"),
    "espacamento_entre_posts_min": (int, 30, 360, "espaçamento entre posts (min)"),
    "max_carrosseis_dia": (int, 0, 4, "carrosséis por conta/dia"),
    "jitter_max_min": (int, 0, 30, "variação de horário (min)"),
    "max_atraso_horas": (int, 1, 24, "atraso máximo antes de vencer (h)"),
    "bateria_minima": (int, 0, 80, "bateria mínima (%)"),
}


def _reespacar_pendentes(cfg: dict) -> int:
    """Regra de ritmo mudou → a fila PENDENTE de reels se reorganiza sozinha
    (o operador 17:46: 'as mudanças que eu faço não acontecem' — ele mudava o
    intervalo e os horários já marcados ficavam velhos). Recascateia por
    conta a partir de agora, com o motor de horários padrão."""
    import agendar
    from datetime import timedelta
    agora = datetime.now()
    n = 0
    with fila_travada():
        fila = ler_fila()
        reels = [l for l in fila if (l.get("tipo") or "reel") == "reel"]
        contas = sorted({l["conta"] for l in reels if l["status"] == "pendente"})
        for conta in contas:
            pend = sorted((l for l in reels if l["status"] == "pendente" and l["conta"] == conta),
                          key=lambda l: (l["quando"], l["arquivo"]))
            fixos = [l for l in reels if l not in pend]      # postados contam pro teto do dia
            ov = cfg.get("overrides_conta", {}).get(conta, {})
            teto = int(ov.get("max_posts_dia") or cfg.get("max_posts_dia", 3))
            dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
            i = 0
            while i < len(pend):
                chave = f"{dia:%Y-%m-%d}"
                ja = agendar._agendados_no_dia(fixos, conta, chave)
                cabe = max(teto - ja, 0)
                if cabe:
                    minimo = agora if dia.date() == agora.date() else None
                    horas = agendar.horarios_do_dia(dia, ja + cabe, cfg, semente=conta,
                                                    inicio_minimo=minimo)
                    for h in [h for h in horas[ja:] if h > agora]:
                        if i >= len(pend):
                            break
                        pend[i]["quando"] = f"{h:%Y-%m-%d %H:%M}"
                        i += 1
                        n += 1
                dia += timedelta(days=1)
        salvar_fila(fila)
    if n:
        logar("REESPACADO", detalhe=f"{n} pendente(s) reorganizados pela regra nova")
    return n


_REGRAS_DE_RITMO = {"intervalo_minimo_min", "espacamento_entre_posts_min",
                    "max_posts_dia", "janela"}


def editar_regra(nome: str, valor: str) -> str:
    if nome == "janela":
        try:
            ini, fim = valor.split("-")
            datetime.strptime(ini.strip(), "%H:%M"); datetime.strptime(fim.strip(), "%H:%M")
        except ValueError:
            raise AcaoInvalida("Janela inválida — use HH:MM-HH:MM.")
        cfg = carregar_config()
        cfg["janela_inicio"], cfg["janela_fim"] = ini.strip(), fim.strip()
        salvar_config(cfg)
        logar("REGRA_EDITADA", detalhe=f"janela = {valor}")
        n = _reespacar_pendentes(cfg)
        extra = f" {n} post(s) pendente(s) reorganizados." if n else ""
        return f"Janela de postagem: {ini.strip()}–{fim.strip()}.{extra}"
    if nome not in REGRAS_EDITAVEIS:
        raise AcaoInvalida(f"Regra desconhecida: {nome}.")
    tipo, minimo, maximo, rotulo = REGRAS_EDITAVEIS[nome]
    try:
        v = tipo(valor)
    except (TypeError, ValueError):
        raise AcaoInvalida(f"Valor inválido pra {rotulo}.")
    if not minimo <= v <= maximo:
        raise AcaoInvalida(f"{rotulo}: use entre {minimo} e {maximo}.")
    cfg = carregar_config()
    cfg[nome] = v
    salvar_config(cfg)
    logar("REGRA_EDITADA", detalhe=f"{nome} = {v}")
    extra = ""
    if nome in _REGRAS_DE_RITMO:
        n = _reespacar_pendentes(cfg)
        extra = f" {n} post(s) pendente(s) reorganizados pelos horários novos." if n else ""
    return f"{rotulo} agora é {v}.{extra}"


def pausar_tudo(pausar: bool) -> str:
    est = postador.carregar_estado()
    est["pausado"] = pausar
    est["motivo_pausa"] = "pausado pelo Myriad" if pausar else ""
    postador.salvar_estado(est)
    logar("AUTOMACAO_PAUSADA" if pausar else "AUTOMACAO_RETOMADA")
    return "Automação pausada — nada posta até você retomar." if pausar else "Automação retomada."


# ---------- aparelho ----------

def reiniciar_instagram() -> str:
    """PEDIDO, não execução direta (18/09): mexer no IG do aparelho a partir
    do painel disputava o adb com o motor e travava tudo. Agora registra o
    pedido; o motor força-stop + reabre o IG entre posts, no próximo ciclo."""
    estado = postador.carregar_estado()
    if estado.get("pausado"):
        raise AcaoInvalida("Operação pausada — retome antes de reiniciar o Instagram.")
    if estado.get("reiniciar_ig_pedido"):
        return "Reinício do Instagram já pedido — o robô executa no próximo ciclo."
    estado["reiniciar_ig_pedido"] = True
    postador.salvar_estado(estado)
    logar("IG_REINICIAR_PEDIDO", detalhe="botão do painel")
    return "Reinício do Instagram pedido — o robô faz isso em até 1 minuto."


def aquecer_agora() -> str:
    """Botão do painel (o operador 14/09: 'só terá aquecimento quando eu apertar').
    Registra o pedido; o motor roda a sessão no ciclo seguinte, com as
    guardas normais (zona morta de post, conexão, bateria)."""
    estado = postador.carregar_estado()
    if estado.get("pausado"):
        raise AcaoInvalida("Operação pausada — retome antes de aquecer.")
    if estado.get("aquecer_pedido"):
        return "Aquecimento já pedido — o robô executa no próximo ciclo."
    estado["aquecer_pedido"] = True
    postador.salvar_estado(estado)
    logar("AQUECIMENTO_PEDIDO", detalhe="botão do painel")
    return "Aquecimento pedido — o robô roda a sessão em até 1 minuto."


def testar_conexao() -> str:
    """SÓ LEITURA e SEM BLOQUEAR (18/09): a versão antiga chamava
    resolver_conexao (re-armava o Wi-Fi, reiniciando o adbd) e o painel
    inteiro travava se o motor estivesse no meio de um post — o adb é
    serializado, e um `shell` de bateria fica minutos na fila atrás do
    upload. Agora: só `adb devices` (rápido, não disputa o aparelho) e a
    bateria vem do último heartbeat que o motor já gravou — nada de mandar
    comando novo pro aparelho ocupado."""
    import conexao
    try:
        devs = conexao.listar_devices(conexao.executar_adb(["devices"], timeout=6))
    except Exception:
        return "⚠ Não consegui falar com o adb agora — tente de novo em instantes."
    serial = conexao.serial_usb(devs) or conexao.serial_wifi(devs)
    if not serial:
        return "Sem conexão: nem USB nem Wi-Fi respondendo. Plugue o cabo uma vez pra armar."
    import json
    from pathlib import Path
    bat = ""
    try:
        arq = Path(__file__).resolve().parent / "logs" / "status_conexao.json"
        cx = json.loads(arq.read_text(encoding="utf-8"))
        if cx.get("bateria") is not None:
            bat = f" · bateria {cx['bateria']}%{' ⚡' if cx.get('carregando') else ''} (último sinal)"
    except Exception:
        pass
    return f"Conectado: {serial}{bat}."
