let selectedProtocol = null;
let connectionOk = false;
let currentServerId = null;
let qrLinkText = '';

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadProtocols();
});

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('page-install').classList.add('hidden');
  document.getElementById('page-manage').classList.add('hidden');

  if (tab === 'install') {
    document.getElementById('page-install').classList.remove('hidden');
    document.querySelectorAll('.tab')[0].classList.add('active');
  } else {
    document.getElementById('page-manage').classList.remove('hidden');
    document.querySelectorAll('.tab')[1].classList.add('active');
    loadServers();
  }
}

// ── Protocols ─────────────────────────────────────────────────────────────────
async function loadProtocols() {
  try {
    const res = await fetch('/api/protocols');
    const protocols = await res.json();
    renderProtocols(protocols);
  } catch (e) {
    document.getElementById('protocol-grid').innerHTML =
      '<div style="color:var(--red)">Не удалось загрузить протоколы</div>';
  }
}

function blockingLabel(level) {
  // 5 = почти не блокируется, 1 = легко блокируется
  const map = {
    5: { txt: 'Обход блокировок: отлично', cls: 'b5' },
    4: { txt: 'Обход блокировок: хорошо', cls: 'b4' },
    3: { txt: 'Обход блокировок: средне', cls: 'b3' },
    2: { txt: 'Обход блокировок: слабо', cls: 'b2' },
    1: { txt: 'Обход блокировок: легко блокируется', cls: 'b1' },
  };
  return map[level] || map[3];
}

function shieldBar(level) {
  let s = '';
  for (let i = 1; i <= 5; i++) {
    s += `<span class="shield ${i <= level ? 'on' : ''}">🛡</span>`;
  }
  return s;
}

function renderProtocols(protocols) {
  const grid = document.getElementById('protocol-grid');
  grid.innerHTML = '';
  // recommended first
  protocols.sort((a, b) => (b.recommended - a.recommended) || (b.blocking_level - a.blocking_level));
  protocols.forEach(p => {
    const card = document.createElement('div');
    card.className = 'protocol-card';
    card.dataset.id = p.id;
    const bl = blockingLabel(p.blocking_level);
    card.innerHTML = `
      <div class="selected-check">✓</div>
      ${p.recommended ? '<div class="rec-badge">⭐ Рекомендуем</div>' : ''}
      <div class="protocol-icon">${p.icon}</div>
      <div class="protocol-name">${escHtml(p.name)}</div>
      <div class="protocol-desc">${escHtml(p.description)}</div>
      <div class="protocol-block ${bl.cls}">
        <div class="block-shields" title="${escHtml(bl.txt)}">${shieldBar(p.blocking_level)}</div>
        <div class="block-txt">${escHtml(bl.txt)}</div>
      </div>
      <div class="protocol-tags">
        <span class="ptag">⚙️ ${escHtml(p.ease || '')}</span>
        ${p.devices ? `<span class="ptag" title="${escHtml(p.devices)}">📱 устройства</span>` : ''}
      </div>
      <button class="why-btn" onclick="event.stopPropagation(); toggleWhy(this)">Подробнее про блокировки ▾</button>
      <div class="why-text">${escHtml(p.blocking_text || '')}<br><br><strong>Работает на:</strong> ${escHtml(p.devices || '')}</div>
    `;
    card.addEventListener('click', () => selectProtocol(p, card));
    grid.appendChild(card);
  });
}

function toggleWhy(btn) {
  const txt = btn.nextElementSibling;
  const open = txt.classList.toggle('show');
  btn.textContent = open ? 'Скрыть ▴' : 'Подробнее про блокировки ▾';
}

function selectProtocol(p, card) {
  document.querySelectorAll('.protocol-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  selectedProtocol = p;
  document.getElementById('step-install').classList.remove('card--locked');
  document.getElementById('selected-summary').innerHTML =
    `Выбран: <strong>${p.icon} ${p.name}</strong> — ${p.description}`;
}

// ── Toggle password ───────────────────────────────────────────────────────────
function togglePass() {
  const inp = document.getElementById('password');
  inp.type = inp.type === 'password' ? 'text' : 'password';
}

// ── Test connection ───────────────────────────────────────────────────────────
async function testConnection() {
  const btn = document.getElementById('btn-test');
  const host = document.getElementById('host').value.trim();
  const port = parseInt(document.getElementById('port').value) || 22;
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;

  if (!host || !password) { showTestResult('error', '⚠️ Введите IP-адрес и пароль'); return; }

  btn.disabled = true;
  btn.textContent = '⏳ Подключаюсь...';
  showTestResult('loading', '🔌 Проверяю соединение...');

  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port, username, password }),
    });
    const data = await res.json();
    if (data.success) {
      showTestResult('ok', `✅ Подключено! ${data.message}`);
      connectionOk = true;
      document.getElementById('step-protocol').classList.remove('card--locked');
    } else {
      showTestResult('error', `❌ ${data.message}`);
      connectionOk = false;
    }
  } catch (e) {
    showTestResult('error', '❌ Ошибка запроса');
  }
  btn.disabled = false;
  btn.innerHTML = '<span class="btn-icon">🔌</span> Проверить соединение';
}

