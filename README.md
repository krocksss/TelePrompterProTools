<p align="center">
  <img src="static/autor.png" width="96" alt="Marllon Machado"><br>
  <b>Prompter</b> · teleprompter sincronizado com o Pro Tools<br>
  feito por <a href="https://github.com/krocksss"><b>Marllon Machado (krocksss)</b></a>
</p>

# Prompter · teleprompter sincronizado com o Pro Tools

Roda no MESMO computador do Pro Tools (Windows ou macOS), na bandeja, quase sem consumo. Ao dar play no
Pro Tools a letra aparece na linha certa, palavra por palavra, num segundo monitor. Dar play no estúdio do
Prompter também faz o Pro Tools tocar (e vice-versa). O show continua rodando no Pro Tools: o Prompter só
sincroniza a exibição do texto com a música.

## Baixar e instalar (uma interação)
**[⬇ Downloads (Releases)](https://github.com/krocksss/TelePrompterProTools/releases/latest)**

| Sistema | Arquivo | O que fazer |
|---|---|---|
| Windows 10/11 | `PrompterSetup-x.y.z.exe` | Executar → **Instalar**. Instala o Prompter **e o loopMIDI** (porta MIDI virtual) de uma vez. Pede permissão de administrador uma vez. |
| macOS (Apple Silicon) | `Prompter-x.y.z-mac-arm64.dmg` | Arrastar para Aplicativos. Na 1ª vez: botão direito → **Abrir** (app não assinado pela Apple). |
| macOS (Intel) | `Prompter-x.y.z-mac-x86_64.dmg` | idem |

Toda vez que abrir o Prompter: ele **abre o Pro Tools junto** e abre a **tela do teleprompter no navegador**
(`http://localhost:8797`) com os botões **✎ Editar letra**, **♪ Transcrever faixa** e **⚙ Configuração**
(aparecem ao mover o mouse). A sessão aberta no Pro Tools entra sozinha na biblioteca e é transcrita em
segundo plano (na 1ª vez baixa o modelo de transcrição, ~1,6 GB).

O Prompter olha o GitHub (releases) e avisa quando há versão nova; no Windows atualiza com um clique.

## Como sincroniza (duas fontes, juntas)
- **PTSL** (Pro Tools Scripting Library, gRPC em localhost:31416, Pro Tools ≥ 2022.12, inclusive o Intro):
  sem driver, sem configuração. Dá nome/caminho da sessão, play/stop, cursor, e COMANDA o Pro Tools
  (play, stop, locate). Posição durante o play = ponto de partida + relógio local (erro típico 0,03 s,
  às vezes 0,2 s pelo arranque do Pro Tools). Comprovado no Pro Tools Intro 2026.4.1.
- **MTC** (opcional, "precisão máxima"): timecode MIDI frame a frame. Windows: loopMIDI (instalado junto)
  com a porta "Pro Tools MTC". macOS: o Prompter cria a porta virtual sozinho. No Pro Tools, uma vez:
  Setup › Peripherals › Synchronization › MTC Generator Port = "Pro Tools MTC" e botão **Gen MTC** aceso.

## Transcrição (validada em "8 SEGUNDOS", 3m45, CPU)
1. PyAV converte qualquer áudio para WAV (não depende de ffmpeg instalado).
2. Demucs htdemucs isola a voz, em processo filho de prioridade baixa (`Prompter --demucs in out`), ~2 min.
3. faster-whisper **large-v3-turbo** int8, vad_filter=False (o VAD descarta voz cantada), beam 5, tempo por
   palavra. Medido contra a letra corrigida: **turbo 2,9% de erro de palavra**, medium 27,5%.
4. Filtros de alucinação, quebra de verso por pausa/pontuação/tamanho. Nunca roda enquanto o Pro Tools toca.
5. Letra EXATA: `letra.txt` na pasta da música ou "letra oficial (colar)" no estúdio → cada verso é casado
   com as palavras ouvidas e recebe o tempo real (palavra a palavra).
6. "♪ Transcrever faixa": escolhe qual arquivo/faixa da sessão transcrever.

## Estúdio de letras (/estudio)
Forma de onda com cursor e marca de cada verso, lista de versos com tempo e texto. `▶` comanda o Pro Tools
(botão 🔗 aceso) ou o áudio local. `Enter` = "este verso começa AGORA" (marcação por toque), `Ctrl+Enter`
divide, `Backspace` no início junta, `Alt+←/→` ±2 s, salva sozinho. "realinhar com o áudio" recalcula os
tempos pelas palavras ouvidas depois de corrigir o texto.

## Teclas no teleprompter
`F` tela cheia · `espaço` play/stop no Pro Tools · `←` `→` linha na mão · `A` automático.

## Compilar
```
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu   # + pywin32 pyinstaller
.\build\build.ps1            # Windows: dist\PrompterSetup-<v>.exe (Inno Setup + loopMIDI em build\vendor)
bash build/mac/build.sh      # macOS: dist/Prompter-<v>-mac-<arch>.dmg
```
O GitHub Actions (`.github/workflows/build.yml`) gera os três instaladores e publica na Release a cada tag `v*`.
Dados do usuário: Windows `%LOCALAPPDATA%\Prompter\data`, macOS `~/Library/Application Support/Prompter/data`.

## Rodar do fonte
```
python app.py                      # ou .\subir.ps1 (bandeja)
python fake_protools.py "Nome"     # simula o Pro Tools por MTC (precisa loopMIDI)
```

## GOTCHAs
- PTSL: `GetTransportState` responde em ~30 ms; não existe "posição durante o play" (por isso o relógio local).
  Com "insertion follows playback" desligado o cursor volta ao ponto de partida ao parar (o app segue isso).
- Pro Tools no Windows é MDI: "Edit: Sessão" é janela FILHA de DigiAppWndClass (reserva quando não há PTSL).
- MTC só sai com o botão Gen MTC aceso; escolher a porta em Peripherals não basta.
- `tasklist`/`winget` saem em codepage OEM: nunca `text=True` sem `errors="replace"`.
- Mesma música em dois lugares (MP3 na pasta + sessão) = mesmo id; os áudios se somam.
- "localhost" no Windows tenta IPv6 → aiohttp `host=None`.

---
Crédito: **Marllon Machado** · [github.com/krocksss](https://github.com/krocksss). loopMIDI é de Tobias Erichsen
([tobias-erichsen.de](https://www.tobias-erichsen.de/software/loopmidi.html)), instalador oficial incluído sem alterações.
