# -*- coding: utf-8 -*-
"""Diagnóstico: navega até a galeria do composer de POST e despeja a
hierarquia pra achar os IDs reais (botão 'Selecionar vários', miniaturas,
Avançar). Não posta nada. Uso: python diag_carrossel.py exemplo.social"""
import sys
import time
from pathlib import Path

import driver_instagram as ig

conta = sys.argv[1] if len(sys.argv) > 1 else ""
PACOTE = ig.PACOTE_IG
LOGS = Path(__file__).parent / "logs"

d = ig.conectar(None)
d.screen_on(); time.sleep(1)
d.unlock(); time.sleep(1)
d.app_start(PACOTE, stop=True)
time.sleep(6)
ig._fechar_popups(d)
ig.garantir_conta(d, conta, LOGS)

# abre criação
if d(resourceId=f"{PACOTE}:id/profile_tab").wait(timeout=12):
    d(resourceId=f"{PACOTE}:id/profile_tab").click(); time.sleep(2)
ig._fechar_popups(d)
alvo = d(descriptionContains="Criar novo")
if alvo.wait(timeout=10):
    alvo.click()
time.sleep(4)
ig._fechar_popups(d)

# aba POST
aba = ig._achar(d, ig.TXT_ABA_POST, timeout=6)
if aba:
    aba.click(); time.sleep(2)
novo = ig._achar(d, ["Iniciar novo vídeo", "Start new video", "Iniciar novo"], timeout=3)
if novo:
    novo.click(); time.sleep(2)

time.sleep(2)
xml = d.dump_hierarchy()
saida = LOGS / "diag_carrossel.xml"
saida.write_text(xml, encoding="utf-8")
d.screenshot(str(LOGS / "diag_carrossel.png"))

# resumo dos elementos clicáveis com id/desc/text úteis
import re
print("== elementos com 'select'/'multi'/'carousel'/'next' no id/desc ==")
for m in re.finditer(r'<node[^>]+>', xml):
    tag = m.group(0)
    rid = re.search(r'resource-id="([^"]*)"', tag)
    desc = re.search(r'content-desc="([^"]*)"', tag)
    txt = re.search(r'text="([^"]*)"', tag)
    blob = " ".join(x.group(1) for x in (rid, desc, txt) if x and x.group(1))
    if re.search(r'select|multi|carousel|next|avan|gallery|picker', blob, re.I):
        print(f"  id={rid.group(1) if rid else '':45} desc={desc.group(1) if desc else '':20} text={txt.group(1) if txt else ''}")
print(f"\nXML completo: {saida}")
print(f"screenshot: {LOGS / 'diag_carrossel.png'}")
ig.apagar_tela(d)