function showTestResult(type, msg) {
  const el = document.getElementById('test-result');
  el.className = `test-result test-result--${type}`;
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ── Start install ─────────────────────────────────────────────────────────────
async function startInstall() {
  if (!selectedProtocol) { alert('Выберите протокол VPN'); return; }
  if (!connectionOk) { alert('Сначала проверьте соединение'); return; }

  const btn = document.getElementById('btn-install');
  btn.disabled = true;

  document.getElementById('terminal-card').classList.remove('hidden');
  document.getElementById('config-card').classList.add('hidden');
  document.getElementById('error-card').classList.add('hidden');
  document.getElementById('terminal').innerHTML = '';
  setStatusBadge('running', '⏳ Выполняется');
  document.getElementById('terminal-card').scrollIntoView({ behavior: 'smooth' });

  const payload = {
    host: document.getElementById('host').value.trim(),
    port: parseInt(document.getElementById('port').value) || 22,
    username: document.getElementById('username').value.trim(),
    password: document.getElementById('password').value,
    protocol: selectedProtocol.id,
    deepseek_api_key: document.getElementById('ai-key').value.trim(),
  };

  try {
    const res = await fetch('/api/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) { showError(data.error); btn.disabled = false; return; }
    connectWS(data.session_id, payload.host);
  } catch (e) {
    showError('Не удалось запустить установку: ' + e.message);
    btn.disabled = false;
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connectWS(sessionId, serverIp) {
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${wsProto}://${location.host}/ws/${sessionId}`);

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'log') {
      appendLog(msg.message);
    } else if (msg.type === 'done') {
      if (msg.status === 'done') {
        setStatusBadge('done', '✅ Готово');
        showConfig(msg.config, serverIp);
        if (msg.server_id) currentServerId = msg.server_id;
      } else {
        setStatusBadge('error', '❌ Ошибка');
        showError(msg.error || 'Неизвестная ошибка');
      }
      document.getElementById('btn-install').disabled = false;
    } else if (msg.type === 'error') {
      appendLog('❌ ' + msg.message);
      setStatusBadge('error', '❌ Ошибка');
    }
  };
  ws.onerror = () => appendLog('⚠️ WebSocket ошибка');
}

function appendLog(line) {
  const terminal = document.getElementById('terminal');
  const div = document.createElement('div');
  div.className = 'log-line ' + getLogClass(line);
  div.textContent = line;
  terminal.appendChild(div);
  terminal.scrollTop = terminal.scrollHeight;
}

function getLogClass(line) {
  if (line.includes('✅') || line.includes('успешно') || line.includes('Готово')) return 'log-line--ok';
  if (line.includes('❌') || /error|ошибка/i.test(line)) return 'log-line--error';
  if (line.includes('⚠️')) return 'log-line--warn';
  if (line.includes('🤖')) return 'log-line--ai';
  if (line.includes('📋') || line.includes('[')) return 'log-line--step';
  return '';
}

function setStatusBadge(type, text) {
  const badge = document.getElementById('status-badge');
  badge.className = `status-badge status-badge--${type}`;
  badge.textContent = text;
}

// ── Config display ────────────────────────────────────────────────────────────
function showConfig(config, serverIp) {
  if (!config) return;
  const card = document.getElementById('config-card');
  const content = document.getElementById('config-content');
  card.classList.remove('hidden');
  content.innerHTML = buildConfigHTML(config, serverIp, selectedProtocol?.name || '');
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function buildConfigHTML(config, serverIp, protocolName) {
  const type = config.type || '';
  let html = `
    <div class="config-block" style="border-color:rgba(63,185,80,0.3);background:rgba(63,185,80,0.05);margin-bottom:16px">
      <p style="color:var(--green);font-size:.95rem;font-weight:600">🎉 Установка завершена!</p>
      <p style="color:var(--text2);font-size:.85rem;margin-top:4px">
        Сервер: <strong style="color:var(--text)">${escHtml(serverIp)}</strong> ·
        Протокол: <strong style="color:var(--text)">${escHtml(protocolName)}</strong>
      </p>
    </div>`;

  if ((type === 'wireguard' || type === 'openvpn') && config.client_config) {
    const cfg = config.client_config.replace(/SERVER_IP/g, serverIp);
    const ext = type === 'wireguard' ? 'conf' : 'ovpn';
    html += `<div class="config-block">
      <h3>📲 Подключись за 30 секунд</h3>
      ${config.qr ? `
        <div class="qr-inline">
          <img src="data:image/png;base64,${config.qr}" class="qr-inline-img" alt="QR">
          <div class="qr-inline-steps">
            <p><strong>На телефоне:</strong></p>
            <p>1. Установи приложение <strong>WireGuard</strong> (App Store / Google Play)</p>
            <p>2. Нажми ➕ → «Сканировать QR-код»</p>
            <p>3. Наведи камеру на этот код — готово!</p>
          </div>
        </div>` : ''}
      <p style="font-size:.84rem;color:var(--text2);margin:10px 0 6px">На компьютере — скачай файл и импортируй в приложение:</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="copy-btn" onclick="downloadFile('client.${ext}', 'cfg-text')">💾 Скачать конфиг (.${ext})</button>
        <button class="copy-btn" onclick="copyText('cfg-text')">📋 Скопировать текст</button>
      </div>
      <pre id="cfg-text" style="display:none">${escHtml(cfg)}</pre>
    </div>`;
  } else if (type === '3x-ui') {
    const url = (config.panel_url || '').replace('SERVER_IP', serverIp);
    html += `<div class="config-block">
      <h3>3X-UI Панель</h3>
      <div class="config-kv">
        <div class="config-kv-item"><span class="k">URL</span><span class="v"><a href="${escHtml(url)}" target="_blank" style="color:var(--accent)">${escHtml(url)}</a></span></div>
        <div class="config-kv-item"><span class="k">Логин</span><span class="v">${escHtml(config.default_user||'admin')}</span></div>
        <div class="config-kv-item"><span class="k">Пароль</span><span class="v">${escHtml(config.default_pass||'admin')}</span></div>
      </div>
    </div>
    <div class="config-block" style="border-color:rgba(210,153,34,0.3)">
      <p style="color:var(--yellow);font-size:.88rem">⚠️ ${escHtml(config.note||'')}</p>
    </div>`;
  } else if (type === 'vless-reality') {
    html += `<div class="config-block">
      <h3>📲 Подключись за 30 секунд</h3>
      ${config.qr ? `
        <div class="qr-inline">
          <img src="data:image/png;base64,${config.qr}" class="qr-inline-img" alt="QR">
          <div class="qr-inline-steps">
            <p><strong>На телефоне:</strong></p>
            <p>1. Установи <strong>v2RayTun</strong> или <strong>Hiddify</strong> (App Store / Google Play)</p>
            <p>2. Нажми ➕ → «Добавить из QR-кода»</p>
            <p>3. Наведи камеру — готово!</p>
          </div>
        </div>` : ''}
      ${config.link ? `
        <p style="font-size:.84rem;color:var(--text2);margin:10px 0 6px">Или скопируй ссылку и вставь в приложение:</p>
        <pre id="cfg-text">${escHtml(config.link)}</pre>
        <button class="copy-btn" onclick="copyText('cfg-text')">📋 Скопировать ссылку</button>` : ''}
    </div>`;
  } else if (type === 'shadowsocks') {
    html += `<div class="config-block">
      <h3>📲 Подключись за 30 секунд</h3>
      ${config.qr ? `
        <div class="qr-inline">
          <img src="data:image/png;base64,${config.qr}" class="qr-inline-img" alt="QR">
          <div class="qr-inline-steps">
            <p><strong>На телефоне:</strong></p>
            <p>1. Установи <strong>Outline</strong> или <strong>Shadowrocket</strong></p>
            <p>2. Добавь сервер по QR-коду</p>
            <p>3. Готово!</p>
          </div>
        </div>` : ''}
      ${config.link ? `
        <p style="font-size:.84rem;color:var(--text2);margin:10px 0 6px">Или скопируй ссылку:</p>
        <pre id="cfg-text">${escHtml(config.link)}</pre>
        <button class="copy-btn" onclick="copyText('cfg-text')">📋 Скопировать ссылку</button>` : ''}
    </div>`;
  } else if (type === 'outline') {
    html += `<div class="config-block">
      <h3>Outline</h3>
      <pre id="cfg-text">${escHtml(config.access_info||'')}</pre>
      <button class="copy-btn" onclick="copyText('cfg-text')">📋 Скопировать access key</button>
    </div>`;
  } else if (type === 'ikev2') {
    html += `<div class="config-block">
      <h3>IKEv2 / IPSec</h3>
      <div class="config-kv">
        <div class="config-kv-item"><span class="k">Сервер</span><span class="v">${escHtml(serverIp)}</span></div>
      </div>
      ${config.raw ? `<pre style="margin-top:10px">${escHtml(config.raw)}</pre>` : ''}
      <p style="font-size:.85rem;color:var(--text2);margin-top:8px">${escHtml(config.note||'')}</p>
    </div>`;
  }
  return html;
}

// ── Error / Reset ─────────────────────────────────────────────────────────────
function showError(msg) {
  document.getElementById('error-card').classList.remove('hidden');
  document.getElementById('error-content').textContent = msg;
  document.getElementById('error-card').scrollIntoView({ behavior: 'smooth' });
}

function resetToStart() {
  document.getElementById('error-card').classList.add('hidden');
  document.getElementById('terminal-card').classList.add('hidden');
  document.getElementById('config-card').classList.add('hidden');
  document.getElementById('btn-install').disabled = false;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Servers management ────────────────────────────────────────────────────────
async function loadServers() {
  const container = document.getElementById('servers-list');
  container.innerHTML = '<div class="empty-state">Загрузка...</div>';
  closeServerDetail();
  try {
    const res = await fetch('/api/servers');
    const servers = await res.json();
    if (!servers.length) {
      container.innerHTML = '<div class="empty-state">Нет сохранённых серверов.<br>Установи VPN — он появится здесь автоматически.</div>';
      return;
    }
    const icons = { wireguard:'🔒', openvpn:'🛡️', '3x-ui':'⚡', 'vless-reality':'🌐', shadowsocks:'🔑', outline:'📦', ikev2:'📱' };
    container.innerHTML = `<div class="servers-grid">${servers.map(s => `
      <div class="server-card" onclick="openServerDetail('${s.id}', ${JSON.stringify(s).replace(/"/g,'&quot;')})">
        <div class="server-icon">${icons[s.protocol] || '🖥️'}</div>
        <div class="server-info">
          <div class="server-host">${escHtml(s.host)}</div>
          <div class="server-meta">${escHtml(s.username)}@${escHtml(s.host)}:${s.port}</div>
        </div>
        <div class="proto-badge">${escHtml(s.protocol_name)}</div>
        <div class="server-actions" onclick="event.stopPropagation()">
          <button class="btn btn--danger" style="padding:6px 10px;font-size:.8rem" onclick="deleteServer('${s.id}')">🗑</button>
        </div>
      </div>`).join('')}
    </div>`;
  } catch (e) {
    container.innerHTML = `<div class="empty-state" style="color:var(--red)">Ошибка: ${e.message}</div>`;
  }
}

async function deleteServer(id) {
  if (!confirm('Убрать сервер из списка?\n\n(VPN на самом сервере останется. Для полного сноса используй "Снести VPN" внутри сервера.)')) return;
  await fetch(`/api/servers/${id}`, { method: 'DELETE' });
  loadServers();
}

async function uninstallVPN(serverId, protocolName) {
  if (!confirm(`⚠️ ПОЛНЫЙ СНОС\n\nЭто остановит и удалит ${protocolName} с сервера, сотрёт конфиги и всех клиентов. Действие необратимо.\n\nПродолжить?`)) return;

  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ Сношу...';
  try {
    const res = await fetch(`/api/servers/${serverId}/uninstall`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      alert('✅ VPN снесён с сервера и убран из списка.');
      switchTab('manage');
    } else {
      alert('❌ Ошибка сноса: ' + (data.error || 'неизвестно'));
      btn.disabled = false;
      btn.textContent = '🧨 Снести VPN с сервера';
    }
  } catch (e) {
    alert('❌ Ошибка: ' + e.message);
    btn.disabled = false;
    btn.textContent = '🧨 Снести VPN с сервера';
  }
}

async function openServerDetail(id, server) {
  currentServerId = id;
  const detail = document.getElementById('server-detail');
  const content = document.getElementById('detail-content');
  document.getElementById('detail-title').textContent = server.host;
  document.getElementById('detail-badge').textContent = server.protocol_name;
  detail.classList.remove('hidden');
  content.innerHTML = '<div class="empty-state">Подключение к серверу...</div>';
  detail.scrollIntoView({ behavior: 'smooth' });

  try {
    const res = await fetch(`/api/servers/${id}/clients`);
    const data = await res.json();
    renderServerDetail(detail, content, server, data);
  } catch (e) {
    content.innerHTML = `<div class="empty-state" style="color:var(--red)">Ошибка подключения: ${e.message}</div>`;
  }
}

function renderServerDetail(detail, content, server, data) {
  const protocol = server.protocol;
  let html = '';

  // Protocols with client list (WireGuard, OpenVPN)
  if (protocol === 'wireguard' || protocol === 'openvpn') {
    const clients = data.clients || [];
    const ext = protocol === 'wireguard' ? 'conf' : 'ovpn';
    html += `
      <div class="config-block">
        <h3>Клиенты (${clients.length})</h3>
        ${clients.length ? `
          <table class="clients-table">
            <thead><tr><th>Имя</th><th>Действия</th></tr></thead>
            <tbody>
              ${clients.map(c => `<tr>
                <td>${escHtml(c.name)}</td>
                <td style="display:flex;gap:6px;flex-wrap:wrap;padding:8px 12px">
                  <button class="btn btn--ghost" style="padding:5px 10px;font-size:.8rem"
                    onclick="downloadClientConfig('${server.id}','${escHtml(c.name)}','${ext}')">💾 Скачать</button>
                  ${protocol === 'wireguard' ? `
                  <button class="btn btn--ghost" style="padding:5px 10px;font-size:.8rem"
                    onclick="showClientQR('${server.id}','${escHtml(c.name)}')">📲 QR</button>` : ''}
                  <button class="btn btn--danger" style="padding:5px 10px;font-size:.8rem"
                    onclick="removeClient('${server.id}','${escHtml(c.name)}')">🗑</button>
                </td>
              </tr>`).join('')}
            </tbody>
          </table>` : '<p style="color:var(--text2);font-size:.88rem;padding:8px 0">Нет клиентов</p>'}
        <div class="add-client-row">
          <div class="form-group" style="flex:1">
            <label>Имя нового клиента</label>
            <input type="text" id="new-client-name" placeholder="phone1, laptop..." value="">
          </div>
          <button class="btn btn--primary" onclick="addClient('${server.id}')">+ Добавить</button>
        </div>
      </div>`;
  }

  // VLESS+Reality — show link + QR
  else if (protocol === 'vless-reality') {
    const info = data.info || {};
    if (info.link) {
      html += `<div class="config-block">
        <h3>VLESS подключение</h3>
        <pre id="vless-link" style="font-size:.75rem">${escHtml(info.link)}</pre>
        <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
          <button class="copy-btn" onclick="copyText('vless-link')">📋 Скопировать ссылку</button>
          ${info.qr ? `<button class="copy-btn" onclick="showQRImg('${info.qr}', 'VLESS+Reality', ${JSON.stringify(info.link)})">📲 QR-код</button>` : ''}
        </div>
        <div class="config-kv" style="margin-top:12px">
          <div class="config-kv-item"><span class="k">UUID</span><span class="v">${escHtml(info.uid||'')}</span></div>
          <div class="config-kv-item"><span class="k">Порт</span><span class="v">${info.port||443}</span></div>
        </div>
      </div>
      <div class="config-block">
        <h3>Клиенты</h3>
        <div class="config-kv">
          <div class="config-kv-item"><span class="k">Windows/Android</span><span class="v">v2rayN, Nekoray, Hiddify</span></div>
          <div class="config-kv-item"><span class="k">iOS/macOS</span><span class="v">Streisand, FoXray, Sing-Box</span></div>
        </div>
      </div>`;
    } else {
      html += `<div class="config-block"><p style="color:var(--red)">${escHtml(info.error||'Не удалось получить конфигурацию')}</p></div>`;
    }
  }

  // Shadowsocks — show ss:// link + QR
  else if (protocol === 'shadowsocks') {
    const info = data.info || {};
    if (info.link) {
      html += `<div class="config-block">
        <h3>Shadowsocks подключение</h3>
        <div class="config-kv">
          <div class="config-kv-item"><span class="k">Сервер</span><span class="v">${escHtml(server.host)}</span></div>
          <div class="config-kv-item"><span class="k">Порт</span><span class="v">${info.port||8388}</span></div>
          <div class="config-kv-item"><span class="k">Метод</span><span class="v">${escHtml(info.method||'')}</span></div>
          <div class="config-kv-item"><span class="k">Пароль</span><span class="v">${escHtml(info.password||'')}</span></div>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button class="copy-btn" onclick="navigator.clipboard.writeText(${JSON.stringify(info.link)})">📋 Скопировать ss:// ссылку</button>
          ${info.qr ? `<button class="copy-btn" onclick="showQRImg('${info.qr}', 'Shadowsocks', ${JSON.stringify(info.link)})">📲 QR-код</button>` : ''}
        </div>
      </div>`;
    } else {
      html += `<div class="config-block"><p style="color:var(--red)">${escHtml(info.error||'Ошибка получения данных')}</p></div>`;
    }
  }

  // 3X-UI — just link to panel
  else if (protocol === '3x-ui') {
    const cfg = server.config || {};
    const url = (cfg.panel_url||'').replace('SERVER_IP', server.host);
    html += `<div class="config-block">
      <h3>3X-UI Панель управления</h3>
      <div class="config-kv">
        <div class="config-kv-item"><span class="k">URL</span><span class="v">
          <a href="${escHtml(url)}" target="_blank" style="color:var(--accent)">${escHtml(url)}</a>
        </span></div>
        <div class="config-kv-item"><span class="k">Логин</span><span class="v">${escHtml(cfg.default_user||'admin')}</span></div>
      </div>
      <p style="font-size:.82rem;color:var(--text2);margin-top:10px">
        Управление пользователями, протоколами и трафиком — в панели 3X-UI.
      </p>
    </div>`;
  }

  // Outline
  else if (protocol === 'outline') {
    const cfg = server.config || {};
    html += `<div class="config-block">
      <h3>Outline Manager — ключ доступа</h3>
      <p style="font-size:.84rem;color:var(--text2);margin-bottom:10px">
        Скопируй строку ниже (вместе с фигурными скобками) и вставь в <strong>Outline Manager → Step 2</strong>.
        Через менеджер добавляй пользователей и получай ключи.
      </p>
      ${cfg.manager_key ? `<pre id="outline-key">${escHtml(cfg.manager_key)}</pre>
      <button class="copy-btn" onclick="copyText('outline-key')">📋 Скопировать ключ менеджера</button>`
        : `<pre>${escHtml(cfg.access_info||'нет данных')}</pre>`}
    </div>
    <div class="config-block">
      <h3>Скачать Outline Manager</h3>
      <div class="config-kv">
        <div class="config-kv-item"><span class="k">Windows/Mac/Linux</span><span class="v"><a href="https://getoutline.org/get-started/#step-1" target="_blank" style="color:var(--accent)">getoutline.org</a></span></div>
      </div>
    </div>`;
  }

  // IKEv2
  else if (protocol === 'ikev2') {
    html += `<div class="config-block">
      <h3>IKEv2 / IPSec</h3>
      <div class="config-kv">
        <div class="config-kv-item"><span class="k">Сервер</span><span class="v">${escHtml(server.host)}</span></div>
      </div>
      <div class="config-kv" style="margin-top:12px">
        <div class="config-kv-item"><span class="k">iOS/macOS</span><span class="v">Настройки → VPN → IKEv2</span></div>
        <div class="config-kv-item"><span class="k">Windows</span><span class="v">Параметры → Сеть → VPN</span></div>
        <div class="config-kv-item"><span class="k">Android</span><span class="v">strongSwan VPN Client</span></div>
      </div>
    </div>`;
  }

  // Maintenance — reinstall (fix a hung/broken install)
  html += `
    <div class="config-block" style="border-color:rgba(245,158,11,0.3);background:rgba(245,158,11,0.04);margin-top:8px">
      <h3 style="color:#f59e0b">♻️ Переустановить</h3>
      <p style="font-size:.84rem;color:var(--text2);margin-bottom:12px">
        Если установка зависла или что-то сломалось — снесёт старую и поставит ${escHtml(server.protocol_name)} заново начисто.
      </p>
      <button class="btn" style="border-color:#f59e0b;color:#f59e0b"
        onclick="reinstallServer('${server.id}', '${escHtml(server.protocol_name)}')">
        ♻️ Переустановить начисто
      </button>
    </div>`;

  // Danger zone — full uninstall
  html += `
    <div class="config-block" style="border-color:rgba(248,81,73,0.3);background:rgba(248,81,73,0.04);margin-top:8px">
      <h3 style="color:var(--red)">⚠️ Опасная зона</h3>
      <p style="font-size:.84rem;color:var(--text2);margin-bottom:12px">
        Полностью удалить ${escHtml(server.protocol_name)} с сервера: остановка сервиса, удаление пакетов, конфигов и всех клиентов.
      </p>
      <button class="btn btn--danger" onclick="uninstallVPN('${server.id}', '${escHtml(server.protocol_name)}')">
        🧨 Снести VPN с сервера
      </button>
    </div>`;

  content.innerHTML = html || '<div class="empty-state">Нет данных для отображения</div>';
}

function closeServerDetail() {
  document.getElementById('server-detail').classList.add('hidden');
  currentServerId = null;
}

async function addClient(serverId) {
  const nameEl = document.getElementById('new-client-name');
  const name = nameEl.value.trim();
  if (!name) { alert('Введи имя клиента'); return; }

  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳...';

  try {
    const res = await fetch(`/api/servers/${serverId}/clients`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_name: name }),
    });
    const data = await res.json();
    if (data.error) { alert('Ошибка: ' + data.error); return; }
    if (data.config) {
      // Show config immediately
      if (data.qr) showQRImg(data.qr, name, data.config);
    }
    nameEl.value = '';
    // Reload detail
    const srv = await (await fetch(`/api/servers`)).json();
    const s = srv.find(x => x.id === serverId);
    if (s) openServerDetail(serverId, s);
  } catch (e) {
    alert('Ошибка: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '+ Добавить';
  }
}

