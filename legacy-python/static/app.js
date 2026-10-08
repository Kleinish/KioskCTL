const $ = (id) => document.getElementById(id);
let token = localStorage.getItem('kioskctl_token') || '';
let timer = null;
let lastStatus = null;
let mqttFormDirty = false;
let haFormDirty = false;
let browserExperienceDirty = false;
let idleFormDirty = false;
let thresholdFormDirty = false;
let screensaverFormDirty = false;
let signageFormDirty = false;
let immichFormDirty = false;

const browserExperienceIds = ['browserZoom','browserColorScheme','pullThreshold','pullToRefresh','edgeDrawer','onscreenKeyboard','browserPages'];
const idleFormIds = ['idleEnabled','idleDimAfter','idleOffAfter','idleDimBrightness','idleWakeOnInput'];
const mqttFormIds = ['mqttEnabled','mqttHost','mqttPort','mqttUsername','mqttPassword','mqttBaseTopic'];
const haFormIds = ['haEnabled','haDiscoveryPrefix'];
const thresholdFormIds = ['cpuThreshold','memoryThreshold','diskThreshold','temperatureThreshold'];
const screensaverFormIds = ['screensaverEnabled','screensaverAfter','screensaverInterval','screensaverFit','screensaverBackground','screensaverShuffle','screensaverKeepDisplayOn'];
const signageFormIds = ['signageEnabled','signageAfter','signageInterval','signageFit','signageBackground','signageShuffle','signageKeepDisplayOn','signageScheduleEnabled','signageScheduleStart','signageScheduleEnd'];
const immichFormIds = ['immichEnabled','immichServerUrl','immichApiKey','immichAlbumId','immichAfter','immichInterval','immichFit','immichBackground','immichRandomCount','immichKeepDisplayOn'];
function formHasFocus(ids) { return !!document.activeElement && ids.includes(document.activeElement.id); }

function applyTheme(theme){
  const next=theme==='light'?'light':'dark';
  document.documentElement.dataset.theme=next;
  localStorage.setItem('kioskctl_theme',next);
  const b=$('themeToggle');
  if(b){b.textContent=next==='light'?'☾ Dark mode':'☀ Light mode';b.setAttribute('aria-label',`Switch to ${next==='light'?'dark':'light'} mode`);}
}
function currentTheme(){return document.documentElement.dataset.theme==='light'?'light':'dark';}

const viewTitles = {dashboard:'Dashboard', settings:'Settings', system:'System'};
function setSettingsPane(name){
  const target=['browser','display','plugins'].includes(name)?name:'browser';
  document.querySelectorAll('[data-settings-pane]').forEach(p=>p.classList.toggle('active',p.dataset.settingsPane===target));
  document.querySelectorAll('[data-settings-target]').forEach(b=>b.classList.toggle('active',b.dataset.settingsTarget===target));
  localStorage.setItem('kioskctl_settings_pane',target);
  if(target==='display' && token) setTimeout(refreshScreensaverAssets,0);
  if(target==='plugins' && token && lastStatus) setTimeout(()=>renderPlugins(lastStatus),0);
}
function setView(name){
  let requested=name||'dashboard';
  if(requested==='overview') requested='dashboard';
  if(requested==='plugins'){setSettingsPane('plugins');requested='settings';}
  if(requested==='diagnostics') requested='system';
  if(requested==='browser' || requested==='display'){setSettingsPane(requested);requested='settings';}
  const target=viewTitles[requested]?requested:'dashboard';
  document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.dataset.view===target));
  document.querySelectorAll('[data-view-target]').forEach(b=>b.classList.toggle('active',b.dataset.viewTarget===target));
  $('pageTitle').textContent=viewTitles[target];
  const headerHealth=$('healthIndicators'); if(headerHealth) headerHealth.classList.toggle('hidden',target!=='dashboard');
  const headerPower=$('dashboardPower'); if(headerPower) headerPower.classList.toggle('hidden',target!=='dashboard');
  localStorage.setItem('kioskctl_view',target);
  $('sidebar').classList.remove('open'); $('sidebarBackdrop').classList.remove('open');
  if(target==='system' && token) refreshDiagnostics();
  if(target==='settings' && localStorage.getItem('kioskctl_settings_pane')==='plugins' && token && lastStatus) renderPlugins(lastStatus);
}

function log(msg) { $('log').textContent = `${new Date().toLocaleTimeString()}  ${msg}\n` + $('log').textContent.slice(0, 4000); }

async function api(path, options={}) {
  const headers = {'X-API-Key': token, ...(options.headers || {})};
  if (options.body && typeof options.body !== 'string') { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body); }
  const r = await fetch(`/api/${path}`, {...options, headers, cache:'no-store'});
  if (!r.ok) { let message = `${r.status} ${r.statusText}`; try { const j = await r.json(); message = j.detail || message; } catch (_) {} throw new Error(message); }
  const type = r.headers.get('content-type') || '';
  return type.includes('application/json') ? r.json() : r;
}

