const state = { generatedCodes: [], currentPage: 'dashboard' };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[character]);
}

function formatDate(value) {
  if (!value) return '--';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function planName(value) {
  return ({ monthly: '月卡', quarterly: '季卡', yearly: '年卡', permanent: '永久', custom: '自定义' })[value] || value;
}

function statusName(value) {
  return ({ unused: '未使用', used: '已使用', disabled: '已禁用', void: '已作废', active: '有效', expired: '已到期', revoked: '已解绑' })[value] || value;
}

function toast(message, error = false) {
  const node = $('#toast');
  node.textContent = message;
  node.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.className = 'toast', 2800);
}

async function bridge(method, ...args) {
  const result = await window.pywebview.api[method](...args);
  if (!result.ok) throw new Error(result.error || '操作失败');
  return result.data;
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = '处理中...';
  } else if (button.dataset.label) {
    button.textContent = button.dataset.label;
  }
}

async function login(event) {
  event.preventDefault();
  const button = event.submitter;
  const error = $('#login-error');
  error.textContent = '';
  setBusy(button, true);
  try {
    const serverUrl = $('#server-url').value.trim();
    await bridge('set_server', serverUrl);
    await bridge('login', $('#username').value.trim(), $('#password').value);
    $('#password').value = '';
    $('#server-label').textContent = serverUrl;
    $('#login-view').classList.add('hidden');
    $('#app-view').classList.remove('hidden');
    await loadDashboard();
  } catch (exception) {
    error.textContent = exception.message;
  } finally {
    setBusy(button, false);
  }
}

async function showPage(page) {
  state.currentPage = page;
  $$('.nav-item').forEach(node => node.classList.toggle('active', node.dataset.page === page));
  $$('.page').forEach(node => node.classList.toggle('active', node.id === `page-${page}`));
  try {
    if (page === 'dashboard') await loadDashboard();
    if (page === 'cards') await loadCards();
    if (page === 'licenses') await loadLicenses();
    if (page === 'logs') await loadLogs();
  } catch (exception) { toast(exception.message, true); }
}

async function loadDashboard() {
  const data = await bridge('stats');
  $('#stat-unused').textContent = data.unused_cards;
  $('#stat-active').textContent = data.active_licenses;
  $('#stat-expiring').textContent = data.expiring_licenses;
  $('#stat-devices').textContent = data.active_devices;
}

async function generateCards(event) {
  event.preventDefault();
  const button = event.submitter;
  const plan = $('#plan-type').value;
  const payload = {
    plan_type: plan,
    count: Number($('#card-count').value),
    device_limit: Number($('#device-limit').value),
    offline_grace_hours: Number($('#grace-hours').value),
    channel: $('#channel').value.trim() || null,
    notes: $('#card-notes').value.trim() || null
  };
  if (plan === 'custom') payload.duration_days = Number($('#duration-days').value);
  setBusy(button, true);
  try {
    const data = await bridge('generate_cards', payload);
    state.generatedCodes = data.codes;
    $('#generated-codes').value = data.codes.join('\n');
    $('#batch-label').textContent = `批次 ${data.batch_id} · ${data.codes.length} 张`;
    $('#generated-panel').classList.remove('hidden');
    toast('卡密已生成，请立即保存明文');
  } catch (exception) { toast(exception.message, true); }
  finally { setBusy(button, false); }
}

async function loadCards() {
  const data = await bridge('cards', $('#card-status').value, $('#card-search').value.trim());
  const body = $('#cards-body');
  if (!data.items.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">没有符合条件的卡密</td></tr>';
    return;
  }
  body.innerHTML = data.items.map(card => `<tr>
    <td><code>${escapeHtml(card.code_hint)}</code></td>
    <td>${escapeHtml(planName(card.plan_type))}</td>
    <td><span class="badge ${escapeHtml(card.status)}">${escapeHtml(statusName(card.status))}</span></td>
    <td>${escapeHtml(card.channel || '--')}</td><td>${formatDate(card.created_at)}</td><td>${formatDate(card.used_at)}</td>
    <td><div class="row-actions">${card.status === 'unused' ? `<button data-card-action="disable" data-id="${card.id}">禁用</button><button class="danger" data-card-action="void" data-id="${card.id}">作废</button>` : ''}${card.status === 'disabled' ? `<button data-card-action="enable" data-id="${card.id}">恢复</button>` : ''}</div></td>
  </tr>`).join('');
}

