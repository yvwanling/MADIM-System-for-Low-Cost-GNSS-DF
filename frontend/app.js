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
let agentTraceStore = [];

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
  container.appendChild(
    createCard(
      '平均位置误差',
      summary.mean_position_error_m == null ? 'N/A' : `${Number(summary.mean_position_error_m).toFixed(2)} m`
    )
  );
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
    row.innerHTML = `
      <div>${name}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div>${count}</div>
    `;
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
      <td>${epoch.integrity_risk ?? 'N/A'}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderToolSources(toolSources) {
  const container = document.getElementById('toolSourceList');
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
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen)} ...`;
}

function safeJson(value) {
  try {
    return JSON.stringify(value);
  } catch (err) {
    return String(value);
  }
}

function buildToolDetailsHtml(trace) {
  const toolCalls = trace.tool_calls || [];
  if (!toolCalls.length) {
    return '<div class="trace-summary">本阶段没有额外工具调用。</div>';
  }

  return toolCalls.map(item => `
    <div class="trace-tool">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <strong>${item.tool}</strong>
        <span class="source-tag">${item.source}</span>
      </div>
      <div class="trace-summary"><strong>参数：</strong>${truncateText(safeJson(item.arguments), 260)}</div>
      <div class="trace-summary"><strong>结果：</strong>${truncateText(item.result_summary, 420)}</div>
    </div>
  `).join('');
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
  container.innerHTML = '';

  const toolbar = document.createElement('div');
  toolbar.style.display = 'flex';
  toolbar.style.justifyContent = 'flex-end';
  toolbar.style.gap = '8px';
  toolbar.style.marginBottom = '12px';
  toolbar.innerHTML = `
    <button id="expandAllTraceBtn" type="button" style="padding:8px 12px;border:none;border-radius:10px;background:#eef2ff;color:#4f46e5;cursor:pointer;">展开全部详情</button>
    <button id="collapseAllTraceBtn" type="button" style="padding:8px 12px;border:none;border-radius:10px;background:#f3f4f6;color:#111827;cursor:pointer;">收起全部详情</button>
  `;
  container.appendChild(toolbar);

  agentTraceStore.forEach((trace, index) => {
    const block = document.createElement('div');
    block.className = 'trace-block';

    block.innerHTML = `
      <div class="trace-head">
        <div>
          <h3>${trace.agent}</h3>
          <p>${trace.role}</p>
        </div>
        <div class="badge ${trace.used_llm ? 'badge-llm' : 'badge-rule'}">
          ${trace.used_llm ? 'LLM 规划' : '规则执行'}
        </div>
      </div>

      <div class="trace-objective"><strong>目标：</strong>${trace.objective || '无'}</div>
      <div class="trace-objective"><strong>决策：</strong>${trace.decision_summary || '无'}</div>
      <div class="trace-handoff"><strong>交接：</strong>${trace.handoff_to || '无'}</div>

      <div style="margin-top:12px;">
        <button
          id="traceToggle_${index}"
          type="button"
          style="padding:8px 12px;border:none;border-radius:10px;background:#eef2ff;color:#4f46e5;cursor:pointer;"
        >
          查看流程详情
        </button>
      </div>

      <div
        id="traceDetails_${index}"
        style="display:none;margin-top:12px;"
        data-loaded=""
        data-expanded="false"
      ></div>
    `;

    container.appendChild(block);
  });

  const expandBtn = document.getElementById('expandAllTraceBtn');
  const collapseBtn = document.getElementById('collapseAllTraceBtn');

  if (expandBtn) {
    expandBtn.addEventListener('click', expandAllTraceDetails);
  }
  if (collapseBtn) {
    collapseBtn.addEventListener('click', collapseAllTraceDetails);
  }

  agentTraceStore.forEach((_, index) => {
    const btn = document.getElementById(`traceToggle_${index}`);
    if (btn) {
      btn.addEventListener('click', () => toggleTraceDetails(index));
    }
  });
}

async function loadDatasets() {
  try {
    const datasets = await fetchJson(`${API_BASE}/api/navigation/datasets`);
    const select = document.getElementById('datasetName');
    if (!select) return;

    select.innerHTML = '';
    datasets.forEach(ds => {
      const opt = document.createElement('option');
      opt.value = ds.name;
      opt.textContent = `${ds.name} - ${ds.description}`;
      select.appendChild(opt);
    });
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
      if (mapContainer) {
        mapContainer.textContent = mapConfig.note || '未配置高德地图 JS API Key。';
      }
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
  if (playbackState.timer) {
    clearInterval(playbackState.timer);
    playbackState.timer = null;
  }
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
  const strategyHtml = Object.entries(stats.strategy_distribution || {})
    .map(([k, v]) => `<div><strong>${k}</strong>：${v}</div>`)
    .join('');

  el.innerHTML = `
    <div><strong>轨迹点数：</strong>${stats.point_count ?? trajectory.points.length}</div>
    <div><strong>分段数：</strong>${stats.segment_count ?? 0}</div>
    <div><strong>轨迹长度：</strong>${Number(stats.track_length_m || 0).toFixed(1)} m</div>
    <div><strong>高风险点：</strong>${stats.high_risk_points ?? 0}</div>
    <div><strong>跳变点：</strong>${stats.jump_points ?? 0}</div>
    <div style="margin-top:8px"><strong>策略分布</strong></div>
    ${strategyHtml || '<div>暂无</div>'}
  `;
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
    <div><strong>跳变：</strong>${point.jump_detected ? '是' : '否'}</div>
  `;
}

