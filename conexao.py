# -*- coding: utf-8 -*-
"""Camada de conexão do postador — USB ou ADB por Wi-Fi (modo sem fio).

Regra de ouro: com cabo plugado, USB manda e o Wi-Fi é armado como efeito
colateral (salva o IP atual → funciona em qualquer rede, ex.: casa da avó).
Sem cabo, conecta no IP salvo. Sem nenhum dos dois, o chamador ADIA o post.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time

from driver_instagram import _adb_bin

PORTA_TCP = 5555

_servidor_garantido = False


def _matar_arvore(pid: int) -> None:
    """Mata o processo E os descendentes (taskkill /T). Matar só o filho
    direto deixa o descendente vivo segurando o pipe — a causa do travamento."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def _garantir_servidor_adb(bin_adb: str) -> None:
    """Sobe o daemon do adb com handles em DEVNULL, uma vez por processo.
    Assim, se o daemon (re)nascer, ele NÃO herda o pipe de nenhum comando
    capturado — profilaxia do travamento de pipe herdado."""
    global _servidor_garantido
    if _servidor_garantido:
        return
    _servidor_garantido = True
    try:
        subprocess.run([bin_adb, "start-server"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=20)
    except Exception:
        pass  # o próximo comando tenta de novo do jeito normal


def executar_adb(args: list[str], timeout: int = 30, bin: str | None = None) -> str:
    """Roda o adb e devolve stdout+stderr como texto (o adb mistura os dois).

    NÃO usa subprocess.run(capture_output=...): no Windows, quando um comando
    auto-inicia o daemon do adb, o daemon herda o pipe de stdout e o
    communicate() pós-timeout bloqueia até o daemon morrer — foi isso que
    congelou o postador por 4h09 (24/08) e 1h09 (25/08). Aqui:
      - a leitura do pipe roda numa thread (linha a linha, saída parcial salva);
      - o prazo vale pro PROCESSO: estourou, mata a árvore inteira e levanta;
      - se o processo saiu mas um órfão segura o pipe, devolve o que já foi
        lido na hora, sem matar o órfão (pode ser o próprio daemon do adb).
    """
    bin_adb = bin or _adb_bin()
    if bin is None:
        _garantir_servidor_adb(bin_adb)
    cmd = [bin_adb] + list(args)
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    pedacos: list[str] = []

    def _ler() -> None:
        try:
            for linha in proc.stdout:
                pedacos.append(linha)
        except Exception:
            pass

    leitor = threading.Thread(target=_ler, daemon=True)
    leitor.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _matar_arvore(proc.pid)
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        raise subprocess.TimeoutExpired(cmd, timeout, output="".join(pedacos))
    # Processo saiu. Se o pipe segue aberto por um órfão, não espera por ele:
    # meio segundo de cortesia pro leitor drenar e devolve o que há.
    leitor.join(0.5)
    return "".join(pedacos)


def listar_devices(saida: str) -> list[tuple[str, str]]:
    """Pares (serial, estado) da saída de `adb devices`."""
    devs = []
    for linha in saida.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("List of devices") or linha.startswith("*"):
            continue
        partes = linha.split()
        if len(partes) >= 2:
            devs.append((partes[0], partes[1]))
    return devs


def serial_usb(devs: list[tuple[str, str]]) -> str | None:
    return next((s for s, e in devs if e == "device" and ":" not in s), None)


def serial_wifi(devs: list[tuple[str, str]]) -> str | None:
    return next((s for s, e in devs
                 if e == "device" and s.endswith(f":{PORTA_TCP}")), None)


def extrair_ip(saida_ip_route: str) -> str | None:
    m = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", saida_ip_route)
    return m.group(1) if m else None


def extrair_bateria(saida_dumpsys: str) -> tuple[int | None, bool]:
    m = re.search(r"level:\s*(\d+)", saida_dumpsys)
    nivel = int(m.group(1)) if m else None
    carregando = bool(re.search(
        r"(AC powered: true|USB powered: true|Wireless powered: true)",
        saida_dumpsys))
    return nivel, carregando


def bateria_ok(nivel: int | None, carregando: bool, minimo: int) -> tuple[bool, str]:
    """Sem leitura ou carregando = ok (o guardrail nunca pode travar o dia à toa)."""
    if nivel is None or carregando or nivel >= minimo:
        return True, ""
    return False, f"bateria baixa ({nivel}%) — põe pra carregar"


def ler_bateria(serial: str, executar=executar_adb) -> tuple[int | None, bool]:
    """Nível e estado de carga do aparelho. Falha de leitura vira (None, False):
    o guardrail nunca pode travar o dia por não conseguir LER a bateria."""
    try:
        return extrair_bateria(executar(["-s", serial, "shell", "dumpsys", "battery"]))
    except Exception:
        return None, False


_armados: set[str] = set()  # seriais USB já armados NESTE processo


def armar_sem_fio(serial: str, executar=executar_adb) -> str | None:
    """Arma o modo sem fio numa plugada USB: adbd em modo TCP (porta 5555),
    Doze desativado (senão o Android derruba o Wi-Fi desplugado e parado — e aí
    nem dá pra acordar remoto) e descobre o IP atual. Tudo dura até o próximo
    reinício do aparelho — a plugada seguinte re-arma os três juntos."""
    executar(["-s", serial, "tcpip", str(PORTA_TCP)])
    time.sleep(2)  # o adbd reinicia em modo TCP
    executar(["-s", serial, "shell", "dumpsys", "deviceidle", "disable"])
    return extrair_ip(executar(["-s", serial, "shell", "ip", "route"]))


TENTATIVAS_VOLTA = 6      # ~6s: o adbd reinicia rápido, mas não instantâneo


def _esperar_aparelho(serial: str, alvo_wifi: str, executar, dormir,
                      tentativas: int = TENTATIVAS_VOLTA) -> str | None:
    """Espera o aparelho reaparecer depois do `tcpip` e devolve um serial VIVO.

    `adb tcpip 5555` reinicia o adbd e o serial USB some por alguns segundos.
    Devolver o serial antigo aí é entregar um aparelho que não existe: em
    03/09 a coleta de views falhou nas 5 contas com "device não encontrado",
    todas no mesmo segundo, por causa disto. Preferimos o USB (mais estável);
    se ele não voltar, o endereço Wi-Fi serve.
    """
    for _ in range(tentativas):
        devs = listar_devices(executar(["devices"]))
        vivos = {s for s, e in devs if e == "device"}
        if serial in vivos:
            return serial
        if alvo_wifi and alvo_wifi in vivos:
            return alvo_wifi
        dormir(1)
    # Última cartada: o endereço Wi-Fi só aparece em `devices` depois de um
    # `connect` — esperar por ele sem conectar seria esperar pra sempre.
    if alvo_wifi:
        executar(["connect", alvo_wifi], timeout=10)
        vivos = {s for s, e in listar_devices(executar(["devices"])) if e == "device"}
        if alvo_wifi in vivos:
            return alvo_wifi
    return None


# --- autocura do servidor adb (18/09) -------------------------------------
# Terceiro tipo de falha catalogado: o DAEMON do adb no PC entra em estado
# zumbi ("already connected" com `devices` vazio) enquanto o celular está
# na rede. O remédio, provado na mão em 18/09, é `adb kill-server`. Aqui o
# motor aplica sozinho: N ciclos seguidos sem conexão + porta 5555 do
# aparelho ALCANÇÁVEL (prova de que o problema é local) → reinicia o daemon.
FALHAS_PARA_CURA = 3
CURA_INTERVALO_S = 600          # no máximo 1 cura a cada 10 min (sem loop)
_falhas_seguidas = 0
_ultima_cura = float("-inf")


def porta_alcancavel(ip: str, porta: int = PORTA_TCP, timeout: float = 2.0) -> bool:
    """O aparelho responde na porta do adb? Se sim e o adb local não enxerga,
    o defeito é do servidor adb do PC, não do celular."""
    import socket
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


def _curar_servidor_adb(executar) -> None:
    global _servidor_garantido
    try:
        executar(["kill-server"], timeout=20)
    except Exception:
        pass
    _servidor_garantido = False     # o próximo comando re-sobe o daemon limpo


def garantir_conexao(cfg: dict, executar=executar_adb,
                     dormir=time.sleep, alcancavel=porta_alcancavel,
                     relogio=time.monotonic) -> tuple[str | None, bool]:
    """Resolve o serial efetivo do ciclo: USB manda (e arma o Wi-Fi 1x por
    plugada); senão Wi-Fi pelo IP salvo; senão (None, False) → chamador ADIA.
    Retorna (serial, cfg_mudou) — se mudou, o chamador persiste o config.

    Re-armar em TODA plugada (não só na primeira do processo) é o contrato:
    é assim que o IP é reaprendido numa rede nova (ex.: casa da avó) e que
    tcpip+Doze-disable voltam depois de um reboot do aparelho."""
    global _falhas_seguidas, _ultima_cura
    devs = listar_devices(executar(["devices"]))
    usb = serial_usb(devs)
    if usb:
        _falhas_seguidas = 0
        mudou = False
        if usb not in _armados:
            ip = armar_sem_fio(usb, executar)
            _armados.add(usb)
            if ip:
                cfg["ip_aparelho"] = ip
                mudou = True
            # O tcpip acabou de reiniciar o adbd: o serial USB some por alguns
            # segundos. Só devolvemos um serial depois de vê-lo VIVO de novo.
            ip_atual = (cfg.get("ip_aparelho") or "").strip()
            vivo = _esperar_aparelho(
                usb, f"{ip_atual}:{PORTA_TCP}" if ip_atual else "",
                executar, dormir)
            return vivo, mudou
        elif not (cfg.get("ip_aparelho") or "").strip():
            # Já armado nesta plugada mas a descoberta de IP falhou (Wi-Fi
            # ainda subindo) e não há IP salvo: retenta SÓ o `ip route` — sem
            # IP a sessão não serve pra nada, e re-rodar tcpip reiniciaria o
            # adbd à toa a cada ciclo.
            ip = extrair_ip(executar(["-s", usb, "shell", "ip", "route"]))
            if ip:
                cfg["ip_aparelho"] = ip
                mudou = True
        return usb, mudou

    # Sem USB: fecha a sessão de plugada. A próxima vez que o cabo entrar,
    # `usb not in _armados` será True de novo e o arme roda do zero.
    _armados.clear()

    ip = (cfg.get("ip_aparelho") or "").strip()
    if not ip:
        return None, False
    alvo = f"{ip}:{PORTA_TCP}"
    conectados = {s for s, e in devs if e == "device"}
    if alvo not in conectados:
        executar(["connect", alvo], timeout=10)
        devs = listar_devices(executar(["devices"]))
        conectados = {s for s, e in devs if e == "device"}
    if alvo in conectados:
        _falhas_seguidas = 0
        return alvo, False

    # Falhou. Se o aparelho está ALCANÇÁVEL e já falhamos N ciclos seguidos,
    # o suspeito é o daemon local: kill-server e uma retentativa na hora.
    _falhas_seguidas += 1
    if (_falhas_seguidas >= FALHAS_PARA_CURA
            and (relogio() - _ultima_cura) >= CURA_INTERVALO_S
            and alcancavel(ip)):
        _ultima_cura = relogio()
        _falhas_seguidas = 0
        _curar_servidor_adb(executar)
        executar(["connect", alvo], timeout=10)
        conectados = {s for s, e in listar_devices(executar(["devices"])) if e == "device"}
        if alvo in conectados:
            return alvo, False
    return None, False
