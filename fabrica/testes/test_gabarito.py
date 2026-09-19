import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from fabrica import gabarito


DIR_FONTES = Path(__file__).parents[1] / "fontes"


def test_moldura_tarja_no_topo_e_resto_transparente():
    im = gabarito.desenhar_moldura("SE ELE PEDIR DESCONTO NA FRENTE DOS OUTROS", DIR_FONTES)
    assert im.size == (1080, 1920)
    assert im.mode == "RGBA"
    # abaixo da tarja: transparente (o edit do operador aparece inteiro)
    for xy in [(540, gabarito.TOPO_PRETO + 10), (540, 1150), (100, 1700), (980, 500)]:
        assert im.getpixel(xy)[3] == 0, f"deveria ser transparente em {xy}"
    # tarja do topo: preta opaca (headline nunca cai sobre imagem) —
    # sondas FORA da caixa da headline, onde só pode haver tarja
    for xy in [(540, 10), (25, 300), (1060, 415), (540, 100)]:
        r, g, b, a = im.getpixel(xy)
        assert a == 255 and r < 30, f"tarja do topo não é preta opaca em {xy}"


def test_headline_dentro_da_caixa_e_nunca_fora_da_tarja():
    im = gabarito.desenhar_moldura("SE ELE PEDIR DESCONTO NA FRENTE DOS OUTROS", DIR_FONTES)
    hx0, hy0, hx1, hy1 = gabarito.CAIXA_HEADLINE
    achou_branco = False
    for y in range(0, 1920, 2):
        for x in range(0, 1080, 4):
            r, g, b, a = im.getpixel((x, y))
            if a > 0 and r > 200 and g > 200 and b > 200:
                achou_branco = True
                assert hy0 <= y <= hy1, f"texto branco fora da caixa da headline: y={y}"
                assert y < gabarito.TOPO_PRETO, f"texto abaixo da tarja preta: y={y}"
    assert achou_branco, "headline não foi desenhada"


def test_headline_gigante_reprova():
    with pytest.raises(gabarito.HeadlineNaoCabe):
        gabarito.desenhar_moldura(
            "UMA HEADLINE ABSURDAMENTE COMPRIDA QUE NAO TEM COMO CABER "
            "EM DUAS LINHAS DENTRO DA CAIXA DO TOPO DE JEITO NENHUM MESMO", DIR_FONTES)
