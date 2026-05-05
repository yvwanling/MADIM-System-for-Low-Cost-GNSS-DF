const API_BASE = 'http://localhost:8000';

let hasAnalysis = false;
let latestAnalysis = null;
let mapConfig = null;
let amapReadyPromise = null;
let mapInstance = null;
let mapOverlays = [];
let playbackMarker = null;
let startMarker = null;
let endMarker = null;
let jumpMarkers = [];
let hotspotMarkers = [];
let agentTraceStore = [];
let hotspotStore = [];
let selectedHotspotId = null;



function showLanding() {
  document.getElementById('landingPage')?.classList.remove('hidden');
  document.getElementById('appPage')?.classList.add('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openWorkspace() {
  document.getElementById('landingPage')?.classList.add('hidden');
  document.getElementById('loginModal')?.classList.add('hidden');
  document.getElementById('appPage')?.classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  localStorage.setItem('madi_navagent_entered', 'true');
}

function openLoginModal() {
  document.getElementById('loginModal')?.classList.remove('hidden');
}

function closeLoginModal() {
  document.getElementById('loginModal')?.classList.add('hidden');
}

function bindLandingEvents() {
  document.getElementById('enterAppBtn')?.addEventListener('click', openWorkspace);
  document.getElementById('landingExploreBtn')?.addEventListener('click', openWorkspace);
  document.getElementById('loginOpenBtn')?.addEventListener('click', openLoginModal);
  document.getElementById('loginCloseBtn')?.addEventListener('click', closeLoginModal);
  document.getElementById('loginModal')?.addEventListener('click', (event) => {
    if (event.target?.id === 'loginModal') closeLoginModal();
  });
  document.getElementById('loginSubmitBtn')?.addEventListener('click', () => {
    const name = document.getElementById('loginName')?.value?.trim();
    if (name) localStorage.setItem('madi_navagent_user', name);
    openWorkspace();
  });
  document.getElementById('landingDemoBtn')?.addEventListener('click', () => {
    openWorkspace();
    setTimeout(() => {
      const demoButton = document.getElementById('demoBtn');
      if (demoButton) demoButton.click();
    }, 450);
  });
}

let playbackState = {
  points: [],
  index: 0,
  timer: null,
  playing: false,
  intervalMs: 450,
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function setStatus(text, ok = true) {
  const el = document.getElementById('statusBar');
  if (!el) return;
  el.textContent = text;
  el.style.background = ok ? '#eefcf5' : '#fee2e2';
  el.style.color = ok ? '#059669' : '#b91c1c';
}

function setMapStatus(text, ok = true) {
  const el = document.getElementById('mapStatus');
  if (!el) return;
  el.textContent = text;
  el.style.background = ok ? '#eef2ff' : '#fee2e2';
  el.style.color = ok ? '#4f46e5' : '#b91c1c';
}
function setMiniStatus(elementId, text, ok = true) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = text;
  el.style.background = ok ? '#eef2ff' : '#fee2e2';
  el.style.color = ok ? '#4f46e5' : '#b91c1c';
}


function setCollapsibleMeta(elementId, text) {
  const el = document.getElementById(elementId);
  if (el) el.textContent = text;
}

function applyCollapsibleState(section, collapsed) {
  const trigger = section.querySelector('.collapsible-trigger');
  const body = section.querySelector('.collapsible-body');
  if (!body) return;
  section.classList.toggle('collapsed', collapsed);
  body.hidden = collapsed;
  body.style.display = collapsed ? 'none' : '';
  if (trigger) trigger.setAttribute('aria-expanded', String(!collapsed));
}

function initCollapsibles() {
  document.querySelectorAll('[data-collapsible]').forEach(section => {
    const trigger = section.querySelector('.collapsible-trigger');
    const body = section.querySelector('.collapsible-body');
    if (!trigger || !body) return;

    // 初始状态由 HTML 中的 collapsed 类决定；这里再用 hidden + inline display 兜底，
    // 即使浏览器缓存了旧 style.css，也能真正折叠。
    applyCollapsibleState(section, section.classList.contains('collapsed'));

    if (trigger.dataset.bound === 'true') return;
    trigger.addEventListener('click', () => {
      const nextCollapsed = !section.classList.contains('collapsed');
      applyCollapsibleState(section, nextCollapsed);
    });

    trigger.dataset.bound = 'true';
  });
}

function createCard(title, value) {
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `<h3>${title}</h3><div class="value">${value}</div>`;
  return card;
}

function renderSummary(summary) {
  const container = document.getElementById('summaryCards');
  if (!container) return;
  container.innerHTML = '';
  container.appendChild(createCard('总历元数', summary.total_epochs));
  container.appendChild(createCard('固定成功率', `${(summary.fix_rate * 100).toFixed(2)}%`));
  container.appendChild(createCard('平均置信度', Number(summary.avg_confidence || 0).toFixed(2)));
  container.appendChild(createCard('主导策略', summary.dominant_strategy || 'N/A'));
  container.appendChild(createCard('重试轮数', summary.retry_rounds ?? 0));
  container.appendChild(createCard('平均位置误差', summary.mean_position_error_m == null ? 'N/A' : `${Number(summary.mean_position_error_m).toFixed(2)} m`));
}

function drawLineChart(canvasId, valuesA, valuesB, titleA, titleB) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const padding = 32;
  const plotWidth = canvas.width - padding * 2;
  const plotHeight = canvas.height - padding * 2;
  const allValues = [...valuesA, ...(valuesB || [])].filter(v => Number.isFinite(v));
  if (!allValues.length) {
    ctx.fillStyle = '#111827';
    ctx.font = '14px Arial';
    ctx.fillText('暂无可绘制数据', 20, 40);
    return;
  }
  const minV = Math.min(...allValues);
  const maxV = Math.max(...allValues);
  const range = Math.max(maxV - minV, 1e-6);
  ctx.strokeStyle = '#cbd5e1';
  ctx.strokeRect(padding, padding, plotWidth, plotHeight);

  function drawSeries(values, color) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    let started = false;
    values.forEach((value, index) => {
      if (!Number.isFinite(value)) return;
      const x = padding + (index / Math.max(values.length - 1, 1)) * plotWidth;
      const y = padding + plotHeight - ((value - minV) / range) * plotHeight;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
  }

  drawSeries(valuesA, '#4f46e5');
  if (valuesB) drawSeries(valuesB, '#059669');
  ctx.fillStyle = '#111827';
  ctx.font = '12px Arial';
  ctx.fillText(`max ${maxV.toFixed(2)}`, padding, 14);
  ctx.fillText(`min ${minV.toFixed(2)}`, padding, canvas.height - 8);
  ctx.fillStyle = '#4f46e5';
  ctx.fillRect(canvas.width - 200, 14, 12, 12);
  ctx.fillStyle = '#111827';
  ctx.fillText(titleA, canvas.width - 182, 24);
  if (valuesB) {
    ctx.fillStyle = '#059669';
    ctx.fillRect(canvas.width - 90, 14, 12, 12);
    ctx.fillStyle = '#111827';
    ctx.fillText(titleB, canvas.width - 72, 24);
  }
}

function renderRiskBars(distribution) {
  const box = document.getElementById('riskBars');
  if (!box) return;
  box.innerHTML = '';
  const total = Object.values(distribution || {}).reduce((a, b) => a + b, 0) || 1;
  Object.entries(distribution || {}).forEach(([name, count]) => {
    const row = document.createElement('div');
    row.className = 'bar-row';
    const pct = (count / total) * 100;
    row.innerHTML = `<div>${name}</div><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><div>${count}</div>`;
    box.appendChild(row);
  });
}

function renderFindings(findings) {
  const list = document.getElementById('findingsList');
  if (!list) return;
  list.innerHTML = '';
  (findings || []).forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    list.appendChild(li);
  });
}