async function removeClient(serverId, clientName) {
  if (!confirm(`Удалить клиента "${clientName}"?`)) return;
  await fetch(`/api/servers/${serverId}/clients/${encodeURIComponent(clientName)}`, { method: 'DELETE' });
  const srv = await (await fetch(`/api/servers`)).json();
  const s = srv.find(x => x.id === serverId);
  if (s) openServerDetail(serverId, s);
}

async function downloadClientConfig(serverId, clientName, ext) {
  const res = await fetch(`/api/servers/${serverId}/clients/${encodeURIComponent(clientName)}/config`);
  const data = await res.json();
  if (data.config) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([data.config], { type: 'text/plain' }));
    a.download = `${clientName}.${ext}`;
    a.click();
  } else {
    alert(data.error || 'Конфиг не найден');
  }
}

async function showClientQR(serverId, clientName) {
  const res = await fetch(`/api/servers/${serverId}/clients/${encodeURIComponent(clientName)}/config`);
  const data = await res.json();
  if (data.qr) {
    showQRImg(data.qr, clientName, data.config || '');
  } else {
    alert(data.error || 'QR недоступен');
  }
}

// ── QR Modal ──────────────────────────────────────────────────────────────────
function showQRImg(b64, title, link) {
  document.getElementById('qr-title').textContent = title;
  document.getElementById('qr-img').src = 'data:image/png;base64,' + b64;
  document.getElementById('qr-link').textContent = typeof link === 'string' ? link : '';
  qrLinkText = typeof link === 'string' ? link : '';
  document.getElementById('qr-modal').classList.remove('hidden');
}

