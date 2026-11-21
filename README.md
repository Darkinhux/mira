# Mira — roda de atalhos no Mouse 4

Segure o **Mouse 4** (botão lateral do mouse), aponte para um atalho e solte.

![Roda de atalhos](docs/roda.gif)

Visual neon/ciberpunk: brilho de verdade (transparência por pixel), anéis girando,
scanlines, pulso na opção escolhida e um glitch rápido quando a roda abre.

- **Segurar e soltar:** segure o Mouse 4, mova o mouse na direção do atalho e solte.
- **Clique rápido:** um toque no Mouse 4 deixa a roda aberta; aí é só clicar no atalho.
- **Fechar:** `Esc`, botão direito, clicar no centro ou apertar o Mouse 4 de novo.
- O Mouse 4 deixa de funcionar como "Voltar" no navegador enquanto o Mira estiver aberto.

Atalhos que já vêm prontos: Steam, Discord, recorte de tela, print da tela inteira,
navegador, explorador de arquivos, play/pause de música e gerenciador de tarefas.

## Instalação (Windows 10/11)

1. Instale o [Python 3.11 ou mais novo](https://www.python.org/downloads/) e marque
   **"Add python.exe to PATH"** na instalação.
2. Baixe esta pasta e dê dois cliques em **`instalar.bat`**.
3. Dê dois cliques em **`iniciar.bat`**. Vai aparecer um ícone perto do relógio.

Para abrir junto com o Windows, clique com o botão direito no ícone perto do relógio
e marque **"Iniciar com o Windows"**.

## Recorte de tela

Escolha **Recortar**, arraste um retângulo e solte. A imagem é **copiada** (é só colar
com `Ctrl+V` no Discord, por exemplo) e **salva** em `Imagens\Mira`. Clique no aviso
que aparece para abrir a imagem. `Esc` ou o botão direito cancelam.

## Personalizar os atalhos

Clique com o botão direito no ícone perto do relógio → **Editar atalhos**, mude o
`config.json` e depois → **Recarregar atalhos**. A roda aceita de 2 a 12 itens.

```json
{ "name": "Spotify",  "icon": "🎵", "type": "open",  "target": "spotify:" }
{ "name": "Valorant", "icon": "🔫", "type": "open",  "target": "C:\\Riot Games\\Riot Client\\RiotClientServices.exe",
  "args": ["--launch-product=valorant", "--launch-patchline=live"] }
{ "name": "YouTube",  "icon": "▶️", "type": "open",  "target": "https://youtube.com" }
{ "name": "Mutar",    "icon": "🔇", "type": "keys",  "keys": "media_volume_mute" }
{ "name": "Bloquear", "icon": "🔒", "type": "keys",  "keys": "win+l" }
{ "name": "Desligar", "icon": "⏻",  "type": "command", "command": "shutdown /s /t 60" }
{ "name": "Recortar", "icon": "✂️", "type": "snip" }
{ "name": "Print",    "icon": "🖥️", "type": "screenshot" }
```

| `type`       | O que faz                                                              | Campos            |
|--------------|------------------------------------------------------------------------|-------------------|
| `open`       | Abre programa, pasta, site ou protocolo (`steam://`, `discord://`…)    | `target`, `args`  |
| `keys`       | Aperta uma combinação de teclas (`ctrl+shift+esc`, `win+e`, `media_next`) | `keys`         |
| `command`    | Roda um comando do Prompt                                              | `command`         |
| `snip`       | Recorte de uma área da tela                                            | —                 |
| `screenshot` | Print de todas as telas                                                | —                 |

O `icon` pode ser um emoji ou o caminho de uma imagem (`.png`, `.ico`…), por exemplo
`"icons/steam.png"`. Caminhos podem usar `%LOCALAPPDATA%` e afins.

Atalhos de jogos da Steam: `"target": "steam://rungameid/730"` (troque o número pelo ID do jogo).

Outras opções do `config.json` (troque as cores para criar seu tema — ex.: `neon` `#f9f002` e `accent` `#00f0ff`):

| Opção               | Padrão              | Descrição                                     |
|---------------------|---------------------|-----------------------------------------------|
| `trigger`           | `mouse4`            | `mouse4`, `mouse5` ou `middle` (roda do mouse) |
| `radius`            | `170`               | Tamanho da roda                               |
| `inner_radius`      | `55`                | Tamanho do círculo do meio                    |
| `neon`              | `#00f0ff`           | Cor neon principal (linhas e textos)          |
| `accent`            | `#ff2a6d`           | Cor de destaque (opção escolhida, cantoneiras) |
| `background`        | `#0b0b16`           | Cor de fundo das fatias                       |
| `animations`        | `true`              | `false` desliga as animações (PC mais fraco)  |
| `screenshot_folder` | `~/Pictures/Mira`   | Onde os prints são salvos                     |

## Problemas comuns

- **A roda não aparece no jogo:** jogos em *tela cheia exclusiva* ficam por cima de tudo.
  Use o modo **"janela sem bordas" (borderless)** nas configurações do jogo.
- **Não funciona em programas abertos como administrador:** o Windows bloqueia isso.
  Execute o Mira como administrador também.
- **Algo deu errado:** veja o arquivo `mira.log` nesta pasta.