function renderEpochTable(epochs) {
  const tbody = document.getElementById('epochTable');
  const total = Array.isArray(epochs) ? epochs.length : 0;
  setCollapsibleMeta('epochTableCollapseMeta', total ? `展示 ${Math.min(total, 150)} / ${total} 条` : '暂无数据');
  if (!tbody) return;
  tbody.innerHTML = '';
  (epochs || []).slice(0, 150).forEach(epoch => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${epoch.timestamp ?? 'N/A'}</td>
      <td>${epoch.heading_raw_deg?.toFixed?.(2) ?? 'N/A'}</td>
      <td>${epoch.heading_smoothed_deg?.toFixed?.(2) ?? 'N/A'}</td>
      <td>${Number(epoch.quality_score || 0).toFixed(2)}</td>
      <td>${Number(epoch.confidence || 0).toFixed(2)}</td>
      <td>${epoch.model_choice ?? 'N/A'}</td>
      <td>${epoch.strategy_profile ?? 'N/A'}</td>
      <td>#${epoch.candidate_index ?? 0}/${epoch.candidate_count ?? 0}</td>
      <td>${Number(epoch.separation_score || 0).toFixed(3)}</td>
      <td>${Number(epoch.dynamic_threshold_m || 0).toFixed(4)}</td>
      <td>${Number(epoch.baseline_error_m || 0).toFixed(4)}</td>
      <td>${epoch.integrity_risk ?? 'N/A'}</td>`;
    tbody.appendChild(tr);
  });
}

function renderToolSources(toolSources) {
  const container = document.getElementById('toolSourceList');
  const count = Object.keys(toolSources || {}).length;
  setCollapsibleMeta('toolSourceCollapseMeta', count ? `共 ${count} 个工具` : '暂无工具');
  if (!container) return;
  container.innerHTML = '';
  Object.entries(toolSources || {}).forEach(([tool, source]) => {
    const div = document.createElement('div');
    div.className = 'tool-item';
    div.innerHTML = `<strong>${tool}</strong><span>${source}</span>`;
    container.appendChild(div);
  });
}

function truncateText(value, maxLen = 220) {
  if (value == null) return '无';
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length <= maxLen ? text : `${text.slice(0, maxLen)} ...`;
}

function safeJson(value) {
  try { return JSON.stringify(value); } catch (err) { return String(value); }
}

function buildToolDetailsHtml(trace) {
  const toolCalls = trace.tool_calls || [];
  if (!toolCalls.length) return '<div class="trace-summary">本阶段没有额外工具调用。</div>';
  return toolCalls.map(item => `
    <div class="trace-tool">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;"><strong>${item.tool}</strong><span class="source-tag">${item.source}</span></div>
      <div class="trace-summary"><strong>参数：</strong>${truncateText(safeJson(item.arguments), 260)}</div>
      <div class="trace-summary"><strong>结果：</strong>${truncateText(item.result_summary, 420)}</div>
    </div>`).join('');
}

function toggleTraceDetails(index) {
  const trace = agentTraceStore[index];
  if (!trace) return;
  const details = document.getElementById(`traceDetails_${index}`);
  const button = document.getElementById(`traceToggle_${index}`);
  if (!details || !button) return;
  const expanded = details.dataset.expanded === 'true';
  if (expanded) {
    details.style.display = 'none';
    details.dataset.expanded = 'false';
    button.textContent = '查看流程详情';
    return;
  }
  if (!details.dataset.loaded) {
    details.innerHTML = buildToolDetailsHtml(trace);
    details.dataset.loaded = 'true';
  }
  details.style.display = 'block';
  details.dataset.expanded = 'true';
  button.textContent = '收起流程详情';
}

function expandAllTraceDetails() {
  agentTraceStore.forEach((_, index) => {
    const details = document.getElementById(`traceDetails_${index}`);
    const button = document.getElementById(`traceToggle_${index}`);
    if (!details || !button) return;
    if (!details.dataset.loaded) {
      details.innerHTML = buildToolDetailsHtml(agentTraceStore[index]);
      details.dataset.loaded = 'true';
    }
    details.style.display = 'block';
    details.dataset.expanded = 'true';
    button.textContent = '收起流程详情';
  });
}

function collapseAllTraceDetails() {
  agentTraceStore.forEach((_, index) => {
    const details = document.getElementById(`traceDetails_${index}`);
    const button = document.getElementById(`traceToggle_${index}`);
    if (!details || !button) return;
    details.style.display = 'none';
    details.dataset.expanded = 'false';
    button.textContent = '查看流程详情';
  });
}

function renderAgentTrace(traces) {
  const container = document.getElementById('agentTrace');
  if (!container) return;
  agentTraceStore = Array.isArray(traces) ? traces : [];
  setCollapsibleMeta('agentTraceCollapseMeta', agentTraceStore.length ? `共 ${agentTraceStore.length} 个 Agent 阶段` : '暂无轨迹');
  container.innerHTML = '';
  const toolbar = document.createElement('div');
  toolbar.style.display = 'flex';
  toolbar.style.justifyContent = 'flex-end';
  toolbar.style.gap = '8px';
  toolbar.style.marginBottom = '12px';
  toolbar.innerHTML = `
    <button id="expandAllTraceBtn" type="button" style="padding:8px 12px;border:none;border-radius:10px;background:#eef2ff;color:#4f46e5;cursor:pointer;">展开全部详情</button>
    <button id="collapseAllTraceBtn" type="button" style="padding:8px 12px;border:none;border-radius:10px;background:#f3f4f6;color:#111827;cursor:pointer;">收起全部详情</button>`;
  container.appendChild(toolbar);
  agentTraceStore.forEach((trace, index) => {
    const block = document.createElement('div');
    block.className = 'trace-block';
    block.innerHTML = `
      <div class="trace-head"><div><h3>${trace.agent}</h3><p>${trace.role}</p></div><div class="badge ${trace.used_llm ? 'badge-llm' : 'badge-rule'}">${trace.used_llm ? 'LLM 规划' : '规则执行'}</div></div>
      <div class="trace-objective"><strong>目标：</strong>${trace.objective || '无'}</div>
      <div class="trace-objective"><strong>决策：</strong>${trace.decision_summary || '无'}</div>
      <div class="trace-handoff"><strong>交接：</strong>${trace.handoff_to || '无'}</div>
      <div style="margin-top:12px;"><button id="traceToggle_${index}" type="button" style="padding:8px 12px;border:none;border-radius:10px;background:#eef2ff;color:#4f46e5;cursor:pointer;">查看流程详情</button></div>
      <div id="traceDetails_${index}" style="display:none;margin-top:12px;" data-loaded="" data-expanded="false"></div>`;
    container.appendChild(block);
  });
  document.getElementById('expandAllTraceBtn')?.addEventListener('click', expandAllTraceDetails);
  document.getElementById('collapseAllTraceBtn')?.addEventListener('click', collapseAllTraceDetails);
  agentTraceStore.forEach((_, index) => document.getElementById(`traceToggle_${index}`)?.addEventListener('click', () => toggleTraceDetails(index)));
}

function renderWorkflow(workflow) {
  const container = document.getElementById('workflowTimeline');
  if (!container) return;
  if (!workflow?.length) {
    container.textContent = '等待分析。';
    return;
  }
  container.innerHTML = workflow.map(step => `
    <div class="workflow-item">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;">
        <strong>${step.label}</strong>
        <span class="status-pill status-${step.status}">${step.status}</span>
      </div>
      <div class="workflow-meta">
        <span>${step.agent}</span>
        <span>执行 ${step.runs || 0} 次</span>
      </div>
      ${step.note ? `<div class="trace-summary">${step.note}</div>` : ''}
    </div>`).join('');
}

function renderProtocolLog(logs) {
  const container = document.getElementById('protocolLog');
  if (!container) return;
  if (!logs?.length) {
    container.textContent = '本次分析未触发关键协议。';
    return;
  }
  container.innerHTML = logs.map(item => `
    <div class="protocol-item">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;">
        <strong>${item.protocol}</strong>
        <span class="status-pill status-${item.status}">${item.status}</span>
      </div>
      <div class="protocol-meta">
        <span>${item.sender} → ${item.receiver}</span>
        <span>${item.phase}</span>
      </div>
      <div class="trace-summary">request_id=${item.request_id}${item.reason ? ` ｜ ${item.reason}` : ''}</div>
    </div>`).join('');
}

async function loadDatasets(preferredName = null) {
  try {
    const datasets = await fetchJson(`${API_BASE}/api/navigation/datasets`);
    const select = document.getElementById('datasetName');
    if (!select) return;
    const previous = preferredName || select.value;
    select.innerHTML = '';
    datasets.forEach(ds => {
      const opt = document.createElement('option');
      opt.value = ds.name;
      opt.textContent = `${ds.name} - ${ds.description}`;
      select.appendChild(opt);
    });
    if (previous && datasets.some(ds => ds.name === previous)) {
      select.value = previous;
    }
    setStatus('后端已连接');
  } catch (err) {
    setStatus(`后端连接失败：${err.message}`, false);
  }
}

async function loadMapConfig() {
  try {
    mapConfig = await fetchJson(`${API_BASE}/api/navigation/map-config`);
    if (!mapConfig.enabled) {
      setMapStatus(mapConfig.note || '未配置高德地图');
      const mapContainer = document.getElementById('mapContainer');
      if (mapContainer) mapContainer.textContent = mapConfig.note || '未配置高德地图 JS API Key。';
    }
  } catch (err) {
    setMapStatus(`地图配置失败：${err.message}`, false);
  }
}

function buildPayload() {
  return {
    baseline_length_m: parseFloat(document.getElementById('baselineLength').value),
    candidate_count: parseInt(document.getElementById('candidateCount').value, 10),
    use_llm: document.getElementById('useLlm').checked,
    enable_amap_geocode: document.getElementById('enableAmap').checked,
  };
}

function clearPlaybackTimer() {
  if (playbackState.timer) clearInterval(playbackState.timer);
  playbackState.timer = null;
  playbackState.playing = false;
  const btn = document.getElementById('playbackToggle');
  if (btn) btn.textContent = '开始回放';
}

function updateTrajectoryStats(trajectory) {
  const el = document.getElementById('trajectoryStats');
  if (!el) return;
  if (!trajectory || !trajectory.points?.length) {
    el.textContent = '暂无轨迹数据。';
    return;
  }
  const stats = trajectory.stats || {};
  const strategyHtml = Object.entries(stats.strategy_distribution || {}).map(([k, v]) => `<div><strong>${k}</strong>：${v}</div>`).join('');
  el.innerHTML = `
    <div><strong>轨迹点数：</strong>${stats.point_count ?? trajectory.points.length}</div>
    <div><strong>分段数：</strong>${stats.segment_count ?? 0}</div>
    <div><strong>轨迹长度：</strong>${Number(stats.track_length_m || 0).toFixed(1)} m</div>
    <div><strong>热点数：</strong>${stats.hotspot_count ?? 0}</div>
    <div><strong>高风险点：</strong>${stats.high_risk_points ?? 0}</div>
    <div><strong>跳变点：</strong>${stats.jump_points ?? 0}</div>
    <div style="margin-top:8px"><strong>策略分布</strong></div>
    ${strategyHtml || '<div>暂无</div>'}`;
}

function renderCollectionAdvice(trajectory) {
  const el = document.getElementById('collectionAdvice');
  if (!el) return;
  const advice = trajectory?.collection_advice || [];
  if (!advice.length) {
    el.textContent = '暂无建议。';
    return;
  }
  el.innerHTML = advice.map(item => `<div>• ${item}</div>`).join('');
}

function updatePlaybackInfo(point, index, total) {
  const el = document.getElementById('playbackCurrentInfo');
  if (!el) return;
  if (!point) {
    el.textContent = '暂无轨迹数据。';
    return;
  }
  el.innerHTML = `
    <div><strong>进度：</strong>${index + 1} / ${total}</div>
    <div><strong>时间：</strong>${point.timestamp}</div>
    <div><strong>位置：</strong>${point.latitude.toFixed(6)}, ${point.longitude.toFixed(6)}</div>
    <div><strong>平滑航向：</strong>${point.heading_smoothed_deg == null ? 'N/A' : point.heading_smoothed_deg.toFixed(2) + '°'}</div>
    <div><strong>速度：</strong>${point.speed_knots == null ? 'N/A' : point.speed_knots.toFixed(2) + ' kn'}</div>
    <div><strong>置信度：</strong>${Number(point.confidence || 0).toFixed(2)}</div>
    <div><strong>风险：</strong>${point.risk}</div>
    <div><strong>策略：</strong>${point.strategy_profile}</div>
    <div><strong>模式：</strong>${point.model_choice}</div>
    <div><strong>阈值/误差：</strong>${Number(point.dynamic_threshold_m || 0).toFixed(4)} / ${Number(point.baseline_error_m || 0).toFixed(4)} m</div>
    <div><strong>跳变：</strong>${point.jump_detected ? '是' : '否'}</div>`;
}

function updatePlaybackFrame(index) {
  if (!playbackState.points.length) return;
  playbackState.index = Math.max(0, Math.min(index, playbackState.points.length - 1));
  const point = playbackState.points[playbackState.index];
  document.getElementById('playbackSlider').value = String(playbackState.index);
  updatePlaybackInfo(point, playbackState.index, playbackState.points.length);
  if (playbackMarker && window.AMap) {
    playbackMarker.setPosition([point.longitude, point.latitude]);
    if (point.heading_smoothed_deg != null) playbackMarker.setAngle(point.heading_smoothed_deg);
    mapInstance?.setCenter([point.longitude, point.latitude]);
  }
}

function startPlayback() {
  if (!playbackState.points.length) return;
  clearPlaybackTimer();
  playbackState.playing = true;
  const btn = document.getElementById('playbackToggle');
  if (btn) btn.textContent = '暂停回放';
  playbackState.timer = window.setInterval(() => {
    if (playbackState.index >= playbackState.points.length - 1) {
      clearPlaybackTimer();
      return;
    }
    updatePlaybackFrame(playbackState.index + 1);
  }, playbackState.intervalMs);
}

async function ensureAMapLoaded() {
  if (!mapConfig || !mapConfig.enabled) throw new Error(mapConfig?.note || '未配置高德地图。');
  if (window.AMap) return window.AMap;
  if (amapReadyPromise) return amapReadyPromise;
  amapReadyPromise = new Promise((resolve, reject) => {
    if (mapConfig.security_js_code) window._AMapSecurityConfig = { securityJsCode: mapConfig.security_js_code };
    const script = document.createElement('script');
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(mapConfig.key)}&plugin=AMap.Scale,AMap.ToolBar`;
    script.async = true;
    script.onload = () => resolve(window.AMap);
    script.onerror = () => reject(new Error('高德地图脚本加载失败，请检查 JS Key 或安全码。'));
    document.head.appendChild(script);
  });
  return amapReadyPromise;
}