function showQRFromText(text, title) {
  // For WireGuard config — generate QR from text via server?
  // Fallback: show text only (QR for WG config is too long, show info)
  alert('Импортируй .conf файл в WireGuard — QR для конфига WG слишком длинный. Используй кнопку "Скачать".');
}

function closeQR() {
  document.getElementById('qr-modal').classList.add('hidden');
}

function copyQRLink() {
  if (qrLinkText) navigator.clipboard.writeText(qrLinkText);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function copyText(id) {
  const text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = '✅ Скопировано!';
    setTimeout(() => btn.textContent = orig, 2000);
  });
}

function downloadFile(filename, id) {
  const text = document.getElementById(id).textContent;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  a.download = filename;
  a.click();
}

// ── Update ────────────────────────────────────────────────────────────────────

async function loadVersion() {
  try {
    const r = await fetch('/api/version');
    const v = await r.json();
    const badge = document.getElementById('version-badge');
    if (!badge) return;
    const ver = v.version ? `v${v.version}` : '';
    const sha = v.commit && v.commit !== 'unknown' ? ` · ${v.commit}` : '';
    badge.textContent = ver + sha;
    const btn = document.getElementById('btn-update');
    if (v.up_to_date === false && btn) {
      btn.classList.add('has-update');
      btn.title = 'Доступно обновление!';
    }
  } catch {}
}