function esc(v){return String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));}
function fmtUptime(sec) { const d=Math.floor(sec/86400),h=Math.floor((sec%86400)/3600),m=Math.floor((sec%3600)/60); return `${d}d ${h}h ${m}m`; }
function stat(label,value,sub='') { return `<div class="stat"><div class="label">${label}</div><div class="value">${value ?? '—'}</div>${sub?`<div class="sub">${sub}</div>`:''}</div>`; }
function indicator(label,value,threshold,unit=''){
  const numeric=Number(value); const limit=Number(threshold||0); const available=Number.isFinite(numeric);
  const alert=available && limit>0 && numeric>=limit; const disabled=limit<=0;
  const cls=disabled?'disabled':(alert?'alert':'ok');
  const shown=available?`${Math.round(numeric)}${unit}`:'—';
  const note=disabled?'threshold disabled':`alert ≥ ${limit}${unit}`;
  return `<div class="header-health-item ${cls}" title="${esc(label)}: ${esc(shown)}; ${esc(note)}"><span class="indicator-light"></span><span class="header-health-label">${esc(label)}</span><strong>${esc(shown)}</strong></div>`;
}
function renderHealthIndicators(s){
  const t=s.monitoring?.thresholds||{};
  const idle=s.idle||{}, saver=s.screensaver||{};
  let mode='ACTIVE',modeClass='ok',modeTitle='Kiosk active';
  if(saver.active){mode='SAVER';modeClass='screensaver';modeTitle=`${saver.provider_name||'Screensaver'} active`; }
  else if(idle.state==='off'){mode='SLEEP';modeClass='sleep';modeTitle='Display powered off by idle policy';}
  else if(idle.state==='dimmed'){mode='DIM';modeClass='sleep';modeTitle='Display dimmed by idle policy';}
  $('healthIndicators').innerHTML=[
    indicator('CPU',s.cpu_percent,t.cpu_percent,'%'),
    indicator('MEM',s.memory_percent,t.memory_percent,'%'),
    indicator('DISK',s.disk_percent,t.disk_percent,'%'),
    indicator('TEMP',s.temperature_c,t.temperature_c,'°C'),
    `<div class="header-health-item ${s.browser_active?'ok':'alert'}" title="Browser ${s.browser_active?'running':'not running'}"><span class="indicator-light"></span><span class="header-health-label">WEB</span><strong>${s.browser_active?'OK':'OFF'}</strong></div>`,
    `<div class="header-health-item ${modeClass}" title="${esc(modeTitle)}"><span class="indicator-light"></span><span class="header-health-label">MODE</span><strong>${mode}</strong></div>`
  ].join('');
}
function renderSystemMetrics(s){
  $('systemStats').innerHTML=[
    stat('CPU',`${Math.round(Number(s.cpu_percent||0))}%`),
    stat('Memory',`${Math.round(Number(s.memory_percent||0))}%`),
    stat('Disk',`${Math.round(Number(s.disk_percent||0))}%`),
    stat('Temp',s.temperature_c==null?'—':`${Math.round(Number(s.temperature_c))}°C`,s.temperature_sensor||''),
    stat('Uptime',fmtUptime(Number(s.uptime_seconds||0))),
    stat('Browser',s.browser_active?'Running':(s.kiosk_enabled?'Starting / Failed':'Disabled'))
  ].join('');
  const t=s.monitoring?.thresholds||{};
  if(!thresholdFormDirty && !formHasFocus(thresholdFormIds)){
    $('cpuThreshold').value=t.cpu_percent??90; $('memoryThreshold').value=t.memory_percent??90;
    $('diskThreshold').value=t.disk_percent??90; $('temperatureThreshold').value=t.temperature_c??80;
  }
}
function modeLabel(m) { return `${m.width}×${m.height} @ ${Number(m.refresh_hz).toFixed(1)}Hz${m.preferred?' ★':''}`; }
function pagesToText(pages){return (pages||[]).map(p=>`${p.name||'Page'} | ${p.url||''}`).join('\n');}
function parsePages(text){
  const pages=[];
  String(text||'').split(/\r?\n/).map(x=>x.trim()).filter(Boolean).forEach((line,index)=>{
    let name='',url=''; const pipe=line.indexOf('|');
    if(pipe>=0){name=line.slice(0,pipe).trim();url=line.slice(pipe+1).trim();}else{url=line;name=`Page ${index+1}`;}
    if(!/^https?:\/\//i.test(url) && !/^file:\/\//i.test(url)) throw new Error(`Page URL must start with http://, https://, or file://: ${url}`);
    pages.push({name:name||`Page ${index+1}`,url});
  });
  return pages;
}
function renderBrowserExperience(s){
  const x=s.browser_experience||{}, t=x.touch_ui||{};
  if(!browserExperienceDirty && !formHasFocus(browserExperienceIds)){
    const zoom=String(x.zoom??1); if(![...$('browserZoom').options].some(o=>o.value===zoom))$('browserZoom').add(new Option(`${Math.round(Number(zoom)*100)}%`,zoom));
    $('browserZoom').value=zoom; $('browserColorScheme').value=x.color_scheme||'auto'; $('pullThreshold').value=t.pull_threshold_px??110; $('pullToRefresh').checked=t.pull_to_refresh!==false;
    $('edgeDrawer').checked=!!t.edge_drawer; $('onscreenKeyboard').checked=!!t.onscreen_keyboard; $('browserPages').value=pagesToText(x.pages||[]);
  }
  const pages=[{name:'Home',url:s.configured_url},...(x.pages||[])];
  const selected=$('pageSelect').value; $('pageSelect').innerHTML='<option value="">Configured pages</option>'+pages.map((p,i)=>`<option value="${esc(p.url)}">${esc(p.name||`Page ${i+1}`)}</option>`).join('');
  if([...$('pageSelect').options].some(o=>o.value===selected))$('pageSelect').value=selected;
}
function renderIdle(s){
  const i=s.idle||{};
  if(!idleFormDirty && !formHasFocus(idleFormIds)){
    $('idleEnabled').checked=!!i.enabled; $('idleDimAfter').value=i.dim_after_seconds??300; $('idleOffAfter').value=i.off_after_seconds??600;
    $('idleDimBrightness').value=i.dim_brightness??20; $('idleWakeOnInput').checked=i.wake_on_input!==false;
  }
  const state=i.state||'active'; $('idleBadge').textContent=i.enabled?state.toUpperCase():'DISABLED';
  $('idleBadge').className=`status-badge ${i.enabled?(state==='active'?'ok-badge':'warn-badge'):''}`;
  $('idleInfo').textContent=`Idle state: ${state} • idle ${i.idle_seconds??0}s • monitoring ${(i.monitored_devices||[]).length} input device${(i.monitored_devices||[]).length===1?'':'s'}${i.last_error?` • ${i.last_error}`:''}`;
}

function renderScreensaver(s){
  const sc=s.screensaver||{};
  if(!screensaverFormDirty && !formHasFocus(screensaverFormIds)){
    $('screensaverEnabled').checked=!!sc.enabled;
    $('screensaverAfter').value=sc.after_seconds??120;
    $('screensaverInterval').value=sc.interval_seconds??10;
    $('screensaverFit').value=sc.fit||'contain';
    $('screensaverBackground').value=sc.background||'#000000';
    $('screensaverShuffle').checked=!!sc.shuffle;
    $('screensaverKeepDisplayOn').checked=sc.keep_display_on!==false;
  }
  $('screensaverBadge').textContent=sc.active?'ACTIVE':(sc.enabled?'ARMED':'DISABLED');
  $('screensaverBadge').className=`status-badge ${sc.active?'warn-badge':(sc.enabled?'ok-badge':'')}`;
  const images=Array.isArray(sc.images)?sc.images:[];
  $('screensaverImages').innerHTML=images.length?images.map(name=>`<div class="asset-row"><span title="${esc(name)}">${esc(name)}</span><button type="button" class="danger compact-delete" data-delete-screensaver="${esc(name)}">Delete</button></div>`).join(''):'No slideshow images uploaded.';
}

async function refreshScreensaverAssets(){
  try{
    const data=await api('screensaver/images');
    if(lastStatus){
      lastStatus.screensaver={...(lastStatus.screensaver||{}),...(data.config||{}),images:data.images||[],active:!!data.active};
      renderScreensaver(lastStatus);
      renderHealthIndicators(lastStatus);
    }
  }catch(e){console.debug('screensaver inventory refresh',e);}
}

function renderPlugins(s) {
  const m=s.mqtt||{};

  // Keep live connection/status information updating, but never overwrite a form
  // while the user is editing it. A dirty form remains local until Save or reload.
  if (!mqttFormDirty && !formHasFocus(mqttFormIds)) {
    $('mqttEnabled').checked=!!m.enabled;
    $('mqttHost').value=m.host||'';
    $('mqttPort').value=m.port||1883;
    $('mqttUsername').value=m.username||'';
    $('mqttBaseTopic').value=m.base_topic||'kioskctl';
    $('mqttPassword').value='';
  }
  $('mqttPassword').placeholder=m.password_set?'Stored password — leave blank to keep it':'MQTT password';
  $('mqttBadge').textContent=m.connected?'CONNECTED':(m.enabled?'DISCONNECTED':'DISABLED');
  $('mqttBadge').className=`status-badge ${m.connected?'ok-badge':(m.enabled?'warn-badge':'')}`;
  $('mqttInfo').textContent=`${m.host||'—'}:${m.port||'—'} • ${m.client_id||'—'} • topic ${m.device_topic||'—'}${m.last_error?` • last error: ${m.last_error}`:''}`;

  const ha=s.plugins?.homeassistant||{};
  if (!haFormDirty && !formHasFocus(haFormIds)) {
    $('haEnabled').checked=!!ha.enabled;
    $('haDiscoveryPrefix').value=ha.discovery_prefix||'homeassistant';
  }
  $('haBadge').textContent=ha.enabled?(ha.mqtt_connected?'ACTIVE':'WAITING FOR MQTT'):'DISABLED';
  $('haBadge').className=`status-badge ${ha.enabled&&ha.mqtt_connected?'ok-badge':(ha.enabled?'warn-badge':'')}`;
  $('haInfo').textContent=`${ha.entities||0} entities • discovery ${ha.discovery_prefix||'homeassistant'} • last publish ${ha.last_publish?new Date(ha.last_publish).toLocaleString():'never'}${ha.last_error?` • ${ha.last_error}`:''}`;
  const manifest=ha.manifest||s.plugin_manifests?.homeassistant||{}; $('haManifest').textContent=`Capabilities: ${(manifest.capabilities||[]).join(' • ')||'—'}`;
  $('republishHa').disabled=!(ha.enabled&&m.connected);

  const signage=s.plugins?.digital_signage||{};
  $('digitalSignageConfig').classList.toggle('hidden',!signage.installed);
  $('installSignage').classList.toggle('hidden',!!signage.installed);
  $('removeSignage').classList.toggle('hidden',!signage.installed);
  $('signageCatalogBadge').textContent=signage.installed?(signage.enabled?'ACTIVE':'INSTALLED'):'AVAILABLE';
  $('signageCatalogBadge').className=`status-badge ${signage.installed?(signage.enabled?'ok-badge':''):''}`;
  if(signage.installed){
    if(!signageFormDirty && !formHasFocus(signageFormIds)){
      $('signageEnabled').checked=!!signage.enabled;
      $('signageAfter').value=signage.after_seconds??120;
      $('signageInterval').value=signage.interval_seconds??10;
      $('signageFit').value=signage.fit||'cover';
      $('signageBackground').value=signage.background||'#000000';
      $('signageShuffle').checked=!!signage.shuffle;
      $('signageKeepDisplayOn').checked=signage.keep_display_on!==false;
      $('signageScheduleEnabled').checked=!!signage.schedule_enabled;
      $('signageScheduleStart').value=signage.schedule_start||'00:00';
      $('signageScheduleEnd').value=signage.schedule_end||'23:59';
      const days=new Set((signage.schedule_days||[0,1,2,3,4,5,6]).map(Number));
      document.querySelectorAll('#signageDays input').forEach(x=>x.checked=days.has(Number(x.value)));
    }
    $('signageBadge').textContent=signage.enabled?(signage.schedule_active?'ARMED':'OUTSIDE SCHEDULE'):'DISABLED';
    $('signageBadge').className=`status-badge ${signage.enabled?(signage.schedule_active?'ok-badge':'warn-badge'):''}`;
    const images=Array.isArray(signage.images)?signage.images:[];
    $('signageImages').innerHTML=images.length?images.map(name=>`<div class="asset-row"><span title="${esc(name)}">${esc(name)}</span><button type="button" class="danger compact-delete" data-delete-signage="${esc(name)}">Delete</button></div>`).join(''):'No signage images uploaded.';
  }

  const immich=s.plugins?.immich||{};
  $('immichConfig').classList.toggle('hidden',!immich.installed);
  $('installImmich').classList.toggle('hidden',!!immich.installed);
  $('removeImmich').classList.toggle('hidden',!immich.installed);
  $('immichCatalogBadge').textContent=immich.installed?(immich.enabled?'ACTIVE':'INSTALLED'):'AVAILABLE';
  $('immichCatalogBadge').className=`status-badge ${immich.installed?(immich.enabled?'ok-badge':''):''}`;
  if(immich.installed){
    if(!immichFormDirty && !formHasFocus(immichFormIds)){
      $('immichEnabled').checked=!!immich.enabled;
      $('immichServerUrl').value=immich.server_url||'';
      $('immichApiKey').value='';
      $('immichAlbumId').value=immich.album_id||'';
      $('immichAfter').value=immich.after_seconds??120;
      $('immichInterval').value=immich.interval_seconds??15;
      $('immichFit').value=immich.fit||'contain';
      $('immichBackground').value=immich.background||'#000000';
      $('immichRandomCount').value=immich.random_count??100;
      $('immichKeepDisplayOn').checked=immich.keep_display_on!==false;
    }
    $('immichApiKey').placeholder=immich.api_key_set?'Stored API key — leave blank to keep it':'Immich API key';
    $('immichBadge').textContent=immich.enabled?'ACTIVE':'DISABLED';
    $('immichBadge').className=`status-badge ${immich.enabled?'ok-badge':''}`;
    $('immichInfo').textContent=`${immich.asset_count||0} cached image${immich.asset_count===1?'':'s'}${immich.album_id?` • album ${immich.album_id}`:' • random library'} • original source when browser-compatible${immich.last_error?` • ${immich.last_error}`:''}`;
  }
}
function populateDisplay(s) {
  const currentOut = s.display_config?.output || 'auto';
  const outSelect = $('displayOutput');
  outSelect.innerHTML = '<option value="auto">Auto</option>' + (s.output_details||[]).map(o=>`<option value="${o.name}">${o.name}</option>`).join('');
  outSelect.value = [...outSelect.options].some(o=>o.value===currentOut) ? currentOut : 'auto';
  const selected = (s.output_details||[]).find(o=>o.name===outSelect.value) || (s.output_details||[])[0];
  const modes = [];
  const seen = new Set();
  (selected?.modes||[]).forEach(m=>{ const key=`${m.width}x${m.height}`; if(!seen.has(key)){seen.add(key);modes.push(m);} });
  $('displayMode').innerHTML = '<option value="preferred">Preferred</option>' + modes.map(m=>`<option value="${m.width}x${m.height}">${modeLabel(m)}</option>`).join('');
  $('displayMode').value = [...$('displayMode').options].some(o=>o.value===String(s.display_config?.mode)) ? String(s.display_config.mode) : 'preferred';
  $('displayTransform').value = String(s.display_config?.transform || 'normal');
  const scale = String(s.display_config?.scale ?? 1);
  if (![...$('displayScale').options].some(o=>o.value===scale)) $('displayScale').add(new Option(`${Math.round(Number(scale)*100)}%`,scale));
  $('displayScale').value=scale;
  updateRefreshOptions(selected, $('displayMode').value, s.display_config?.refresh_hz ?? 'auto');
  if(selected){ const cm=selected.current_mode; $('displayInfo').textContent = `${selected.name} • ${cm?modeLabel(cm):'mode unknown'} • scale ${selected.scale ?? '—'} • ${selected.transform ?? 'normal'} • socket ${s.wayland_display||'—'}`; }
  else $('displayInfo').textContent='No Wayland output detected';
}

function updateRefreshOptions(selected, modeValue, wanted='auto') {
  const sel=$('displayRefresh');
  let candidates=selected?.modes||[];
  if(modeValue!=='preferred' && /^\d+x\d+$/.test(modeValue)){
    const [w,h]=modeValue.split('x').map(Number); candidates=candidates.filter(m=>m.width===w&&m.height===h);
  } else if(selected?.preferred_mode) {
    const p=selected.preferred_mode; candidates=candidates.filter(m=>m.width===p.width&&m.height===p.height);
  }
  const rates=[...new Set(candidates.map(m=>Number(m.refresh_hz).toFixed(3)))];
  sel.innerHTML='<option value="auto">Auto / closest</option>'+rates.map(r=>`<option value="${r}">${Number(r).toFixed(2)} Hz</option>`).join('');
  const want=String(wanted); sel.value=[...sel.options].some(o=>o.value===want)?want:'auto';
}

async function refreshStatus() {
  try {
    const s = await api('status'); lastStatus=s;
    $('authCard').classList.add('hidden'); $('dashboard').classList.remove('hidden'); $('sideNav').classList.remove('hidden');

    // Render each area independently. One unexpected/missing field must never
    // prevent Display, Audio, Temperature or Input from updating.
    try {
      $('online').textContent = s.browser_active ? '● ONLINE' : '● AGENT ONLINE';
      $('subtitle').textContent = `${s.device_name} • ${s.distro?.name || 'Linux'}`;
      const fullUrl=s.current_url || s.configured_url || '—';
      $('currentUrl').textContent=fullUrl; $('currentUrl').title=fullUrl; $('remoteScreenCard').title=fullUrl==='—'?'':`Current kiosk URL: ${fullUrl}`; $('url').value=s.configured_url || '';
      renderHealthIndicators(s); renderSystemMetrics(s);
      $('providerInfo').textContent=`Kiosk: ${s.kiosk_enabled?'enabled':'disabled'} • Provider: ${s.browser_provider||'—'} • ${s.browser_executable||'—'}`;
      $('enableKiosk').disabled=!!s.kiosk_enabled; $('disableKiosk').disabled=!s.kiosk_enabled;
      if(s.viewport) $('viewportInfo').textContent=`Viewport: ${Math.round(Number(s.viewport.innerWidth||0))}×${Math.round(Number(s.viewport.innerHeight||0))} • DPR ${s.viewport.dpr ?? '—'}`; else $('viewportInfo').textContent='Viewport: —';
    } catch(e) { console.error('core render', e); log(`UI core render: ${e.message}`); }

    try {
      if(s.volume!=null){$('volume').disabled=false;$('volume').value=s.volume;$('volumeLabel').textContent=`${s.volume}%`;}else{$('volume').disabled=true;$('volumeLabel').textContent='Unavailable';}
      $('audioInfo').textContent=`Provider: ${s.audio_provider || 'none detected'}`;
      if(s.brightness!=null){$('brightness').disabled=false;$('brightness').value=s.brightness;$('brightnessLabel').textContent=`${s.brightness}%`;}else{$('brightness').disabled=true;$('brightnessLabel').textContent='Unavailable';}
      $('tempInfo').textContent=`Sensor: ${s.temperature_sensor || 'none selected'}`;
      const devices=(s.input_devices||[]).filter(d=>d.type!=='other').slice(0,12);
      $('inputInfo').innerHTML=devices.length?devices.map(d=>`<div class="device-pill"><span>${esc(d.name)}</span><span>${esc(d.type)}${d.event?` • ${esc(d.event)}`:''}</span></div>`).join(''):'No input devices classified';
      $('rotateTouch').checked=s.input_config?.rotate_touch_with_display!==false;
      $('ignoreTouchMouse').checked=s.input_config?.ignore_touch_mouse_emulation!==false;
      $('disableTouchpad').checked=s.input_config?.disable_touchpad_in_kiosk===true;
      const tm=s.touch_mapping||{}; const touchCount=(tm.touchscreens||[]).length;
      const activeMatrices=Object.values(tm.active_matrices||{});
      const activeCount=tm.matrix?activeMatrices.filter(v=>v===tm.matrix).length:0;
      const activeText=touchCount&&tm.enabled?` • matrix active ${activeCount}/${touchCount}`:'';
      $('touchInfo').textContent=`Touch mapping: ${tm.enabled?'follows display':'disabled'} • ${tm.transform||'normal'} • ${tm.matrix||'no matrix'} • ${touchCount} touchscreen${touchCount===1?'':'s'} detected${tm.rule_installed?' • rule installed':''}${activeText}`;
      const tp=s.touch_pointer_suppression||{}; const pc=(tp.candidates||[]).length;
      $('touchPointerInfo').textContent=`Touch pointer suppression: ${tp.enabled?'enabled':'disabled'} • ${pc} compatibility mouse node${pc===1?'':'s'} detected${tp.rule_installed?' • rule installed':''}${pc?` • active ${tp.active_count||0}/${pc}`:''}`;
      const tps=s.touchpad_suppression||{}; const tc=(tps.candidates||[]).length;
      $('touchpadInfo').textContent=`Touchpad suppression: ${tps.enabled?'enabled':'disabled'} • ${tc} touchpad node${tc===1?'':'s'} detected${tps.rule_installed?' • rule installed':''}${tc?` • active ${tps.active_count||0}/${tc}`:''}`;
    } catch(e) { console.error('hardware render', e); log(`UI hardware render: ${e.message}`); }

    try {
      if(s.geometry){
        const g=s.geometry;
        $('geometryInfo').className=`screen-help ${g.matched?'geometry-ok':'geometry-warn'}`;
        $('geometryInfo').textContent=`Geometry: ${g.matched?'matched':'mismatch'} • output ${g.expected_width}×${g.expected_height} • browser ${g.browser_width}×${g.browser_height}`;
      } else { $('geometryInfo').className='screen-help'; $('geometryInfo').textContent=`Geometry: ${s.browser_active?'waiting for display data':'—'}`; }
      populateDisplay(s);
      if(s.display_source) $('displayInfo').textContent += ` • ${s.display_source}`;
    } catch(e) { console.error('display render', e); log(`UI display render: ${e.message}`); }

    try { renderBrowserExperience(s); } catch(e) { console.error('browser experience render',e); log(`UI browser experience render: ${e.message}`); }
    try { renderIdle(s); } catch(e) { console.error('idle render',e); log(`UI idle render: ${e.message}`); }
    try { renderScreensaver(s); } catch(e) { console.error('screensaver render',e); log(`UI screensaver render: ${e.message}`); }
    try {
      const p=s.browser_prompts||{}; $('disablePasswords').checked=!p.password_manager; $('blockNotifications').checked=(p.notifications||'block')==='block'; $('disableAutofill').checked=!p.autofill; $('disableTranslate').checked=!p.translate;
    } catch(e) { console.error('prompt render', e); }

    try { renderPlugins(s); } catch(e) { console.error('plugin render', e); log(`UI plugin render: ${e.message}`); }
  } catch(e) {
    console.error('status refresh', e);
    $('online').textContent='● LOCKED / OFFLINE';
    if(String(e).includes('401')){$('authCard').classList.remove('hidden');$('dashboard').classList.add('hidden');$('sideNav').classList.add('hidden');}
    else log(`Status: ${e.message}`);
  }
}

async function refreshShot(){try{const r=await fetch('/api/screenshot',{headers:{'X-API-Key':token},cache:'no-store'});if(!r.ok)throw new Error(await r.text());const blob=await r.blob();const old=$('screen').src;$('screen').src=URL.createObjectURL(blob);if(old.startsWith('blob:'))URL.revokeObjectURL(old);}catch(e){log(`Screenshot: ${e.message}`);}}
function showFocus(f){ if(!f){$('focusInfo').textContent='Focus: —';return;} const name=[f.tag,f.type,f.id?`#${f.id}`:''].filter(Boolean).join(' '); $('focusInfo').textContent=`Focus: ${name||'unknown'}${f.editable?' • editable':' • not editable'}`; }

async function refreshDiagnostics(){try{
  $('diagnostics').textContent='Loading diagnostics…';
  const d=await api('diagnostics');
  $('diagSummary').innerHTML=`<span class="ok">${d.summary.ok} OK</span><span class="${d.summary.warnings?'warn-text':'ok'}">${d.summary.warnings} warnings</span>`;
  $('diagnostics').textContent=d.checks.map(c=>`${c.ok?'OK  ':'WARN'} ${c.id.padEnd(18)} ${c.message}`).join('\n')+
    `\n\nBrowser: ${d.browser.provider} ${d.browser.version||''}`+
    `\nAudio: ${d.audio.provider||'none'}`+
    `\nWayland: ${d.display.wayland_display||'unknown'} @ ${d.display.runtime_dir||''} (${d.display.source||'unknown source'})`+
    `\nOutputs: ${(d.display.outputs||[]).map(o=>o.name).join(', ')||'none'}`+
    `\nGeometry: ${d.display.geometry?(d.display.geometry.matched?'matched':'MISMATCH'):'unknown'}`+
    `\nInputs: ${(d.input_devices||[]).filter(x=>x.type!=='other').map(x=>`${x.type}:${x.name}`).join(' | ')||'none classified'}`+
    `\nTouch rotation: ${d.touch_mapping?.enabled?'enabled':'disabled'} ${d.touch_mapping?.matrix||''}`+
    `\nMQTT: ${d.mqtt?.enabled?(d.mqtt.connected?'connected':'DISCONNECTED'):'disabled'} ${d.mqtt?.host||''}:${d.mqtt?.port||''}`+
    `\nHome Assistant: ${d.plugins?.homeassistant?.enabled?(d.plugins.homeassistant.mqtt_connected?'active':'waiting'):'disabled'}`;
}catch(e){$('diagnostics').textContent=`Diagnostics failed: ${e.message}`;}}


$('saveToken').onclick=()=>{token=$('token').value.trim();localStorage.setItem('kioskctl_token',token);refreshStatus().then(()=>{refreshShot();refreshDiagnostics();});}; $('token').value=token;
applyTheme(currentTheme()); $('themeToggle').onclick=()=>applyTheme(currentTheme()==='light'?'dark':'light');
$('refreshShot').onclick=refreshShot; $('refreshDiagnostics').onclick=refreshDiagnostics;
$('go').onclick=async()=>{try{const u=$('url').value.trim();await api('browser/url',{method:'POST',body:{url:u}});log(`Set home URL and opened ${u}`);await refreshStatus();setTimeout(refreshShot,800);}catch(e){log(e.message);}};
$('openPage').onclick=async()=>{const u=$('pageSelect').value;if(!u)return;try{await api('browser/navigate',{method:'POST',body:{url:u}});log(`Opened configured page ${u}`);setTimeout(refreshStatus,400);setTimeout(refreshShot,800);}catch(e){log(`Page: ${e.message}`);}};

document.querySelectorAll('[data-action]').forEach(btn=>btn.onclick=async()=>{if(btn.dataset.confirm&&!confirm(btn.dataset.confirm))return;try{await api(btn.dataset.action,{method:'POST'});log(`${btn.textContent}: OK`);setTimeout(refreshStatus,800);setTimeout(refreshShot,1200);}catch(e){log(`${btn.textContent}: ${e.message}`);}});

$('savePrompts').onclick=async()=>{try{await api('browser/prompts',{method:'POST',body:{password_manager:!$('disablePasswords').checked,notifications:$('blockNotifications').checked?'block':'ask',autofill:!$('disableAutofill').checked,translate:!$('disableTranslate').checked}});log('Browser prompt settings applied');setTimeout(refreshStatus,1200);}catch(e){log(`Browser settings: ${e.message}`);}};
$('saveBrowserExperience').onclick=async()=>{
  const b=$('saveBrowserExperience'),f=$('browserExperienceStatus'); b.disabled=true;f.className='save-status pending';f.textContent='Saving browser experience…';
  try{const pages=parsePages($('browserPages').value);const body={zoom:Number($('browserZoom').value),color_scheme:$('browserColorScheme').value,pages,pull_to_refresh:$('pullToRefresh').checked,pull_threshold_px:Number($('pullThreshold').value),edge_drawer:$('edgeDrawer').checked,onscreen_keyboard:$('onscreenKeyboard').checked};
    const r=await api('browser/experience',{method:'POST',body});browserExperienceDirty=false;f.className='save-status ok-text';f.textContent=r.restarted?'Saved — browser restarted with new touch features.':'Saved — touch features applied.';log('Browser experience saved');setTimeout(refreshStatus,1200);setTimeout(refreshShot,1800);
  }catch(e){f.className='save-status error-text';f.textContent=`Save failed: ${e.message}`;log(`Browser experience: ${e.message}`);}finally{b.disabled=false;}
};

$('applyBrowserTheme').onclick=async()=>{
  const f=$('browserThemeStatus'); f.textContent='Applying…';
  try{const r=await api('browser/color-scheme',{method:'POST',body:{color_scheme:$('browserColorScheme').value}});browserExperienceDirty=false;f.textContent=r.restarted?`Applied ${r.color_scheme} theme; browser restarted.`:(r.applied?`Applied ${r.color_scheme} theme to kiosk page.`:`Saved ${r.color_scheme}; browser will apply it when available.`);log(`Kiosk page theme: ${r.color_scheme}`);setTimeout(refreshStatus,400);setTimeout(refreshShot,700);}
  catch(e){f.textContent=`Theme failed: ${e.message}`;log(`Page theme: ${e.message}`);}
};

$('displayOutput').onchange=()=>{if(lastStatus)populateDisplay({...lastStatus,display_config:{...lastStatus.display_config,output:$('displayOutput').value}});};
$('displayMode').onchange=()=>{if(!lastStatus)return;const selected=(lastStatus.output_details||[]).find(o=>o.name===$('displayOutput').value)||(lastStatus.output_details||[])[0];updateRefreshOptions(selected,$('displayMode').value,'auto');};
$('applyDisplay').onclick=async()=>{try{
  const r=await api('display/config',{method:'POST',body:{output:$('displayOutput').value,mode:$('displayMode').value,refresh_hz:$('displayRefresh').value,scale:Number($('displayScale').value),transform:$('displayTransform').value,rotate_touch_with_display:$('rotateTouch').checked,ignore_touch_mouse_emulation:$('ignoreTouchMouse').checked,disable_touchpad_in_kiosk:$('disableTouchpad').checked}});
  const msg=r.session_restarted?'Display + touch rotation applied; kiosk session restarted':(r.warning?`Display saved: ${r.warning}`:'Display + input configuration applied');
  log(msg);setTimeout(refreshStatus,r.session_restarted?1500:500);setTimeout(refreshShot,r.session_restarted?2200:800);
}catch(e){log(`Display: ${e.message}`);}};
$('reinitDisplay').onclick=async()=>{try{log('Reinitializing display…');await api('display/reinitialize',{method:'POST'});log('Display reinitialized');setTimeout(refreshStatus,600);setTimeout(refreshShot,900);}catch(e){log(`Reinitialize: ${e.message}`);}};
$('saveIdle').onclick=async()=>{const b=$('saveIdle'),f=$('idleSaveStatus');b.disabled=true;f.className='save-status pending';f.textContent='Saving idle policy…';try{const r=await api('idle/config',{method:'POST',body:{enabled:$('idleEnabled').checked,dim_after_seconds:Number($('idleDimAfter').value),off_after_seconds:Number($('idleOffAfter').value),dim_brightness:Number($('idleDimBrightness').value),wake_on_input:$('idleWakeOnInput').checked}});idleFormDirty=false;f.className='save-status ok-text';f.textContent='Idle & wake settings saved.';renderIdle({...lastStatus,idle:r.idle});log('Idle & wake settings saved');setTimeout(refreshStatus,500);}catch(e){f.className='save-status error-text';f.textContent=`Save failed: ${e.message}`;log(`Idle: ${e.message}`);}finally{b.disabled=false;}};

$('saveScreensaver').onclick=async()=>{const b=$('saveScreensaver'),f=$('screensaverSaveStatus');b.disabled=true;f.className='save-status pending';f.textContent='Saving screensaver…';try{await api('screensaver/config',{method:'POST',body:{enabled:$('screensaverEnabled').checked,after_seconds:Number($('screensaverAfter').value),interval_seconds:Number($('screensaverInterval').value),fit:$('screensaverFit').value,background:$('screensaverBackground').value,shuffle:$('screensaverShuffle').checked,keep_display_on:$('screensaverKeepDisplayOn').checked}});screensaverFormDirty=false;f.className='save-status ok-text';f.textContent='Screensaver settings saved.';log('Screensaver settings saved');await refreshStatus();}catch(e){f.className='save-status error-text';f.textContent=`Save failed: ${e.message}`;log(`Screensaver: ${e.message}`);}finally{b.disabled=false;}};

$('uploadScreensaverImages').onclick=async()=>{const files=[...($('screensaverFiles').files||[])],f=$('screensaverUploadStatus'),b=$('uploadScreensaverImages');if(!files.length){f.className='save-status error-text';f.textContent='Choose one or more images first.';return;}b.disabled=true;try{let done=0;for(const file of files){if(file.size>15*1024*1024)throw new Error(`${file.name} is larger than 15 MiB`);f.className='save-status pending';f.textContent=`Uploading ${file.name} (${done+1}/${files.length})…`;const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result||'').split(',',2)[1]||'');r.onerror=()=>reject(r.error||new Error('File read failed'));r.readAsDataURL(file);});await api('screensaver/images',{method:'POST',body:{name:file.name,data_base64:data}});done++;}f.className='save-status ok-text';f.textContent=`Uploaded ${done} image${done===1?'':'s'}.`;$('screensaverFiles').value='';await refreshStatus();await refreshScreensaverAssets();}catch(e){f.className='save-status error-text';f.textContent=`Upload failed: ${e.message}`;log(`Screensaver upload: ${e.message}`);}finally{b.disabled=false;}};

