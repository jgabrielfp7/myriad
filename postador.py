# -*- coding: utf-8 -*-
"""
Postador automático de Reels — exemplo.corp (v1)

O cérebro: lê a fila (fila.csv), respeita os guardrails (cap diário, intervalo
mínimo, kill-switch) e chama o driver que dirige o app real do Instagram.

Uso:
    python postador.py --checar              # testa conexão com o aparelho
    python postador.py --teste ARQUIVO.mp4   # dry-run: percorre o fluxo, NÃO posta
    python postador.py --agora ARQUIVO.mp4   # posta AGORA (ignora a fila)
    python postador.py                       # modo normal: fica rodando e posta pela fila

Fila (fila.csv): arquivo,quando,status,resultado,postado_em
    - arquivo: nome do .mp4 dentro de videos/ (a legenda vem do .txt de mesmo nome)
    - quando:  AAAA-MM-DD HH:MM
    - status:  pendente | postado | erro | cancelado
"""

import argparse
import csv
import json
import random
import sys
import time
from datetime import datetime, date
from pathlib import Path

import driver_instagram as ig
import conexao
import aquecimento

RAIZ = Path(__file__).parent
ARQ_CONFIG = RAIZ / "config.json"
ARQ_FILA = RAIZ / "fila.csv"
ARQ_ESTADO = RAIZ / "estado.json"
ARQ_LOG = RAIZ / "logs" / "log.csv"
PASTA_VIDEOS = RAIZ / "videos"
PASTA_LOGS = RAIZ / "logs"

CAMPOS_FILA = ["conta", "arquivo", "quando", "status", "resultado", "postado_em", "views", "tipo"]
# tipo: "" ou "reel" = Reel (retrocompatível) · "carrossel" = post de fotos
# (arquivo aponta pra pasta de slides em videos/carrosseis/<nome>/)
PASTA_CARROSSEIS = RAIZ / "videos" / "carrosseis"


# ---------- infra ----------

def carregar_config() -> dict:
    return json.loads(ARQ_CONFIG.read_text(encoding="utf-8-sig"))


def salvar_config(cfg: dict) -> None:
    """Grava o config SEM BOM (BOM já derrubou o robô no boot — 2026-08-23)."""
    ARQ_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def resolver_conexao(cfg: dict) -> str | None:
    """Serial efetivo do momento (USB > Wi-Fi > None) + persiste IP novo.

    Persiste SÓ a chave que mudou, sobre o config fresco do disco: gravar o
    dict inteiro da memória já apagou overrides_conta/espacamento escritos
    pelo painel no meio do caminho (clobber de 14/09)."""
    serial, mudou = conexao.garantir_conexao(cfg)
    if mudou:
        try:
            fresco = carregar_config()
        except FileNotFoundError:
            fresco = dict(cfg)
        fresco["ip_aparelho"] = cfg.get("ip_aparelho")
        salvar_config(fresco)
        logar("ARMADO_WIFI", detalhe=f"ip={cfg.get('ip_aparelho')}")
    return serial


