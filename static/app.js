'use strict';

const $ = id => document.getElementById(id);
const state = {page:'scanner', sessions:[], status:null, snapshot:null, date:null, seconds:null,
  follow:true, all:false, quality:false, search:'', selected:null, chartMode:'market', chartKey:null,
  request:0, refreshing:false, serverOffset:0, offline:false};
const isNumber = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
const number = (value, digits=2) => isNumber(value) ? Number(value).toLocaleString('es-MX',{minimumFractionDigits:digits,maximumFractionDigits:digits}) : '—';
const pct = (value, digits=2, sign=true) => isNumber(value) ? `${sign && Number(value)>0 ? '+' : ''}${number(value,digits)} %` : '—';
const score = value => isNumber(value) ? number(value,1) : 'Sin score';
const candidate = row => row.home_b_candidate === true || row.home_b_candidate === 1 || row.home_b_candidate === 'True';
const cutLabel = seconds => ({10:'10 segundos',30:'30 segundos',60:'1 minuto',90:'1 minuto y medio'}[seconds] || `${seconds} segundos`);
const fmtTime = (value, zone='America/New_York') => {
  const date = new Date(value); if (!value || !Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat('es-MX',{timeZone:zone,hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date);
};
const fmtDate = value => value ? new Intl.DateTimeFormat('es-MX',{timeZone:'UTC',day:'numeric',month:'long',year:'numeric'}).format(new Date(value+'T12:00:00Z')) : '—';
const node = (tag, text, cls) => {const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
function sourceLabel(source) {
  if (!source) return 'Fuente no indicada';
  if (source.includes('yahoo')) return 'Yahoo · captura WebSocket';
  if (source.includes('alpaca')) return 'Alpaca · datos históricos';
  return source.replaceAll('_',' ');
}
async function api(path) {
  const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(12000)});
  if (!response.ok) {const err=new Error(`No se pudo consultar el escáner (${response.status}).`);err.status=response.status;throw err;}
  return response.json();
}
function query(path) {
  const values=new URLSearchParams({date:state.date||'',seconds:String(state.seconds||'')});
  return path+'?'+values.toString();
}
function clockTick() {
  const now=new Date(Date.now()+state.serverOffset);
  $('clock-ny').textContent=fmtTime(now);
  $('clock-hmo').textContent=fmtTime(now,'America/Hermosillo');
}
function renderStatus(status) {
  state.status=status;
  if(status.now_ny){const date=new Date(status.now_ny);if(Number.isFinite(date.getTime()))state.serverOffset=date.getTime()-Date.now();}
  clockTick();
  $('metric-universe').textContent=String(status.universe_count||72);
  const worker=status.worker||{};
  const heartbeat=worker.heartbeat || worker.updated_at;
  const age=heartbeat ? Math.max(0,Math.round((Date.now()+state.serverOffset-new Date(heartbeat).getTime())/1000)) : null;
  const fresh=age!==null && age<60;
  const labels={programado:'Captura programada',preparando:'Preparando la sesión',capturando:'Capturando apertura',listo:'Captura terminada',importado:'Sesión importada',sin_captura:'Sin captura de hoy',cerrado:'Mercado cerrado',detenido:'Capturador detenido',error:'Revisar capturador'};
  const label=fresh ? (labels[worker.state] || 'Capturador activo') : 'Capturador sin conexión';
  $('worker-state').textContent=label;
  const tone=!fresh || ['sin_captura','detenido'].includes(worker.state) ? 'warning' : worker.state==='error' ? 'error' : 'online';
  document.querySelector('#worker-pill .status-dot').className='status-dot '+tone;
  $('capture-dot').className='status-dot '+tone;
  $('worker-message').textContent=fresh ? worker.message || label : 'El capturador no ha reportado actividad reciente. Puedes consultar el historial.';
  $('heartbeat-age').textContent=age===null ? 'Sin señal del proceso' : age<60 ? `Actividad hace ${age} s` : `Última actividad: ${fmtTime(heartbeat)} ET`;
}
function renderNotice() {
  const note=$('connection-notice');
  if(state.offline){note.hidden=false;note.textContent='No hay conexión con el servidor del escáner. Se conserva en pantalla la última información recibida; puede estar desactualizada.';return;}
  if(state.snapshot?.imported){note.hidden=false;note.textContent=`Sesión importada del ${fmtDate(state.snapshot.date)} · resultados guardados.`;return;}
  const today=state.status?.now_ny?.slice(0,10);
  if(state.page==='scanner' && state.date && today && state.date!==today){note.hidden=false;note.textContent=`No hay un corte guardado de hoy. Estás viendo la última sesión disponible: ${fmtDate(state.date)}.`;return;}
  note.hidden=true;
}
const reduceMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
const narrowLayout=window.matchMedia('(max-width: 53rem)');
const cutMotion={left:0,width:0,leftVelocity:0,widthVelocity:0,targetLeft:0,targetWidth:0,last:0,frame:0};
function paintCutIndicator(){
  const indicator=document.querySelector('.cut-indicator');
  indicator.style.transform=`translateX(${cutMotion.left}px) scaleX(${cutMotion.width/(indicator.offsetWidth||80)})`;
}
function advanceCutIndicator(now){
  const dt=Math.min((now-cutMotion.last)/1000,.032);
  cutMotion.last=now;
  const frequency=2*Math.PI/.32;
  for(let i=0;i<4;i++){
    const step=dt/4;
    cutMotion.leftVelocity+=((cutMotion.targetLeft-cutMotion.left)*frequency**2-2*frequency*cutMotion.leftVelocity)*step;
    cutMotion.widthVelocity+=((cutMotion.targetWidth-cutMotion.width)*frequency**2-2*frequency*cutMotion.widthVelocity)*step;
    cutMotion.left+=cutMotion.leftVelocity*step;
    cutMotion.width+=cutMotion.widthVelocity*step;
  }
  const moving=Math.abs(cutMotion.left-cutMotion.targetLeft)+Math.abs(cutMotion.width-cutMotion.targetWidth)>.18 ||
    Math.abs(cutMotion.leftVelocity)+Math.abs(cutMotion.widthVelocity)>3;
  if(!moving){cutMotion.left=cutMotion.targetLeft;cutMotion.width=cutMotion.targetWidth;cutMotion.leftVelocity=0;cutMotion.widthVelocity=0;}
  paintCutIndicator();
  cutMotion.frame=moving ? requestAnimationFrame(advanceCutIndicator) : 0;
}
function positionCutIndicator(immediate=false){
  const group=document.querySelector('.cut-tabs');
  const active=group.querySelector('button.active:not(:disabled)');
  group.classList.toggle('has-indicator',Boolean(active));
  if(!active)return;
  const unchanged=cutMotion.targetLeft===active.offsetLeft && cutMotion.targetWidth===active.offsetWidth;
  if(unchanged && !immediate && !reduceMotion.matches)return;
  cutMotion.targetLeft=active.offsetLeft;cutMotion.targetWidth=active.offsetWidth;
  if(immediate || reduceMotion.matches || !cutMotion.width){
    cancelAnimationFrame(cutMotion.frame);cutMotion.frame=0;
    cutMotion.left=cutMotion.targetLeft;cutMotion.width=cutMotion.targetWidth;
    cutMotion.leftVelocity=0;cutMotion.widthVelocity=0;paintCutIndicator();
  }else if(!cutMotion.frame){
    cutMotion.last=performance.now();cutMotion.frame=requestAnimationFrame(advanceCutIndicator);
  }
}
function arrangeWorkspace(){
  const layout=document.querySelector('.scanner-layout');
  const first=layout.querySelector(narrowLayout.matches ? '.detail-column' : '.opportunity-panel');
  if(layout.firstElementChild!==first)layout.prepend(first);
}
function renderSessions() {
  const el=$('session-date');
  if(!state.sessions.length){el.disabled=true;return;}
  el.disabled=false;
  const sessionKeys=state.sessions.map(session=>session.date).join(',');
  if(el.dataset.keys!==sessionKeys){
    el.replaceChildren();
    for(const session of state.sessions){const option=node('option',fmtDate(session.date));option.value=session.date;el.append(option);}
    el.dataset.keys=sessionKeys;
  }
  el.value=state.date;
  const session=state.sessions.find(s=>s.date===state.date);
  for(const button of document.querySelectorAll('[data-cut]')){
    const seconds=Number(button.dataset.cut);button.disabled=!(session?.cuts||[]).map(Number).includes(seconds);
    button.classList.toggle('active',seconds===state.seconds);button.setAttribute('aria-pressed',String(seconds===state.seconds));
  }
  $('follow-latest').classList.toggle('active',state.follow);$('follow-latest').setAttribute('aria-pressed',String(state.follow));
  positionCutIndicator();
}
async function refreshAll(force=false) {
  if(state.refreshing)return;state.refreshing=true;
  try {
    const [status,sessions]=await Promise.all([api('/api/status'),api('/api/sessions')]);
    renderStatus(status);state.sessions=Array.isArray(sessions)?sessions:(sessions.sessions||[]);
    state.sessions.sort((a,b)=>b.date.localeCompare(a.date));state.offline=false;
    if(state.follow && state.page==='scanner')state.date=state.sessions[0]?.date||null;
    if(!state.date || !state.sessions.some(s=>s.date===state.date))state.date=state.sessions[0]?.date||null;
    const session=state.sessions.find(s=>s.date===state.date);
    if(session && (state.follow || !session.cuts.map(Number).includes(Number(state.seconds))))state.seconds=Math.max(...session.cuts.map(Number));
    renderSessions();renderNotice();
    if(state.date && state.seconds){
      if(force || state.snapshot?.date!==state.date || state.snapshot?.seconds!==state.seconds)await loadSnapshot();
    }else renderEmpty();
  }catch(error){state.offline=true;renderNotice();$('worker-state').textContent='Servidor sin conexión';if(!state.snapshot)renderEmpty('No se pudo conectar','Comprueba que el servidor de la nueva versión esté iniciado. Volveremos a intentarlo automáticamente.');}
  finally{state.refreshing=false;}
}
async function loadSnapshot() {
  const request=++state.request;
  try{
    const snapshot=await api(query('/api/snapshot'));if(request!==state.request)return;
    if(!snapshot?.rows){state.snapshot=null;renderEmpty();return;}
    state.snapshot=snapshot;state.offline=false;
    const rows=snapshot.rows;
    const candidates=rows.filter(candidate);
    if(!rows.some(r=>r.ticker===state.selected))state.selected=candidates.sort(sortRows)[0]?.ticker||null;
    $('metric-universe').textContent=String(rows.length||state.status?.universe_count||72);
    $('metric-coverage').textContent=`${rows.filter(r=>isNumber(r.price_at_cutoff)).length} con precio en este corte`;
    $('metric-candidates').textContent=String(candidates.length);
    $('metric-quality').textContent=String(candidates.filter(r=>isNumber(r.score_home_b)&&Number(r.score_home_b)>=70).length);
    $('metric-cut').textContent=String(state.seconds);
    $('metric-cut-time').textContent=`${fmtTime(snapshot.cutoff_at)} ET`;
    const captureTime=snapshot.captured_at ? ` · calculado ${fmtTime(snapshot.captured_at)} ET` : '';
    $('session-origin').textContent=sourceLabel(snapshot.source)+captureTime+' · Pesos nuevos';
    const exportLink=$('export-csv');exportLink.href=query('/api/export');exportLink.classList.remove('disabled');exportLink.setAttribute('aria-disabled','false');
    renderNotice();renderTable();renderDetails();
  }catch(error){if(request!==state.request)return;state.offline=true;renderNotice();if(!state.snapshot)renderEmpty('Sin datos para este corte','El corte seleccionado no está disponible todavía.');}
}
function sortRows(a,b){return (Number(b.score_home_b??-1)-Number(a.score_home_b??-1))||String(a.ticker).localeCompare(String(b.ticker));}
function renderEmpty(title='La sesión aún no tiene datos',description='Los cortes aparecerán cuando el capturador los guarde. No necesitas dejar esta página abierta.'){
  if(!state.snapshot){$('opportunity-rows').replaceChildren();$('table-empty').hidden=false;$('table-empty').querySelector('h3').textContent=title;$('table-empty').querySelector('p').textContent=description;$('visible-count').textContent='Sin resultados todavía';$('metric-candidates').textContent='—';$('metric-quality').textContent='—';$('metric-cut').textContent='—';}
}
function renderTable(){
  const rows=(state.snapshot?.rows||[]).filter(row=>(state.all||candidate(row))&&(!state.quality||(isNumber(row.score_home_b)&&Number(row.score_home_b)>=70))&&String(row.ticker).toUpperCase().includes(state.search.toUpperCase())).sort(sortRows);
  $('visible-count').textContent=`${rows.length} ${rows.length===1?'empresa':'empresas'} · corte de ${cutLabel(state.seconds)}`;
  $('show-candidates').classList.toggle('active',!state.all);$('show-candidates').setAttribute('aria-pressed',String(!state.all));$('show-all').classList.toggle('active',state.all);$('show-all').setAttribute('aria-pressed',String(state.all));
  $('opportunity-title').textContent=state.all?'Diagnóstico completo':'Oportunidades';
  const picker=$('compact-ticker');
  const choices=rows.some(row=>row.ticker===state.selected) ? rows :
    [...(state.snapshot?.rows||[]).filter(row=>row.ticker===state.selected),...rows];
  picker.replaceChildren();
  const placeholder=node('option','Seleccionar');placeholder.value='';picker.append(placeholder);
  for(const row of choices){const option=node('option',`${row.ticker} · ${score(row.score_home_b)}`);option.value=row.ticker;picker.append(option);}
  picker.disabled=choices.length===0;
  picker.value=state.selected||'';
  const rowList=$('opportunity-rows');
  const focusedTicker=rowList.contains(document.activeElement) ? document.activeElement.dataset.ticker : null;
  rowList.replaceChildren();$('table-empty').hidden=rows.length>0;
  if(!rows.length){$('table-empty').querySelector('h3').textContent='No hay empresas con estos filtros';$('table-empty').querySelector('p').textContent='Prueba a quitar el filtro de score o consulta todas las empresas para revisar los motivos.';}
  for(const row of rows){
    const tr=node('tr');tr.classList.toggle('selected',row.ticker===state.selected);tr.setAttribute('aria-selected',String(row.ticker===state.selected));
    const company=node('td');const button=node('button',row.ticker,'ticker-button');button.dataset.ticker=row.ticker;button.setAttribute('aria-label',`Ver ${row.ticker}, score ${score(row.score_home_b)}`);company.append(button,node('span',row.gap_direction==='UP'?'Gap alcista':row.gap_direction==='DOWN'?'Gap bajista':'Sin gap','ticker-direction'));tr.append(company);
    const scoreTd=node('td');const scoreBox=node('div',undefined,'score-cell');
    if(isNumber(row.score_home_b)){const value=Number(row.score_home_b);scoreBox.classList.add(value>=70?'good':value>=60?'regular':'low');const track=node('div',undefined,'score-track');const fill=node('div',undefined,'score-fill');fill.style.width=Math.max(0,Math.min(100,value))+'%';track.append(fill);scoreBox.append(track,node('strong',number(value,1)));}
    else{scoreBox.classList.add('missing');scoreBox.textContent='Sin score';}
    scoreTd.append(scoreBox);tr.append(scoreTd,node('td',pct(row.gap_at_open_pct,2),Number(row.gap_at_open_pct)>=0?'positive':'negative'),node('td',pct(row.distance_cut_outside_bb_pct,2,false)));
    tr.addEventListener('click',()=>selectTicker(row.ticker,true));rowList.append(tr);
    if(row.ticker===focusedTicker)button.focus({preventScroll:true});
  }
}
function selectTicker(ticker, reveal=false){
  state.selected=ticker;renderTable();renderDetails();
  if(reveal && narrowLayout.matches)document.querySelector('.chart-panel').scrollIntoView({behavior:reduceMotion.matches?'auto':'smooth',block:'start'});
}
function renderDetails(){
  const row=state.snapshot?.rows.find(r=>r.ticker===state.selected);
  if(!row){
    $('signal-panel').hidden=true;$('data-provenance').hidden=true;$('chart-placeholder').hidden=false;
    $('external-chart').hidden=true;$('cut-chart').hidden=true;$('chart-error').hidden=true;
    $('selected-ticker').textContent='Gráfica';$('selected-summary').textContent='Selecciona una empresa.';
    $('selected-direction').hidden=true;$('yahoo-link').removeAttribute('href');$('yahoo-link').classList.add('disabled');
    state.chartKey=null;return;
  }
  $('selected-ticker').textContent=row.ticker;$('selected-direction').hidden=false;$('selected-direction').textContent=row.gap_direction==='UP'?'GAP ALCISTA':row.gap_direction==='DOWN'?'GAP BAJISTA':'SIN GAP';
  $('selected-summary').textContent=`${fmtDate(state.date)} · gap ${pct(row.gap_at_open_pct)} · fuera de BB ${pct(row.distance_cut_outside_bb_pct,2,false)}`;
  const yahoo=$('yahoo-link');yahoo.href=`https://finance.yahoo.com/quote/${encodeURIComponent(row.ticker==='SPX'?'^GSPC':row.ticker)}/chart/`;yahoo.classList.remove('disabled');yahoo.setAttribute('aria-disabled','false');
  $('signal-panel').hidden=false;$('data-provenance').hidden=false;
  $('detail-score').textContent=isNumber(row.score_home_b)?number(row.score_home_b,1):'—';$('detail-status').textContent=row.home_b_status||'Sin diagnóstico';
  $('detail-first').textContent=isNumber(row.first_price)?'$'+number(row.first_price,3):'—';$('detail-price').textContent=isNumber(row.price_at_cutoff)?'$'+number(row.price_at_cutoff,3):'—';$('detail-reversal').textContent=pct(row.reversal_pct,3);$('detail-prior-width').textContent=pct(row.prior_bb_width_pct,2,false);$('detail-width').textContent=pct(row.cutoff_bb_width_pct,2,false);$('detail-expansion').textContent=pct(row.bb_width_expansion_pct,1);
  $('score-breakdown').replaceChildren();
  const components=[['Lateralidad · 30%','lateral'],['Bandas delgadas · 30%','narrow'],['Estabilidad · 20%','stable'],['Distancia exterior · 20%','distance']];
  for(const [name,key]of components){const el=node('div',undefined,'breakdown-row');const value=row[`pattern_quality_${key}`];el.append(node('span',name),node('strong',isNumber(value)?`${number(value,1)}/100`:'—'));$('score-breakdown').append(el);}
  $('pattern-comparison').textContent=`Con los pesos anteriores: ${score(row.score_home_b_previous)}${isNumber(row.pattern_score_ceiling)?` · Tope por calidad de bandas: ${score(row.pattern_score_ceiling)}`:''}`;
  const pathLabel=row.pattern_coverage==='observations'?'Recorrido medido con las cotizaciones guardadas.':row.pattern_coverage==='endpoints'?'Este corte conserva el primer y último precio; no se conoce el recorrido intermedio.':'';
  const historyLabel=isNumber(row.pattern_prior_width_percentile)?` Percentil de ancho previo: ${number(row.pattern_prior_width_percentile*100,0)}.`:'';
  $('pattern-coverage').textContent=pathLabel+historyLabel;
  $('data-source').textContent=`Fuente del score: ${sourceLabel(row.source||state.snapshot.source)}${state.snapshot.imported?' · importado':''}`;
  let timestamp=`Último precio registrado: ${fmtTime(row.last_time)} ET`;
  if(row.last_time){
    const age=(new Date(state.snapshot.cutoff_at).getTime()-new Date(row.last_time).getTime())/1000;
    if(Number.isFinite(age)&&age>=0)timestamp+=` · ${number(age,0)} s antes del corte`;
  }
  $('data-timestamp').textContent=timestamp;
  renderChart(row);
}
function tvSymbol(ticker){
  const nasdaq=new Set('AMZN AAPL GOOG META MSFT NFLX TSLA PLTR ORCL AMD MU NVDA QCOM AVGO DASH LYFT QQQ PYPL LI COIN HOOD MRNA AAL SBUX COST MRVL WMT'.split(' '));
  const amex=new Set('SOXL DIA SPY IWM TNA TZA GLD SLV USO URA'.split(' '));
  if(ticker==='SPX')return'SP:SPX';return (nasdaq.has(ticker)?'NASDAQ:':amex.has(ticker)?'AMEX:':'NYSE:')+ticker;
}
let plotlyPromise;
function loadPlotly(){if(window.Plotly)return Promise.resolve(window.Plotly);if(plotlyPromise)return plotlyPromise;plotlyPromise=new Promise((resolve,reject)=>{const script=node('script');script.src='/vendor/plotly.min.js';script.onload=()=>resolve(window.Plotly);script.onerror=()=>{plotlyPromise=null;reject(new Error('No se pudo cargar la gráfica del corte.'));};document.head.append(script);});return plotlyPromise;}
async function renderChart(row){
  const market=state.chartMode==='market';
  document.querySelectorAll('[data-chart]').forEach(button=>{button.classList.toggle('active',button.dataset.chart===state.chartMode);button.setAttribute('aria-pressed',String(button.dataset.chart===state.chartMode));});
  $('chart-placeholder').hidden=true;$('external-chart').hidden=!market;$('cut-chart').hidden=market;
  $('chart-source-note').textContent=market?'TradingView · la cotización puede venir con retraso.':'Precios y bandas guardados por el escáner.';
  $('chart-footnote').textContent=market?'Para revisar los datos que determinaron el score, abre Vista del corte.':`${fmtDate(state.date)} · ${state.seconds} s desde la apertura`;
  const key=market?'market:'+row.ticker:`cut:${state.date}:${state.seconds}:${row.ticker}`;
  if(state.chartKey===key)return;state.chartKey=key;$('chart-error').hidden=true;
  if(market){
    const host=$('external-chart');host.replaceChildren();
    const container=node('div',undefined,'tradingview-widget-container');const widget=node('div',undefined,'tradingview-widget-container__widget');const copyright=node('div',undefined,'tradingview-widget-copyright');const link=node('a',`${row.ticker} por TradingView`);link.href=`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSymbol(row.ticker))}`;link.target='_blank';link.rel='noopener noreferrer nofollow';copyright.append(link);container.append(widget,copyright);host.append(container);
    const script=node('script');script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';script.async=true;script.textContent=JSON.stringify({autosize:true,symbol:tvSymbol(row.ticker),interval:'15',timezone:'America/New_York',theme:'light',style:'1',locale:'es',backgroundColor:'rgba(255, 254, 251, 1)',withdateranges:true,hide_side_toolbar:false,allow_symbol_change:false,save_image:false,studies:['BB@tv-basicstudies'],calendar:false,support_host:'https://www.tradingview.com'});script.onerror=()=>{if(state.chartKey===key){$('chart-error').textContent='No se pudo cargar TradingView. Puedes abrir Yahoo con el enlace superior o consultar la vista del corte guardado.';$('chart-error').hidden=false;}};container.append(script);
  }else{
    $('cut-chart').replaceChildren();const loading=node('div','Cargando la información del corte…','chart-empty');$('cut-chart').append(loading);
    try{
      const [figure,Plotly]=await Promise.all([api(query('/api/chart')+'&ticker='+encodeURIComponent(row.ticker)),loadPlotly()]);
      if(state.chartKey!==key)return;
      if(!figure.data?.length)throw new Error(figure.error||'No hay precios guardados para dibujar este corte.');
      const {height,template,...layout}=figure.layout||{};
      const data=figure.data.map(trace=>{
        const color=trace.name?.includes('inferior') ? '#7155ad' : trace.name?.includes('superior') ? '#087568' : null;
        if(color && trace.line)return {...trace,line:{...trace.line,color}};
        if(trace.name==='Precios observados')return {...trace,marker:{...trace.marker,color:'#9b630a'}};
        return trace;
      });
      $('cut-chart').replaceChildren();
      await Plotly.newPlot('cut-chart',data,{...layout,autosize:true,paper_bgcolor:'#fff',plot_bgcolor:'#fff',
        font:{family:'system-ui, sans-serif',color:'#424c5a'},
        annotations:(layout.annotations||[]).map(item=>({...item,font:{...item.font,color:'#525a67'}})),
        xaxis:{...layout.xaxis,automargin:true,gridcolor:'#edf0f5'},
        yaxis:{...layout.yaxis,automargin:true,gridcolor:'#edf0f5'}
      },{responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']});
    }
    catch(error){if(state.chartKey!==key)return;$('cut-chart').replaceChildren();$('chart-error').textContent=error.status===404?'No hay velas guardadas para esta empresa y fecha. El CSV conserva los valores de la señal, pero no incluye el historial de velas.':error.message;$('chart-error').hidden=false;}
  }
}
function changePage(page){
  if(state.page===page)return;
  state.page=page;state.follow=page==='scanner';state.chartMode=page==='scanner'?'market':'cut';
  document.querySelectorAll('[data-page]').forEach(button=>{
    const active=button.dataset.page===page;button.classList.toggle('active',active);
    if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  });
  $('page-title').textContent=page==='scanner'?'Escáner de apertura':'Historial de apertura';
  $('page-description').textContent=page==='scanner'?'Gap, giro y calidad del patrón de Bollinger.':'Consulta los cortes de una sesión guardada.';
  renderDetails();refreshAll();
}
document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>changePage(button.dataset.page)));
$('session-date').addEventListener('change',()=>{state.date=$('session-date').value;state.follow=false;state.seconds=Math.max(...state.sessions.find(s=>s.date===state.date).cuts.map(Number));state.selected=null;state.chartKey=null;renderSessions();loadSnapshot();});
document.querySelectorAll('[data-cut]').forEach(button=>button.addEventListener('click',()=>{state.seconds=Number(button.dataset.cut);state.follow=false;renderSessions();loadSnapshot();}));
$('follow-latest').addEventListener('click',()=>{state.follow=true;refreshAll();});
$('show-candidates').addEventListener('click',()=>{state.all=false;renderTable();});$('show-all').addEventListener('click',()=>{state.all=true;renderTable();});
$('ticker-search').addEventListener('input',event=>{state.search=event.target.value;renderTable();});$('quality-only').addEventListener('change',event=>{state.quality=event.target.checked;renderTable();});
$('compact-ticker').addEventListener('change',event=>selectTicker(event.target.value||null));
document.querySelectorAll('[data-chart]').forEach(button=>button.addEventListener('click',()=>{if(state.chartMode!==button.dataset.chart||!$('chart-error').hidden){state.chartMode=button.dataset.chart;state.chartKey=null;renderDetails();}}));
$('refresh-now').addEventListener('click',()=>refreshAll(true));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshAll();});
narrowLayout.addEventListener('change',arrangeWorkspace);
reduceMotion.addEventListener('change',()=>positionCutIndicator(true));
window.addEventListener('resize',()=>{positionCutIndicator(true);if(window.Plotly&&!$('cut-chart').hidden&&$('cut-chart').data)window.Plotly.Plots.resize('cut-chart');});
arrangeWorkspace();clockTick();setInterval(clockTick,1000);refreshAll();setInterval(refreshAll,10000);
