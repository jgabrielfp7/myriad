# -*- coding: utf-8 -*-
"""
Driver do Instagram — dirige o app REAL via uiautomator2 (toques nativos).
Nenhuma chamada de API da Meta em nenhum ponto: o post nasce dentro do app,
no aparelho, exatamente como um post manual.

Estratégia de seletores: texto/descrição (PT com fallback EN) e resource-id,
nunca coordenada de pixel — sobrevive a pequenas mudanças de UI.
"""

import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import uiautomator2 as u2

PACOTE_IG = "com.instagram.android"
PASTA_CAMERA_APARELHO = "/sdcard/DCIM/Camera"

# Caminhos onde o adb costuma estar (fallback se não estiver no PATH da sessão)
_ADB_FALLBACKS = [
    r"C:\platform-tools\adb.exe",
    r"C:\Android\platform-tools\adb.exe",
]


def _adb_bin() -> str:
    """Localiza o executável do adb: PATH primeiro, depois locais conhecidos."""
    achado = shutil.which("adb")
    if achado:
        return achado
    for c in _ADB_FALLBACKS:
        if Path(c).exists():
            return c
    return "adb"  # última tentativa; se falhar, o erro é claro

# Textos da UI (PT primeiro, EN como fallback — depende do idioma do aparelho)
TXT_AVANCAR = ["Avançar", "Next"]
TXT_COMPARTILHAR = ["Compartilhar", "Share"]
TXT_ABA_REEL = ["Reel", "Reels", "REEL", "REELS"]
TXT_ABA_POST = ["PUBLICAR", "Publicação", "PUBLICAÇÃO", "Publicar", "POST", "Post"]
TXT_SELECIONAR_VARIOS = ["Selecionar vários", "Selecionar varios", "Select multiple",
                         "SELECIONAR VÁRIOS"]
TXT_NOVA_PUBLICACAO = ["Criar", "Nova publicação", "New post", "Create"]
# Só dispensas INOFENSIVAS. NUNCA incluir "Cancelar"/"Fechar"/"Descartar" —
# num editor de post, esses botões ABORTAM a publicação inteira.
TXT_POPUPS = [
    "Agora não", "Agora Não", "Not now", "Not Now",
    # Onboarding de conta recém-logada ("Configurar em um novo dispositivo"):
    # "Pular" só pula etapas opcionais — nunca aborta um post.
    "Pular", "Skip",
]
# Diálogo "Você não pode trocar de conta enquanto está carregando alguma coisa"
# — aparece quando o upload do post ANTERIOR ainda processa em 2º plano
# (derrubou o reel06 em 2026-08-23 22:46). Transitório: OK + esperar + tentar de novo.
TXT_TROCA_BLOQUEADA = [
    "não pode trocar de conta", "can't switch accounts", "cannot switch accounts",
]

# Sinais de restrição/bloqueio → dispara o kill-switch
TXT_BLOQUEIO = [
    "Tente novamente mais tarde", "Try again later",
    "restringimos", "We restrict", "We limit",
    "temporariamente bloqueado", "temporarily blocked",
    "Ação bloqueada", "Action blocked",
]


class BloqueioDetectado(Exception):
    """O app mostrou um aviso de restrição — o postador deve pausar TUDO."""


class FalhaNoFluxo(Exception):
    """Um passo do fluxo de postagem não foi encontrado/completado."""


def conectar(serial: str | None = None) -> u2.Device:
    """Conecta ao aparelho via ADB (USB). serial=None pega o único conectado."""
    d = u2.connect(serial) if serial else u2.connect()
    d.implicitly_wait(10)
    return d


def apagar_tela(d: u2.Device) -> None:
    """Apaga a tela ao fim de um fluxo automático (pedido do operador, 28/08).
    Com "Permanecer ativo" ligado ela nunca apaga sozinha no cabo. Nunca
    levanta exceção — apagar a tela jamais pode derrubar um fluxo."""
    try:
        d.screen_off()
    except Exception:
        pass


def info_aparelho(d: u2.Device) -> str:
    info = d.info
    return f"{info.get('productName', '?')} (Android {d.device_info.get('version', '?')})"