async function cardAction(button) {
  const action = button.dataset.cardAction;
  const labels = { disable: '禁用', enable: '恢复', void: '作废' };
  if (!confirm(`确认${labels[action]}这张卡密？`)) return;
  setBusy(button, true);
  try {
    await bridge('update_card', button.dataset.id, action);
    await loadCards();
    toast(`卡密已${labels[action]}`);
  } catch (exception) { toast(exception.message, true); }
}

async function loadLicenses() {
  const data = await bridge('licenses', $('#license-status').value, $('#license-search').value.trim());
  const list = $('#licenses-list');
  if (!data.items.length) {
    list.innerHTML = '<div class="panel empty">没有符合条件的授权</div>';
    return;
  }
  list.innerHTML = data.items.map(item => `<article class="license-item">
    <div class="license-head">
      <div><span class="field-caption">授权 ID</span><span class="license-id">${escapeHtml(item.id)}</span></div>
      <div><span class="field-caption">状态</span><span class="badge ${escapeHtml(item.status)}">${escapeHtml(statusName(item.status))}</span></div>
      <div><span class="field-caption">套餐</span>${escapeHtml(planName(item.plan_type))}</div>
      <div><span class="field-caption">到期时间</span>${formatDate(item.expires_at)}</div>
      <div class="row-actions">
        <button data-license-action="extend" data-id="${item.id}">延期</button>
        ${item.status === 'disabled' ? `<button data-license-action="enable" data-id="${item.id}">恢复</button>` : `<button class="danger" data-license-action="disable" data-id="${item.id}">禁用</button>`}
        <button data-license-action="set_permanent" data-id="${item.id}">设为永久</button>
        <button data-license-action="rebind" data-id="${item.id}">生成换机码</button>
      </div>
    </div>
    <div class="devices">${item.devices.length ? item.devices.map(device => `<div class="device-row">
      <code title="${escapeHtml(device.machine_hash)}">${escapeHtml(device.machine_hash)}</code>
      <span>${escapeHtml(device.label || '未命名设备')}</span>
      <span class="badge ${escapeHtml(device.status)}">${escapeHtml(statusName(device.status))}</span>
      ${device.status === 'active' ? `<button class="danger" data-unbind="${device.id}">解绑</button>` : '<span></span>'}
    </div>`).join('') : '<div class="empty">暂无设备</div>'}</div>
  </article>`).join('');
}

function openLicenseAction(button) {
  const action = button.dataset.licenseAction;
  if (action === 'rebind') return createRebindCode(button.dataset.id, button);
  const names = { extend: '延长授权', disable: '禁用授权', enable: '恢复授权', set_permanent: '设为永久授权' };
  $('#action-title').textContent = names[action];
  $('#action-license-id').value = button.dataset.id;
  $('#action-name').value = action;
  $('#action-days-field').classList.toggle('hidden', action !== 'extend');
  $('#action-note').value = '';
  $('#action-dialog').showModal();
}

async function submitLicenseAction(event) {
  event.preventDefault();
  const action = $('#action-name').value;
  const days = action === 'extend' ? Number($('#action-days').value) : null;
  setBusy($('#action-confirm'), true);
  try {
    await bridge('license_action', $('#action-license-id').value, action, days, $('#action-note').value.trim());
    $('#action-dialog').close();
    await loadLicenses();
    toast('授权已更新');
  } catch (exception) { toast(exception.message, true); }
  finally { setBusy($('#action-confirm'), false); }
}

async function createRebindCode(licenseId, button) {
  if (!confirm('换机码使用后会撤销旧设备。确认生成 24 小时有效的一次性换机码？')) return;
  setBusy(button, true);
  try {
    const data = await bridge('create_rebind_code', licenseId, '管理员生成换机码');
    await bridge('copy_text', data.code);
    alert(`换机码已生成并复制：\n\n${data.code}\n\n有效期至：${formatDate(data.expires_at)}`);
  } catch (exception) { toast(exception.message, true); }
  finally { setBusy(button, false); }
}

