# -*- coding: utf-8 -*-
"""Diagnóstico: replica a preparação do driver, abre o IG, e despeja
a árvore limpa do feed + lista os elementos clicáveis (pra achar o botão +)."""
import time
import uiautomator2 as u2

d = u2.connect()
d.screen_on()
time.sleep(1)
d.unlock()
time.sleep(1)
d.press("home")
time.sleep(1)
d.app_start("com.instagram.android", stop=True)
time.sleep(9)

xml = d.dump_hierarchy()
open("logs/feed.xml", "w", encoding="utf-8").write(xml)
print("=== feed.xml salvo:", len(xml), "chars ===\n")

print("=== ELEMENTOS CLICÁVEIS (desc | text | resource-id) ===")
for el in d.xpath("//*[@clickable='true']").all():
    info = el.attrib
    desc = info.get("content-desc", "")
    text = info.get("text", "")
    rid = info.get("resource-id", "")
    if desc or text or rid:
        print(f"  [{desc}] | [{text}] | {rid}")
