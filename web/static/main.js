// Обновление статуса серверов
async function updateServersStatus() {
    try {
        const response = await fetch('/api/servers');
        const servers = await response.json();
        
        const serversList = document.getElementById('servers-list');
        serversList.innerHTML = '';
        
        for (const [serverId, server] of Object.entries(servers)) {
            const card = document.createElement('div');
            card.className = `server-card ${server.status}`;
            
            const statusBadge = server.status === 'online' ? '🟢 Онлайн' : 
                               server.status === 'offline' ? '🔴 Офлайн' : 
                               '⚠️ Ошибка';
            
            const pingInfo = server.ping_ms ? `Пинг: ${server.ping_ms.toFixed(0)} мс` : '';
            
            card.innerHTML = `
                <div class="server-info">
                    <h3>${server.name}</h3>
                    <p>${server.description || ''}</p>
                    <p><small>${server.endpoint || ''} ${pingInfo}</small></p>
                </div>
                <div class="server-status">
                    <span class="status-badge ${server.status}">${statusBadge}</span>
                </div>
            `;
            
            serversList.appendChild(card);
        }
    } catch (error) {
        console.error('Ошибка загрузки статуса серверов:', error);
        document.getElementById('servers-list').innerHTML = 
            '<p style="color: red;">Ошибка загрузки статуса серверов</p>';
    }
}

// Обновление статуса сервисов (WireGuard, AmneziaWG, Shadowsocks, MTProto)
async function updateServicesStatus() {
    const el = document.getElementById('services-list');
    if (!el) return;
    try {
        const response = await fetch('/api/services');
        const data = await response.json();
        if (data.error) {
            el.innerHTML = '<p style="color: red;">Ошибка: ' + data.error + '</p>';
            return;
        }
        el.innerHTML = '';
        for (const s of data.services || []) {
            const card = document.createElement('div');
            card.className = 'service-card ' + (s.status || 'unknown');
            const statusBadge = s.status === 'online' ? '🟢 Доступен' :
                s.status === 'offline' ? '🔴 Недоступен' : '⚠️ Не проверено';
            card.innerHTML = `
                <div class="service-info">
                    <strong>${s.server_name}</strong> — ${s.service}
                    ${s.note ? '<br><small>' + s.note + '</small>' : ''}
                </div>
                <span class="status-badge ${s.status || 'unknown'}">${statusBadge}</span>
            `;
            el.appendChild(card);
        }
    } catch (err) {
        console.error('Ошибка загрузки сервисов:', err);
        el.innerHTML = '<p style="color: red;">Ошибка загрузки сервисов</p>';
    }
}

// Форматирование байтов в МБ/ГБ
function formatBytes(bytes) {
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' ГБ';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' МБ';
    if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' КБ';
    return bytes + ' Б';
}

// Обновление блока трафика
async function updateTraffic() {
    const el = document.getElementById('traffic-list');
    if (!el) return;
    try {
        const response = await fetch('/api/traffic');
        const data = await response.json();
        if (data.error) {
            el.innerHTML = '<p style="color: red;">Ошибка: ' + data.error + '</p>';
            return;
        }
        const rows = data.rows || [];
        const byUser = data.by_user || [];
        if (rows.length === 0 && byUser.length === 0) {
            el.innerHTML = '<p>Нет данных о трафике (подключите клиентов к нодам).</p>';
            return;
        }
        let html = '';
        if (byUser.length > 0) {
            html += '<table class="users-table traffic-table"><thead><tr><th>Пользователь</th><th>Принято</th><th>Отправлено</th></tr></thead><tbody>';
            for (const u of byUser) {
                const name = (u.username || 'ID ' + u.telegram_id);
                html += '<tr><td>' + name + '</td><td>' + formatBytes(u.rx_bytes) + '</td><td>' + formatBytes(u.tx_bytes) + '</td></tr>';
            }
            html += '</tbody></table>';
        }
        if (rows.length > 0) {
            html += '<p class="traffic-detail-caption"><strong>По устройствам (сервер / IP):</strong></p>';
            html += '<table class="users-table traffic-table"><thead><tr><th>Пользователь</th><th>Сервер</th><th>IP</th><th>Принято</th><th>Отправлено</th></tr></thead><tbody>';
            for (const r of rows) {
                const name = (r.username || 'ID ' + r.telegram_id);
                html += '<tr><td>' + name + '</td><td>' + r.server_id + '</td><td>' + (r.wg_ip || '—') + '</td><td>' + formatBytes(r.rx_bytes) + '</td><td>' + formatBytes(r.tx_bytes) + '</td></tr>';
            }
            html += '</tbody></table>';
        }
        el.innerHTML = html;
    } catch (err) {
        console.error('Ошибка загрузки трафика:', err);
        el.innerHTML = '<p style="color: red;">Ошибка загрузки трафика</p>';
    }
}

// Обновление времени последнего обновления
function updateLastUpdate() {
    const now = new Date();
    const el = document.getElementById('last-update');
    if (el) el.textContent = now.toLocaleString('ru-RU');
}

// Автообновление каждые 30 секунд
setInterval(() => {
    updateServersStatus();
    updateServicesStatus();
    updateTraffic();
    updateLastUpdate();
}, 30000);

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    updateServersStatus();
    updateServicesStatus();
    updateTraffic();
    updateLastUpdate();
});
