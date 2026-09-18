# Mensagens de estado do Prompter

Trabalho de 18/set/2026 sobre a camada de feedback ao usuário (teleprompter, estúdio, configuração).
Nada do fluxo do app mudou: transcrição, PTSL, sessões e pastas fazem exatamente o que faziam. O que mudou é
**o que o usuário lê enquanto espera** e **de onde esse texto vem**.

## O problema

"Quando dá play na música e o app vai instalar o modelo antes de dar play, ele usa o mesmo espaço/mensagem da
transcrição da música."

O que o código fazia:

- O backend mandava **só texto solto**: `progresso.etapa` ("baixando modelo de transcrição (só uma vez, 1620 MB)",
  "isolando a voz", "ouvindo a letra"...). As telas não tinham como saber *em que fase* estavam; só repetiam o texto.
- No estúdio existe **um único bloco** (`#guide`). Ao apertar play, `togglePlay()` escrevia ali "Carregando a música
  no Pro Tools", mas cada evento SSE com `progresso` chamava `renderGuide()`, que **reescrevia o bloco com a
  transcrição** ("baixando modelo 42%"). A mensagem do play sumia no meio.
- No teleprompter, baixar modelo, isolar voz e transcrever usavam a mesma tela `#msg`, com o mesmo visual: título =
  nome da música, subtítulo = texto do `etapa` + "A letra aparece aqui quando terminar".
- O preparo do Pro Tools para o play (converter áudio, fechar a sessão anterior, abrir/criar sessão, importar na faixa 1)
  **não tinha nenhum progresso no backend**; o estúdio inventava um texto genérico no cliente.
- O ramo "sessão sem áudio" do guia era inalcançável (a checagem "outra sessão" vinha antes e vencia sempre), então
  o guia dizia "troca para a sessão desta música" numa situação em que o backend na verdade **coloca a música na
  sessão vazia**.

## O mecanismo novo

**Um mapa só**, `static/estados.js` (vanilla, sem framework, sem CDN; entra no build porque o PyInstaller empacota
`static/` inteiro):

```
ESTADOS[codigo] = { area, tipo, icone, titulo, sub, curto?, rotulo? }
estadoDe(codigo, ctx)  -> {titulo, sub, icone, tipo, area, curto, rotulo, pct}
codigoTranscricao(status, progresso) -> codigo (usa progresso.fase; sem fase, deduz do texto antigo)
barraHTML(estado)      -> barra de progresso (só quando tipo = progresso)
```

- `tipo`: `info` (parado, diz o próximo passo) · `espera` (anel girando) · `progresso` (barra com %) · `erro`
  (próximo passo sugerido) · `ok`.
- `area`: rótulo pequeno em caixa alta acima do título (TRANSCRIÇÃO · PRO TOOLS · PASTA · ATUALIZAÇÃO · PROMPTER):
  cada parte do app tem a própria cara.
- `titulo`/`sub` podem ser funções do contexto (nome da sessão, MB, N de M, versão, erro).

O backend passou a mandar **um código estruturado ao lado de cada texto antigo** (os textos continuam, por
compatibilidade):

| Onde | Campo novo | Valores |
|---|---|---|
| `song.progresso` (transcrição) | `fase` (+ `extra.mb`, `extra.mb_ok`, `extra.tentativa`) | `fila`, `audio_lendo`, `modelo_baixando`, `modelo_liberando`, `modelo_carregando`, `separador_baixando`, `voz_isolando`, `ouvindo`, `alinhando` |
| `view.preparo` (novo, `state.prep`) | `fase`, `musica`, `sid`, `sessao`, `sessao_anterior` | `sessao_preparando`, `audio_convertendo`, `sessao_fechando`, `sessao_abrindo`, `sessao_criando`, `audio_importando` |
| `pasta.progresso` / `view.pasta_progresso` | `fase`, `n`, `total`, `musica` | `pasta_abrindo`, `pasta_importando` |
| `UPDATE` / `setup.update` / `view.update_fase` | `fase`, `mb` | `upd_baixando`, `upd_instalando`, `upd_erro`, `upd_sem_resposta` |
| `view.pt_estado`, `view.abre_pt` | código da conexão | `fechado`, `conectando`, `sem_sessao`, `sessao` |
| respostas `{ok:false}` de `/api/transport` e `/api/protools/session` | `codigo` | `pt_desconectado`, `pasta_carregando`, `sem_audio`, `preparo_falhou`, `transporte_falhou` |
| `/api/setup` | `transcribing_progresso` | progresso da música em transcrição (para o chip da Configuração) |

