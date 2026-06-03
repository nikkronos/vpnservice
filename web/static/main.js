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

function _dotCls(s) {
    return 'status-dot ' + (s === 'online' ? 'dot-on' : s === 'offline' ? 'dot-off' : 'dot-unknown');
}
function _esc(s) {
    return String(s == null ? '' : s).replace(/[<>"&]/g, c => ({ '<': '&lt;', '>': '&gt;', '"': '&quot;', '&': '&amp;' }[c]));
}

async function loadServices() {
    const cont = document.getElementById('status-services');
    if (!cont) return;
    try {
        const r = await fetch('/api/services', { cache: 'no-store' });
        const data = await r.json();
        const items = (data.services || []).map(s =>
            `<div class="status-item" title="${_esc(s.note)}">` +
            `<span class="${_dotCls(s.status)}"></span><span>${_esc(s.service)}</span></div>`
        );
        const h = data.health || {};
        if (h.stale) {
            const mins = h.checked_ago_sec ? Math.floor(h.checked_ago_sec / 60) : '?';
            items.push(`<div class="status-item" title="health-check не обновлялся — статусы могут быть неактуальны" style="color:#e0a800">⚠ health-check ${mins} мин назад</div>`);
        }
        cont.innerHTML = items.join('');
    } catch (e) {
        cont.innerHTML = '<div class="status-item"><span class="status-dot dot-unknown"></span><span>сервисы: ошибка</span></div>';
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
        // act-traffic не ставим здесь — он считается из total_bytes в loadTraffic
        // (резет-aware lifetime, см. SESSION_SUMMARY_2026-05-29 фикс #6).

        // VLESS трафик (per-server summary, scripts/vless_summary_accounting.py).
        const vlessTotal = d.vless_total_bytes || 0;
        const vlessEl = document.getElementById('act-vless-traffic');
        if (vlessEl) vlessEl.textContent = vlessTotal > 0 ? fmt(vlessTotal) : '—';
        // В подпись добавим разбивку по серверам если данные есть.
        const vlessLabel = document.getElementById('act-vless-label');
        if (vlessLabel && d.vless_by_server) {
            const parts = Object.entries(d.vless_by_server)
                .filter(([, v]) => v > 0)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([srv, v]) => `${srv}: ${fmt(v)}`);
            if (parts.length) {
                vlessLabel.title = 'Per-inbound через Xray stats. По серверам: ' + parts.join(' · ');
            }
        }
    } catch (e) {}
}

const STATUS_META = {
    active:     { label: 'активен',    cls: 'st-active' },
    idle:       { label: 'тихий',      cls: 'st-idle' },
    onboarding: { label: 'онбординг',  cls: 'st-onb' },
    no_config:  { label: 'без конфига', cls: 'st-noconf' },
    expired:    { label: 'истёк',      cls: 'st-expired' },
};
const STATUS_PRIORITY = {
    active: 0, idle: 1, onboarding: 2, no_config: 3, expired: 4,
};

function renderStatus(u) {
    const meta = STATUS_META[u.status] || { label: u.status || '—', cls: 'st-unknown' };
    let suffix = '';
    if (u.is_grandfather) {
        suffix = ' · ∞';
    } else if (typeof u.days_left === 'number') {
        suffix = u.days_left >= 0 ? ` · ${u.days_left}д` : ` · −${Math.abs(u.days_left)}д`;
    }
    return `<span class="status-badge ${meta.cls}" title="${meta.label}${suffix}">${meta.label}${suffix}</span>`;
}

// ── Сортировка ─────────────────────────────────────────────────────────
// Глобальное состояние; null = серверная сортировка (priority группа → handshake desc).
let _sortState = { key: null, dir: 'asc' };
let _lastUsers = [];

function _sqliteTs(s) {
    if (!s) return 0;
    // SQLite-формат "YYYY-MM-DD HH:MM:SS" → unix; не критично что timezone.
    const t = Date.parse(s.replace(' ', 'T') + 'Z') / 1000;
    return isFinite(t) ? t : 0;
}

function _keyFn(key) {
    switch (key) {
        case 'name':    return u => (u.username || `id${u.telegram_id}`).toLowerCase();
        case 'email':   return u => u.email_verified ? 1 : 0;
        case 'status':  return u => STATUS_PRIORITY[u.status] ?? 9;
        case 'traffic': return u => (u.rx_bytes || 0) + (u.tx_bytes || 0);
        case 'total':   return u => u.total_bytes || 0;
        case 'device':  return u => u.platform || '';
        case 'last':    return u => u.last_handshake || 0;
        case 'vless':   return u => _sqliteTs(u.vless_requested_at);
        case 'proxy':   return u => _sqliteTs(u.proxy_requested_at);
        default:        return () => 0;
    }
}

function _sortUsers(users) {
    if (_sortState.key === null || _sortState.key === 'num') return users;
    const k = _keyFn(_sortState.key);
    const sign = _sortState.dir === 'asc' ? 1 : -1;
    return [...users].sort((a, b) => {
        const ka = k(a), kb = k(b);
        if (ka < kb) return -1 * sign;
        if (ka > kb) return  1 * sign;
        return 0;
    });
}

function _updateSortIndicators() {
    document.querySelectorAll('th.th-sort').forEach(th => {
        const key = th.dataset.sort;
        th.classList.remove('sort-asc', 'sort-desc');
        if (_sortState.key === key) {
            th.classList.add(_sortState.dir === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });
}

function _onHeaderClick(ev) {
    const th = ev.currentTarget;
    const key = th.dataset.sort;
    if (!key || key === 'num') {
        // Клик по «№» сбрасывает к серверной сортировке.
        _sortState = { key: null, dir: 'asc' };
    } else if (_sortState.key === key) {
        _sortState.dir = _sortState.dir === 'asc' ? 'desc' : 'asc';
    } else {
        _sortState = { key, dir: 'asc' };
        // Для числовых колонок логичнее стартовать с desc (большие сверху).
        if (['traffic', 'total', 'last', 'vless', 'proxy', 'email'].includes(key)) {
            _sortState.dir = 'desc';
        }
    }
    _renderUsers(_lastUsers);
}

function _bindSortHeaders() {
    document.querySelectorAll('th.th-sort').forEach(th => {
        th.addEventListener('click', _onHeaderClick);
    });
}

function _renderUsers(users) {
    const tbody = document.getElementById('users-tbody');
    if (!tbody) return;
    const sorted = _sortUsers(users);
    const platformIcon = p => ({ ios: '🍎', android: '🤖', pc: '💻' }[p] || '💻');

    tbody.innerHTML = sorted.map((u, idx) => {
        const name = u.username ? `@${u.username}` : `ID ${u.telegram_id}`;
        const sessionBytes = (u.rx_bytes || 0) + (u.tx_bytes || 0);
        const rowClasses = [];
        if (!u.has_peer) rowClasses.push('row-no-peer');
        else if (sessionBytes === 0) rowClasses.push('row-idle');
        const rowAttr = rowClasses.length ? ` class="${rowClasses.join(' ')}"` : '';
        const traffic = sessionBytes > 0 ? `${fmt(u.rx_bytes)} / ${fmt(u.tx_bytes)}` : '—';
        const totalAll = u.total_bytes ? fmt(u.total_bytes) : '—';
        const platform = u.platform ? `${platformIcon(u.platform)} ${u.platform}` : '—';
        const proxy = u.proxy_requested_at
            ? `<span class="hs-recent" title="${u.proxy_requested_at}">✓ ${relDate(u.proxy_requested_at)}</span>`
            : '<span class="hs-never">—</span>';
        // VLESS: рендер аналогично прокси. Свежий hit (за 24 ч) — ярче.
        let vlessHtml = '<span class="hs-never">—</span>';
        if (u.vless_requested_at) {
            const ts = _sqliteTs(u.vless_requested_at);
            const diff = Math.floor(Date.now() / 1000) - ts;
            const cls = diff < 86400 ? 'hs-now' : (diff < 7 * 86400 ? 'hs-recent' : 'hs-old');
            vlessHtml = `<span class="${cls}" title="${u.vless_requested_at}">✓ ${relDate(u.vless_requested_at)}</span>`;
        }
        const email = u.email_verified
            ? '<span class="hs-now" title="Авторизован по email">✓</span>'
            : '<span class="hs-never">—</span>';
        return `<tr${rowAttr}>
            <td class="td-num">${idx + 1}</td>
            <td class="td-name">${name}</td>
            <td class="td-email">${email}</td>
            <td class="td-status">${renderStatus(u)}</td>
            <td class="td-traffic">${traffic}</td>
            <td class="td-total">${totalAll}</td>
            <td class="td-platform">${platform}</td>
            <td class="td-hs">${relTime(u.last_handshake)}</td>
            <td class="td-vless">${vlessHtml}</td>
            <td class="td-proxy">${proxy}</td>
        </tr>`;
    }).join('');

    _updateSortIndicators();

    // Общий трафик в шапке считаем как сумму lifetime total_bytes.
    // Раньше /api/stats суммировал только rx+tx текущей AWG-сессии (resetable
    // при рестарте контейнера), что давало в 10+ раз меньше реальности.
    const totalLifetime = users.reduce((s, u) => s + (u.total_bytes || 0), 0);
    const act = document.getElementById('act-traffic');
    if (act) act.textContent = totalLifetime > 0 ? fmt(totalLifetime) : '—';
}

async function loadTraffic() {
    const tbody = document.getElementById('users-tbody');
    const note = document.getElementById('traffic-note');
    if (!tbody) return;
    try {
        const r = await fetch('/api/traffic', { cache: 'no-store' });
        const data = await r.json();
        if (data.error) {
            tbody.innerHTML = `<tr><td colspan="10" class="err">Ошибка: ${data.error}</td></tr>`;
            return;
        }
        if (note && data.last_update) {
            const d = new Date(data.last_update);
            note.textContent = 'обновлено ' + d.toLocaleTimeString('ru-RU');
        }
        const users = data.users || [];
        if (!users.length) {
            tbody.innerHTML = '<tr><td colspan="10" class="loading">Нет данных</td></tr>';
            return;
        }
        _lastUsers = users;
        _renderUsers(users);
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="10" class="err">Ошибка загрузки</td></tr>`;
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

document.addEventListener('DOMContentLoaded', () => {
    _bindSortHeaders();
    loadAll();
});
setInterval(loadAll, 60 * 1000);