$('screensaverImages').onclick=async e=>{const b=e.target.closest('[data-delete-screensaver]');if(!b)return;const name=b.dataset.deleteScreensaver;if(!confirm(`Delete screensaver image "${name}"?`))return;try{await api(`screensaver/images/${encodeURIComponent(name)}`,{method:'DELETE'});log(`Deleted screensaver image: ${name}`);await refreshStatus();await refreshScreensaverAssets();}catch(err){log(`Delete image: ${err.message}`);}};
$('previewScreensaver').onclick=async()=>{try{await api('screensaver/preview',{method:'POST'});log('Screensaver preview started');setTimeout(refreshStatus,400);setTimeout(refreshShot,700);}catch(e){log(`Screensaver preview: ${e.message}`);}};
$('stopScreensaver').onclick=async()=>{try{await api('screensaver/stop',{method:'POST'});log('Returned from screensaver');setTimeout(refreshStatus,400);setTimeout(refreshShot,700);}catch(e){log(`Screensaver stop: ${e.message}`);}};

let volTimer,brightTimer;
$('volume').oninput=()=>{$('volumeLabel').textContent=`${$('volume').value}%`;clearTimeout(volTimer);volTimer=setTimeout(async()=>{try{await api('audio/volume',{method:'POST',body:{percent:+$('volume').value}})}catch(e){log(e.message)}},250);};
$('brightness').oninput=()=>{$('brightnessLabel').textContent=`${$('brightness').value}%`;clearTimeout(brightTimer);brightTimer=setTimeout(async()=>{try{await api('display/brightness',{method:'POST',body:{percent:+$('brightness').value}})}catch(e){log(e.message)}},250);};