O SSE (`/api/stream`) passou a disparar também quando `preparo`, `pasta_progresso` ou `session_audio_n` mudam.

**Prioridade nas telas** (o que o usuário acabou de pedir vence o que roda em segundo plano):
erro grudado (até o usuário agir) → preparo do Pro Tools para o play → espera pedida pela tela (criar sessão,
alinhar) → pasta carregando → transcrição → conexão/sessão do Pro Tools → pronto.

No teleprompter, quando **já há letra na tela**, os avisos (preparo, pasta, retranscrição) aparecem num **toast**
pequeno no alto, sem cobrir os versos. Sem letra, a mensagem grande ocupa a tela.

## Inventário: antes → depois

### Teleprompter (`static/index.html`)

| Situação real | Antes (texto/espaço) | Compartilhava com | Depois |
|---|---|---|---|
| Pro Tools não encontrado | `#msg` "Abrindo o Pro Tools" | — | `pt_fechado` · espera · PRO TOOLS · "Abrindo o Pro Tools" + "leva de 30 s a 1 min; se não abrir sozinho, abra você mesmo" (título vira "Pro Tools fechado" se `abrir_protools` está desligado) |
| Pro Tools aberto, PTSL ainda não respondeu | `#msg` "Pro Tools aberto, nenhuma sessão" | sem sessão | `pt_conectando` · espera · "Pro Tools aberto, conectando" + "uns segundos; se ficar assim, versão anterior a 2022.12" |
| Conectado, sem sessão | `#msg` "Pro Tools aberto, nenhuma sessão" | conectando | `pt_sem_sessao` · info |
| Sessão aberta sem música na lista | `#msg` "Sessão X sem letra" | — | `sessao_sem_letra` · info |
| Música na fila (pendente) | `#msg` nome + "na fila para transcrever. A letra aparece aqui…" | todas as fases da transcrição | `fila` · espera · TRANSCRIÇÃO + nome da música em linha própria |
| Lendo/convertendo o áudio | `#msg` nome + "lendo o áudio" | idem | `audio_lendo` · espera · "alguns segundos" |
| **Baixando o modelo Whisper (1ª vez)** | `#msg` nome + "baixando modelo de transcrição (só uma vez, 1620 MB) · 42%" | idem | `modelo_baixando` · progresso · "Baixando o modelo de transcrição" + "só uma vez: 1,6 GB, de 3 a 20 min; você já pode dar play" + barra **42% · 680 de 1620 MB** |
| Modelo baixado, arquivo preso (antivírus) | nome + "modelo baixado, aguardando o arquivo liberar (tentativa 2 de 6)" | idem | `modelo_liberando` · espera |
| **Carregando o modelo na memória** | (nenhuma: ficava "lendo o áudio" ou "baixando 99%") | idem | `modelo_carregando` · espera · "Preparando o modelo de transcrição" + "10 a 40 s; depois só na próxima abertura" |
| Baixando o Demucs (1ª vez) | nome + "baixando o separador de voz (só uma vez, 80 MB) e isolando a voz" | idem | `separador_baixando` · espera · "80 MB, cerca de 1 min" |
| Isolando a voz | nome + "isolando a voz · 63%" | idem | `voz_isolando` · progresso · "cerca de 2 min por música" |
| Transcrevendo | nome + "ouvindo a letra · 27%" | idem | `ouvindo` · progresso · "1 a 4 min conforme o computador; pausa enquanto o Pro Tools toca" |
| Alinhando com letra oficial | (nenhuma) | idem | `alinhando` · espera |
| Transcrição falhou | `#msg` nome + texto cru do erro | sem voz / sem letra | `erro_transcricao` · erro · erro + "tente de novo; se repetir veja o log" |
| Sem voz nos arquivos | `#msg` nome + "nenhuma voz encontrada nos arquivos" | erro | `sem_voz` · erro · "pode ser faixa só de instrumentos; escolha outra faixa ou cole a letra" |
| Pronta mas sem versos | `#msg` nome + "sem letra ainda" | erro | `sem_letra` · info |
| **Play pediu preparo do Pro Tools** (converter, fechar anterior, abrir, criar, importar) | (nenhuma no teleprompter) | — | `audio_convertendo` / `sessao_fechando` / `sessao_abrindo` / `sessao_criando` / `audio_importando` · espera · PRO TOOLS. Sem letra: tela inteira; com letra: **toast** no alto |
| Pasta sendo carregada (N de M) | (nenhuma) | — | `pasta_abrindo` · espera / `pasta_importando` · progresso "2 de 3" (tela inteira ou toast) |
| Retranscrição de música que já tem letra | `#msg` cobria a letra | — | letra continua na tela + toast "Transcrevendo a letra · 55%" |
| SSE caiu | `#msg` "Prompter desconectado / reconectando" | — | `desconectado` · erro · "reconectando sozinho; se não voltar, abra pela bandeja" |
| Barra do topo: "Pro Tools fechado / sem sessão / nome", "MTC / sincronizado / sem sincronia", `tc ▶/■` | inalterado | — | inalterado (são chips de status, não esperas) |
| Botão "Versão X disponível" | inalterado | — | inalterado |