function clearMapOverlays() {
  clearPlaybackTimer();
  if (mapInstance && mapOverlays.length) mapInstance.remove(mapOverlays);
  mapOverlays = [];
  jumpMarkers = [];
  hotspotMarkers = [];
  playbackMarker = null;
  startMarker = null;
  endMarker = null;
}

function renderHotspotDetail(hotspot) {
  const el = document.getElementById('hotspotDetail');
  if (!el) return;
  if (!hotspot) {
    selectedHotspotId = null;
    el.textContent = '点击地图中的热点标记或列表项，查看局部解释。';
    return;
  }
  selectedHotspotId = hotspot.id;
  el.innerHTML = `
    <div><strong>${hotspot.title}</strong></div>
    <div><strong>时间窗：</strong>${hotspot.start_timestamp} ~ ${hotspot.end_timestamp}</div>
    <div><strong>风险等级：</strong>${hotspot.risk}</div>
    <div><strong>平均置信度：</strong>${Number(hotspot.avg_confidence || 0).toFixed(2)}</div>
    <div><strong>平均质量分数：</strong>${Number(hotspot.avg_quality_score || 0).toFixed(2)}</div>
    <div><strong>平均卫星数：</strong>${Number(hotspot.avg_satellite_count || 0).toFixed(2)}</div>
    <div><strong>跳变次数：</strong>${hotspot.jump_count || 0}</div>
    <div><strong>区段长度：</strong>${Number(hotspot.length_m || 0).toFixed(1)} m</div>
    <div><strong>主导策略：</strong>${hotspot.dominant_strategy || 'N/A'}</div>
    <div><strong>原因：</strong>${(hotspot.reasons || []).join('、')}</div>
    <div><strong>解释：</strong>${hotspot.explanation || 'N/A'}</div>
    <div><strong>建议：</strong>${hotspot.recommendation || 'N/A'}</div>
    <button id="diagnoseHotspotBtn" class="inline-action-btn" type="button">深挖诊断该热点</button>
    <div id="hotspotDiagnosisResult" class="diagnosis-box muted">点击按钮后生成局部诊断证据链。</div>`;
  document.getElementById('diagnoseHotspotBtn')?.addEventListener('click', diagnoseSelectedHotspot);
}

