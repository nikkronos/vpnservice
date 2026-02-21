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
    updateLastUpdate();
}, 30000);

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    updateServersStatus();
    updateServicesStatus();
    updateLastUpdate();
});