### Estúdio (`static/editar.html`)

| Situação real | Antes | Compartilhava com | Depois |
|---|---|---|---|
| Transcrição (todas as fases) | `#guide` busy, círculo "1", h3 = texto do `etapa`, p = "A letra aparece aqui…", barra amarela | **o mesmo `#guide` do play** (o SSE apagava a mensagem do play) | `#guide` com ícone da fase no círculo, rótulo TRANSCRIÇÃO, título/subtítulo próprios, barra + "42% · 680 de 1620 MB" só quando há número; anel girando nas esperas |
| **Play precisou preparar o Pro Tools** | `#guide` "Carregando a música no Pro Tools / Convertendo o áudio e preparando a sessão" (genérico, escrito no cliente, apagado pelo SSE) | transcrição | fases reais do backend (`view.preparo`): "Convertendo o áudio" → "Salvando e fechando “Untitled”" → "Criando a sessão “X”" / "Abrindo a sessão “X”" → "Colocando a música na faixa 1". Têm prioridade sobre a transcrição; ao terminar, o guia volta sozinho à transcrição |
| Play falhou | `#guide` bad "Não deu para preparar o Pro Tools" + erro cru; apagado no próximo SSE | — | erro **grudado** até clicar "Tentar de novo", com código: `pt_desconectado` ("espere a bolinha conectado acender"), `sem_audio` ("solte a música de novo"), `pasta_carregando`, `transporte_falhou`, `erro_preparo` |
| Criar sessão / Colocar na sessão (botões) | `#guide` "Preparando a sessão…" / "Colocando a música na sessão…" escrito no cliente | idem | `guideBusy` até o backend responder, depois fases reais; erro grudado |
| Colar letra oficial / Realinhar | (nenhuma) | — | `alinhando` · espera enquanto o PUT roda |
| Pro Tools fechado / aberto sem PTSL | "Abra o Pro Tools" / "Pro Tools aberto, sem conexão" | — | `pt_fechado` / `pt_conectando` (agora redesenha quando `protools` muda — antes não) |
| Pasta carregando | `#guide` "Carregando a pasta X" + `msg` cru; botão "Carregando…" | — | `pasta_abrindo` / `pasta_importando` com **N de M** no guia e no botão ("Colocando 2 de 3…") |
| Pasta falhou ao carregar | (nunca aparecia; `pasta.erro` era gravado e ignorado) | — | `pasta_erro` no guia e linha vermelha sob a pasta; some quando um carregamento dá certo |
| Pasta não aberta / música fora da linha do tempo / pronta na pasta | textos ok | — | `pt_pasta_fora` / `pt_pasta_falta` / `pronto_pasta` (mesmos textos, pelo mapa) |
| Outra sessão aberta / sem sessão / pronta | textos ok | — | `pt_outra_sessao` / `pt_sem_sessao` / `pronto` |
| Sessão aberta e vazia | "Outra sessão está aberta… troca para a sessão desta música" (ramo certo era inalcançável) | outra sessão | `pt_sessao_vazia` · "coloca a música na faixa 1 desta sessão" (é o que `ensure_session` faz) |
| Erro de transcrição / sem voz | erro cru + "Tentar de novo"; sem-voz caía no estado do Pro Tools | — | `erro_transcricao` / `sem_voz` com ações "Escolher outra faixa" e "Colar letra oficial" |
| Chip da música na lista e no cabeçalho | "na fila" / "transcrevendo" | — | fase curta: "baixando o modelo 42%", "isolando a voz 63%", "preparando o modelo"… |
| Envio de arquivo (dropzone) | só barra; erro em `alert('falha no envio')` | — | "Enviando a música · 42%", "Música recebida. Entrou na fila", "Não deu para enviar. Confira se é MP3/WAV…" no próprio bloco |
| Chips do cabeçalho, `#tSrc` ("Pro Tools, posição estimada" etc.), "sem forma de onda" | inalterados | — | inalterados |

