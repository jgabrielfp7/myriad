# -*- coding: utf-8 -*-
"""Testes da camada de conexão (modo sem fio) — sem celular, tudo simulado."""

from conexao import (PORTA_TCP, bateria_ok, extrair_bateria, extrair_ip,
                     ler_bateria, listar_devices, serial_usb, serial_wifi)

SAIDA_DEVICES_USB = """List of devices attached
R9XR804DPGJ\tdevice
"""
SAIDA_DEVICES_WIFI = """List of devices attached
192.168.0.42:5555\tdevice
"""
SAIDA_DEVICES_MISTA = """* daemon not running; starting now at tcp:5037
* daemon started successfully
List of devices attached
R9XR804DPGJ\tdevice
192.168.0.42:5555\tdevice
192.168.15.7:5555\toffline
"""


def test_listar_devices_ignora_cabecalho_e_daemon():
    devs = listar_devices(SAIDA_DEVICES_MISTA)
    assert devs == [("R9XR804DPGJ", "device"),
                    ("192.168.0.42:5555", "device"),
                    ("192.168.15.7:5555", "offline")]


def test_serial_usb_so_pega_estado_device_sem_dois_pontos():
    assert serial_usb(listar_devices(SAIDA_DEVICES_MISTA)) == "R9XR804DPGJ"
    assert serial_usb(listar_devices(SAIDA_DEVICES_WIFI)) is None
    assert serial_usb(listar_devices("List of devices attached\n")) is None


def test_serial_wifi_so_pega_porta_5555_online():
    assert serial_wifi(listar_devices(SAIDA_DEVICES_MISTA)) == "192.168.0.42:5555"
    assert serial_wifi(listar_devices(SAIDA_DEVICES_USB)) is None


def test_extrair_ip_do_ip_route():
    saida = ("192.168.0.0/24 dev wlan0 proto kernel scope link "
             "src 192.168.0.42\n")
    assert extrair_ip(saida) == "192.168.0.42"
    assert extrair_ip("") is None


def test_extrair_bateria_nivel_e_carregando():
    dump = "Current Battery Service state:\n  AC powered: false\n  USB powered: true\n  level: 61\n"
    assert extrair_bateria(dump) == (61, True)
    dump2 = "  AC powered: false\n  USB powered: false\n  Wireless powered: false\n  level: 18\n"
    assert extrair_bateria(dump2) == (18, False)
    assert extrair_bateria("lixo qualquer") == (None, False)


def test_bateria_ok_regras():
    assert bateria_ok(80, False, 20) == (True, "")
    assert bateria_ok(18, True, 20) == (True, "")        # carregando: sempre ok
    assert bateria_ok(None, False, 20) == (True, "")     # sem leitura: não trava o dia
    ok, motivo = bateria_ok(18, False, 20)
    assert ok is False and "18%" in motivo


def test_ler_bateria_repassa_a_leitura():
    def adb_ok(args, timeout=30):
        return "level: 61\nUSB powered: true\n"
    assert ler_bateria("R9X", executar=adb_ok) == (61, True)


def test_ler_bateria_falha_de_leitura_vira_none_false():
    """Se o subprocess do adb explodir (device caiu no meio do ciclo, timeout,
    adb sumiu), o guardrail de bateria não pode ser derrubado por isso."""
    def adb_quebrado(args, timeout=30):
        raise TimeoutError("device offline")
    assert ler_bateria("R9X", executar=adb_quebrado) == (None, False)


import conexao
from conexao import garantir_conexao


class AdbFalso:
    """Executor de adb simulado: responde por prefixo de comando e grava chamadas."""

    def __init__(self, devices="", ip_route="", devices_apos_connect=None):
        self.devices = devices
        self.ip_route = ip_route
        self.devices_apos_connect = devices_apos_connect
        self.chamadas = []

    def __call__(self, args, timeout=30):
        self.chamadas.append(list(args))
        if args[-1] == "devices" or args == ["devices"]:
            if (self.devices_apos_connect is not None
                    and any(c and c[0] == "connect" for c in self.chamadas)):
                return self.devices_apos_connect
            return self.devices
        if "route" in args:
            return self.ip_route
        return ""


def _limpar_armados():
    conexao._armados.clear()


