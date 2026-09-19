# -*- coding: utf-8 -*-
"""Testes do guarda de foco: overlay de outro app (ex.: Play Store com a promo
do Edits) deve ser dispensado com "voltar" até o IG reassumir."""

from driver_instagram import PACOTE_IG, _garantir_ig_em_foco


class AparelhoFalso:
    """Simula d.app_current()/d.press(): cada 'back' avança pro próximo foco."""

    def __init__(self, focos):
        self.focos = list(focos)
        self.backs = 0

    def app_current(self):
        return {"package": self.focos[0]}

    def press(self, tecla):
        assert tecla == "back"
        self.backs += 1
        if len(self.focos) > 1:
            self.focos.pop(0)


def test_ig_em_foco_nao_faz_nada():
    d = AparelhoFalso([PACOTE_IG])
    _garantir_ig_em_foco(d, pausa=0)
    assert d.backs == 0


def test_play_store_em_foco_volta_ate_o_ig():
    d = AparelhoFalso(["com.android.vending", PACOTE_IG])
    _garantir_ig_em_foco(d, pausa=0)
    assert d.backs == 1
    assert d.app_current()["package"] == PACOTE_IG


def test_overlay_teimoso_desiste_apos_max_back():
    d = AparelhoFalso(["com.android.vending"])
    _garantir_ig_em_foco(d, max_back=4, pausa=0)
    assert d.backs == 4  # tentou, desistiu — quem decide o erro é o chamador


class _Sel:
    def __init__(self, existe, ao_clicar=None):
        self.exists = existe
        self._ao_clicar = ao_clicar

    def click(self):
        if self._ao_clicar:
            self._ao_clicar()


class TelaFalsa:
    """Simula d(text=...)/d(textContains=...) pro diálogo de troca bloqueada."""

    def __init__(self, com_dialogo):
        self.com_dialogo = com_dialogo
        self.ok_clicado = False

    def _fechar(self):
        self.ok_clicado = True
        self.com_dialogo = False

    def __call__(self, **kw):
        if kw.get("textContains") and "não pode trocar" in kw["textContains"]:
            return _Sel(self.com_dialogo)
        if kw.get("text") == "OK":
            return _Sel(self.com_dialogo, ao_clicar=self._fechar)
        return _Sel(False)


def test_dialogo_de_troca_bloqueada_e_dispensado_com_ok():
    from driver_instagram import _troca_bloqueada
    d = TelaFalsa(com_dialogo=True)
    assert _troca_bloqueada(d) is True
    assert d.ok_clicado is True


def test_sem_dialogo_nao_clica_nada():
    from driver_instagram import _troca_bloqueada
    d = TelaFalsa(com_dialogo=False)
    assert _troca_bloqueada(d) is False
    assert d.ok_clicado is False


class TelaComSheetEdits:
    """Simula a bottom-sheet da promo do Edits (28/08): botão "Baixar app"
    dentro do próprio IG. Um "voltar" fecha a sheet."""

    def __init__(self, com_sheet):
        self.com_sheet = com_sheet
        self.backs = 0
        self.baixar_clicado = False

    def __call__(self, **kw):
        if kw.get("text") in ("Baixar app", "Download app"):
            return _Sel(self.com_sheet, ao_clicar=self._clicou_baixar)
        return _Sel(False)

    def _clicou_baixar(self):
        self.baixar_clicado = True

    def press(self, tecla):
        assert tecla == "back"
        self.backs += 1
        self.com_sheet = False


def test_sheet_do_edits_fecha_com_voltar_sem_clicar_baixar():
    from driver_instagram import _fechar_sheet_edits
    d = TelaComSheetEdits(com_sheet=True)
    assert _fechar_sheet_edits(d) is True
    assert d.backs == 1
    assert d.baixar_clicado is False


def test_sem_sheet_do_edits_nao_aperta_nada():
    from driver_instagram import _fechar_sheet_edits
    d = TelaComSheetEdits(com_sheet=False)
    assert _fechar_sheet_edits(d) is False
    assert d.backs == 0


def test_falha_ao_ler_foco_nao_aperta_nada():
    class SemLeitura:
        def __init__(self):
            self.backs = 0

        def app_current(self):
            raise RuntimeError("uiautomator fora do ar")

        def press(self, tecla):
            self.backs += 1

    d = SemLeitura()
    _garantir_ig_em_foco(d, pausa=0)
    assert d.backs == 0