### Configuração (`static/config.html`)

| Situação | Antes | Depois |
|---|---|---|
| Atualização baixando | botão "baixando 37%", `updMsg` = texto cru | botão "baixando 37%", `updMsg` = "**Baixando a versão 2.0.22.** 210 MB. Uns minutos…" + barra "37% · 78 de 210 MB" |
| Instalando | botão "instalando", texto cru | "**Instalando a atualização.** Confirme o pedido de administrador…" |
| Falhou | texto cru amarelo | "**A atualização não aconteceu.** código… Clique de novo e aceite…" em vermelho |
| GitHub sem resposta | "sem resposta do GitHub" | idem + subtítulo |
| Chip "Transcrição" | "transcrevendo" | fase curta da música em transcrição ("baixando o modelo 42%") |
| loopMIDI (`loopmidi_msg`) | textos do backend | inalterado (já eram próprios) |

## Arquivos alterados

- `app.py` — `Transcriber.set_prog(..., fase=)` e códigos em todas as chamadas; fase `modelo_carregando` antes de abrir o
  `WhisperModel` (o vigia do download para de escrever assim que o download termina); fase `alinhando`;
  `State.prep` + `PTLink.set_prep()` com fases em `import_into_session` e `make_session` (agora um invólucro
  `try/finally` sobre `_make_session`, para o preparo nunca ficar preso); `pasta.progresso` com `fase/n/total/musica`;
  `pasta.erro` limpo quando um carregamento dá certo; `UPDATE.fase/mb`; `current_view` com `pt_estado`, `abre_pt`,
  `preparo`, `update_fase` e `pasta_progresso` completo; chave do SSE inclui `preparo`, `pasta_progresso`,
  `session_audio_n`; `codigo` nos erros de `/api/transport` e `/api/protools/session`; `setup_status` com
  `transcribing_progresso` e `update.fase/mb`; **`--simular`** (só instância de teste): liga `POST /api/simular` e não
  sobe as threads PTSL/PTWatcher. `VERSION` intocado.
- `static/estados.js` — **novo**: o mapa e os helpers.
- `static/index.html` — `showEstado()`/`toast()` no lugar de `showMsg()`; CSS do cartão (ícone, rótulo, barra, anel) e do
  toast; lógica de escolha do estado em `applyView`.
- `static/editar.html` — `showGuide()`/`falha()`/`renderGuide()` com prioridade e erro grudado; play, criar sessão,
  importar, alinhar, colar letra pelo mapa; chips com fase; botão e erro das pastas; mensagens do envio; guia
  redesenha quando `protools`/`preparo` mudam e após recarregar a lista.
- `static/config.html` — atualização e chip do modelo pelo mapa.
- `docs/MENSAGENS-DE-ESTADO.md` — este arquivo.

Não tocados: `build/`, `.github/`, `installer.iss`, `VERSION`, `requirements.txt`.