function highlightHotspot(hotspotId) {
  document.querySelectorAll('.hotspot-item').forEach(node => {
    node.classList.toggle('active', node.dataset.hotspotId === hotspotId);
  });
  const hotspot = hotspotStore.find(item => item.id === hotspotId);
  renderHotspotDetail(hotspot || null);
  if (hotspot && mapInstance) mapInstance.setCenter([hotspot.center.longitude, hotspot.center.latitude]);
}

function renderHotspotList(trajectory) {
  const el = document.getElementById('hotspotList');
  hotspotStore = trajectory?.hotspots || [];
  setCollapsibleMeta('hotspotCollapseMeta', hotspotStore.length ? `共 ${hotspotStore.length} 个热点` : '暂无明显热点');
  if (!el) return;
  if (!hotspotStore.length) {
    el.textContent = '暂无明显风险热点。';
    renderHotspotDetail(null);
    return;
  }
  el.innerHTML = hotspotStore.map(item => `
    <div class="hotspot-item" data-hotspot-id="${item.id}">
      <h4>${item.title}</h4>
      <p>${item.start_timestamp} ~ ${item.end_timestamp}</p>
      <p>平均置信度 ${Number(item.avg_confidence || 0).toFixed(2)} ｜ 跳变 ${item.jump_count || 0} 次</p>
      <p>${(item.reasons || []).join('、')}</p>
    </div>`).join('');
  document.querySelectorAll('.hotspot-item').forEach(node => node.addEventListener('click', () => highlightHotspot(node.dataset.hotspotId)));
  highlightHotspot(hotspotStore[0].id);
}

