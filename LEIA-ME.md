# Myriad — postador automático de Reels (on-device)

Sistema que posta Reels e carrosséis no Instagram **pelo próprio celular Android**
(via ADB/uiautomator2), sem API — como um humano tocando na tela. Inclui:

- **Myriad** (`myriad.bat`) — painel de controle em `http://127.0.0.1:8776`:
  visão geral, aparelhos, contas, posts, biblioteca, automação.
- **Postador** (`iniciar.bat`) — o robô que executa a fila (com vigia que
  relança se cair).
- **Agendador** (`agendar.bat`) — larga vídeo + legenda em `videos/` e ele
  enfileira sozinho.
- **Fábrica** (`fabrica/`) — gera os Reels (headline serifada + karaokê de
  legenda + trilha) a partir de roteiro + áudio.

## Requisitos

- Windows com **Python 3.11+** (`pip install -r requirements.txt`)
- **ADB** no PATH (platform-tools do Android)
- **ffmpeg** no PATH (só para a fábrica de vídeos)
- Um celular Android com **Depuração USB** ativa e o Instagram logado na(s)
  conta(s) que vão postar

## Primeiros passos

1. `pip install -r requirements.txt`
2. Plugue o celular via USB e autorize a depuração.
3. Edite `config.json`: preencha `contas_agendamento` com o(s) @ da(s) conta(s)
   e ajuste `max_posts_dia` / janela de horários.
4. `myriad.bat` → abre o painel na porta 8776.
5. Coloque um `.mp4` + um `.txt` (legenda, mesmo nome) em `videos/` e agende
   pela Biblioteca do painel (ou rode `agendar.bat`).
6. `iniciar.bat` liga o robô.

## Estrutura de dados (criada em uso, fora do git)

- `fila.csv` — a fila de posts (conta, arquivo, quando, status, views)
- `estado.json` — estado do robô
- `logs/` — logs e capturas de diagnóstico
- `videos/<conta>/` — estoque dedicado de uma conta específica

## Avisos

- Cadência conservadora por design (posts/dia + espaçamento mínimo + jitter):
  automação de postagem viola os termos do Instagram e contas podem ser
  penalizadas. Use em conta que você aceita arriscar, e suba o ritmo devagar.
- O painel e o robô usam o MESMO aparelho — não rode dois robôs no mesmo
  celular ao mesmo tempo.
- 1ª vez em um aparelho novo pode exigir calibração dos seletores do app
  (`python postador.py --diag-alcance <conta>` gera `logs/alcance_diag.png/.xml`
  para ajuste).

## Testes

```
python -m pytest -q
```