def _gravar_status_conexao(serial: str | None, cfg: dict) -> None:
    """Status pro dashboard: modo de conexão + bateria. Nunca derruba o ciclo."""
    try:
        nivel, carregando = None, False
        if serial:
            nivel, carregando = conexao.ler_bateria(serial)
        modo = "sem_conexao" if not serial else ("wifi" if ":" in serial else "usb")
        PASTA_LOGS.mkdir(exist_ok=True)
        (PASTA_LOGS / "status_conexao.json").write_text(json.dumps({
            "ts": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "modo": modo,
            "ip": cfg.get("ip_aparelho"), "bateria": nivel,
            "carregando": carregando}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def carregar_estado() -> dict:
    if ARQ_ESTADO.exists():
        return json.loads(ARQ_ESTADO.read_text(encoding="utf-8-sig"))
    return {"pausado": False, "motivo_pausa": ""}


def salvar_estado(estado: dict) -> None:
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def logar(evento: str, arquivo: str = "", detalhe: str = "") -> None:
    PASTA_LOGS.mkdir(exist_ok=True)
    novo = not ARQ_LOG.exists()
    with open(ARQ_LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["data_hora", "evento", "arquivo", "detalhe"])
        w.writerow([f"{datetime.now():%Y-%m-%d %H:%M:%S}", evento, arquivo, detalhe])
    print(f"[{datetime.now():%H:%M:%S}] {evento} {arquivo} {detalhe}".strip())


def ler_fila() -> list[dict]:
    if not ARQ_FILA.exists():
        return []
    with open(ARQ_FILA, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def salvar_fila(linhas: list[dict]) -> None:
    with open(ARQ_FILA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_FILA)
        w.writeheader()
        w.writerows(linhas)


# ---------- lock da fila (painel Myriad ↔ robô) ----------
# Um post real leva MINUTOS entre ler a fila e salvar. Se o painel mexer na
# fila nesse meio tempo (reagendar, cancelar, publicar agora), um salvar_fila
# cru do robô esmagaria a mudança. Regra desde 14/09: toda escrita da fila é
# ler-modificar-gravar SOB LOCK, e o robô salva por MERGE DE LINHA (só a linha
# que ele processou), nunca despejando a cópia velha inteira.

ARQ_FILA_LOCK = PASTA_LOGS / "fila.lock"


class _FilaTravada:
    def __enter__(self):
        import msvcrt
        PASTA_LOGS.mkdir(exist_ok=True)
        self._f = open(ARQ_FILA_LOCK, "a+")
        inicio = time.time()
        while True:
            try:
                msvcrt.locking(self._f.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                if time.time() - inicio > 10:
                    self._f.close()
                    raise TimeoutError("fila ocupada por outro processo")
                time.sleep(0.2)

    def __exit__(self, *exc):
        import msvcrt
        try:
            self._f.seek(0)
            msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._f.close()
        return False


def fila_travada() -> _FilaTravada:
    return _FilaTravada()


def atualizar_linha_fila(linha: dict) -> None:
    """Salva SÓ esta linha: relê a fila do disco sob lock e aplica os campos
    da linha por cima da versão de lá (match conta+arquivo — nomes são únicos
    por conta via agendar.nome_no_postador). Linha sumiu (painel removeu) e o
    desfecho importa (postado/erro)? Reanexa: histórico não se perde."""
    with fila_travada():
        fila = ler_fila()
        chave = (linha.get("conta", ""), linha.get("arquivo", ""))
        for l in fila:
            if (l.get("conta", ""), l.get("arquivo", "")) == chave:
                l.update({k: linha.get(k, "") for k in CAMPOS_FILA})
                break
        else:
            if linha.get("status") in ("postado", "erro", "vencido"):
                fila.append({k: linha.get(k, "") for k in CAMPOS_FILA})
        salvar_fila(fila)


def carregar_legenda(nome_video: str) -> str:
    arq = PASTA_VIDEOS / (Path(nome_video).stem + ".txt")
    if not arq.exists():
        raise FileNotFoundError(
            f"Legenda não encontrada: {arq.name} — crie o .txt com o mesmo nome do vídeo")
    return arq.read_text(encoding="utf-8-sig").strip()


# ---------- guardrails ----------

def posts_da_conta_hoje(fila: list[dict], conta: str,
                        tipo: str | None = None) -> list[datetime]:
    """Horários dos posts com sucesso HOJE de uma conta específica, lidos da
    própria fila (postado_em). Guardrails são por conta — cada conta tem seu
    próprio cap e intervalo, então postar em duas contas no mesmo dia é ok.
    tipo=None conta tudo; "reel" só Reels (inclui linhas antigas sem tipo);
    "carrossel" só carrosséis."""
    feitos = []
    for l in fila:
        if tipo is not None:
            t = (l.get("tipo") or "reel").strip() or "reel"
            if t != tipo:
                continue
        if l.get("conta", "").strip() == conta and l["status"] == "postado" and l.get("postado_em"):
            try:
                dt = datetime.strptime(l["postado_em"].strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if dt.date() == date.today():
                feitos.append(dt)
    return feitos


def _eh_erro_conexao(e: BaseException) -> bool:
    """True se a exceção (ou sua causa) for perda de conexão com o aparelho
    (USB caiu, adb não acha o device). Esse caso é RECUPERÁVEL: mantém o vídeo
    na fila pra postar quando reconectar, em vez de descartá-lo."""
    sinais = ("not found", "unable to connect", "cannot connect", "device offline",
              "broken pipe", "connection", "adberror", "httperror",
              "uiautomator2 server", "device '", "closed", "timeout", "refused",
              "sem conexão")
    atual, vistos = e, 0
    while atual is not None and vistos < 8:
        txt = f"{type(atual).__name__} {atual}".lower()
        if any(s in txt for s in sinais):
            return True
        atual = atual.__cause__ or atual.__context__
        vistos += 1
    return False


def pode_postar_agora(cfg: dict, fila: list[dict], conta: str, agora: datetime | None = None) -> tuple[bool, str]:
    """Guardrails POR CONTA: cap diário e intervalo mínimo contam só os posts
    daquela conta. Assim as duas contas podem postar no mesmo dia sem uma
    estourar o limite da outra."""
    reels = posts_da_conta_hoje(fila, conta, tipo="reel")
    if len(reels) >= cfg["max_posts_dia"]:
        return False, f"cap diário da conta {conta} atingido ({cfg['max_posts_dia']})"
    # intervalo conta SÓ entre reels — o operador 14/09: "entre reels e
    # carrossel não precisa intervalo"
    if reels:
        minutos = ((agora or datetime.now()) - max(reels)).total_seconds() / 60
        if minutos < cfg["intervalo_minimo_min"]:
            return False, (f"intervalo mínimo da conta {conta}: faltam "
                           f"{cfg['intervalo_minimo_min'] - minutos:.0f} min")
    return True, ""


def pode_postar_carrossel(cfg: dict, fila: list[dict], conta: str, agora: datetime | None = None) -> tuple[bool, str]:
    """Cap próprio do carrossel (1/dia por conta, configurável) + intervalo
    mínimo SÓ entre carrosséis (o operador 14/09: reel e carrossel não se bloqueiam)."""
    carrosseis = posts_da_conta_hoje(fila, conta, tipo="carrossel")
    cap = cfg.get("max_carrosseis_dia", 1)
    if len(carrosseis) >= cap:
        return False, f"cap diário de carrossel da conta {conta} atingido ({cap})"
    if carrosseis:
        minutos = ((agora or datetime.now()) - max(carrosseis)).total_seconds() / 60
        if minutos < cfg["intervalo_minimo_min"]:
            return False, (f"intervalo mínimo da conta {conta}: faltam "
                           f"{cfg['intervalo_minimo_min'] - minutos:.0f} min")
    return True, ""


# ---------- núcleo ----------

def executar_carrossel(cfg: dict, nome_pasta: str, conta: str = "",
                       dry_run: bool = False, serial: str | None = None) -> None:
    """Publica um carrossel: a pasta videos/carrosseis/<nome>/ contém os
    slides (slide-01..NN) e a legenda.txt. Mesma semântica do executar_post."""
    pasta = PASTA_CARROSSEIS / nome_pasta
    if not pasta.is_dir():
        raise FileNotFoundError(f"Pasta do carrossel não encontrada: {pasta}")
    legenda_arq = pasta / "legenda.txt"
    legenda = (legenda_arq.read_text(encoding="utf-8-sig").strip()
               if legenda_arq.exists() else "")

    if serial is None:
        serial = resolver_conexao(cfg)
    if serial is None:
        raise RuntimeError("sem conexão com o aparelho — plugue o cabo uma vez")
    d = ig.conectar(serial)
    logar("CONECTADO", detalhe=ig.info_aparelho(d))
    try:
        ig.postar_carrossel(d, serial, pasta, legenda, PASTA_LOGS,
                            conta=conta.strip(), dry_run=dry_run)
    finally:
        ig.apagar_tela(d)


def executar_post(cfg: dict, nome_video: str, conta: str = "",
                  dry_run: bool = False, serial: str | None = None) -> None:
    """Conecta, garante a conta certa, posta (ou dry-run) e loga.
    Levanta exceção em falha/bloqueio."""
    video = PASTA_VIDEOS / nome_video
    if not video.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {video}")
    legenda = carregar_legenda(nome_video)

    if serial is None:
        serial = resolver_conexao(cfg)
    if serial is None:
        raise RuntimeError("sem conexão com o aparelho — plugue o cabo uma vez")
    d = ig.conectar(serial)
    logar("CONECTADO", detalhe=ig.info_aparelho(d))
    try:
        ig.postar_reel(d, serial, video, legenda, PASTA_LOGS,
                       conta=conta.strip(), dry_run=dry_run)
    finally:
        ig.apagar_tela(d)  # tela apagada ao fim do fluxo, com ou sem erro


def processar_fila(cfg: dict, serial: str | None = None) -> None:
    estado = carregar_estado()
    if estado["pausado"]:
        return  # kill-switch ativo: não faz NADA até o o operador destravar

    fila = ler_fila()
    agora = datetime.now()
    for linha in fila:
        if linha["status"] != "pendente":
            continue
        quando = datetime.strptime(linha["quando"].strip(), "%Y-%m-%d %H:%M")
        if agora < quando:
            continue

        # pausa POR CONTA (painel Myriad, 14/09) vem ANTES do relógio de
        # atraso: pausar uma conta congela os posts dela como estão — não
        # pode transformá-los em "vencido" enquanto o dono decide
        if linha.get("conta", "").strip() in cfg.get("contas_pausadas", []):
            continue

        # Guardrail de job zumbi (28/08, aprendido com o reel59): catch-up é
        # pra atraso do MESMO dia (notebook dormiu, rede caiu). Job mais velho
        # que max_atraso_horas NUNCA posta sozinho — vira "vencido" e fica
        # esperando decisão humana (remarcar ou virar estoque).
        max_atraso_h = cfg.get("max_atraso_horas", 6)
        if (agora - quando).total_seconds() > max_atraso_h * 3600:
            linha["status"] = "vencido"
            linha["resultado"] = (f"agendado {linha['quando']}, atraso passou de "
                                  f"{max_atraso_h}h — não posta sem remarcação")
            atualizar_linha_fila(linha)
            logar("VENCIDO", linha["arquivo"],
                  f"atraso > {max_atraso_h}h — precisa de remarcação humana")
            continue

        conta = linha.get("conta", "").strip()
        tipo = (linha.get("tipo") or "reel").strip() or "reel"
        # hierarquia de regra (Myriad 14/09): global → override da conta
        ov = cfg.get("overrides_conta", {}).get(conta, {})
        cfg_conta = {**cfg, **ov} if ov else cfg
        if tipo == "carrossel":
            ok, motivo = pode_postar_carrossel(cfg_conta, fila, conta)
        else:
            ok, motivo = pode_postar_agora(cfg_conta, fila, conta)
        if not ok:
            logar("ADIADO", linha["arquivo"], motivo)
            continue

        # Mídia ainda não está na pasta (fila montada antes dos arquivos):
        # não é erro — mantém pendente e tenta de novo quando chegar.
        if tipo == "carrossel":
            if not (PASTA_CARROSSEIS / linha["arquivo"]).is_dir():
                logar("ADIADO", linha["arquivo"],
                      "pasta do carrossel ainda não está em videos/carrosseis/")
                continue
        elif not (PASTA_VIDEOS / linha["arquivo"]).exists():
            logar("ADIADO", linha["arquivo"], "vídeo ainda não está em videos/")
            continue

        # Modo sem fio: sem conexão nenhuma, ADIA (retenta a cada ciclo).
        if serial is None:
            serial = resolver_conexao(cfg)
        if serial is None:
            logar("ADIADO", linha["arquivo"],
                  "sem conexão com o aparelho — plugue o cabo uma vez")
            continue

        # Guardrail de bateria: desplugado e abaixo do mínimo, ADIA.
        nivel, carregando = conexao.ler_bateria(serial)
        ok_bat, motivo_bat = conexao.bateria_ok(
            nivel, carregando, cfg.get("bateria_minima", 20))
        if not ok_bat:
            logar("ADIADO", linha["arquivo"], motivo_bat)
            continue

        # jitter: espera aleatória curta pra não postar sempre no segundo exato
        jitter = random.randint(0, cfg.get("jitter_max_min", 7) * 60)
        if jitter:
            logar("AGUARDANDO_JITTER", linha["arquivo"], f"{jitter // 60} min")
            time.sleep(jitter)

        try:
            if tipo == "carrossel":
                executar_carrossel(cfg, linha["arquivo"], conta=conta, serial=serial)
            else:
                executar_post(cfg, linha["arquivo"], conta=conta, serial=serial)
            linha["status"] = "postado"
            linha["postado_em"] = f"{datetime.now():%Y-%m-%d %H:%M}"
            linha["resultado"] = "ok"
            logar("POSTADO", linha["arquivo"], f"conta={conta} tipo={tipo}")
        except ig.BloqueioDetectado as e:
            linha["status"] = "erro"
            linha["resultado"] = str(e)
            estado.update(pausado=True,
                          motivo_pausa=f"{datetime.now():%Y-%m-%d %H:%M} — {e}")
            salvar_estado(estado)
            logar("KILL_SWITCH", linha["arquivo"], str(e))
            print("\n" + "=" * 60)
            print("🛑 KILL-SWITCH: o Instagram mostrou aviso de restrição.")
            print("   TUDO pausado. Veja o screenshot em logs/ e fale com o Claude.")
            print("   Para destravar depois: apague o estado.json.")
            print("=" * 60 + "\n")
        except Exception as e:
            if _eh_erro_conexao(e):
                # Queda de conexão: NÃO perde o vídeo — mantém pendente e
                # tenta de novo no próximo ciclo (quando o USB voltar).
                linha["resultado"] = f"conexao caiu, vai reintentar: {str(e)[:120]}"
                logar("RETENTATIVA", linha["arquivo"],
                      "sem conexao com o aparelho — mantido na fila p/ catch-up")
            else:
                linha["status"] = "erro"
                linha["resultado"] = str(e)[:200]
                logar("ERRO", linha["arquivo"], str(e)[:200])
        finally:
            # merge por linha: o post levou minutos e o painel pode ter
            # mexido na fila nesse meio tempo — só ESTA linha é nossa
            atualizar_linha_fila(linha)

        break  # no máximo 1 post por ciclo — cadência humana


def _slots_pendentes(fila: list[dict]) -> list[datetime]:
    out = []
    for l in fila:
        if l["status"] != "pendente":
            continue
        try:
            out.append(datetime.strptime(l["quando"].strip(), "%Y-%m-%d %H:%M"))
        except ValueError:
            continue
    return out


def _aquecer_sob_demanda(cfg: dict, serial: str | None) -> bool:
    """Sessão única pedida pelo botão do painel (o operador 14/09: aquecimento só
    quando ele apertar). Mesmas guardas do automático: zona morta de post,
    conexão, bateria. Retorna True quando o pedido foi CONSUMIDO (sessão
    rodou ou falhou de vez); False = adiado, tenta no próximo ciclo."""
    aq = aquecimento.cfg_aquecimento(cfg)
    conta = (aq["contas"] or ["exemplo.group"])[0]
    agora = datetime.now()
    slots = _slots_pendentes(ler_fila())
    if any(abs((agora - sl).total_seconds()) < aquecimento.EXCLUSAO_POST_MIN * 60
           for sl in slots):
        logar("AQUECIMENTO_ADIADO", conta, "pedido do painel: post a menos de 20 min")
        return False
    if serial is None:
        serial = resolver_conexao(cfg)
    if serial is None:
        logar("AQUECIMENTO_ADIADO", conta, "pedido do painel: sem conexão")
        return False
    nivel, carregando = conexao.ler_bateria(serial)
    ok_bat, motivo_bat = conexao.bateria_ok(
        nivel, carregando, cfg.get("bateria_minima", 20))
    if not ok_bat:
        logar("AQUECIMENTO_ADIADO", conta, f"pedido do painel: {motivo_bat}")
        return False
    try:
        d = ig.conectar(serial)
        try:
            stats = aquecimento.sessao(d, conta, aq, PASTA_LOGS)
        finally:
            ig.apagar_tela(d)
        logar("AQUECEU", conta,
              f"pedido do painel: {stats['reels']} reels / {stats['curtidas']} curtidas")
    except ig.BloqueioDetectado as e:
        estado = carregar_estado()
        estado.update(pausado=True,
                      motivo_pausa=f"{datetime.now():%Y-%m-%d %H:%M} — {e}")
        salvar_estado(estado)
        logar("KILL_SWITCH", conta, f"no aquecimento: {e}")
    except Exception as e:
        if _eh_erro_conexao(e):
            logar("AQUECIMENTO_ADIADO", conta,
                  f"pedido do painel: conexao caiu: {str(e)[:100]}")
            return False
        logar("AQUECIMENTO_ERRO", conta, str(e)[:200])
    return True


def processar_aquecimento(cfg: dict, serial: str | None = None) -> None:
    """Roda no ciclo DEPOIS da fila (post tem prioridade). Executa no máximo
    1 sessão de aquecimento vencida por ciclo, com as mesmas guardas dos
    posts (pausa, conexão, bateria) + zona morta de 20 min ao redor de
    qualquer slot pendente. Erro na sessão NÃO retenta no dia (cap 1/dia
    vale até pra falha); queda de conexão retenta no próximo ciclo."""
    estado = carregar_estado()
    if estado["pausado"]:
        return
    # botão "Reiniciar Instagram" do painel: pedido consumido entre posts, no
    # ciclo (o painel NÃO toca o aparelho — o adb é serializado com o motor)
    if estado.get("reiniciar_ig_pedido"):
        if serial:
            try:
                conexao.executar_adb(["-s", serial, "shell", "am", "force-stop", "com.instagram.android"])
                conexao.executar_adb(["-s", serial, "shell", "monkey", "-p", "com.instagram.android", "1"])
                logar("IG_REINICIADO", detalhe=serial)
            except Exception as e:
                logar("IG_REINICIAR_FALHOU", detalhe=str(e)[:120])
            estado = carregar_estado()
            estado.pop("reiniciar_ig_pedido", None)
            salvar_estado(estado)
        return
    # botão "Aquecer agora" do painel: fura o sorteio, roda UMA sessão
    if estado.get("aquecer_pedido"):
        if _aquecer_sob_demanda(cfg, serial):
            estado = carregar_estado()
            estado.pop("aquecer_pedido", None)
            salvar_estado(estado)
        return
    aq = aquecimento.cfg_aquecimento(cfg)
    if not aq["ativo"] or not aq["contas"]:
        return

    fila = ler_fila()
    agora = datetime.now()
    slots = _slots_pendentes(fila)
    plano = aquecimento.plano_do_dia(aq, slots, agora)

    for conta, s in plano["sessoes"].items():
        if s["feito"] is not False:
            continue
        alvo = datetime.strptime(f"{plano['data']} {s['quando']}", "%Y-%m-%d %H:%M")
        if agora < alvo:
            continue
        # a fila pode ter mudado desde o sorteio: re-checa a zona morta agora
        perto = any(abs((agora - sl).total_seconds()) < aquecimento.EXCLUSAO_POST_MIN * 60
                    for sl in slots)
        if perto:
            logar("AQUECIMENTO_ADIADO", conta, "post a menos de 20 min — espera")
            continue
        if serial is None:
            serial = resolver_conexao(cfg)
        if serial is None:
            logar("AQUECIMENTO_ADIADO", conta, "sem conexão com o aparelho")
            continue
        nivel, carregando = conexao.ler_bateria(serial)
        ok_bat, motivo_bat = conexao.bateria_ok(
            nivel, carregando, cfg.get("bateria_minima", 20))
        if not ok_bat:
            logar("AQUECIMENTO_ADIADO", conta, motivo_bat)
            continue

        try:
            d = ig.conectar(serial)
            try:
                stats = aquecimento.sessao(d, conta, aq, PASTA_LOGS)
            finally:
                ig.apagar_tela(d)  # tela apagada mesmo se a sessão falhar
            s.update(feito=True, **stats)
            logar("AQUECEU", conta,
                  f"{stats['reels']} reels / {stats['curtidas']} curtidas")
        except ig.BloqueioDetectado as e:
            s["feito"] = "erro"
            estado = carregar_estado()
            estado.update(pausado=True,
                          motivo_pausa=f"{datetime.now():%Y-%m-%d %H:%M} — {e}")
            salvar_estado(estado)
            logar("KILL_SWITCH", conta, f"no aquecimento: {e}")
        except Exception as e:
            if _eh_erro_conexao(e):
                logar("AQUECIMENTO_ADIADO", conta,
                      f"conexao caiu, retenta no proximo ciclo: {str(e)[:100]}")
            else:
                s["feito"] = "erro"
                logar("AQUECIMENTO_ERRO", conta, str(e)[:200])
        finally:
            aquecimento.salvar_plano(plano)
        break  # no máximo 1 sessão por ciclo


def _bater_ponto() -> None:
    """Escreve um timestamp a cada ciclo — o dashboard usa isso pra saber se
    o postador está rodando ao vivo."""
    try:
        PASTA_LOGS.mkdir(exist_ok=True)
        (PASTA_LOGS / "heartbeat.txt").write_text(
            f"{datetime.now():%Y-%m-%d %H:%M:%S}", encoding="utf-8")
    except Exception:
        pass


def _manter_acordado(ativo: bool) -> None:
    """O loop em si não conta como 'atividade' pro Windows — sem isto o
    notebook dorme por ociosidade e congela o postador no meio do dia."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if ativo else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


_TRAVA_INSTANCIA = None  # handle global: a trava vive enquanto o processo viver


def _garantir_instancia_unica() -> bool:
    """Um postador SÓ. Dois motores já postaram em dupla (14/09: vigia
    relançou o filho enquanto um manual rodava — rascunho perdido + post
    dobrado por pouco). Lock exclusivo em logs/postador.lock: o segundo
    processo desiste na hora, seja manual ou do vigia."""
    global _TRAVA_INSTANCIA
    import msvcrt
    PASTA_LOGS.mkdir(exist_ok=True)
    f = open(PASTA_LOGS / "postador.lock", "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return False
    _TRAVA_INSTANCIA = f
    return True


def modo_normal(cfg: dict) -> None:
    if not _garantir_instancia_unica():
        logar("JA_RODANDO", detalhe="outro postador ativo — este processo desiste")
        print("Já existe um postador rodando. Saindo.")
        return
    logar("INICIADO", detalhe="modo normal — checando a fila a cada minuto")
    print("Postador rodando. Ctrl+C para parar.")
    _manter_acordado(True)
    try:
        while True:
            _bater_ponto()
            try:
                # config fresco POR CICLO: pausas/limites/regras editados no
                # painel valem no minuto seguinte, sem reiniciar o motor
                cfg = carregar_config()
                serial = resolver_conexao(cfg)
                _gravar_status_conexao(serial, cfg)
                processar_fila(cfg, serial)
                processar_aquecimento(cfg, serial)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # falha no ciclo não derruba o loop
                logar("ERRO_CICLO", detalhe=str(e)[:200])
            time.sleep(60)
    finally:
        _manter_acordado(False)


def modo_coletar(cfg: dict) -> None:
    """Lê os views dos Reels já postados (por conta) e grava na coluna `views`
    da fila. Não posta nada — só leitura. Mapeia por ordem: o Reel mais recente
    no perfil = a linha postada mais recente daquela conta."""
    fila = ler_fila()
    serial = resolver_conexao(cfg)
    if serial is None:
        print("❌ Sem conexão: nem USB nem Wi-Fi. Plugue o cabo uma vez pra armar.")
        return
    d = ig.conectar(serial)
    logar("COLETA_INICIO", detalhe=ig.info_aparelho(d))

    por_conta: dict[str, list[dict]] = {}
    for l in fila:
        if l["status"] == "postado":
            por_conta.setdefault(l.get("conta", "").strip(), []).append(l)

    if not por_conta:
        print("Nenhum post concluído ainda pra coletar alcance.")
        return

    for conta, rows in por_conta.items():
        # mais recente primeiro (casa com a ordem do grid de Reels)
        rows_ord = sorted(rows, key=lambda r: r.get("postado_em", ""), reverse=True)
        try:
            views = ig.coletar_views_conta(d, conta, PASTA_LOGS, n=len(rows_ord))
        except Exception as e:
            logar("COLETA_ERRO", conta, str(e)[:150])
            print(f"⚠ {conta}: {str(e)[:120]}")
            continue
        coletadas = 0
        for row, v in zip(rows_ord, views):
            if v is None:
                continue  # miniatura ainda sem contador — não apaga o que há
            row["views"] = str(v)
            coletadas += 1
            logar("VIEWS", row["arquivo"], f"{conta} = {v}")
            atualizar_linha_fila(row)     # merge por linha: coleta longa não esmaga o painel
        print(f"✅ {conta}: {coletadas} contagem(ns) coletada(s) "
              f"({len(views)} miniatura(s) lida(s)).")
    ig.apagar_tela(d)
    print("Coleta de alcance concluída.")


def modo_diag_alcance(cfg: dict, conta: str) -> None:
    """Troca pra conta, abre a aba de Reels do perfil e despeja a tela pra
    calibrar a coleta de views (gera logs/alcance_diag.png/.xml)."""
    serial = resolver_conexao(cfg)
    if serial is None:
        print("❌ Sem conexão: nem USB nem Wi-Fi. Plugue o cabo uma vez pra armar.")
        return
    d = ig.conectar(serial)
    ig.garantir_conta(d, conta, PASTA_LOGS)
    d(resourceId=f"{ig.PACOTE_IG}:id/profile_tab").click()
    time.sleep(3)
    for sel in (d(descriptionContains="Reels"), d(descriptionContains="reels")):
        if sel.exists:
            sel.click(); time.sleep(3); break
    caminho = ig.dump_perfil_reels(d, PASTA_LOGS, "diag")
    print(f"✅ Tela do perfil/reels de {conta} despejada em {caminho} (+ .png)")


def modo_aquecer(cfg: dict, conta: str) -> None:
    """1 sessão de aquecimento agora (calibração/diagnóstico). Ignora o
    horário sorteado mas RESPEITA o cap 1/dia: conta já aquecida hoje recusa."""
    conta = conta.strip().lstrip("@")
    aq = aquecimento.cfg_aquecimento(cfg)
    fila = ler_fila()
    plano = aquecimento.plano_do_dia(aq, _slots_pendentes(fila), datetime.now())
    sessao_plano = plano["sessoes"].get(conta)
    if sessao_plano and sessao_plano["feito"] is not False:
        print(f"❌ {conta} já aqueceu hoje (cap 1/dia). Amanhã tem de novo.")
        return
    serial = resolver_conexao(cfg)
    if serial is None:
        print("❌ Sem conexão com o aparelho.")
        return
    d = ig.conectar(serial)
    print(f"Aquecendo {conta}...")
    stats = aquecimento.sessao(d, conta, aq, PASTA_LOGS)
    if sessao_plano is None:
        sessao_plano = {"quando": f"{datetime.now():%H:%M}", "feito": False,
                        "reels": 0, "curtidas": 0}
        plano["sessoes"][conta] = sessao_plano
    sessao_plano.update(feito=True, **stats)
    aquecimento.salvar_plano(plano)
    logar("AQUECEU", conta, f"{stats['reels']} reels / {stats['curtidas']} curtidas (via --aquecer)")
    print(f"✅ {stats['reels']} reels vistos, {stats['curtidas']} curtida(s).")


def modo_checar(cfg: dict) -> None:
    print("Conectando ao aparelho...")
    serial = resolver_conexao(cfg)
    if serial is None:
        print("❌ Sem conexão: nem USB nem Wi-Fi. Plugue o cabo uma vez pra armar.")
        return
    modo = "Wi-Fi" if ":" in serial else "USB"
    d = ig.conectar(serial)
    nivel, carregando = conexao.ler_bateria(serial)
    bat_txt = "—" if nivel is None else f"{nivel}%"
    print(f"✅ Conectado via {modo}: {ig.info_aparelho(d)} · "
          f"bateria {bat_txt}{' (carregando)' if carregando else ''}")
    apps = d.app_list()
    if ig.PACOTE_IG in apps:
        print("✅ Instagram instalado no aparelho")
    else:
        print("❌ Instagram NÃO encontrado no aparelho — instale e logue a exemplo.corp")
    print(f"Fila: {len([l for l in ler_fila() if l['status'] == 'pendente'])} pendente(s)")
    estado = carregar_estado()
    print(f"Kill-switch: {'🛑 PAUSADO — ' + estado['motivo_pausa'] if estado['pausado'] else 'ok'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Postador automático de Reels (exemplo.corp)")
    p.add_argument("--checar", action="store_true", help="testa a conexão com o aparelho")
    p.add_argument("--teste", metavar="ARQUIVO", help="dry-run: fluxo completo SEM postar")
    p.add_argument("--agora", metavar="ARQUIVO", help="posta o arquivo imediatamente")
    p.add_argument("--conta", metavar="@USUARIO", default="",
                   help="troca pra esta conta antes de postar (usar com --teste/--agora)")
    p.add_argument("--coletar", action="store_true",
                   help="lê os views dos Reels postados e grava na fila (não posta)")
    p.add_argument("--diag-alcance", metavar="@USUARIO", dest="diag_alcance",
                   help="despeja a tela de perfil/reels da conta p/ calibrar a coleta")
    p.add_argument("--aquecer", metavar="@USUARIO",
                   help="roda 1 sessão de aquecimento agora nesta conta (respeita o cap 1/dia)")
    p.add_argument("--teste-carrossel", metavar="PASTA", dest="teste_carrossel",
                   help="dry-run de carrossel: pasta em videos/carrosseis/ (usar com --conta)")
    p.add_argument("--carrossel-agora", metavar="PASTA", dest="carrossel_agora",
                   help="posta o carrossel da pasta imediatamente (usar com --conta)")
    args = p.parse_args()

    cfg = carregar_config()
    if args.checar:
        modo_checar(cfg)
    elif args.coletar:
        modo_coletar(cfg)
    elif args.diag_alcance:
        modo_diag_alcance(cfg, args.diag_alcance)
    elif args.aquecer:
        modo_aquecer(cfg, args.aquecer)
    elif args.teste_carrossel:
        logar("DRY_RUN_INICIO", args.teste_carrossel, f"carrossel conta={args.conta}")
        executar_carrossel(cfg, args.teste_carrossel, conta=args.conta, dry_run=True)
        logar("DRY_RUN_OK", args.teste_carrossel,
              "carrossel: fluxo completo até a legenda — veja o screenshot em logs/")
        print("✅ Dry-run de carrossel concluído SEM postar. Confira o screenshot em logs/.")
    elif args.carrossel_agora:
        executar_carrossel(cfg, args.carrossel_agora, conta=args.conta)
        logar("POSTADO", args.carrossel_agora,
              f"via --carrossel-agora conta={args.conta} tipo=carrossel")
        print("✅ Carrossel postado.")
    elif args.teste:
        logar("DRY_RUN_INICIO", args.teste, f"conta={args.conta}")
        executar_post(cfg, Path(args.teste).name, conta=args.conta, dry_run=True)
        logar("DRY_RUN_OK", args.teste,
              "fluxo completo até a tela de compartilhar — veja o screenshot em logs/")
        print("✅ Dry-run concluído SEM postar. Confira o screenshot em logs/.")
    elif args.agora:
        executar_post(cfg, Path(args.agora).name, conta=args.conta)
        logar("POSTADO", Path(args.agora).name, f"via --agora conta={args.conta}")
        print("✅ Postado.")
    else:
        modo_normal(cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEncerrado pelo operador.")
        sys.exit(0)