async function renderTrajectoryMap(data) {
  const trajectory = data.optional_context?.trajectory;
  if (!trajectory || !trajectory.points?.length) {
    setMapStatus('暂无轨迹数据', false);
    document.getElementById('mapContainer').textContent = '当前分析没有可展示的轨迹点。';
    updateTrajectoryStats(null);
    updatePlaybackInfo(null, 0, 0);
    renderHotspotList(null);
    renderCollectionAdvice(null);
    return;
  }
  updateTrajectoryStats(trajectory);
  renderHotspotList(trajectory);
  renderCollectionAdvice(trajectory);
  playbackState.points = trajectory.points;
  playbackState.index = 0;
  playbackState.intervalMs = trajectory.playback?.default_interval_ms || 450;
  document.getElementById('playbackSlider').max = String(Math.max(playbackState.points.length - 1, 0));
  document.getElementById('playbackSlider').value = '0';
  const hint = document.getElementById('playbackHint');
  if (hint) hint.textContent = `共加载 ${trajectory.points.length} 个轨迹点，可按时间回放。`;

  if (!mapConfig || !mapConfig.enabled) {
    setMapStatus(mapConfig?.note || '地图未配置', false);
    document.getElementById('mapContainer').textContent = '已生成轨迹数据，但未配置高德 JS API，无法渲染地图。';
    updatePlaybackInfo(trajectory.points[0], 0, trajectory.points.length);
    return;
  }

  try {
    const AMap = await ensureAMapLoaded();
    document.getElementById('mapContainer').textContent = '';
    if (!mapInstance) {
      mapInstance = new AMap.Map('mapContainer', {
        resizeEnable: true,
        zoom: 13,
        center: [trajectory.center.longitude, trajectory.center.latitude],
        viewMode: '2D',
      });
      mapInstance.addControl(new AMap.Scale());
      mapInstance.addControl(new AMap.ToolBar());
    }
    clearMapOverlays();

    trajectory.segments.forEach(seg => {
      const polyline = new AMap.Polyline({
        path: seg.path,
        strokeColor: seg.color,
        strokeWeight: seg.jump_detected ? 8 : 6,
        strokeOpacity: 0.95,
        lineJoin: 'round',
        lineCap: 'round',
        showDir: false,
      });
      polyline.on('mouseover', () => setMapStatus(`风险 ${seg.risk} | 置信度 ${Number(seg.mean_confidence || 0).toFixed(2)} | 策略 ${seg.strategy_profile}`));
      mapOverlays.push(polyline);
    });

    startMarker = new AMap.Marker({
      position: [trajectory.start_point.longitude, trajectory.start_point.latitude],
      title: '起点',
      label: { content: '<div style="padding:2px 6px;background:#10b981;color:#fff;border-radius:999px;">起点</div>', direction: 'top' },
    });
    endMarker = new AMap.Marker({
      position: [trajectory.end_point.longitude, trajectory.end_point.latitude],
      title: '终点',
      label: { content: '<div style="padding:2px 6px;background:#ef4444;color:#fff;border-radius:999px;">终点</div>', direction: 'top' },
    });
    playbackMarker = new AMap.Marker({
      position: [trajectory.start_point.longitude, trajectory.start_point.latitude],
      title: '当前回放点',
      content: '<div class="playback-marker"></div>',
      offset: new AMap.Pixel(-9, -9),
    });
    mapOverlays.push(startMarker, endMarker, playbackMarker);

    trajectory.points.filter(point => point.jump_detected).forEach(point => {
      const marker = new AMap.CircleMarker({
        center: [point.longitude, point.latitude],
        radius: 5,
        strokeColor: '#8b5cf6',
        strokeWeight: 2,
        fillColor: '#8b5cf6',
        fillOpacity: 0.45,
      });
      jumpMarkers.push(marker);
      mapOverlays.push(marker);
    });

    hotspotStore.forEach(hotspot => {
      const marker = new AMap.CircleMarker({
        center: [hotspot.center.longitude, hotspot.center.latitude],
        radius: 8 + Math.round((hotspot.severity_score || 0.5) * 6),
        strokeColor: '#0ea5e9',
        strokeWeight: 2,
        fillColor: hotspot.risk === 'high' ? '#ef4444' : '#f59e0b',
        fillOpacity: 0.32,
      });
      marker.on('click', () => highlightHotspot(hotspot.id));
      hotspotMarkers.push(marker);
      mapOverlays.push(marker);
    });

    mapInstance.add(mapOverlays);
    mapInstance.setFitView(mapOverlays, false, [60, 60, 60, 60]);
    updatePlaybackFrame(0);
    setMapStatus('轨迹地图已加载');
  } catch (err) {
    setMapStatus(err.message, false);
    document.getElementById('mapContainer').textContent = err.message;
  }
}

