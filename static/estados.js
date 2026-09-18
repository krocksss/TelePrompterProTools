/* Prompter - mensagens de estado, num lugar so.
   Cada situacao que faz o usuario esperar (ou agir) tem uma mensagem propria: titulo curto, subtitulo dizendo o
   que esta acontecendo e quanto costuma demorar, um icone e um tipo visual. As telas (teleprompter, estudio,
   configuracao) NAO escrevem esses textos: pedem estadoDe(codigo, contexto) e so desenham.
   Os codigos vem do backend (progresso.fase, preparo.fase, pasta_progresso.fase, update.fase, pt_estado, codigo
   de erro) ou de situacoes que so a tela conhece (enviando arquivo, desconectado).

   tipo:  info      - situacao parada, diz o proximo passo (neutro)
          espera    - algo esta acontecendo, sem numero (anel girando)
          progresso - algo esta acontecendo, com % (barra)
          erro      - falhou, com o proximo passo sugerido
          ok        - pronto
   area:  o "capitulo" a que a mensagem pertence (Transcricao, Pro Tools, Pasta, Atualizacao, Prompter):
          aparece como rotulo pequeno em cima do titulo, para cada parte ter a sua cara. */
(function () {
  function escE(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  function mbTxt(mb) { mb = Number(mb) || 0; return mb >= 1000 ? (mb / 1000).toFixed(1).replace('.', ',') + ' GB' : Math.round(mb) + ' MB'; }
  function q(s) { return '“' + escE(s) + '”'; }   // "nome" com aspas tipograficas
  const T = 'Transcrição', P = 'Pro Tools', F = 'Pasta', U = 'Atualização', R = 'Prompter';

  const ESTADOS = {
    /* ---------- transcricao da letra (progresso.fase) ---------- */
    fila:               { area: T, tipo: 'espera', icone: '…', curto: 'na fila',
                          titulo: 'Na fila para transcrever',
                          sub: 'Começa em instantes. Se houver outra música na frente, ela vai primeiro.' },
    audio_lendo:        { area: T, tipo: 'espera', icone: '♫', curto: 'lendo o áudio',
                          titulo: 'Lendo o áudio',
                          sub: 'Convertendo o arquivo para o formato de trabalho. Alguns segundos.' },
    modelo_baixando:    { area: T, tipo: 'progresso', icone: '⇣', curto: c => 'baixando o modelo' + (c.pct != null ? ' ' + c.pct + '%' : ''),
                          titulo: 'Baixando o modelo de transcrição',
                          sub: c => 'Só acontece uma vez: são ' + mbTxt(c.mb || 1620) + ', de 3 a 20 minutos conforme a internet. '
                                  + 'Você já pode dar play; a letra chega quando terminar.',
                          rotulo: c => (c.mb_ok != null ? c.mb_ok + ' de ' + (c.mb || 1620) + ' MB' : '') },
    modelo_liberando:   { area: T, tipo: 'espera', icone: '⇣', curto: 'liberando o modelo',
                          titulo: 'Modelo baixado, liberando o arquivo',
                          sub: c => 'O antivírus costuma segurar o arquivo por alguns segundos' + (c.tentativa ? ' (tentativa ' + c.tentativa + ' de ' + (c.de || 6) + ')' : '') + '.' },
    modelo_carregando:  { area: T, tipo: 'espera', icone: '◌', curto: 'preparando o modelo',
                          titulo: 'Preparando o modelo de transcrição',
                          sub: 'Carregando o modelo na memória: de 10 a 40 segundos. Depois disso é só na próxima abertura do Prompter.' },
    separador_baixando: { area: T, tipo: 'espera', icone: '⇣', curto: 'baixando o separador',
                          titulo: 'Baixando o separador de voz',
                          sub: c => 'Só na primeira vez: ' + mbTxt(c.mb || 80) + ', cerca de 1 minuto. Em seguida a voz é isolada.' },
    voz_isolando:       { area: T, tipo: 'progresso', icone: '♪', curto: c => 'isolando a voz' + (c.pct != null ? ' ' + c.pct + '%' : ''),
                          titulo: 'Isolando a voz',
                          sub: 'Separando o canto dos instrumentos para ouvir melhor a letra. Cerca de 2 minutos por música.' },
    ouvindo:            { area: T, tipo: 'progresso', icone: '✎', curto: c => 'transcrevendo' + (c.pct != null ? ' ' + c.pct + '%' : ''),
                          titulo: 'Transcrevendo a letra',
                          sub: 'Ouvindo a música e anotando cada palavra com o tempo dela. De 1 a 4 minutos, conforme o computador. Pausa sozinho enquanto o Pro Tools toca.' },
    alinhando:          { area: T, tipo: 'espera', icone: '≡', curto: 'alinhando',
                          titulo: 'Alinhando com a letra oficial',
                          sub: 'Casando cada verso com as palavras ouvidas no áudio. Alguns segundos.' },
    transcrevendo:      { area: T, tipo: 'espera', icone: '✎', curto: 'transcrevendo',   // fase desconhecida: usa o texto antigo
                          titulo: 'Transcrevendo',
                          sub: c => (c.etapa ? escE(c.etapa) + '. ' : '') + 'A letra aparece aqui quando terminar, com o tempo de cada palavra.' },
    sem_voz:            { area: T, tipo: 'erro', icone: '!', curto: 'sem voz',
                          titulo: 'Não encontrei voz neste áudio',
                          sub: 'Pode ser uma faixa só de instrumentos. Escolha outra faixa em "Transcrever de novo" ou cole a letra oficial.' },
    erro_transcricao:   { area: T, tipo: 'erro', icone: '!', curto: 'erro',
                          titulo: 'A transcrição falhou',
                          sub: c => (c.erro ? escE(c.erro) + '. ' : '') + 'Tente de novo; se repetir, veja o log em Configuração.' },
    sem_letra:          { area: T, tipo: 'info', icone: '✎', curto: 'sem letra',
                          titulo: 'Sem versos ainda',
                          sub: 'Abra a música em Músicas e letras para escrever ou colar a letra.' },

    /* ---------- Pro Tools: conexao e sessao (pt_estado + situacao da musica) ---------- */
    pt_fechado:         { area: P, tipo: 'espera', icone: '◌',
                          titulo: c => c.abre_pt === false ? 'Pro Tools fechado' : 'Abrindo o Pro Tools',
                          sub: c => (c.abre_pt === false ? 'Abra o Pro Tools; o Prompter conecta sozinho em seguida.' : 'Ele leva de 30 segundos a 1 minuto para abrir. Se não abrir sozinho, abra você mesmo; o Prompter conecta em seguida.') },
    pt_conectando:      { area: P, tipo: 'espera', icone: '◌',
                          titulo: 'Pro Tools aberto, conectando',
                          sub: 'Esperando o Pro Tools responder: uns segundos depois de ele terminar de abrir. Se ficar assim, a versão pode ser anterior a 2022.12.' },
    pt_sem_sessao:      { area: P, tipo: 'info', icone: '▢',
                          titulo: 'Pro Tools sem sessão aberta',
                          sub: c => c.tela === 'prompter' ? 'Abra a sessão da música no Pro Tools, ou crie em Músicas e letras com um clique.'
                                                          : 'Aperte play: o Prompter cria a sessão com a música na faixa 1 e toca. Ou abra a sessão no Pro Tools.' },
    pt_outra_sessao:    { area: P, tipo: 'info', icone: '▢',
                          titulo: 'Outra sessão está aberta no Pro Tools',
                          sub: c => 'Aberta agora: ' + q(c.sessao) + '. Aperte play: o Prompter troca para a sessão desta música antes de tocar (a atual é salva).' },
    pt_sessao_vazia:    { area: P, tipo: 'info', icone: '▢',
                          titulo: c => 'A sessão ' + q(c.sessao) + ' está sem áudio',
                          sub: 'Aperte play: o Prompter coloca a música na faixa 1 desta sessão e toca. Ou clique abaixo para só colocar.' },
    sessao_sem_letra:   { area: P, tipo: 'info', icone: '▢',
                          titulo: c => 'Sessão ' + q(c.sessao) + ' sem letra',
                          sub: 'Adicione a música para transcrever a letra; ela fica ligada a esta sessão.' },
    pronto:             { area: P, tipo: 'ok', icone: '✓',
                          titulo: c => 'Pronta e sincronizada com ' + q(c.sessao),
                          sub: 'Aperte play aqui ou no Pro Tools. O teleprompter acompanha palavra por palavra.' },

    /* ---------- Pro Tools: preparo antes do play (preparo.fase) ---------- */
    sessao_preparando:  { area: P, tipo: 'espera', icone: '▶',
                          titulo: 'Preparando o Pro Tools',
                          sub: 'Deixando a música pronta para tocar. O play começa em seguida, em uns segundos.' },
    audio_convertendo:  { area: P, tipo: 'espera', icone: '♫',
                          titulo: 'Convertendo o áudio',
                          sub: 'Preparando o arquivo no formato da sessão. Alguns segundos; o play vem em seguida.' },
    sessao_fechando:    { area: P, tipo: 'espera', icone: '▢',
                          titulo: c => 'Salvando e fechando ' + q(c.sessao_anterior),
                          sub: 'A sessão aberta é salva antes da troca. Uns 2 segundos.' },
    sessao_abrindo:     { area: P, tipo: 'espera', icone: '▢',
                          titulo: c => 'Abrindo a sessão ' + q(c.sessao),
                          sub: 'O Pro Tools está abrindo a sessão desta música. De 5 a 15 segundos.' },
    sessao_criando:     { area: P, tipo: 'espera', icone: '▢',
                          titulo: c => 'Criando a sessão ' + q(c.sessao),
                          sub: 'Sessão nova no Pro Tools, salva na pasta Sessoes. Cerca de 10 segundos.' },
    audio_importando:   { area: P, tipo: 'espera', icone: '⇥',
                          titulo: 'Colocando a música na faixa 1',
                          sub: c => 'Importando o áudio na sessão ' + q(c.sessao) + '. Alguns segundos; o play vem em seguida.' },
    erro_preparo:       { area: P, tipo: 'erro', icone: '!',
                          titulo: 'Não deu para preparar o Pro Tools',
                          sub: c => (c.erro ? escE(c.erro) + '. ' : '') + 'Confira se o Pro Tools está aberto e responde, e tente de novo.' },
    pt_desconectado:    { area: P, tipo: 'erro', icone: '!',
                          titulo: 'Pro Tools não conectado',
                          sub: 'Abra o Pro Tools e espere a bolinha "conectado" acender no alto; depois aperte play de novo.' },
    sem_audio:          { area: P, tipo: 'erro', icone: '!',
                          titulo: 'A música não tem arquivo de áudio',
                          sub: 'O arquivo foi movido ou apagado. Solte a música de novo em Adicionar música.' },
    transporte_falhou:  { area: P, tipo: 'erro', icone: '!',
                          titulo: 'O Pro Tools não respondeu ao play',
                          sub: c => (c.erro ? escE(c.erro) + '. ' : '') + 'Tente de novo. Se repetir, dê play no próprio Pro Tools; o teleprompter acompanha do mesmo jeito.' },

    /* ---------- pastas (setlists): uma sessao com todas as musicas (pasta_progresso.fase) ---------- */
    pasta_abrindo:      { area: F, tipo: 'espera', icone: '▸',
                          titulo: c => 'Abrindo a sessão da pasta ' + q(c.pasta),
                          sub: 'Abrindo (ou criando) a sessão que reúne todas as músicas. De 5 a 15 segundos.' },
    pasta_importando:   { area: F, tipo: 'progresso', icone: '⇥',
                          titulo: c => 'Colocando ' + q(c.musica) + ' na linha do tempo',
                          sub: c => 'Música ' + c.n + ' de ' + c.total + ' da pasta ' + q(c.pasta) + '. Uns 10 segundos por música, só na primeira vez; depois trocar é na hora.',
                          rotulo: c => c.n + ' de ' + c.total },
    pasta_carregando:   { area: F, tipo: 'espera', icone: '▸',
                          titulo: 'A pasta ainda está sendo carregada',
                          sub: 'Espere terminar e aperte play de novo.' },
    pt_pasta_fora:      { area: F, tipo: 'info', icone: '▸',
                          titulo: c => 'A pasta ' + q(c.pasta) + ' não está aberta no Pro Tools',
                          sub: 'Aperte play: o Prompter abre a sessão da pasta com todas as músicas enfileiradas (só na primeira vez) e toca esta.' },
    pt_pasta_falta:     { area: F, tipo: 'info', icone: '▸',
                          titulo: 'Esta música ainda não está na linha do tempo da pasta',
                          sub: 'Aperte play: o Prompter coloca a música no fim da linha do tempo e toca.' },
    pronto_pasta:       { area: F, tipo: 'ok', icone: '✓',
                          titulo: c => 'Na pasta ' + q(c.pasta) + ', pronta no Pro Tools',
                          sub: 'Aperte play: o Pro Tools pula para esta música na hora. Deixando tocar, o teleprompter passa para a próxima sozinho.' },
    pasta_erro:         { area: F, tipo: 'erro', icone: '!',
                          titulo: 'Não deu para carregar a pasta',
                          sub: c => (c.erro ? escE(c.erro) + '. ' : '') + 'Confira se o Pro Tools está aberto e clique em "Carregar no Pro Tools" de novo.' },

    /* ---------- atualizacao (update.fase) ---------- */
    upd_disponivel:     { area: U, tipo: 'info', icone: '★',
                          titulo: c => 'Versão ' + escE(c.versao) + ' disponível',
                          sub: 'Baixa e instala com um clique; o Prompter fecha e reabre sozinho.' },
    upd_baixando:       { area: U, tipo: 'progresso', icone: '⇣', curto: c => 'baixando ' + (c.pct != null ? c.pct + '%' : ''),
                          titulo: c => 'Baixando a versão ' + escE(c.versao),
                          sub: c => (c.mb ? mbTxt(c.mb) + '. ' : '') + 'Uns minutos, conforme a internet. Pode continuar usando o Prompter.',
                          rotulo: c => (c.mb && c.pct != null ? Math.round(c.mb * c.pct / 100) + ' de ' + c.mb + ' MB' : '') },
    upd_instalando:     { area: U, tipo: 'espera', icone: '★', curto: 'instalando',
                          titulo: 'Instalando a atualização',
                          sub: 'Confirme o pedido de administrador do Windows. O Prompter fecha e reabre sozinho em cerca de 1 minuto.' },
    upd_erro:           { area: U, tipo: 'erro', icone: '!', curto: 'falhou',
                          titulo: 'A atualização não aconteceu',
                          sub: c => (c.erro ? escE(c.erro) + ' ' : '') + 'Clique em "Baixar e instalar" de novo e aceite o pedido de administrador.' },
    upd_sem_resposta:   { area: U, tipo: 'info', icone: '★', curto: 'sem resposta',
                          titulo: 'Sem resposta do GitHub',
                          sub: 'Não consegui ver se há versão nova. Tento de novo mais tarde; confira a internet se persistir.' },

    /* ---------- o proprio Prompter (so a tela sabe) ---------- */
    desconectado:       { area: R, tipo: 'erro', icone: '!',
                          titulo: 'Prompter desconectado',
                          sub: 'O programa fechou ou está reiniciando. Reconectando sozinho; se não voltar, abra o Prompter pela bandeja.' },
    enviando:           { area: R, tipo: 'progresso', icone: '⇡', curto: c => 'enviando' + (c.pct != null ? ' ' + c.pct + '%' : ''),
                          titulo: 'Enviando a música',
                          sub: 'Copiando o arquivo para a pasta de músicas. Em seguida ela entra na fila de transcrição.' },
    enviado:            { area: R, tipo: 'ok', icone: '✓',
                          titulo: 'Música recebida',
                          sub: 'Entrou na fila de transcrição.' },
    envio_erro:         { area: R, tipo: 'erro', icone: '!',
                          titulo: 'Não deu para enviar',
                          sub: c => (c.erro ? escE(c.erro) + '. ' : '') + 'Confira se é um arquivo de áudio (MP3, WAV, M4A, FLAC, AIFF, OGG) e tente de novo.' },
  };

  function txt(v, c) { return typeof v === 'function' ? v(c) : (v == null ? '' : v); }

  /* estadoDe(codigo, ctx) -> {codigo, area, tipo, icone, titulo, sub, curto, rotulo, pct}
     ctx: pct, mb, mb_ok, tentativa, de, n, total, musica, pasta, sessao, sessao_anterior, versao, erro, etapa, abre_pt, tela */
  function estadoDe(codigo, ctx) {
    ctx = ctx || {};
    const e = ESTADOS[codigo] || ESTADOS.transcrevendo;
    const pct = ctx.pct != null ? Math.max(0, Math.min(100, Math.round(ctx.pct))) : (e.tipo === 'progresso' && ctx.n != null && ctx.total ? Math.round((ctx.n - 1) / ctx.total * 100) : null);
    return { codigo: ESTADOS[codigo] ? codigo : 'transcrevendo', area: e.area, tipo: e.tipo, icone: e.icone,
             titulo: txt(e.titulo, ctx), sub: txt(e.sub, ctx), curto: txt(e.curto, ctx) || txt(e.titulo, ctx),
             rotulo: txt(e.rotulo, ctx), pct: pct };
  }

  /* Do backend para o codigo: progresso.fase (transcricao) com fallback por status e texto antigo. */
  function codigoTranscricao(status, progresso) {
    if (progresso && progresso.fase && ESTADOS[progresso.fase]) return progresso.fase;
    if (status === 'pendente' && !progresso) return 'fila';
    if (status === 'sem-voz') return 'sem_voz';
    if (status === 'erro') return 'erro_transcricao';
    const et = (progresso && progresso.etapa) || '';
    if (/modelo/.test(et) && /baix/.test(et)) return 'modelo_baixando';
    if (/separador/.test(et)) return 'separador_baixando';
    if (/isolando/.test(et)) return 'voz_isolando';
    if (/ouvindo/.test(et)) return 'ouvindo';
    if (/lendo/.test(et)) return 'audio_lendo';
    if (/fila/.test(et)) return 'fila';
    return 'transcrevendo';
  }
  function ctxTranscricao(progresso, extra) {
    const x = (progresso && progresso.extra) || {};
    return Object.assign({ pct: progresso ? progresso.pct : null, etapa: progresso ? progresso.etapa : null }, x, extra || {});
  }

  /* Barra de progresso: HTML pronto (as telas estilizam .est-bar/.est-pct). pct null = indeterminada. */
  function barraHTML(est) {
    if (est.tipo !== 'progresso') return '';   // espera = anel girando no icone, sem barra
    const det = est.pct != null;
    return '<div class="est-bar' + (det ? '' : ' indet') + '"><i' + (det ? ' style="width:' + est.pct + '%"' : '') + '></i></div>'
         + (det || est.rotulo ? '<div class="est-pct">' + (det ? est.pct + '%' : '') + (est.rotulo ? (det ? ' · ' : '') + escE(est.rotulo) : '') + '</div>' : '');
  }

  window.ESTADOS = ESTADOS;
  window.estadoDe = estadoDe;
  window.codigoTranscricao = codigoTranscricao;
  window.ctxTranscricao = ctxTranscricao;
  window.barraHTML = barraHTML;
  window.escEstado = escE;
})();