def enviar_video(serial: str | None, caminho_video: Path) -> str:
    """Copia o vídeo pro rolo de câmera do aparelho e avisa a galeria (media scan)."""
    destino = f"{PASTA_CAMERA_APARELHO}/{caminho_video.name}"
    base = [_adb_bin()] + (["-s", serial] if serial else [])
    # Apaga uma cópia pré-existente ANTES de enviar: assim o arquivo recebe uma
    # data de adição nova e vira o "mais recente" da galeria de forma garantida
    # (importante quando há vários vídeos pré-carregados no aparelho).
    subprocess.run(base + ["shell", "rm", "-f", destino],
                   check=False, capture_output=True)
    subprocess.run(base + ["shell", "am", "broadcast",
                           "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                           "-d", f"file://{destino}"],
                   check=False, capture_output=True)
    subprocess.run(base + ["push", str(caminho_video), destino],
                   check=True, capture_output=True)
    subprocess.run(base + ["shell", "am", "broadcast",
                           "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                           "-d", f"file://{destino}"],
                   check=True, capture_output=True)
    time.sleep(3)  # a galeria demora um pouco pra indexar
    return destino


def enviar_slides_ordenados(serial: str | None, slides: list[Path]) -> list[str]:
    """Envia os slides de um carrossel com DATA espaçada por posição, pra galeria
    do IG ordenar deterministicamente. Sem isto os slides (renderizados no mesmo
    instante) têm data colada e a galeria embaralha a ordem (bug de 28/08).

    slide-01 recebe a data MAIS NOVA; cada slide seguinte 2 min mais velho. E a
    varredura (media scan) roda do mais velho pro mais novo, então DATE_ADDED
    também cresce até o slide-01 — os dois critérios de ordenação concordam:
    slide-01 aparece primeiro (instance 0)."""
    base = [_adb_bin()] + (["-s", serial] if serial else [])
    destinos: list[str] = []
    from datetime import datetime as _dt, timedelta as _td
    agora = _dt.now()
    # 1) push + carimbo de data por posição (slide-01 = mais novo)
    for idx, slide in enumerate(slides):
        destino = f"{PASTA_CAMERA_APARELHO}/{slide.name}"
        subprocess.run(base + ["shell", "rm", "-f", destino], check=False, capture_output=True)
        subprocess.run(base + ["push", str(slide), destino], check=True, capture_output=True)
        carimbo = (agora - _td(minutes=2 * idx)).strftime("%Y%m%d%H%M.%S")
        subprocess.run(base + ["shell", "touch", "-t", carimbo, destino],
                       check=False, capture_output=True)
        destinos.append(destino)
    # 2) varredura do mais VELHO pro mais novo (DATE_ADDED cresce até o slide-01)
    for destino in reversed(destinos):
        subprocess.run(base + ["shell", "am", "broadcast",
                               "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                               "-d", f"file://{destino}"], check=False, capture_output=True)
        time.sleep(0.4)
    time.sleep(3)  # a galeria demora a indexar
    return destinos


def apagar_do_aparelho(serial: str | None, destino: str) -> None:
    """Remove o vídeo do celular após postar (gestão de armazenamento). Falha
    silenciosa: limpar é secundário, nunca deve derrubar o post."""
    if not destino:
        return
    base = ["adb"] + (["-s", serial] if serial else [])
    base[0] = _adb_bin()
    try:
        subprocess.run(base + ["shell", "rm", "-f", destino],
                       check=False, capture_output=True, timeout=30)
        subprocess.run(base + ["shell", "am", "broadcast",
                               "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                               "-d", f"file://{destino}"],
                       check=False, capture_output=True, timeout=30)
    except Exception:
        pass


def _achar(d: u2.Device, textos: list[str], timeout: float = 8.0):
    """Procura um elemento por texto exato ou descrição, na ordem dada."""
    fim = time.time() + timeout
    while time.time() < fim:
        for t in textos:
            for sel in (d(text=t), d(description=t), d(textContains=t)):
                if sel.exists:
                    return sel
        time.sleep(0.5)
    return None


def _garantir_ig_em_foco(d: u2.Device, max_back: int = 4, pausa: float = 2.0) -> None:
    """Se outro app cobriu o IG — ex.: a folha do Google Play que o próprio IG
    abre promovendo o app "Edits" (derrubou 8 posts em 2026-08-23) — aperta
    "voltar" até o IG reassumir. Só age quando o app em foco NÃO é o Instagram,
    então nunca interfere num fluxo de post em andamento."""
    for _ in range(max_back):
        try:
            pacote = d.app_current().get("package", "")
        except Exception:
            return  # sem leitura de foco, não arrisca apertar nada
        if pacote == PACOTE_IG:
            return
        d.press("back")
        time.sleep(pausa)


def _troca_bloqueada(d: u2.Device) -> bool:
    """Detecta o diálogo de troca bloqueada por upload em andamento; se estiver
    na tela, dispensa com OK e retorna True (o chamador espera e tenta de novo)."""
    for t in TXT_TROCA_BLOQUEADA:
        if d(textContains=t).exists:
            ok = d(text="OK")
            if ok.exists:
                ok.click()
                time.sleep(1)
            return True
    return False


def _fechar_sheet_edits(d: u2.Device) -> bool:
    """Promo do app "Edits", variante bottom-sheet (28/08): abre POR CIMA do
    compositor DENTRO do próprio IG — o app segue em foco, então a guarda de
    foco não pega (a variante de 23/08 abria o Google Play). Marca da sheet:
    botão "Baixar app". Fecha com "voltar" (nunca clica no botão)."""
    for t in ("Baixar app", "Download app"):
        if d(text=t).exists:
            d.press("back")
            time.sleep(1.5)
            return True
    return False


def _fechar_popups(d: u2.Device) -> None:
    """Fecha diálogos ocasionais (notificações, novidades etc.) sem quebrar o fluxo."""
    _garantir_ig_em_foco(d)
    _fechar_sheet_edits(d)
    for t in TXT_POPUPS:
        sel = d(text=t)
        if sel.exists:
            sel.click()
            time.sleep(1)


def _checar_bloqueio(d: u2.Device) -> None:
    """Se a tela mostrar aviso de restrição, levanta BloqueioDetectado (kill-switch)."""
    xml = d.dump_hierarchy()
    for t in TXT_BLOQUEIO:
        if t.lower() in xml.lower():
            raise BloqueioDetectado(f"Aviso de restrição na tela: '{t}'")


def _screenshot(d: u2.Device, pasta_logs: Path, etapa: str) -> Path:
    pasta_logs.mkdir(parents=True, exist_ok=True)
    arq = pasta_logs / f"erro_{datetime.now():%Y%m%d_%H%M%S}_{etapa}.png"
    d.screenshot(str(arq))
    return arq


def _normaliza_conta(conta: str) -> str:
    return conta.strip().lstrip("@").lower()


def _conta_ativa(d: u2.Device) -> str | None:
    """Lê o @usuário da conta logada agora (título da barra do perfil).
    Retorna None se não conseguir ler — aí o chamador NÃO posta às cegas.
    Seletor confirmado nesta versão: action_bar_title."""
    el = d(resourceId=f"{PACOTE_IG}:id/action_bar_title")
    if el.exists:
        txt = (el.get_text() or "").strip()
        if txt:
            return txt.lstrip("@").lower()
    return None


def garantir_conta(d: u2.Device, conta: str, pasta_logs: Path) -> None:
    """Garante que a conta ATIVA é `conta` antes de postar. Se não conseguir
    CONFIRMAR, levanta FalhaNoFluxo — nunca posta no perfil errado.

    conta vazia = modo conta única (posta no que estiver logado).
    Seletores confirmados (Galaxy A03s, IG PT, 2026-08-22):
      - título/usuário ativo: action_bar_title
      - abrir seletor: action_bar_username_container
      - linha da conta no seletor: content-desc começa com o @usuário"""
    alvo = _normaliza_conta(conta)
    if not alvo:
        return  # sem alvo: não mexe na conta ativa

    handle = conta.strip().lstrip("@")

    _garantir_ig_em_foco(d)
    aba_perfil = d(resourceId=f"{PACOTE_IG}:id/profile_tab")
    if not aba_perfil.wait(timeout=15):
        _garantir_ig_em_foco(d)  # overlay pode ter surgido durante a espera
        if not aba_perfil.wait(timeout=10):
            _screenshot(d, pasta_logs, "garantir_conta_sem_profile_tab")
            raise FalhaNoFluxo("Aba de perfil não apareceu (overlay ou app fora do ar?)")
    aba_perfil.click()
    time.sleep(3)
    _fechar_popups(d)

    if _conta_ativa(d) == alvo:
        return  # já está na conta certa

    # Abre o seletor de contas (nome de usuário + chevron no topo do perfil).
    # Se o upload do post anterior ainda processa, o IG recusa a troca com o
    # diálogo "Você não pode trocar de conta..." — dispensa, espera e re-tenta.
    for _ in range(4):
        if _troca_bloqueada(d):
            time.sleep(30)
            continue
        cont = d(resourceId=f"{PACOTE_IG}:id/action_bar_username_container")
        if not cont.exists:
            _screenshot(d, pasta_logs, "trocar_conta_sem_seletor")
            raise FalhaNoFluxo("Não achei o container do usuário pra abrir a troca")
        cont.click()
        time.sleep(3)
        if _troca_bloqueada(d):
            time.sleep(30)
            continue
        break
    else:
        _screenshot(d, pasta_logs, "trocar_conta_upload_processando")
        raise FalhaNoFluxo(
            "IG recusou a troca de conta repetidamente (upload anterior processando?)")

    # Toca na linha da conta alvo. No seletor, a linha clicável tem content-desc
    # começando com o @usuário (ex.: "exemplo.mind, 2 comentários e mais 19").
    row = d(descriptionStartsWith=handle)
    if not row.exists:
        row = d(textStartsWith=handle)
    if not row.exists:
        _screenshot(d, pasta_logs, "trocar_conta_alvo_nao_listado")
        raise FalhaNoFluxo(f"Conta '{conta}' não apareceu no seletor (logada no aparelho?)")
    row.click()
    time.sleep(5)
    _fechar_popups(d)

    # VERIFICAÇÃO OBRIGATÓRIA: confirma a troca no perfil antes de deixar postar
    d(resourceId=f"{PACOTE_IG}:id/profile_tab").click()
    time.sleep(2)
    confirma = _conta_ativa(d)
    if confirma != alvo:
        _screenshot(d, pasta_logs, "trocar_conta_nao_confirmada")
        raise FalhaNoFluxo(
            f"Não confirmei a troca para '{conta}' (ativa: {confirma}) — não vou postar")


def _num_br(txt: str) -> int | None:
    """Converte contagem do IG em inteiro: '7,2 mil'->7200, '1,3 mi'->1300000,
    '842'->842. Retorna None se não parecer um número."""
    s = txt.strip().lower()
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*(mil|mi|m|k|b)?", s)
    if not m:
        return None
    num = m.group(1).replace(".", "").replace(",", ".")
    try:
        val = float(num)
    except ValueError:
        return None
    suf = m.group(2)
    if suf in ("mil", "k"):
        val *= 1_000
    elif suf in ("mi", "m"):
        val *= 1_000_000
    elif suf == "b":
        val *= 1_000_000_000
    return int(round(val))


def dump_perfil_reels(d: u2.Device, pasta_logs: Path, tag: str = "diag") -> Path:
    """Salva screenshot + hierarquia da tela atual (pra calibrar a coleta de views)."""
    pasta_logs.mkdir(parents=True, exist_ok=True)
    d.dump_hierarchy()
    xml = pasta_logs / f"alcance_{tag}.xml"
    xml.write_text(d.dump_hierarchy(), encoding="utf-8")
    d.screenshot(str(pasta_logs / f"alcance_{tag}.png"))
    return xml


# Miniatura da grade de Reels do perfil (calibrado 2026-08-24, IG PT):
# Button `preview_clip_thumbnail`, content-desc "Reel de <conta>. Número de
# visualizações N. Toque duas vezes para reproduzir ou pausar." Um Reel recém-
# postado ainda SEM contador tem desc sem o trecho de visualizações.
_RE_VIEWS_DESC = re.compile(
    r"visualiza\S*\s+([\d]+(?:[.,]\d+)?\s*(?:mil|mi|m|k|b)?)", re.IGNORECASE)


def _views_de_desc(desc: str) -> int | None:
    """'Reel de exemplo.corp. Número de visualizações 141. Toque...' -> 141.
    None se o desc não traz contagem (reel recém-postado, ainda processando)."""
    m = _RE_VIEWS_DESC.search(desc or "")
    if not m:
        return None
    return _num_br(m.group(1))


def _alinhar_lote(vistos: list, lote: list) -> list:
    """Quantos itens do começo de `lote` já estão no fim de `vistos`?
    Retorna só os itens NOVOS (a cauda do lote), alinhando pela maior
    sobreposição sufixo(vistos)==prefixo(lote) — aguenta contagens repetidas,
    ao contrário de um dedup por valor. Sem sobreposição = lote inteiro é novo."""
    if not vistos:
        return list(lote)
    for k in range(min(len(vistos), len(lote)), 0, -1):
        if vistos[-k:] == lote[:k]:
            return list(lote[k:])
    return list(lote)


def _lote_visivel(d) -> list[tuple[str, int | None]]:
    """Miniaturas de Reel visíveis agora, na ordem da grade (linha a linha,
    esquerda→direita), como (content-desc, views|None)."""
    itens = []
    for el in d.xpath(
            f'//*[@resource-id="{PACOTE_IG}:id/preview_clip_thumbnail"]').all():
        desc = el.attrib.get("content-desc", "")
        if not desc.strip():
            continue
        m = re.match(r"\[(\d+),(\d+)\]", el.attrib.get("bounds", ""))
        x, y = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        itens.append((y, x, desc, _views_de_desc(desc)))
    itens.sort()
    return [(desc, v) for (_, _, desc, v) in itens]


def preparar_tela(d, dormir=time.sleep, abrir_app: bool = False) -> None:
    """Acorda, desbloqueia, vai pra home e (opcional) abre o Instagram do zero.

    **Todo fluxo começa por aqui.** Em 03/09 a coleta de views falhou em duas
    camadas, e as duas eram passos que só o caminho de POSTAR tinha:

    1. tela dormindo (`mWakefulness=Dozing`): as capturas saíam pretas e o
       robô reportava "aba de perfil não apareceu" — não estava vendo um
       overlay, não estava vendo nada;
    2. app fechado: a captura mostrou a TELA INICIAL do Android. A coleta
       assumia o Instagram já aberto, e só funcionava por acidente — quando
       rodava logo depois de uma postagem, que deixava o app de pé.
    """
    d.screen_on()
    dormir(1)
    d.unlock()      # serve pra tela sem senha ou com deslizar
    dormir(1)
    d.press("home")  # fecha barra de notificações: estado previsível
    dormir(1)
    if not abrir_app:
        return
    d.app_start(PACOTE_IG, stop=True)   # do zero: estado previsível
    dormir(6)
    pronto = (d(resourceId=f"{PACOTE_IG}:id/feed_tab").wait(timeout=25)
              or d(resourceId=f"{PACOTE_IG}:id/profile_tab").wait(timeout=5))
    if not pronto:
        dormir(5)   # última margem: acordar do sono deixa a carga lenta


def coletar_views_conta(d: u2.Device, conta: str, pasta_logs: Path,
                        n: int = 20) -> list[int | None]:
    """Troca pra `conta`, abre a aba de Reels do perfil e lê as contagens de
    views das miniaturas, na ordem da grade (mais recente primeiro), rolando
    até juntar `n` itens. Retorna lista de int|None (None = miniatura ainda
    sem contador — mantida na posição pra não deslocar o mapeamento com a
    fila). Pressupõe grade sem Reels fixados (pinned reordena a grade)."""
    preparar_tela(d, abrir_app=True)   # tela dormindo ou app fechado (bug 03/09)
    garantir_conta(d, conta, pasta_logs)
    d(resourceId=f"{PACOTE_IG}:id/profile_tab").click()
    time.sleep(3)
    _fechar_popups(d)

    # Aba de Reels DO PERFIL: profile_tab_icon_view desc="Reels".
    # ⚠ NÃO usar clips_tab — esse id é o Reels do FEED (barra inferior) e
    # tira o app do perfil (aprendido 2026-08-24).
    for sel in (d(resourceId=f"{PACOTE_IG}:id/profile_tab_icon_view",
                  description="Reels"),
                d(descriptionContains="Reels")):
        if sel.exists:
            sel.click()
            time.sleep(3)
            break
    if not d(resourceId=f"{PACOTE_IG}:id/clips_grid_recyclerview").exists:
        dump_perfil_reels(d, pasta_logs, f"{_normaliza_conta(conta)}_semgrade")
        raise FalhaNoFluxo(
            f"Grade de Reels não apareceu no perfil de {conta} "
            f"(veja alcance_*_semgrade.png/xml em logs/)")

    # Rola UMA vez antes de ler: a 1ª linha da grade nasce cortada na borda
    # da tela e o accessibility pode omitir nós parciais (visto no diag de
    # 24/08: só 2 de 3 thumbs no dump) — meio-scroll traz a linha 1 inteira
    # sem tirá-la do topo (o cabeçalho do perfil tem ~2x essa altura).
    d.swipe_ext("up", scale=0.4)
    time.sleep(1.5)

    vistos: list[tuple[str, int | None]] = []
    sem_novidade = 0
    for _ in range(12):  # teto de telas — segurança contra loop infinito
        lote = _lote_visivel(d)
        novos = _alinhar_lote([x[0] for x in vistos], [x[0] for x in lote])
        if novos:
            vistos.extend(lote[len(lote) - len(novos):])
            sem_novidade = 0
        else:
            sem_novidade += 1
            if sem_novidade >= 2:
                break  # fim da grade (duas rolagens sem item novo)
        if len(vistos) >= n:
            break
        d.swipe_ext("up", scale=0.4)
        time.sleep(1.5)

    if not vistos:
        dump_perfil_reels(d, pasta_logs, f"{_normaliza_conta(conta)}_vazio")
        raise FalhaNoFluxo(
            f"Não achei miniaturas de Reels no perfil de {conta} — calibrar "
            f"(veja alcance_*.png/xml em logs/)")
    return [v for (_, v) in vistos[:n]]


def postar_reel(d: u2.Device, serial: str | None, caminho_video: Path,
                legenda: str, pasta_logs: Path, conta: str = "",
                dry_run: bool = False) -> None:
    """
    Fluxo completo: push do vídeo → abrir IG → criar Reel → selecionar o vídeo
    mais recente → avançar → legenda → compartilhar.

    dry_run=True percorre TUDO e para antes de "Compartilhar" (modo --teste).
    Levanta FalhaNoFluxo (com screenshot salvo) ou BloqueioDetectado.
    """
    etapa = "inicio"
    try:
        etapa = "preparar_tela"
        d.screen_on()          # tira do modo dozing/apagado
        time.sleep(1)
        d.unlock()             # desbloqueia (funciona p/ tela sem senha ou com deslizar)
        time.sleep(1)
        d.press("home")        # fecha barra de notificações / estado limpo
        time.sleep(1)

        etapa = "enviar_video"
        destino_aparelho = enviar_video(serial, caminho_video)

        etapa = "abrir_app"
        d.app_start(PACOTE_IG, stop=True)  # começa do zero, estado previsível
        time.sleep(6)
        # Espera o app carregar de verdade (barra de navegação pronta) antes de
        # interagir — acordar do sono profundo deixa a carga mais lenta.
        pronto = (d(resourceId=f"{PACOTE_IG}:id/feed_tab").wait(timeout=25)
                  or d(resourceId=f"{PACOTE_IG}:id/profile_tab").wait(timeout=5))
        if not pronto:
            time.sleep(5)  # última margem
        _fechar_popups(d)
        _checar_bloqueio(d)

        etapa = "garantir_conta"
        # Troca pra conta certa (e CONFIRMA) antes de criar o post.
        # conta vazia = posta no perfil já logado.
        garantir_conta(d, conta, pasta_logs)

        etapa = "botao_criar"
        # Abre a criação pelo botão "Criar novo" do PERFIL: ele tem content-desc
        # (confiável), ao contrário do "+" do feed (ImageView sem rótulo, que
        # some/reaparece quando o feed recarrega). Fallbacks abaixo por segurança.
        if d(resourceId=f"{PACOTE_IG}:id/profile_tab").wait(timeout=12):
            d(resourceId=f"{PACOTE_IG}:id/profile_tab").click()
            time.sleep(2)
        _fechar_popups(d)

        criar = None
        alvo = d(descriptionContains="Criar novo")
        if alvo.wait(timeout=10):
            criar = alvo
        if criar is None:
            alvo2 = d(description="Criar novo") if d(description="Criar novo").exists else None
            criar = alvo2
        if criar is None:  # fallback: "+" do feed
            if d(resourceId=f"{PACOTE_IG}:id/feed_tab").exists:
                d(resourceId=f"{PACOTE_IG}:id/feed_tab").click()
                time.sleep(3)
            c = d(resourceId=f"{PACOTE_IG}:id/action_bar_buttons_container_left")
            if c.wait(timeout=10):
                criar = c
        if criar is None:  # fallback: barra inferior (versões antigas)
            criar = _achar(d, TXT_NOVA_PUBLICACAO, timeout=6)
        if criar is None:
            raise FalhaNoFluxo("Não achei o botão de criar publicação (+)")
        criar.click()
        time.sleep(4)
        _fechar_popups(d)

        etapa = "menu_criar"
        # IG set/2026: "Criar novo" abre um MENU em lista (Reel/Edits/Post/
        # Story…, itens com id `label`). Clica "Reel" ali; sem menu (versão
        # antiga), segue pro fluxo clássico das abas.
        item_menu = d(resourceId=f"{PACOTE_IG}:id/label", text="Reel")
        if item_menu.wait(timeout=8):
            item_menu.click()
            time.sleep(4)
            _fechar_popups(d)

        etapa = "aba_reel"
        # já caiu na galeria? (id da UI nova) — então não há aba pra clicar
        if not d(resourceId=f"{PACOTE_IG}:id/gallery_recycler_view").exists:
            aba = _achar(d, TXT_ABA_REEL, timeout=6)
            if aba:  # em algumas versões o composer já abre direto em Reel
                aba.click()
                time.sleep(2)

        etapa = "rascunho_pendente"
        # Se sobrou um rascunho, o IG pergunta "Continuar editando?" — começamos NOVO
        novo = _achar(d, ["Iniciar novo vídeo", "Start new video"], timeout=4)
        if novo:
            novo.click()
            time.sleep(2)

        etapa = "selecionar_video"
        # A 1ª miniatura da grade é o vídeo mais recente (o que acabamos de enviar).
        # id confirmado nesta versão: gallery_grid_item_thumbnail
        CAPTION_ID = f"{PACOTE_IG}:id/caption_input_text_view"
        thumb = d(resourceId=f"{PACOTE_IG}:id/gallery_grid_item_thumbnail")
        if not thumb.wait(timeout=15):  # espera a galeria gerar as miniaturas
            alt = d(resourceId=f"{PACOTE_IG}:id/gallery_grid").child(
                className="android.widget.CheckBox", instance=0)
            if not alt.exists:
                raise FalhaNoFluxo("Não achei a grade da galeria")
            thumb = alt
        # Toca e CONFIRMA que abriu o editor. Vídeo grande demora — se continuar
        # na galeria, toca de novo (até 3x).
        aberto = False
        for _ in range(3):
            thumb.click()  # instance 0 = mais recente
            time.sleep(5)
            if (_achar(d, TXT_AVANCAR, timeout=8) is not None
                    or d(resourceId=CAPTION_ID).exists):
                aberto = True
                break
            time.sleep(3)  # ainda carregando/na galeria; tenta de novo
        if not aberto:
            raise FalhaNoFluxo("Toquei no vídeo mas o editor não abriu")

        etapa = "avancar_editor"
        # Avança pelas telas de edição ATÉ a tela de legenda, aguardando o
        # PROCESSAMENTO do vídeo (arquivos grandes, 250MB+, demoram). Fica em
        # loop por até ~100s: se a legenda apareceu, para; se há "Avançar",
        # clica; senão espera (provavelmente processando).
        CAPTION_ID = f"{PACOTE_IG}:id/caption_input_text_view"
        fim = time.time() + 100
        while time.time() < fim:
            _fechar_popups(d)
            if d(resourceId=CAPTION_ID).exists:
                break  # chegou na tela de detalhes/legenda
            btn = _achar(d, TXT_AVANCAR, timeout=3)
            if btn is not None:
                btn.click()
                time.sleep(4)
            else:
                time.sleep(3)  # sem botão nem legenda: processando, aguarda

        etapa = "legenda"
        # Campo é AutoCompleteTextView (não EditText) — usa o resource-id.
        # Espera generosa: a tela de detalhes carrega após o processamento.
        campo = d(resourceId=CAPTION_ID)
        if not campo.wait(timeout=20):
            _garantir_ig_em_foco(d)  # overlay (ex.: promo do Edits) pode ter coberto
            if not campo.wait(timeout=10):
                raise FalhaNoFluxo("Não achei o campo de legenda")
        campo.click()
        time.sleep(1.5)
        # Variante nova do IG (2026-08-24): o toque pode abrir um EDITOR de
        # legenda em tela cheia ("Novo reel" + botão OK) onde o campo original
        # some. Digita no campo de edição que EXISTIR na tela, seja qual for.
        alvo = d(resourceId=CAPTION_ID)
        if not alvo.exists:
            alvo = d(className="android.widget.EditText")
        if not alvo.exists:
            alvo = d(className="android.widget.AutoCompleteTextView")
        if not alvo.exists:
            raise FalhaNoFluxo("Campo de legenda sumiu após o toque (variante nova?)")
        alvo.set_text(legenda)
        time.sleep(1)
        ok = d(text="OK")
        if ok.exists:
            ok.click()   # editor em tela cheia: OK volta pra tela de detalhes
        else:
            d.press("back")  # fluxo clássico: só fecha o teclado
        time.sleep(1)

        if dry_run:
            _screenshot(d, pasta_logs, "dry_run_pronto_para_compartilhar")
            apagar_do_aparelho(serial, destino_aparelho)  # limpa o arquivo enviado
            return  # PARA aqui: legenda preenchida, nada postado

        etapa = "avancar_detalhes"
        # Na tela de detalhes o botão de prosseguir é "Avançar" (id share_button)
        btn = d(resourceId=f"{PACOTE_IG}:id/share_button")
        if not btn.exists:
            btn = _achar(d, TXT_AVANCAR + TXT_COMPARTILHAR, timeout=8)
        if btn is None or (hasattr(btn, "exists") and not btn.exists):
            raise FalhaNoFluxo("Não achei o botão Avançar da tela de detalhes")
        btn.click()
        time.sleep(4)

        etapa = "compartilhar"
        _checar_bloqueio(d)
        # 1ª publicação de Reel da conta mostra o aviso "Sobre o Reels":
        # confirmar no botão Compartilhar dele. Depois disso não aparece mais.
        nux = d(resourceId=f"{PACOTE_IG}:id/clips_nux_sheet_share_button")
        if nux.exists:
            nux.click()
        else:
            fim_btn = _achar(d, TXT_COMPARTILHAR, timeout=5)
            if fim_btn:
                fim_btn.click()
        # se não houver nenhum dos dois, o "Avançar" anterior já foi o envio

        etapa = "aguardar_upload"
        # Espera o upload concluir (some o aviso e volta pro feed/perfil). 5 min.
        fim = time.time() + 300
        while time.time() < fim:
            _checar_bloqueio(d)
            ainda_na_tela = (
                d(resourceId=f"{PACOTE_IG}:id/clips_nux_sheet_share_button").exists
                or d(resourceId=f"{PACOTE_IG}:id/share_button").exists
            )
            if not ainda_na_tela:
                time.sleep(15)  # margem pro processamento do upload
                _checar_bloqueio(d)
                apagar_do_aparelho(serial, destino_aparelho)  # libera espaço
                return
            time.sleep(5)
        raise FalhaNoFluxo("Upload não concluiu em 5 minutos")

    except BloqueioDetectado:
        _screenshot(d, pasta_logs, f"BLOQUEIO_{etapa}")
        raise
    except FalhaNoFluxo:
        _screenshot(d, pasta_logs, etapa)
        raise
    except Exception as e:  # erro inesperado: registra com contexto da etapa
        _screenshot(d, pasta_logs, etapa)
        raise FalhaNoFluxo(f"Erro inesperado na etapa '{etapa}': {e}") from e


def postar_carrossel(d: u2.Device, serial: str | None, pasta_slides: Path,
                     legenda: str, pasta_logs: Path, conta: str = "",
                     dry_run: bool = False) -> None:
    """
    Publica um POST de várias fotos (carrossel): push dos slides → abrir IG →
    criar PUBLICAÇÃO (não Reel) → "Selecionar vários" → tocar os slides NA
    ORDEM → avançar → legenda → compartilhar.

    Ordem garantida por construção: os slides (slide-01..NN) são enviados em
    ORDEM REVERSA, então o slide-01 é o arquivo mais recente da galeria
    (miniatura instance 0), o slide-02 é a instance 1, e assim por diante —
    tocar as instances 0..N-1 em sequência numera a seleção em 1..N certinho.

    dry_run=True percorre TUDO e para na tela de legenda preenchida.
    Levanta FalhaNoFluxo (com screenshot) ou BloqueioDetectado.
    """
    slides = sorted(pasta_slides.glob("slide-*.png")) or sorted(pasta_slides.glob("slide-*.jpg"))
    if len(slides) < 2:
        raise FalhaNoFluxo(f"Carrossel precisa de 2+ slides; achei {len(slides)} em {pasta_slides}")
    if len(slides) > 20:
        raise FalhaNoFluxo(f"IG aceita no máximo 20 fotos; achei {len(slides)}")

    etapa = "inicio"
    destinos: list[str] = []
    try:
        etapa = "preparar_tela"
        d.screen_on(); time.sleep(1)
        d.unlock(); time.sleep(1)
        d.press("home"); time.sleep(1)

        etapa = "enviar_slides"
        # datas carimbadas por posição (slide-01 = mais novo) — a galeria ordena
        # por data e os slides renderizados juntos embaralhavam (bug 28/08)
        destinos = enviar_slides_ordenados(serial, slides)

        etapa = "abrir_app"
        d.app_start(PACOTE_IG, stop=True)
        time.sleep(6)
        (d(resourceId=f"{PACOTE_IG}:id/feed_tab").wait(timeout=25)
         or d(resourceId=f"{PACOTE_IG}:id/profile_tab").wait(timeout=5))
        _fechar_popups(d)
        _checar_bloqueio(d)

        etapa = "garantir_conta"
        garantir_conta(d, conta, pasta_logs)

        etapa = "botao_criar"
        if d(resourceId=f"{PACOTE_IG}:id/profile_tab").wait(timeout=12):
            d(resourceId=f"{PACOTE_IG}:id/profile_tab").click()
            time.sleep(2)
        _fechar_popups(d)
        criar = None
        alvo = d(descriptionContains="Criar novo")
        if alvo.wait(timeout=10):
            criar = alvo
        if criar is None:
            if d(resourceId=f"{PACOTE_IG}:id/feed_tab").exists:
                d(resourceId=f"{PACOTE_IG}:id/feed_tab").click()
                time.sleep(3)
            c = d(resourceId=f"{PACOTE_IG}:id/action_bar_buttons_container_left")
            if c.wait(timeout=10):
                criar = c
        if criar is None:
            criar = _achar(d, TXT_NOVA_PUBLICACAO, timeout=6)
        if criar is None:
            raise FalhaNoFluxo("Não achei o botão de criar publicação (+)")
        criar.click()
        time.sleep(4)
        _fechar_popups(d)

        etapa = "menu_criar"
        # IG set/2026: menu em lista — "Post" é o carrossel/fotos.
        item_menu = d(resourceId=f"{PACOTE_IG}:id/label", text="Post")
        if item_menu.wait(timeout=8):
            item_menu.click()
            time.sleep(4)
            _fechar_popups(d)

        etapa = "aba_post"
        # O composer pode abrir em Reel: muda pra PUBLICAÇÃO/POST se a aba existir.
        aba = _achar(d, TXT_ABA_POST, timeout=6)
        if aba:
            aba.click()
            time.sleep(2)

        etapa = "rascunho_pendente"
        novo = _achar(d, ["Iniciar novo vídeo", "Start new video",
                          "Iniciar novo", "Start new"], timeout=3)
        if novo:
            novo.click()
            time.sleep(2)

        etapa = "selecionar_varios"
        # Liga o modo de multi-seleção. id confirmado por diagnóstico 28/08:
        # multi_select_slide_button_alt (desc "Botão Selecionar vários").
        multi = d(resourceId=f"{PACOTE_IG}:id/multi_select_slide_button_alt")
        if not multi.wait(timeout=8):
            multi = None
            for t in TXT_SELECIONAR_VARIOS:
                sel = d(descriptionContains=t) if d(descriptionContains=t).exists else d(text=t)
                if sel.exists:
                    multi = sel
                    break
        if multi is None:
            raise FalhaNoFluxo("Não achei o botão 'Selecionar vários' da galeria")
        multi.click()
        time.sleep(2)

        etapa = "selecionar_slides"
        # A 1ª miniatura (mais recente = slide-01) já vem SELECIONADA por padrão.
        # Lemos o content-desc de cada uma ("Selecionado"/"Não selecionado") e só
        # tocamos nas não-selecionadas, na ordem das instances (0..N-1). Assim a
        # ordem do carrossel = slide-01, slide-02, ... sem risco de desmarcar a 1ª.
        thumb0 = d(resourceId=f"{PACOTE_IG}:id/gallery_grid_item_thumbnail")
        if not thumb0.wait(timeout=15):
            raise FalhaNoFluxo("Não achei a grade da galeria")
        for i in range(len(slides)):
            th = d(resourceId=f"{PACOTE_IG}:id/gallery_grid_item_thumbnail", instance=i)
            if not th.exists:
                raise FalhaNoFluxo(f"Miniatura {i} não existe na grade (esperava {len(slides)})")
            desc = ((th.info or {}).get("contentDescription") or "").strip().lower()
            # "Selecionado ..." / "Selected ..." = já na seleção; "Não selecionado"
            # / "Not selected" / "Unselected" = fora. startswith separa os dois.
            if desc.startswith("selecionado") or desc.startswith("selected"):
                continue  # mantém a posição, não desmarca
            th.click()
            time.sleep(1.2)

        etapa = "avancar_galeria"
        btn = d(resourceId=f"{PACOTE_IG}:id/next_button_textview")
        if not btn.exists:
            btn = _achar(d, TXT_AVANCAR, timeout=8)
        if btn is None or (hasattr(btn, "exists") and not btn.exists):
            raise FalhaNoFluxo("Não achei o Avançar da galeria (multi-seleção)")
        btn.click()
        time.sleep(4)

        etapa = "avancar_ate_legenda"
        CAPTION_ID = f"{PACOTE_IG}:id/caption_input_text_view"
        fim = time.time() + 90
        while time.time() < fim:
            _checar_bloqueio(d)
            if d(resourceId=CAPTION_ID).exists:
                break
            _fechar_popups(d)
            btn = d(resourceId=f"{PACOTE_IG}:id/next_button_textview")
            if not btn.exists:
                btn = _achar(d, TXT_AVANCAR, timeout=4)
            if btn is not None and (not hasattr(btn, "exists") or btn.exists):
                btn.click()
                time.sleep(4)
            else:
                time.sleep(3)
        if not d(resourceId=CAPTION_ID).exists:
            raise FalhaNoFluxo("Não cheguei na tela de legenda do post")

        etapa = "legenda"
        campo = d(resourceId=CAPTION_ID)
        campo.click()
        time.sleep(1.5)
        alvo = d(resourceId=CAPTION_ID)
        if not alvo.exists:
            alvo = d(className="android.widget.EditText")
        if not alvo.exists:
            alvo = d(className="android.widget.AutoCompleteTextView")
        if not alvo.exists:
            raise FalhaNoFluxo("Campo de legenda sumiu após o toque")
        alvo.set_text(legenda)
        time.sleep(1)
        ok = d(text="OK")
        if ok.exists:
            ok.click()
        else:
            d.press("back")
        time.sleep(1)

        if dry_run:
            _screenshot(d, pasta_logs, "dry_run_carrossel_pronto")
            for dst in destinos:
                apagar_do_aparelho(serial, dst)
            return

        etapa = "compartilhar"
        _checar_bloqueio(d)
        btn = d(resourceId=f"{PACOTE_IG}:id/share_button")
        if not btn.exists:
            btn = _achar(d, TXT_COMPARTILHAR + TXT_AVANCAR, timeout=8)
        if btn is None or (hasattr(btn, "exists") and not btn.exists):
            raise FalhaNoFluxo("Não achei o botão Compartilhar do post")
        btn.click()

        etapa = "aguardar_upload"
        fim = time.time() + 300
        while time.time() < fim:
            _checar_bloqueio(d)
            if not d(resourceId=f"{PACOTE_IG}:id/share_button").exists:
                time.sleep(15)
                _checar_bloqueio(d)
                for dst in destinos:
                    apagar_do_aparelho(serial, dst)
                return
            time.sleep(5)
        raise FalhaNoFluxo("Upload do carrossel não concluiu em 5 minutos")

    except BloqueioDetectado:
        _screenshot(d, pasta_logs, f"BLOQUEIO_{etapa}")
        raise
    except FalhaNoFluxo:
        _screenshot(d, pasta_logs, etapa)
        raise
    except Exception as e:
        _screenshot(d, pasta_logs, etapa)
        raise FalhaNoFluxo(f"Erro inesperado na etapa '{etapa}' do carrossel: {e}") from e