function renderScenarioPlan(planResponse) {
  const box = document.getElementById('scenarioPlanResult');
  if (!box) return;
  const plan = planResponse?.plan;
  if (!plan) {
    box.textContent = '暂无策略规划结果。';
    return;
  }
  const skillText = (plan.selected_skills || []).join('、') || '无';
  const tagsText = (plan.scene_tags || []).join('、') || '无';
  const hotspotText = (plan.hotspot_references || []).join('；') || '暂无';
  const adviceHtml = (plan.collection_advice || []).map(item => `<div>• ${item}</div>`).join('');
  box.innerHTML = `
    <div><strong>建议策略模式：</strong>${plan.recommended_mode}</div>
    <div><strong>候选解数量：</strong>${plan.candidate_count}</div>
    <div><strong>搜索半径：</strong>${Number(plan.search_radius_deg || 0).toFixed(1)}°</div>
    <div><strong>temporal hold：</strong>${Number(plan.temporal_hold_strength || 0).toFixed(2)}</div>
    <div><strong>重试阈值：</strong>fix ≥ ${Number(plan.retry_thresholds?.min_fix_rate || 0).toFixed(2)}，高风险比例 ≤ ${Number(plan.retry_thresholds?.max_high_risk_ratio || 0).toFixed(2)}</div>
    <div><strong>恢复模式：</strong>${plan.enable_recovery_mode ? '启用' : '关闭'}</div>
    <div><strong>技能包：</strong>${skillText}</div>
    <div><strong>场景标签：</strong>${tagsText}</div>
    <div><strong>历史热点参考：</strong>${hotspotText}</div>
    <div style="margin-top:8px"><strong>规划解释：</strong>${plan.rationale}</div>
    <div style="margin-top:8px"><strong>采集建议：</strong>${adviceHtml || '暂无'}</div>`;
}


function currentDatasetName() {
  return document.getElementById('datasetName')?.value || latestAnalysis?.dataset?.name || 'google_mtv_local1';
}

