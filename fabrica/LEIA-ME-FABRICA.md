# Fábrica de Reels da Myriad

**Contrato: roteiro (modelo MYRIAD) + áudio entram → vídeo pronto sai.**

## Setup (uma vez)

1. **Edits dos personagens:** jogue os edits (9:16, com o conteúdo já enquadrado
   abaixo da área da headline) em `fabrica/edits/harvey/` e `fabrica/edits/jane/`.
   Sem processamento: cada vídeo usa um TRECHO CONTÍNUO de um edit como fundo,
   no ritmo original da tua edição. O sorteio escolhe o edit e o trecho, e nunca
   repete o edit do vídeo anterior. O edit precisa ser mais longo que a narração.
2. **Trilhas:** jogue 8+ músicas em `fabrica/trilhas/` (mp3/wav). O sorteio gira sozinho.
3. **Fonte (opcional):** o padrão é Playfair Display (já baixada). Se tiver a fonte
   original dos teus vídeos, salve como `fabrica/fontes/HeadlineMyriad.ttf` e/ou
   `fabrica/fontes/KaraokeMyriad.ttf` que a fábrica passa a usar.

## Por vídeo (o teu trabalho diário)

Deixe DOIS arquivos em `fabrica/entrada/`, com o MESMO nome (o "slug"):

- `desconto-plateia.mp3` — o áudio (só a voz; a trilha é da fábrica)
- `desconto-plateia.txt` — o roteiro neste modelo:

```
personagem: harvey
headline: SE ELE PEDIR DESCONTO NA FRENTE DOS OUTROS
---
Olha o que ele fez ali.
Ele não pediu desconto, pediu *plateia*.
Responda o valor com a mesma *calma* de antes.
---
Você já passou por isso numa mesa cheia?

Quem pede desconto na frente dos outros quer pressão social, não preço.
```

- `personagem:` harvey ou jane — os clipes saem SÓ do banco dele
- `*palavra*` no texto falado = destaque dourado no karaokê
- terceira seção = legenda do post (vai junto pro postador)

## Comandos

```
python -m fabrica.fabrica --video desconto-plateia   # produz 1
python -m fabrica.fabrica --lote                     # produz tudo que falta
python -m fabrica.fabrica --prova                    # PNG do 1º quadro de cada vídeo
python -m fabrica.fabrica --entregar desconto-plateia exemplo.corp "2026-08-24 12:00"
```

`--entregar` copia o vídeo + legenda pra `videos/` do postador e agenda na fila.

## O que a fábrica valida ANTES de renderizar (reprova em vez de sair torto)

1. A transcrição do teu áudio bate com o texto do roteiro (≥80% das palavras) —
   se não bater, ela lista as palavras que não confirmou.
2. Existe edit do personagem declarado (o fundo sai SÓ da pasta dele).
3. A headline cabe na caixa do topo em até 2 linhas — headline comprida demais
   é reprovada com aviso pra encurtar (nunca renderiza por cima do vídeo; a
   tarja preta do topo garante isso em qualquer cena). Quebra manual: use `/`.

## Se der errado

- Reprovou: leia o motivo impresso — é sempre um dos 3 acima.
- Primeira transcrição demora (baixa o modelo do Whisper ~460MB, uma vez só).
- Erro de ffmpeg: a linha de comando inteira é impressa — manda pro Claude.