def test_usb_arma_wifi_e_salva_ip(monkeypatch):
    monkeypatch.setattr(conexao.time, "sleep", lambda s: None)
    _limpar_armados()
    adb = AdbFalso(devices="List of devices attached\nR9X\tdevice\n",
                   ip_route="192.168.0.0/24 dev wlan0 src 192.168.0.42\n")
    cfg = {}
    serial, mudou = garantir_conexao(cfg, executar=adb)
    assert serial == "R9X"
    assert mudou is True
    assert cfg["ip_aparelho"] == "192.168.0.42"
    planos = [" ".join(c) for c in adb.chamadas]
    assert any(f"tcpip {conexao.PORTA_TCP}" in p for p in planos)
    assert any("deviceidle disable" in p for p in planos)


def test_usb_arma_apenas_uma_vez_por_processo(monkeypatch):
    monkeypatch.setattr(conexao.time, "sleep", lambda s: None)
    _limpar_armados()
    adb = AdbFalso(devices="List of devices attached\nR9X\tdevice\n",
                   ip_route="x src 10.0.0.5\n")
    cfg = {}
    garantir_conexao(cfg, executar=adb)
    n_tcpip = sum(1 for c in adb.chamadas if "tcpip" in c)
    garantir_conexao(cfg, executar=adb)
    assert sum(1 for c in adb.chamadas if "tcpip" in c) == n_tcpip  # não re-armou
    assert garantir_conexao(cfg, executar=adb)[1] is False  # cfg não muda mais


def test_sem_usb_conecta_no_ip_salvo():
    _limpar_armados()
    adb = AdbFalso(
        devices="List of devices attached\n",
        devices_apos_connect="List of devices attached\n192.168.0.42:5555\tdevice\n")
    cfg = {"ip_aparelho": "192.168.0.42"}
    serial, mudou = garantir_conexao(cfg, executar=adb)
    assert serial == "192.168.0.42:5555"
    assert mudou is False
    assert ["connect", "192.168.0.42:5555"] in adb.chamadas


def test_sem_usb_e_sem_ip_salvo_retorna_none():
    _limpar_armados()
    adb = AdbFalso(devices="List of devices attached\n")
    assert garantir_conexao({}, executar=adb) == (None, False)


def test_sem_usb_e_wifi_inalcancavel_retorna_none():
    _limpar_armados()
    adb = AdbFalso(devices="List of devices attached\n",
                   devices_apos_connect="List of devices attached\n")
    cfg = {"ip_aparelho": "192.168.0.42"}
    assert garantir_conexao(cfg, executar=adb) == (None, False)


def test_replugar_rearma_o_wifi_de_novo(monkeypatch):
    """Spec: TODA plugada re-arma (reaprende IP em rede nova; reativa
    tcpip+Doze-disable se o aparelho reiniciou) — não é 'armar 1x pra sempre
    no processo'. USB -> sem USB -> USB de novo tem que rodar `tcpip` 2x."""
    monkeypatch.setattr(conexao.time, "sleep", lambda s: None)
    _limpar_armados()

    class AdbSequencial:
        """Simula duas plugadas: USB presente, some (fecha a sessão), volta."""

        def __init__(self):
            self.chamadas = []
            self.respostas_devices = iter([
                "List of devices attached\nR9X\tdevice\n",  # plugada 1
                "List of devices attached\nR9X\tdevice\n",  # voltou após o tcpip
                "List of devices attached\n",                # desplugado (1a checagem)
                "List of devices attached\n",                # desplugado (após connect)
                "List of devices attached\nR9X\tdevice\n",   # plugada 2
                "List of devices attached\nR9X\tdevice\n",  # voltou após o tcpip
            ])

        def __call__(self, args, timeout=30):
            self.chamadas.append(list(args))
            if args == ["devices"]:
                return next(self.respostas_devices)
            if "route" in args:
                return "x src 10.0.0.5\n"
            return ""

    adb = AdbSequencial()
    cfg = {}
    serial1, mudou1 = garantir_conexao(cfg, executar=adb)  # plugada 1: arma
    assert serial1 == "R9X" and mudou1 is True
    serial2, _ = garantir_conexao(cfg, executar=adb)       # desplugou
    assert serial2 is None
    serial3, mudou3 = garantir_conexao(cfg, executar=adb)  # plugada 2: re-arma
    assert serial3 == "R9X" and mudou3 is True

    n_tcpip = sum(1 for c in adb.chamadas if "tcpip" in c)
    assert n_tcpip == 2  # uma vez por plugada, não uma vez por processo