function renderStrategyComparison(data) {
  const box = document.getElementById('strategyCompareResult');
  if (!box) return;
  const items = data?.items || [];
  if (!items.length) {
    box.textContent = '暂无策略对比结果。';
    return;
  }
  const rows = items.map(item => `
    <tr class="${item.strategy_name === data.best_strategy ? 'best-row' : ''}">
      <td><strong>${item.display_name}</strong><div class="muted small-text">${item.strategy_name}</div></td>
      <td>${Number(item.score || 0).toFixed(2)}</td>
      <td>${(Number(item.summary.fix_rate || 0) * 100).toFixed(2)}%</td>
      <td>${Number(item.summary.avg_confidence || 0).toFixed(3)}</td>
      <td>${item.summary.risk_distribution?.high || 0}</td>
      <td>${item.summary.retry_rounds ?? 0}</td>
      <td>${item.summary.dominant_strategy || 'N/A'}</td>
      <td>${(item.strengths || []).join('、') || '—'}${item.cautions?.length ? `<br/><span class="warn-text">注意：${item.cautions.join('、')}</span>` : ''}</td>
    </tr>`).join('');
  box.innerHTML = `
    <div class="recommendation-box"><strong>推荐结论：</strong>${data.recommendation || '暂无'}</div>
    <div class="table-wrap compact-table"><table>
      <thead><tr><th>策略</th><th>综合分</th><th>固定率</th><th>置信度</th><th>高风险点</th><th>重试</th><th>主导策略</th><th>优势/风险</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

async function compareStrategies() {
  const datasetName = currentDatasetName();
  try {
    setMiniStatus('strategyCompareStatus', '对比运行中...');
    const payload = { dataset_name: datasetName, ...buildPayload() };
    const data = await fetchJson(`${API_BASE}/api/navigation/compare-strategies`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    renderStrategyComparison(data);
    setMiniStatus('strategyCompareStatus', '对比完成');
    setStatus('多策略对比已完成');
  } catch (err) {
    setMiniStatus('strategyCompareStatus', '对比失败', false);
    setStatus(`策略对比失败：${err.message}`, false);
  }
}

function renderHotspotDiagnosis(data) {
  const box = document.getElementById('hotspotDiagnosisResult');
  if (!box) return;
  const evidence = data.evidence || {};
  const recommendations = (data.recommendations || []).map(item => `<div>• ${item}</div>`).join('');
  const strategy = data.suggested_strategy || {};
  box.classList.remove('muted');
  box.innerHTML = `
    <div><strong>诊断：</strong>${data.diagnosis}</div>
    <div class="diagnosis-grid">
      <div><strong>窗口点数：</strong>${evidence.point_count ?? 'N/A'}</div>
      <div><strong>平均置信度：</strong>${Number(evidence.avg_confidence || 0).toFixed(3)}</div>
      <div><strong>平均质量：</strong>${Number(evidence.avg_quality_score || 0).toFixed(3)}</div>
      <div><strong>平均卫星数：</strong>${Number(evidence.avg_satellite_count || 0).toFixed(2)}</div>
      <div><strong>平均分离度：</strong>${Number(evidence.avg_separation_score || 0).toFixed(3)}</div>
      <div><strong>跳变次数：</strong>${evidence.jump_count ?? 0}</div>
    </div>
    <div style="margin-top:8px"><strong>处理建议：</strong>${recommendations || '暂无'}</div>
    <div style="margin-top:8px"><strong>建议策略：</strong>${strategy.mode || 'N/A'}｜候选 ${strategy.candidate_count ?? 'N/A'}｜半径 ${strategy.search_radius_deg ?? 'N/A'}｜hold ${strategy.temporal_hold_strength ?? 'N/A'}｜恢复模式 ${strategy.enable_recovery_mode ? '启用' : '关闭'}</div>`;
}

async function diagnoseSelectedHotspot() {
  if (!hasAnalysis) return alert('请先完成一次分析。');
  if (!selectedHotspotId) return alert('请先选择一个风险热点。');
  const box = document.getElementById('hotspotDiagnosisResult');
  if (box) box.textContent = '异常窗口深挖诊断 Agent 正在分析...';
  try {
    const data = await fetchJson(`${API_BASE}/api/navigation/diagnose-hotspot`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hotspot_id: selectedHotspotId, use_llm: document.getElementById('useLlm').checked }),
    });
    renderHotspotDiagnosis(data);
    setStatus('热点深挖诊断完成');
  } catch (err) {
    if (box) box.textContent = `诊断失败：${err.message}`;
    setStatus(`热点诊断失败：${err.message}`, false);
  }
}

function renderSampleEvaluation(data) {
  const box = document.getElementById('sampleEvaluationResult');
  if (!box) return;
  const items = data?.items || [];
  const rows = items.map(item => `
    <tr>
      <td><strong>${item.dataset.name}</strong><div class="muted small-text">${item.dataset.description}</div></td>
      <td>${item.summary.total_epochs}</td>
      <td>${(Number(item.summary.fix_rate || 0) * 100).toFixed(2)}%</td>
      <td>${Number(item.summary.avg_confidence || 0).toFixed(3)}</td>
      <td>${item.hotspot_count}</td>
      <td>${item.recommended_strategy}<div class="muted small-text">${item.recommended_scene_goal}</div></td>
    </tr>`).join('');
  const ag = data.aggregate || {};
  box.innerHTML = `
    <div class="recommendation-box"><strong>评测摘要：</strong>共 ${ag.dataset_count || 0} 个数据集，平均固定率 ${(Number(ag.avg_fix_rate || 0) * 100).toFixed(2)}%，平均置信度 ${Number(ag.avg_confidence || 0).toFixed(3)}，总热点 ${ag.total_hotspots || 0} 个。</div>
    <div class="table-wrap compact-table"><table><thead><tr><th>数据集</th><th>历元</th><th>固定率</th><th>置信度</th><th>热点</th><th>推荐策略</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function evaluateSamples() {
  try {
    setMiniStatus('sampleEvalStatus', '评测运行中...');
    const payload = { dataset_name: currentDatasetName(), ...buildPayload() };
    const data = await fetchJson(`${API_BASE}/api/navigation/evaluate-samples`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    renderSampleEvaluation(data);
    setMiniStatus('sampleEvalStatus', '评测完成');
    setStatus('数据集评测完成');
  } catch (err) {
    setMiniStatus('sampleEvalStatus', '评测失败', false);
    setStatus(`数据集评测失败：${err.message}`, false);
  }
}

async function exportReport() {
  if (!hasAnalysis) return alert('请先完成一次分析。');
  try {
    setMiniStatus('reportStatus', '报告生成中...');
    const data = await fetchJson(`${API_BASE}/api/navigation/export-report`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format: 'html' }),
    });
    const blob = new Blob([data.content], { type: data.mime_type || 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const box = document.getElementById('reportExportResult');
    if (box) {
      box.innerHTML = `<div class="recommendation-box"><strong>报告已生成：</strong>${data.filename}｜热点 ${data.summary?.hotspot_count ?? 0} 个｜Agent ${data.summary?.agent_count ?? 0} 个</div><a class="download-link" href="${url}" download="${data.filename}">下载 HTML 报告</a>`;
    }
    setMiniStatus('reportStatus', '报告完成');
    setStatus('报告已生成');
  } catch (err) {
    setMiniStatus('reportStatus', '导出失败', false);
    setStatus(`报告导出失败：${err.message}`, false);
  }
}

async function runDemoMode() {
  const dataset = document.getElementById('datasetName');
  if (dataset) dataset.value = 'google_mtv_local1';
  document.getElementById('baselineLength').value = '1.20';
  document.getElementById('candidateCount').value = '5';
  document.getElementById('sceneGoal').value = '城市峡谷环境优先连续性，尽量降低跳变，并给出下一次采集建议';
  await analyzeSample();
  await planScenario();
  setStatus('标准分析流程已完成：数据分析 + 场景策略规划');
}

function renderAnalysis(data) {
  hasAnalysis = true;
  latestAnalysis = data;
  document.getElementById('datasetTitle').textContent = data.dataset.name;
  document.getElementById('datasetDesc').textContent = data.dataset.description;
  document.getElementById('globalExplanation').textContent = data.explanation;
  renderSummary(data.summary);
  renderRiskBars(data.summary.risk_distribution);
  renderFindings(data.summary.key_findings);
  renderEpochTable(data.epochs);
  renderAgentTrace(data.agent_trace);
  renderToolSources(data.tool_sources);
  renderWorkflow(data.workflow || []);
  renderProtocolLog(data.protocol_log || []);
  const heading = (data.epochs || []).slice(0, 300).map(e => e.heading_smoothed_deg);
  const headingRaw = (data.epochs || []).slice(0, 300).map(e => e.heading_raw_deg);
  const confidence = (data.epochs || []).slice(0, 300).map(e => e.confidence);
  const threshold = (data.epochs || []).slice(0, 300).map(e => e.dynamic_threshold_m);
  const errors = (data.epochs || []).slice(0, 300).map(e => e.baseline_error_m);
  drawLineChart('headingChart', headingRaw, heading, 'raw', 'smoothed');
  drawLineChart('confidenceChart', confidence, null, 'confidence');
  drawLineChart('thresholdChart', threshold, errors, 'threshold', 'baseline error');
  renderTrajectoryMap(data);
  document.getElementById('followupAnswer').textContent = '可以就这次分析继续提问。';
  document.getElementById('scenarioPlanResult').textContent = '可以基于当前分析结果生成场景策略规划。';
}

async function analyzeSample() {
  try {
    setStatus('正在分析数据集...');
    const payload = { dataset_name: document.getElementById('datasetName').value, ...buildPayload() };
    const data = await fetchJson(`${API_BASE}/api/navigation/analyze-sample`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    renderAnalysis(data);
    setStatus('数据集分析完成');
  } catch (err) {
    setStatus(`分析失败：${err.message}`, false);
    setMapStatus('轨迹未加载', false);
  }
}

async function uploadAndAnalyze() {
  const fileInput = document.getElementById('uploadFile');
  if (!fileInput.files.length) return alert('请先选择 NMEA 文件');
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  const refInput = document.getElementById('referenceFile');
  if (refInput.files.length) formData.append('reference_file', refInput.files[0]);
  const payload = buildPayload();
  Object.entries(payload).forEach(([key, value]) => formData.append(key, String(value)));
  try {
    setStatus('正在上传并分析文件...');
    const data = await fetchJson(`${API_BASE}/api/navigation/upload-nmea`, { method: 'POST', body: formData });
    renderAnalysis(data);
    await loadDatasets(data.dataset?.name);
    setStatus(`文件分析完成，已保存到数据集库：${data.dataset?.name || 'uploaded dataset'}。现在可以直接进行数据集评测和多策略对比。`);
  } catch (err) {
    setStatus(`上传分析失败：${err.message}`, false);
    setMapStatus('轨迹未加载', false);
  }
}

async function askFollowup() {
  if (!hasAnalysis) return alert('请先完成一次分析。');
  const question = document.getElementById('followupQuestion').value.trim();
  if (!question) return alert('请输入问题。');
  try {
    setStatus('解释 Agent 正在回答...');
    const data = await fetchJson(`${API_BASE}/api/navigation/followup`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, use_llm: true }),
    });
    document.getElementById('followupAnswer').textContent = data.answer;
    setStatus('解释 Agent 已完成回答');
  } catch (err) {
    setStatus(`追问失败：${err.message}`, false);
  }
}