$('screen').onclick=async(ev)=>{const rect=$('screen').getBoundingClientRect();if(!rect.width||!rect.height)return;const x=(ev.clientX-rect.left)/rect.width,y=(ev.clientY-rect.top)/rect.height;try{const r=await api('input/click',{method:'POST',body:{x,y}});showFocus(r.focus);log(`Remote click: ${Math.round(x*100)}%, ${Math.round(y*100)}%`);setTimeout(refreshShot,350);}catch(e){log(`Remote click: ${e.message}`);}};
$('sendText').onclick=async()=>{try{const r=await api('input/text',{method:'POST',body:{text:$('remoteText').value}});showFocus(r.after||r.before);log(`Sent remote text via ${r.method||'CDP'}`);setTimeout(refreshShot,350);}catch(e){log(`Remote text: ${e.message}`);}};
document.querySelectorAll('.keybtn').forEach(btn=>btn.onclick=async()=>{try{await api('input/key',{method:'POST',body:{key:btn.dataset.key}});setTimeout(refreshShot,350);}catch(e){log(`Remote key: ${e.message}`);}});

browserExperienceIds.forEach(id=>{const el=$(id);el.addEventListener('input',()=>{browserExperienceDirty=true;});el.addEventListener('change',()=>{browserExperienceDirty=true;});});
idleFormIds.forEach(id=>{const el=$(id);el.addEventListener('input',()=>{idleFormDirty=true;});el.addEventListener('change',()=>{idleFormDirty=true;});});
thresholdFormIds.forEach(id=>{const el=$(id);el.addEventListener('input',()=>{thresholdFormDirty=true;});el.addEventListener('change',()=>{thresholdFormDirty=true;});});
screensaverFormIds.forEach(id=>{const el=$(id);el.addEventListener('input',()=>{screensaverFormDirty=true;});el.addEventListener('change',()=>{screensaverFormDirty=true;});});
signageFormIds.forEach(id=>{const el=$(id);if(!el)return;el.addEventListener('input',()=>{signageFormDirty=true;});el.addEventListener('change',()=>{signageFormDirty=true;});});
immichFormIds.forEach(id=>{const el=$(id);if(!el)return;el.addEventListener('input',()=>{immichFormDirty=true;});el.addEventListener('change',()=>{immichFormDirty=true;});});
document.querySelectorAll('#signageDays input').forEach(el=>el.addEventListener('change',()=>{signageFormDirty=true;}));