// Step 1 — check GitHub for a newer version, then offer to update.
async function checkUpdates() {
  const modal = document.getElementById('update-modal');
  const status = document.getElementById('update-status');
  const actions = document.getElementById('update-actions');
  const log = document.getElementById('update-log');
  document.getElementById('update-modal-title').textContent = '🔄 Обновление';
  log.style.display = 'none';
  log.innerHTML = '';
  actions.innerHTML = '';
  status.innerHTML = '<div class="spinner-line">⏳ Проверяю обновления на GitHub...</div>';
  modal.style.display = 'flex';

  let v;
  try {
    v = await (await fetch('/api/version')).json();
  } catch (e) {
    status.innerHTML = '<div class="update-line error">❌ Не удалось проверить версию. Эта панель установлена из старой версии без механизма обновлений — обнови вручную один раз (см. README).</div>';
    return;
  }

  if (v.up_to_date === true) {
    status.innerHTML = `<div class="update-line ok">✅ У вас последняя версия.</div>
      <div class="update-meta">Текущая: v${v.version || '?'} · ${v.commit} · ${v.date}</div>`;
    actions.innerHTML = `<button class="btn" onclick="closeUpdateModal()">Закрыть</button>`;
  } else if (v.up_to_date === false) {
    status.innerHTML = `<div class="update-line warn">⬆️ Доступно обновление!</div>
      <div class="update-meta">Установлено: v${v.version || '?'} · ${v.commit} · ${v.date}</div>`;
    actions.innerHTML = `
      <button class="btn btn--primary" onclick="runUpdate()">Обновить сейчас</button>
      <button class="btn" onclick="closeUpdateModal()">Позже</button>`;
  } else {
    status.innerHTML = `<div class="update-line warn">⚠️ Не удалось сверить с GitHub (нет сети или git недоступен).</div>
      <div class="update-meta">Текущая: v${v.commit || '?'} · ${v.date || ''}</div>`;
    actions.innerHTML = `
      <button class="btn btn--primary" onclick="runUpdate()">Всё равно обновить</button>
      <button class="btn" onclick="closeUpdateModal()">Закрыть</button>`;
  }
}