function updatePlaybackFrame(index) {
  if (!playbackState.points.length) return;
  playbackState.index = Math.max(0, Math.min(index, playbackState.points.length - 1));
  const point = playbackState.points[playbackState.index];

  const slider = document.getElementById('playbackSlider');
  if (slider) slider.value = String(playbackState.index);

  updatePlaybackInfo(point, playbackState.index, playbackState.points.length);

  if (playbackMarker && window.AMap) {
    playbackMarker.setPosition([point.longitude, point.latitude]);
    if (point.heading_smoothed_deg != null) {
      playbackMarker.setAngle(point.heading_smoothed_deg);
    }
    if (mapInstance) {
      mapInstance.setCenter([point.longitude, point.latitude]);
    }
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
  if (!mapConfig || !mapConfig.enabled) {
    throw new Error(mapConfig?.note || '未配置高德地图。');
  }

  if (window.AMap) return window.AMap;
  if (amapReadyPromise) return amapReadyPromise;

  amapReadyPromise = new Promise((resolve, reject) => {
    if (mapConfig.security_js_code) {
      window._AMapSecurityConfig = {
        securityJsCode: mapConfig.security_js_code,
      };
    }

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

  if (mapInstance && mapOverlays.length) {
    mapInstance.remove(mapOverlays);
  }

  mapOverlays = [];
  jumpMarkers = [];
  playbackMarker = null;
  startMarker = null;
  endMarker = null;
}

async function renderTrajectoryMap(data) {
  const trajectory = data.optional_context?.trajectory;

  if (!trajectory || !trajectory.points?.length) {
    setMapStatus('暂无轨迹数据', false);
    const mapContainer = document.getElementById('mapContainer');
    if (mapContainer) {
      mapContainer.textContent = '当前分析没有可展示的轨迹点。';
    }
    updateTrajectoryStats(null);
    updatePlaybackInfo(null, 0, 0);
    return;
  }

  updateTrajectoryStats(trajectory);
  playbackState.points = trajectory.points;
  playbackState.index = 0;
  playbackState.intervalMs = trajectory.playback?.default_interval_ms || 450;

  const slider = document.getElementById('playbackSlider');
  if (slider) {
    slider.max = String(Math.max(playbackState.points.length - 1, 0));
    slider.value = '0';
  }

  const hint = document.getElementById('playbackHint');
  if (hint) {
    hint.textContent = `共加载 ${trajectory.points.length} 个轨迹点，可按时间回放。`;
  }

  if (!mapConfig || !mapConfig.enabled) {
    setMapStatus(mapConfig?.note || '地图未配置', false);
    const mapContainer = document.getElementById('mapContainer');
    if (mapContainer) {
      mapContainer.textContent = '已生成轨迹数据，但未配置高德 JS API，无法渲染地图。';
    }
    updatePlaybackInfo(trajectory.points[0], 0, trajectory.points.length);
    return;
  }

  try {
    const AMap = await ensureAMapLoaded();
    const mapContainer = document.getElementById('mapContainer');
    if (mapContainer) {
      mapContainer.textContent = '';
    }

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

      polyline.on('mouseover', () => {
        setMapStatus(`风险 ${seg.risk} | 置信度 ${Number(seg.mean_confidence || 0).toFixed(2)} | 策略 ${seg.strategy_profile}`);
      });

      mapOverlays.push(polyline);
    });

    startMarker = new AMap.Marker({
      position: [trajectory.start_point.longitude, trajectory.start_point.latitude],
      title: '起点',
      label: {
        content: '<div style="padding:2px 6px;background:#10b981;color:#fff;border-radius:999px;">起点</div>',
        direction: 'top',
      },
    });

    endMarker = new AMap.Marker({
      position: [trajectory.end_point.longitude, trajectory.end_point.latitude],
      title: '终点',
      label: {
        content: '<div style="padding:2px 6px;background:#ef4444;color:#fff;border-radius:999px;">终点</div>',
        direction: 'top',
      },
    });

    playbackMarker = new AMap.Marker({
      position: [trajectory.start_point.longitude, trajectory.start_point.latitude],
      title: '当前回放点',
      content: '<div class="playback-marker"></div>',
      offset: new AMap.Pixel(-9, -9),
    });

    mapOverlays.push(startMarker, endMarker, playbackMarker);

    trajectory.points
      .filter(point => point.jump_detected)
      .forEach(point => {
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

    mapInstance.add(mapOverlays);
    mapInstance.setFitView(mapOverlays, false, [60, 60, 60, 60]);
    updatePlaybackFrame(0);
    setMapStatus('轨迹地图已加载');
  } catch (err) {
    setMapStatus(err.message, false);
    const mapContainer = document.getElementById('mapContainer');
    if (mapContainer) {
      mapContainer.textContent = err.message;
    }
  }
}

function renderAnalysis(data) {
  hasAnalysis = true;
  latestAnalysis = data;

  const title = document.getElementById('datasetTitle');
  const desc = document.getElementById('datasetDesc');
  const explanation = document.getElementById('globalExplanation');
  const followupBox = document.getElementById('followupAnswer');

  if (title) title.textContent = data.dataset.name;
  if (desc) desc.textContent = data.dataset.description;
  if (explanation) explanation.textContent = data.explanation;

  renderSummary(data.summary);
  renderRiskBars(data.summary.risk_distribution);
  renderFindings(data.summary.key_findings);
  renderEpochTable(data.epochs);
  renderAgentTrace(data.agent_trace);
  renderToolSources(data.tool_sources);

  const heading = (data.epochs || []).slice(0, 300).map(e => e.heading_smoothed_deg);
  const headingRaw = (data.epochs || []).slice(0, 300).map(e => e.heading_raw_deg);
  const confidence = (data.epochs || []).slice(0, 300).map(e => e.confidence);
  const threshold = (data.epochs || []).slice(0, 300).map(e => e.dynamic_threshold_m);
  const errors = (data.epochs || []).slice(0, 300).map(e => e.baseline_error_m);

  drawLineChart('headingChart', headingRaw, heading, 'raw', 'smoothed');
  drawLineChart('confidenceChart', confidence, null, 'confidence');
  drawLineChart('thresholdChart', threshold, errors, 'threshold', 'baseline error');
  renderTrajectoryMap(data);

  if (followupBox) {
    followupBox.textContent = '可以就这次分析继续提问。';
  }
}

async function analyzeSample() {
  try {
    setStatus('正在分析样例...');
    const payload = {
      dataset_name: document.getElementById('datasetName').value,
      ...buildPayload(),
    };

    const data = await fetchJson(`${API_BASE}/api/navigation/analyze-sample`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    renderAnalysis(data);
    setStatus('样例分析完成');
  } catch (err) {
    setStatus(`分析失败：${err.message}`, false);
    setMapStatus('轨迹未加载', false);
  }
}

async function uploadAndAnalyze() {
  const fileInput = document.getElementById('uploadFile');
  if (!fileInput.files.length) {
    alert('请先选择 NMEA 文件');
    return;
  }

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);

  const refInput = document.getElementById('referenceFile');
  if (refInput.files.length) {
    formData.append('reference_file', refInput.files[0]);
  }

  const payload = buildPayload();
  Object.entries(payload).forEach(([key, value]) => {
    formData.append(key, String(value));
  });

  try {
    setStatus('正在上传并分析文件...');
    const data = await fetchJson(`${API_BASE}/api/navigation/upload-nmea`, {
      method: 'POST',
      body: formData,
    });

    renderAnalysis(data);
    setStatus('文件分析完成');
  } catch (err) {
    setStatus(`上传分析失败：${err.message}`, false);
    setMapStatus('轨迹未加载', false);
  }
}

async function askFollowup() {
  if (!hasAnalysis) {
    alert('请先完成一次分析。');
    return;
  }

  const question = document.getElementById('followupQuestion').value.trim();
  if (!question) {
    alert('请输入问题。');
    return;
  }

  try {
    setStatus('解释 Agent 正在回答...');
    const data = await fetchJson(`${API_BASE}/api/navigation/followup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        use_llm: document.getElementById('useLlm').checked,
      }),
    });

    const answer = document.getElementById('followupAnswer');
    if (answer) answer.textContent = data.answer;
    setStatus('解释 Agent 已完成回答');
  } catch (err) {
    setStatus(`追问失败：${err.message}`, false);
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
  const analyzeBtn = document.getElementById('analyzeBtn');
  const uploadBtn = document.getElementById('uploadBtn');
  const followupBtn = document.getElementById('followupBtn');
  const playbackToggle = document.getElementById('playbackToggle');
  const playbackSpeed = document.getElementById('playbackSpeed');
  const playbackSlider = document.getElementById('playbackSlider');

  if (analyzeBtn) analyzeBtn.addEventListener('click', analyzeSample);
  if (uploadBtn) uploadBtn.addEventListener('click', uploadAndAnalyze);
  if (followupBtn) followupBtn.addEventListener('click', askFollowup);
  if (playbackToggle) playbackToggle.addEventListener('click', togglePlayback);

  if (playbackSpeed) {
    playbackSpeed.addEventListener('change', (event) => {
      const speed = Number(event.target.value || 1);
      playbackState.intervalMs = Math.max(80, Math.round(450 / speed));
      if (playbackState.playing) {
        startPlayback();
      }
    });
  }

  if (playbackSlider) {
    playbackSlider.addEventListener('input', (event) => {
      clearPlaybackTimer();
      updatePlaybackFrame(Number(event.target.value || 0));
    });
  }
}

window.addEventListener('load', async () => {
  bindEvents();
  await Promise.all([loadDatasets(), loadMapConfig()]);
});