mqttFormIds.forEach(id=>{
  const el=$(id);
  el.addEventListener('input',()=>{mqttFormDirty=true;});
  el.addEventListener('change',()=>{mqttFormDirty=true;});
});
haFormIds.forEach(id=>{
  const el=$(id);
  el.addEventListener('input',()=>{haFormDirty=true;});
  el.addEventListener('change',()=>{haFormDirty=true;});
});

$('saveMqtt').onclick=async()=>{
  const button=$('saveMqtt'), feedback=$('mqttSaveStatus');
  button.disabled=true; feedback.className='save-status pending'; feedback.textContent='Saving MQTT settings…';
  try{
    const body={enabled:$('mqttEnabled').checked,host:$('mqttHost').value.trim(),port:Number($('mqttPort').value),username:$('mqttUsername').value.trim(),base_topic:$('mqttBaseTopic').value.trim()};
    const password=$('mqttPassword').value;if(password)body.password=password;
    const result=await api('mqtt/config',{method:'POST',body});
    mqttFormDirty=false;$('mqttPassword').value='';
    feedback.className='save-status ok-text';
    feedback.textContent=result.connected?'Saved — MQTT connected.':'Saved — reconnecting to MQTT…';
    log('MQTT settings saved; reconnecting');
    await refreshStatus();setTimeout(refreshStatus,800);setTimeout(refreshStatus,2200);
  }catch(e){
    feedback.className='save-status error-text';feedback.textContent=`Save failed: ${e.message}`;log(`MQTT: ${e.message}`);
  }finally{button.disabled=false;}
};
$('saveHa').onclick=async()=>{
  const button=$('saveHa'), feedback=$('haSaveStatus');
  button.disabled=true;feedback.className='save-status pending';feedback.textContent='Saving Home Assistant settings…';
  try{
    const result=await api('plugins/homeassistant/config',{method:'POST',body:{enabled:$('haEnabled').checked,discovery_prefix:$('haDiscoveryPrefix').value.trim()}});
    haFormDirty=false;feedback.className='save-status ok-text';
    const count=result?.publish?.entities||result?.plugin?.entities||0;
    feedback.textContent=result?.publish?.ok===false?'Saved — waiting for MQTT.':`Saved${count?` — published ${count} entities.`:'.'}`;
    log('Home Assistant plugin settings saved');await refreshStatus();setTimeout(refreshStatus,800);
  }catch(e){feedback.className='save-status error-text';feedback.textContent=`Save failed: ${e.message}`;log(`Home Assistant: ${e.message}`);}
  finally{button.disabled=false;}
};
$('republishHa').onclick=async()=>{try{const r=await api('plugins/homeassistant/republish',{method:'POST'});log(`Home Assistant discovery republished (${r.entities||0} entities)`);setTimeout(refreshStatus,400);}catch(e){log(`Home Assistant discovery: ${e.message}`);}};

