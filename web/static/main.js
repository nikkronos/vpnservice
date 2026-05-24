function fmt(bytes) {
    if (!bytes) return '—';
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' ГБ';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' МБ';
    if (bytes >= 1024) return (bytes / 1024).toFixed(0) + ' КБ';
    return bytes + ' Б';
}

function relDate(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr.replace(' ', 'T') + 'Z');
    const now = new Date();
    const diffDays = Math.floor((now - d) / 86400000);
    if (diffDays === 0) return 'сегодня';
    if (diffDays === 1) return 'вчера';
    return `${diffDays} дн назад`;
}

function relTime(ts) {
    if (!ts) return '<span class="hs-never">никогда</span>';
    const diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 0) return '—';
    if (diff < 180) return '<span class="hs-now">● сейчас</span>';
    if (diff < 3600) return `<span class="hs-recent">${Math.floor(diff / 60)} мин назад</span>`;
    if (diff < 86400) return `<span class="hs-today">${Math.floor(diff / 3600)} ч назад</span>`;
    return `<span class="hs-old">${Math.floor(diff / 86400)} дн назад</span>`;
}

function setDot(id, status) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = 'status-dot ' + (status === 'online' ? 'dot-on' : status === 'offline' ? 'dot-off' : 'dot-unknown');
}

async function loadServices() {
    try {
        const r = await fetch('/api/services', { cache: 'no-store' });
        const data = await r.json();
        for (const s of data.services || []) {
            if (s.service.startsWith('Amnezia')) setDot('dot-awg', s.status);
            if (s.service.startsWith('VLESS')) setDot('dot-vless', s.status);
        }
    } catch (e) {
        setDot('dot-awg', 'unknown');
        setDot('dot-vless', 'unknown');
    }
}

async function loadStats() {
    try {
        const r = await fetch('/api/stats', { cache: 'no-store' });
        const d = await r.json();
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = (val === null || val === undefined) ? '—' : val;
        };
        set('stat-users', d.active_users);
        set('stat-peers', d.active_peers);
        set('act-24h', d.active_24h);
        set('act-7d', d.active_7d);
        set('act-30d', d.active_30d);
        set('act-email', d.email_verified_users);
        set('act-proxy', d.proxy_requests_30d);
        const total = (d.total_rx_bytes || 0) + (d.total_tx_bytes || 0);
        set('act-traffic', total > 0 ? fmt(total) : '—');
    } catch (e) {}
}

async function loadTraffic() {
    const tbody = document.getElementById('users-tbody');
    const note = document.getElementById('traffic-note');
    if (!tbody) return;
    try {
        const r = await fetch('/api/traffic', { cache: 'no-store' });
        const data = await r.json();
        if (data.error) {
            tbody.innerHTML = `<tr><td colspan="8" class="err">Ошибка: ${data.error}</td></tr>`;
            return;
        }
        if (note && data.last_update) {
            const d = new Date(data.last_update);
            note.textContent = 'обновлено ' + d.toLocaleTimeString('ru-RU');
        }
        const users = data.users || [];
        if (!users.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="loading">Нет данных</td></tr>';
            return;
        }
        const platformIcon = p => ({ ios: '🍎', android: '🤖', pc: '💻' }[p] || '💻');
        tbody.innerHTML = users.map(u => {
            const name = u.username ? `@${u.username}` : `ID ${u.telegram_id}`;
            const ip = (u.wg_ip || '').replace('/32', '').replace('/24', '');
            const total = u.rx_bytes + u.tx_bytes;
            const rowClass = total > 0 ? '' : ' class="row-idle"';
            const traffic = total > 0 ? `${fmt(u.rx_bytes)} / ${fmt(u.tx_bytes)}` : '—';
            const totalAll = u.total_bytes ? fmt(u.total_bytes) : '—';
            const platform = u.platform ? `${platformIcon(u.platform)} ${u.platform}` : '—';
            const proxy = u.proxy_requested_at
                ? `<span class="hs-recent" title="${u.proxy_requested_at}">✓ ${relDate(u.proxy_requested_at)}</span>`
                : '<span class="hs-never">—</span>';
            const email = u.email_verified
                ? '<span class="hs-now" title="Авторизован по email">✓</span>'
                : '<span class="hs-never">—</span>';
            return `<tr${rowClass}>
                <td class="td-name">${name}</td>
                <td class="td-email">${email}</td>
                <td class="td-ip">${ip || '—'}</td>
                <td class="td-traffic">${traffic}</td>
                <td class="td-total">${totalAll}</td>
                <td class="td-platform">${platform}</td>
                <td class="td-hs">${relTime(u.last_handshake)}</td>
                <td class="td-proxy">${proxy}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="8" class="err">Ошибка загрузки</td></tr>`;
    }
}

function updateClock() {
    const el = document.getElementById('update-time');
    if (el) el.textContent = new Date().toLocaleTimeString('ru-RU');
}

async function loadAll() {
    const btn = document.getElementById('refresh-btn');
    if (btn) { btn.textContent = '↺'; btn.disabled = true; }
    updateClock();
    await Promise.all([loadServices(), loadStats(), loadTraffic()]);
    if (btn) { btn.textContent = '↺ Обновить'; btn.disabled = false; }
}

document.addEventListener('DOMContentLoaded', loadAll);
setInterval(loadAll, 60 * 1000);