def test_armado_sem_ip_reten_so_a_descoberta_de_ip(monkeypatch):
    """Armou (tcpip+Doze) mas a descoberta de IP falhou (Wi-Fi ainda subindo)
    e não há IP salvo: o ciclo seguinte tem que retentar SÓ o `ip route` —
    nunca re-rodar `tcpip` (que reinicia o adbd)."""
    monkeypatch.setattr(conexao.time, "sleep", lambda s: None)
    _limpar_armados()
    respostas_route = iter(["", "x src 10.0.0.9\n"])  # 1a tentativa falha, 2a acha

    class AdbArmaSemIp:
        def __init__(self):
            self.chamadas = []

        def __call__(self, args, timeout=30):
            self.chamadas.append(list(args))
            if args == ["devices"]:
                return "List of devices attached\nR9X\tdevice\n"
            if "route" in args:
                return next(respostas_route)
            return ""

    adb = AdbArmaSemIp()
    cfg = {}
    serial1, mudou1 = garantir_conexao(cfg, executar=adb)
    assert serial1 == "R9X" and mudou1 is False  # armou mas não achou IP
    assert cfg.get("ip_aparelho") is None

    serial2, mudou2 = garantir_conexao(cfg, executar=adb)
    assert serial2 == "R9X" and mudou2 is True
    assert cfg["ip_aparelho"] == "10.0.0.9"

    n_tcpip = sum(1 for c in adb.chamadas if "tcpip" in c)
    assert n_tcpip == 1  # nunca re-rodou tcpip pra retentar o IP


# --- o serial que some depois de armar (bug 03/09) ------------------------
# `adb tcpip 5555` REINICIA o adbd, e o serial USB desaparece por alguns
# segundos. A função devolvia esse serial logo depois de armar, e quem
# recebia trabalhava num aparelho que não existia mais: a coleta de views
# falhou nas 5 contas com "device 'R9XR804DPGJ' not found", todas no mesmo
# segundo. O arme precisa ESPERAR o aparelho voltar antes de devolver.

import conexao


def _executor(sequencia):
    """Devolve as saídas de `adb devices` na ordem, e ecoa os outros comandos."""
    passos = list(sequencia)

    def executar(cmd, timeout=None):
        if cmd and cmd[0] == "devices":
            return passos.pop(0) if passos else "List of devices attached\n"
        if "ip" in cmd and "route" in cmd:
            return "192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.13"
        return ""
    return executar


def test_espera_o_usb_voltar_depois_de_armar(monkeypatch):
    """Some na 1ª checagem, volta na 2ª: tem que devolver o serial USB."""
    monkeypatch.setattr(conexao, "_armados", set())
    sumido = "List of devices attached\n"
    voltou = "List of devices attached\nR9XR804DPGJ\tdevice\n"
    executar = _executor([SAIDA_DEVICES_USB, sumido, voltou])

    serial, _ = conexao.garantir_conexao({"ip_aparelho": ""}, executar=executar,
                                         dormir=lambda s: None)

    assert serial == "R9XR804DPGJ"


def test_se_o_usb_nao_voltar_cai_pro_wifi(monkeypatch):
    """O aparelho ficou só em TCP: usar o endereço Wi-Fi é o caminho certo,
    e é melhor que devolver um serial morto."""
    monkeypatch.setattr(conexao, "_armados", set())
    sumido = "List of devices attached\n"
    so_wifi = f"List of devices attached\n192.168.1.13:{PORTA_TCP}\tdevice\n"
    executar = _executor([SAIDA_DEVICES_USB] + [sumido] * 6 + [so_wifi])

    serial, _ = conexao.garantir_conexao({"ip_aparelho": "192.168.1.13"},
                                         executar=executar, dormir=lambda s: None)

    assert serial == f"192.168.1.13:{PORTA_TCP}"


def test_se_nao_voltar_de_jeito_nenhum_devolve_none(monkeypatch):
    """Sem aparelho, o chamador ADIA — melhor que estourar exceção no meio."""
    monkeypatch.setattr(conexao, "_armados", set())
    sumido = "List of devices attached\n"
    executar = _executor([SAIDA_DEVICES_USB] + [sumido] * 20)

    serial, _ = conexao.garantir_conexao({"ip_aparelho": "192.168.1.13"},
                                         executar=executar, dormir=lambda s: None)

    assert serial is None