async function unbindDevice(button) {
  if (!confirm('解绑后该设备会立即失去授权，确认继续？')) return;
  setBusy(button, true);
  try {
    await bridge('unbind_device', button.dataset.unbind);
    await loadLicenses();
    toast('设备已解绑');
  } catch (exception) { toast(exception.message, true); }
}

async function loadLogs() {
  const data = await bridge('audit_logs');
  $('#logs-body').innerHTML = data.items.length ? data.items.map(log => `<tr>
    <td>${formatDate(log.created_at)}</td><td>${escapeHtml(log.actor_type)} · ${escapeHtml(log.actor_id || '--')}</td>
    <td>${escapeHtml(log.action)}</td><td>${escapeHtml(log.target_type || '--')} · ${escapeHtml(log.target_id || '--')}</td>
    <td>${escapeHtml(log.ip_address || '--')}</td><td title="${escapeHtml(log.detail || '')}">${escapeHtml(log.detail || '--')}</td>
  </tr>`).join('') : '<tr><td colspan="6" class="empty">暂无日志</td></tr>';
}

async function changePassword(event) {
  event.preventDefault();
  const button = event.submitter;
  const currentPassword = $('#current-password').value;
  const newPassword = $('#new-password').value;
  if (newPassword !== $('#confirm-password').value) {
    toast('两次输入的新密码不一致', true);
    return;
  }
  setBusy(button, true);
  try {
    await bridge('change_password', currentPassword, newPassword);
    event.target.reset();
    toast('管理员密码已修改');
  } catch (exception) { toast(exception.message, true); }
  finally { setBusy(button, false); }
}

function bindEvents() {
  $('#login-form').addEventListener('submit', login);
  $('#generate-form').addEventListener('submit', generateCards);
  $('#password-form').addEventListener('submit', changePassword);
  $('#plan-type').addEventListener('change', event => $('#custom-days-field').classList.toggle('hidden', event.target.value !== 'custom'));
  $('#navigation').addEventListener('click', event => { const button = event.target.closest('[data-page]'); if (button) showPage(button.dataset.page); });
  $('#refresh-cards').addEventListener('click', () => loadCards().catch(error => toast(error.message, true)));
  $('#refresh-licenses').addEventListener('click', () => loadLicenses().catch(error => toast(error.message, true)));
  $('[data-refresh="dashboard"]').addEventListener('click', () => loadDashboard().catch(error => toast(error.message, true)));
  $('[data-refresh="logs"]').addEventListener('click', () => loadLogs().catch(error => toast(error.message, true)));
  $('#cards-body').addEventListener('click', event => { const button = event.target.closest('[data-card-action]'); if (button) cardAction(button); });
  $('#licenses-list').addEventListener('click', event => {
    const action = event.target.closest('[data-license-action]');
    const unbind = event.target.closest('[data-unbind]');
    if (action) openLicenseAction(action);
    if (unbind) unbindDevice(unbind);
  });
  $('#action-form').addEventListener('submit', submitLicenseAction);
  $('#copy-codes').addEventListener('click', async () => { try { await bridge('copy_text', state.generatedCodes.join('\n')); toast('已复制全部卡密'); } catch (error) { toast(error.message, true); } });
  $('#export-codes').addEventListener('click', async () => { try { const data = await bridge('export_codes', state.generatedCodes); if (!data.cancelled) toast(`已导出到 ${data.path}`); } catch (error) { toast(error.message, true); } });
  $('#logout-button').addEventListener('click', async () => { await bridge('logout'); $('#app-view').classList.add('hidden'); $('#login-view').classList.remove('hidden'); });
}

window.addEventListener('pywebviewready', async () => {
  bindEvents();
  try {
    const config = await bridge('get_config');
    $('#server-url').value = config.server_url || '';
  } catch (exception) { toast(exception.message, true); }
});