// Step 2 — pull + restart, streaming the log live.
function runUpdate() {
  const status = document.getElementById('update-status');
  const actions = document.getElementById('update-actions');
  const log = document.getElementById('update-log');
  status.innerHTML = '';
  actions.innerHTML = '';
  log.style.display = 'block';
  log.innerHTML = '';

  const btn = document.getElementById('btn-update');
  btn.disabled = true;

  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${wsProto}://${location.host}/ws/update`);

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'log') {
      const line = document.createElement('div');
      line.className = `update-line ${msg.level || ''}`;
      line.textContent = msg.message;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
    } else if (msg.type === 'done') {
      btn.disabled = false;
      if (msg.restart) {
        const countdown = document.createElement('div');
        countdown.className = 'update-line ok';
        log.appendChild(countdown);
        let n = 5;
        const t = setInterval(() => {
          countdown.textContent = `Перезагрузка страницы через ${n}...`;
          if (--n < 0) { clearInterval(t); location.reload(); }
        }, 1000);
      } else {
        actions.innerHTML = `<button class="btn" onclick="closeUpdateModal()">Закрыть</button>`;
      }
    }
  };
  ws.onerror = () => {
    const line = document.createElement('div');
    line.className = 'update-line error';
    line.textContent = '❌ Соединение прервано';
    log.appendChild(line);
    btn.disabled = false;
  };
}