# --- autocura do servidor adb (18/09): daemon zumbi no PC ---

def _executar_zumbi(curado_conecta=True):
    """adb falso: `devices` vem vazio até alguém rodar kill-server; depois
    da cura, o connect passa a funcionar (se curado_conecta)."""
    est = {"curado": False, "cmds": []}
    def _e(args, timeout=30, bin=None):
        est["cmds"].append(list(args))
        if args[0] == "kill-server":
            est["curado"] = True
            return ""
        if args[0] == "devices":
            if est["curado"] and curado_conecta:
                return "List of devices attached\n192.168.1.13:5555\tdevice\n"
            return "List of devices attached\n"
        return ""
    _e.est = est
    return _e


def _zerar_cura():
    conexao._falhas_seguidas = 0
    conexao._ultima_cura = float("-inf")


def test_cura_do_daemon_apos_3_falhas_com_aparelho_alcancavel():
    _zerar_cura()
    cfg = {"ip_aparelho": "192.168.1.13"}
    e = _executar_zumbi()
    t = {"agora": 1000.0}
    args = dict(executar=e, dormir=lambda s: None,
                alcancavel=lambda ip, porta=5555, timeout=2.0: True,
                relogio=lambda: t["agora"])
    # duas falhas: ainda sem cura
    assert conexao.garantir_conexao(cfg, **args) == (None, False)
    assert conexao.garantir_conexao(cfg, **args) == (None, False)
    assert ["kill-server"] not in e.est["cmds"]
    # terceira: kill-server + reconecta na hora
    serial, _ = conexao.garantir_conexao(cfg, **args)
    assert ["kill-server"] in e.est["cmds"]
    assert serial == "192.168.1.13:5555"


def test_sem_cura_quando_o_aparelho_nao_esta_alcancavel():
    _zerar_cura()
    cfg = {"ip_aparelho": "192.168.1.13"}
    e = _executar_zumbi()
    args = dict(executar=e, dormir=lambda s: None,
                alcancavel=lambda ip, porta=5555, timeout=2.0: False,
                relogio=lambda: 1000.0)
    for _ in range(5):
        assert conexao.garantir_conexao(cfg, **args) == (None, False)
    assert ["kill-server"] not in e.est["cmds"]    # celular fora: não é o daemon


def test_cura_respeita_o_intervalo_de_10_minutos():
    _zerar_cura()
    cfg = {"ip_aparelho": "192.168.1.13"}
    e = _executar_zumbi(curado_conecta=False)      # cura não resolve (defeito real)
    t = {"agora": 1000.0}
    args = dict(executar=e, dormir=lambda s: None,
                alcancavel=lambda ip, porta=5555, timeout=2.0: True,
                relogio=lambda: t["agora"])
    for _ in range(3):
        conexao.garantir_conexao(cfg, **args)
    assert e.est["cmds"].count(["kill-server"]) == 1
    for _ in range(6):                             # mais falhas logo depois: sem nova cura
        conexao.garantir_conexao(cfg, **args)
    assert e.est["cmds"].count(["kill-server"]) == 1
    t["agora"] += 601                              # passou o intervalo: pode curar de novo
    for _ in range(3):
        conexao.garantir_conexao(cfg, **args)
    assert e.est["cmds"].count(["kill-server"]) == 2


def test_sucesso_zera_o_contador_de_falhas():
    _zerar_cura()
    cfg = {"ip_aparelho": "192.168.1.13"}
    ok = "List of devices attached\n192.168.1.13:5555\tdevice\n"
    vazio = "List of devices attached\n"
    respostas = iter([vazio, "", vazio, ok, vazio, "", vazio])   # falha, sucesso, falha
    def _e(args, timeout=30, bin=None):
        return next(respostas, vazio)
    args = dict(executar=_e, dormir=lambda s: None,
                alcancavel=lambda ip, porta=5555, timeout=2.0: True,
                relogio=lambda: 1000.0)
    conexao.garantir_conexao(cfg, **args)          # falha (1)
    conexao.garantir_conexao(cfg, **args)          # sucesso -> zera
    assert conexao._falhas_seguidas in (0, 1)