async function installOptionalPlugin(id){try{await api(`plugins/${id}/install`,{method:'POST'});log(`Installed plugin: ${id}`);await refreshStatus();}catch(e){log(`Install plugin ${id}: ${e.message}`);}}
async function removeOptionalPlugin(id){if(!confirm(`Remove ${id.replace('_',' ')} plugin? Its saved settings are retained for reinstall.`))return;try{await api(`plugins/${id}`,{method:'DELETE'});log(`Removed plugin: ${id}`);await refreshStatus();}catch(e){log(`Remove plugin ${id}: ${e.message}`);}}
$('installSignage').onclick=()=>installOptionalPlugin('digital_signage');
$('removeSignage').onclick=()=>removeOptionalPlugin('digital_signage');
$('installImmich').onclick=()=>installOptionalPlugin('immich');
$('removeImmich').onclick=()=>removeOptionalPlugin('immich');

$('saveSignage').onclick=async()=>{const b=$('saveSignage'),f=$('signageSaveStatus');b.disabled=true;f.className='save-status pending';f.textContent='Saving signage settings…';try{const days=[...document.querySelectorAll('#signageDays input:checked')].map(x=>Number(x.value));await api('plugins/digital_signage/config',{method:'POST',body:{enabled:$('signageEnabled').checked,after_seconds:Number($('signageAfter').value),interval_seconds:Number($('signageInterval').value),fit:$('signageFit').value,background:$('signageBackground').value,shuffle:$('signageShuffle').checked,keep_display_on:$('signageKeepDisplayOn').checked,schedule_enabled:$('signageScheduleEnabled').checked,schedule_start:$('signageScheduleStart').value,schedule_end:$('signageScheduleEnd').value,schedule_days:days}});signageFormDirty=false;f.className='save-status ok-text';f.textContent='Digital Signage settings saved.';await refreshStatus();}catch(e){f.className='save-status error-text';f.textContent=`Save failed: ${e.message}`;log(`Digital Signage: ${e.message}`);}finally{b.disabled=false;}};
$('uploadSignageImages').onclick=async()=>{const files=[...($('signageFiles').files||[])],f=$('signageUploadStatus'),b=$('uploadSignageImages');if(!files.length){f.className='save-status error-text';f.textContent='Choose one or more images first.';return;}b.disabled=true;try{let done=0;for(const file of files){if(file.size>15*1024*1024)throw new Error(`${file.name} is larger than 15 MiB`);f.className='save-status pending';f.textContent=`Uploading ${file.name} (${done+1}/${files.length})…`;const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result||'').split(',',2)[1]||'');r.onerror=()=>reject(r.error||new Error('File read failed'));r.readAsDataURL(file);});await api('plugins/digital_signage/assets',{method:'POST',body:{name:file.name,data_base64:data}});done++;}f.className='save-status ok-text';f.textContent=`Uploaded ${done} image${done===1?'':'s'}.`;$('signageFiles').value='';await refreshStatus();}catch(e){f.className='save-status error-text';f.textContent=`Upload failed: ${e.message}`;}finally{b.disabled=false;}};
$('signageImages').onclick=async e=>{const b=e.target.closest('[data-delete-signage]');if(!b)return;const name=b.dataset.deleteSignage;if(!confirm(`Delete signage image "${name}"?`))return;try{await api(`plugins/digital_signage/assets/${encodeURIComponent(name)}`,{method:'DELETE'});await refreshStatus();}catch(err){log(`Delete signage image: ${err.message}`);}};
$('previewSignage').onclick=async()=>{try{await api('plugins/digital_signage/preview',{method:'POST'});log('Digital Signage preview started');setTimeout(refreshStatus,400);setTimeout(refreshShot,700);}catch(e){log(`Digital Signage preview: ${e.message}`);}};
$('stopPluginScreensaver').onclick=async()=>{try{await api('screensaver/stop',{method:'POST'});log('Returned from plugin screensaver');setTimeout(refreshStatus,400);setTimeout(refreshShot,700);}catch(e){log(`Screensaver stop: ${e.message}`);}};