## Como testei

Instância de teste ao lado da instalada (que ficou rodando em 8797, intocada):

```
python app.py --porta 8799 --simular --sem-transcricao --sem-protools --sem-navegador --sem-bandeja
```

`--simular` liga `POST /api/simular` que força `status/progresso/erro` de uma música, `pt_found/ptsl_ok/session/
session_audio_n/session_song/forced_song/prep` do estado, `pasta_progresso`/`pasta_erro` de uma pasta e `UPDATE`.
Com o playwright-cli (headless, 1280×720) percorri, lendo o DOM e tirando capturas:

- Teleprompter: `pt_fechado`, `pt_conectando`, `pt_sem_sessao`, `sessao_sem_letra`; `fila`, `modelo_baixando` (42% ·
  680 de 1620 MB), `modelo_carregando`, `modelo_liberando`, `separador_baixando`, `voz_isolando`, `ouvindo`,
  `alinhando`, `erro`, `sem_voz`; progresso **sem `fase`** (backend antigo) caindo no código certo pelo texto;
  preparo do play sem letra (`audio_convertendo` → `sessao_criando`) em tela inteira; com letra na tela, toast de
  preparo (`sessao_abrindo`) e de retranscrição (55%) sem cobrir os versos. Console sem erros.
- Estúdio: as mesmas fases no guia e no chip; **o cenário do problema**: modelo baixando a 42% + play → o guia mostra
  "Convertendo o áudio" → "Salvando e fechando “Untitled”" → "Colocando a música na faixa 1" e, ao terminar o preparo,
  volta a "Baixando o modelo… 42%"; play com falha real do `/api/transport` (engine ausente) → erro grudado que
  sobrevive aos SSE seguintes; estados do Pro Tools (`pt_conectando` agora aparece, `pt_sessao_vazia` agora
  alcançável); pasta de teste "Show Teste" criada pela API: `pasta_abrindo`, `pasta_importando` (33% · 2 de 3, botão
  "Colocando 2 de 3…"), `pasta_erro` no guia e sob a pasta, sumindo ao limpar; pasta apagada depois; envio de um
  `.txt` → "Não deu para enviar…" no dropzone.
- Configuração: `upd_baixando` (37% · 78 de 210 MB), `upd_instalando`, `upd_erro`, sem atualização.
- Sintaxe: `ast.parse` no `app.py`; `vm.Script` do Node em `estados.js` e nos três scripts inline.

Ao final matei só o PID da instância de teste (python `--porta 8799`); o Prompter instalado continuou.

## O que ficou de fora e por quê

- **Não rodei transcrição real nem Pro Tools real.** As fases novas do backend (`modelo_carregando`, `alinhando`,
  `set_prep` em `make_session`/`import_into_session`) foram conferidas por leitura e por sintaxe; o fluxo de dados até
  a tela foi validado com os mesmos dicionários que o backend produz.
- **"Localizar/dar play"** não tem estado de espera: `locate`/`toggle_play_state` respondem em ~30 ms. Fica só o
  `transporte_falhou` para quando o Pro Tools não responde.
- **`load_pasta` não usa `set_prep`**: a pasta já tinha `progresso` próprio (agora com `fase/n/total`); dentro dela a
  conversão de cada WAV fica coberta pela mensagem "Colocando X na linha do tempo (N de M)".
- **Ecrã do teleprompter durante atualização**: só o botão "Versão X disponível"; o processo de atualização fecha o
  app, então o lugar dela é a Configuração.
- **Chips de status** (barra do topo do teleprompter, cabeçalho do estúdio, `#tSrc`, leds da Configuração) não são
  esperas e ficaram como estavam.
- **Tempos declarados** (3–20 min de download, 10–40 s de carga do modelo, ~2 min Demucs, 1–4 min Whisper, 5–15 s
  abrir sessão, ~10 s criar) são estimativas a partir do README e do código; vale ajustar depois de medir em campo.
- **`--simular`** ficou no `app.py` (guardado pelo flag; nunca registrado no uso normal). Se preferir, é só remover o
  bloco `api_simular` e o `if "--simular"` em `main()`.
