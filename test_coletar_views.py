# -*- coding: utf-8 -*-
"""Testes da coleta de views (calibração 2026-08-24): parse do content-desc
das miniaturas e alinhamento de lotes entre rolagens da grade."""

from driver_instagram import _views_de_desc, _alinhar_lote


# --- _views_de_desc -------------------------------------------------------

def test_desc_real_do_a03s():
    d = ("Reel de exemplo.corp. Número de visualizações 141. "
         "Toque duas vezes para reproduzir ou pausar.")
    assert _views_de_desc(d) == 141


def test_desc_com_milhar():
    d = "Reel de exemplo.group. Número de visualizações 7,2 mil. Toque duas vezes."
    assert _views_de_desc(d) == 7200


def test_desc_sem_contador_retorna_none():
    # Reel recém-postado ainda processando: desc sem o trecho de views
    d = "Reel de exemplo.corp. Toque duas vezes para reproduzir ou pausar."
    assert _views_de_desc(d) is None


def test_painel_de_30_dias_nao_e_confundido():
    # O card "Seu painel" tem 'visualizações' mas o número vem ANTES — o
    # regex ancora no número DEPOIS da palavra, então não deve casar o 991.
    assert _views_de_desc("991 visualizações nos últimos 30 dias.") is None


def test_desc_vazio_ou_none():
    assert _views_de_desc("") is None
    assert _views_de_desc(None) is None


# --- _alinhar_lote --------------------------------------------------------

def test_primeiro_lote_entra_inteiro():
    assert _alinhar_lote([], ["a", "b", "c"]) == ["a", "b", "c"]


def test_sobreposicao_normal():
    assert _alinhar_lote(["a", "b", "c"], ["b", "c", "d", "e"]) == ["d", "e"]


def test_lote_repetido_nao_traz_nada():
    assert _alinhar_lote(["a", "b", "c"], ["a", "b", "c"]) == []


def test_fim_de_grade_lote_e_sufixo():
    assert _alinhar_lote(["a", "b", "c", "d"], ["c", "d"]) == []


def test_contagens_duplicadas_alinham_por_sequencia():
    # dois reels com o MESMO desc (mesma contagem): dedup por valor erraria,
    # alinhamento por sobreposição de sequência não
    vistos = ["x=10", "x=8", "x=8"]
    lote = ["x=8", "x=8", "x=15", "x=9"]
    assert _alinhar_lote(vistos, lote) == ["x=15", "x=9"]


def test_sem_sobreposicao_lote_inteiro_e_novo():
    assert _alinhar_lote(["a", "b"], ["c", "d"]) == ["c", "d"]


# --- preparo da tela ------------------------------------------------------
# Bug de 03/09: a coleta falhou nas 5 contas com "Aba de perfil não apareceu".
# A causa real era outra: a tela estava DORMINDO (mWakefulness=Dozing) e as
# capturas saíam pretas. O caminho de postar acorda o aparelho antes; o de
# coletar não acordava. Mensagem errada custou uma rodada de diagnóstico.

class _AparelhoFalso:
    """Registra a ordem das chamadas — é a ordem que importa aqui."""
    def __init__(self):
        self.chamadas = []

    def screen_on(self):
        self.chamadas.append("screen_on")

    def unlock(self):
        self.chamadas.append("unlock")

    def press(self, tecla):
        self.chamadas.append(f"press:{tecla}")


def test_preparar_tela_acorda_desbloqueia_e_vai_pra_home():
    from driver_instagram import preparar_tela
    d = _AparelhoFalso()

    preparar_tela(d, dormir=lambda s: None)

    assert d.chamadas == ["screen_on", "unlock", "press:home"]


def test_preparar_tela_e_seguro_com_aparelho_ja_acordado():
    """Chamar de novo não pode quebrar: a coleta roda conta a conta."""
    from driver_instagram import preparar_tela
    d = _AparelhoFalso()
    preparar_tela(d, dormir=lambda s: None)
    preparar_tela(d, dormir=lambda s: None)
    assert d.chamadas.count("screen_on") == 2


def test_preparar_tela_abre_o_instagram_do_zero():
    """Bug 03/09 (2ª camada): a tela acordou, mas o app nunca foi aberto — a
    captura mostrou a TELA INICIAL do Android. O caminho de postar abre o app
    com app_start(stop=True); o de coletar assumia o app já aberto e só
    funcionava por acidente, quando a coleta rodava logo após uma postagem."""
    from driver_instagram import preparar_tela, PACOTE_IG

    class _ComApp(_AparelhoFalso):
        def app_start(self, pacote, stop=False):
            self.chamadas.append(f"app_start:{pacote}:{stop}")

        def __call__(self, **kw):
            class _Sel:
                exists = True
                def wait(self, timeout=0): return True
                def click(self): pass
            return _Sel()

    d = _ComApp()
    preparar_tela(d, dormir=lambda s: None, abrir_app=True)

    assert f"app_start:{PACOTE_IG}:True" in d.chamadas
    assert d.chamadas.index("press:home") < d.chamadas.index(f"app_start:{PACOTE_IG}:True")


def test_preparar_tela_sem_abrir_app_continua_igual():
    """Regressão: quem só quer acordar a tela não passa a abrir o app junto."""
    from driver_instagram import preparar_tela
    d = _AparelhoFalso()
    preparar_tela(d, dormir=lambda s: None)
    assert not any(c.startswith("app_start") for c in d.chamadas)