function closeUpdateModal() {
  document.getElementById('update-modal').style.display = 'none';
}

// ── Reinstall a saved server ──────────────────────────────────────────────────

async function reinstallServer(serverId, protocolName) {
  if (!confirm(`♻️ ПЕРЕУСТАНОВКА ${protocolName}\n\nСтарая установка будет снесена, затем поставлена заново начисто. Все текущие клиенты будут пересозданы.\n\nПродолжить?`)) return;

  const modal = document.getElementById('update-modal');
  const status = document.getElementById('update-status');
  const actions = document.getElementById('update-actions');
  const log = document.getElementById('update-log');
  document.getElementById('update-modal-title').textContent = `♻️ Переустановка ${protocolName}`;
  status.innerHTML = '';
  actions.innerHTML = '';
  log.style.display = 'block';
  log.innerHTML = '<div class="update-line">⏳ Запускаю переустановку...</div>';
  modal.style.display = 'flex';

  let sessionId;
  try {
    const res = await fetch(`/api/servers/${serverId}/reinstall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clean: true }),
    });
    const data = await res.json();
    if (data.error) {
      log.innerHTML += `<div class="update-line error">❌ ${data.error}</div>`;
      return;
    }
    sessionId = data.session_id;
  } catch (e) {
    log.innerHTML += `<div class="update-line error">❌ ${e.message}</div>`;
    return;
  }

  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${wsProto}://${location.host}/ws/${sessionId}`);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'log') {
      const m = msg.message;
      let cls = '';
      if (m.includes('✅') || m.includes('🎉')) cls = 'ok';
      else if (m.includes('❌')) cls = 'error';
      else if (m.includes('⚠️') || m.includes('⏱️')) cls = 'warn';
      const line = document.createElement('div');
      line.className = `update-line ${cls}`;
      line.textContent = m;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
    } else if (msg.type === 'done') {
      const line = document.createElement('div');
      line.className = `update-line ${msg.status === 'done' ? 'ok' : 'error'}`;
      line.textContent = msg.status === 'done'
        ? '✅ Переустановка завершена успешно.'
        : `❌ ${msg.error || 'Ошибка переустановки'}`;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
      actions.innerHTML = `<button class="btn" onclick="closeUpdateModal(); switchTab('manage')">Закрыть</button>`;
    }
  };
  ws.onerror = () => {
    log.innerHTML += '<div class="update-line error">⚠️ WebSocket ошибка</div>';
  };
}

loadVersion();