$('saveImmich').onclick=async()=>{const b=$('saveImmich'),f=$('immichSaveStatus');b.disabled=true;f.className='save-status pending';f.textContent='Saving Immich settings…';try{const body={enabled:$('immichEnabled').checked,server_url:$('immichServerUrl').value.trim(),album_id:$('immichAlbumId').value.trim(),after_seconds:Number($('immichAfter').value),interval_seconds:Number($('immichInterval').value),fit:$('immichFit').value,background:$('immichBackground').value,random_count:Number($('immichRandomCount').value),keep_display_on:$('immichKeepDisplayOn').checked};const key=$('immichApiKey').value;if(key)body.api_key=key;await api('plugins/immich/config',{method:'POST',body});immichFormDirty=false;$('immichApiKey').value='';f.className='save-status ok-text';f.textContent='Immich settings saved.';await refreshStatus();}catch(e){f.className='save-status error-text';f.textContent=`Save failed: ${e.message}`;log(`Immich: ${e.message}`);}finally{b.disabled=false;}};
$('testImmich').onclick=async()=>{const f=$('immichSaveStatus');f.className='save-status pending';f.textContent='Testing Immich…';try{const r=await api('plugins/immich/test',{method:'POST'});f.className='save-status ok-text';f.textContent=`Connected${r.server_version?` to Immich ${r.server_version}`:''}; ${r.asset_count||0} photos available • slideshow image access verified.`;await refreshStatus();}catch(e){f.className='save-status error-text';f.textContent=`Immich test failed: ${e.message}`;}};
$('previewImmich').onclick=async()=>{try{await api('plugins/immich/preview',{method:'POST'});log('Immich preview started');setTimeout(refreshStatus,400);setTimeout(refreshShot,700);}catch(e){log(`Immich preview: ${e.message}`);}};