async function planScenario() {
  const goal = document.getElementById('sceneGoal').value.trim();
  if (!goal) return alert('请输入场景目标。');
  try {
    setStatus('场景策略规划中...');
    const data = await fetchJson(`${API_BASE}/api/navigation/plan-scenario`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, use_llm: true }),
    });
    renderScenarioPlan(data);
    setStatus('场景策略规划完成');
  } catch (err) {
    setStatus(`策略规划失败：${err.message}`, false);
  }
}

function togglePlayback() {
  if (!playbackState.points.length) return;
  if (playbackState.playing) {
    clearPlaybackTimer();
    return;
  }
  startPlayback();
}

function bindEvents() {
  bindLandingEvents();
  initCollapsibles();
  document.getElementById('analyzeBtn')?.addEventListener('click', analyzeSample);
  document.getElementById('uploadBtn')?.addEventListener('click', uploadAndAnalyze);
  document.getElementById('followupBtn')?.addEventListener('click', askFollowup);
  document.getElementById('scenePlanBtn')?.addEventListener('click', planScenario);
  document.getElementById('playbackToggle')?.addEventListener('click', togglePlayback);
  document.getElementById('demoBtn')?.addEventListener('click', runDemoMode);
  document.getElementById('compareBtn')?.addEventListener('click', compareStrategies);
  document.getElementById('sampleEvalBtn')?.addEventListener('click', evaluateSamples);
  document.getElementById('exportReportBtn')?.addEventListener('click', exportReport);
  document.getElementById('playbackSpeed')?.addEventListener('change', (event) => {
    const speed = Number(event.target.value || 1);
    playbackState.intervalMs = Math.max(80, Math.round(450 / speed));
    if (playbackState.playing) startPlayback();
  });
  document.getElementById('playbackSlider')?.addEventListener('input', (event) => {
    clearPlaybackTimer();
    updatePlaybackFrame(Number(event.target.value || 0));
  });
}

window.addEventListener('load', async () => {
  bindEvents();
  await Promise.all([loadDatasets(), loadMapConfig()]);
});