$('saveThresholds').onclick=async()=>{const b=$('saveThresholds'),f=$('thresholdSaveStatus');b.disabled=true;f.className='save-status pending';f.textContent='Saving thresholds…';try{const r=await api('monitoring/config',{method:'POST',body:{cpu_percent:Number($('cpuThreshold').value),memory_percent:Number($('memoryThreshold').value),disk_percent:Number($('diskThreshold').value),temperature_c:Number($('temperatureThreshold').value)}});thresholdFormDirty=false;f.className='save-status ok-text';f.textContent='Dashboard thresholds saved.';log('Dashboard indicator thresholds saved');setTimeout(refreshStatus,300);}catch(e){f.className='save-status error-text';f.textContent=`Save failed: ${e.message}`;log(`Thresholds: ${e.message}`);}finally{b.disabled=false;}};

document.querySelectorAll('[data-view-target]').forEach(btn=>btn.onclick=()=>setView(btn.dataset.viewTarget));
document.querySelectorAll('[data-settings-target]').forEach(btn=>btn.onclick=()=>setSettingsPane(btn.dataset.settingsTarget));
setSettingsPane(localStorage.getItem('kioskctl_settings_pane')||'browser');
$('menuToggle').onclick=()=>{$('sidebar').classList.toggle('open');$('sidebarBackdrop').classList.toggle('open');};
$('sidebarBackdrop').onclick=()=>{$('sidebar').classList.remove('open');$('sidebarBackdrop').classList.remove('open');};
setView(localStorage.getItem('kioskctl_view')||'dashboard');

refreshStatus().then(()=>{if(token){refreshShot();refreshDiagnostics();refreshScreensaverAssets();}}); timer=setInterval(refreshStatus,10000); setInterval(()=>{if(token)refreshDiagnostics();},30000);
