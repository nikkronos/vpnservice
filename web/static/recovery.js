document.addEventListener('DOMContentLoaded', () => {
  const tgInput = document.getElementById('recoveryTelegramId');
  const tgResult = document.getElementById('recovery-result');
  const tgBtn = document.getElementById('btnRecoverTelegram');

  const vpnInput = document.getElementById('vpnRecoveryTelegramId');
  const vpnResult = document.getElementById('vpn-recovery-result');
  const vpnBtn = document.getElementById('btnRecoverVpn');
  const vpnAndroidSafe = document.getElementById('vpnRecoveryAndroidSafe');

  // Nothing to do on pages without recovery widgets.
  const hasAnyRecovery = !!(tgInput && tgBtn) || !!(vpnInput && vpnBtn);
  if (!hasAnyRecovery) return;

  const savedId = localStorage.getItem('vpn_recovery_telegram_id');
  if (savedId) {
    if (tgInput) tgInput.value = savedId;
    if (vpnInput) vpnInput.value = savedId;
  }

  function setResult(el, text, isError) {
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? '#b00020' : '#1b5e20';
  }

  if (tgInput && tgBtn && tgResult) {
    tgBtn.addEventListener('click', async () => {
      const telegramId = (tgInput.value || '').trim();
      if (!telegramId) {
        setResult(tgResult, 'Введите Telegram ID.', true);
        return;
      }

      tgBtn.disabled = true;
      setResult(tgResult, 'Восстановление Telegram запущено...', false);

      try {
        localStorage.setItem('vpn_recovery_telegram_id', telegramId);

        const resp = await fetch('/api/recovery/telegram-proxy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ telegram_id: telegramId }),
        });

        const data = await resp.json().catch(() => ({}));
        const link = data.mtproto_proxy_link || '';
        const hint = data.hint || '';

        if (!resp.ok) {
          let msg = 'Ошибка: ' + (data.error || resp.statusText || 'unknown');
          if (link) {
            msg +=
              '\n\nАктуальная ссылка на прокси (как в боте /proxy):\n' +
              link +
              (hint ? '\n\n' + hint : '');
          }
          setResult(tgResult, msg, !link);
          return;
        }

        let okText = 'Готово. Контейнер прокси перезапущен.';
        if (link) {
          okText +=
            '\n\nСсылка на MTProxy (та же, что по команде /proxy в боте):\n' +
            link +
            (hint ? '\n\n' + hint : '');
        }
        setResult(tgResult, okText, false);
      } catch (err) {
        setResult(tgResult, 'Ошибка сети: ' + (err && err.message ? err.message : String(err)), true);
      } finally {
        tgBtn.disabled = false;
      }
    });
  }

  if (vpnInput && vpnBtn && vpnResult && vpnAndroidSafe) {
    vpnBtn.addEventListener('click', async () => {
      const telegramId = (vpnInput.value || '').trim();
      const androidSafe = !!vpnAndroidSafe.checked;

      if (!telegramId) {
        setResult(vpnResult, 'Введите Telegram ID.', true);
        return;
      }

      vpnBtn.disabled = true;
      setResult(vpnResult, 'Генерация VPN-конфига...', false);

      try {
        localStorage.setItem('vpn_recovery_telegram_id', telegramId);

        const resp = await fetch('/api/recovery/vpn', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ telegram_id: telegramId, android_safe: androidSafe }),
        });

        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setResult(vpnResult, 'Ошибка: ' + (data.error || resp.statusText || 'unknown'), true);
          return;
        }

        const filename = data.filename || 'vpn.conf';
        const cfg = data.config || '';
        if (!cfg) {
          setResult(vpnResult, 'Сервер не вернул конфиг.', true);
          return;
        }

        setResult(vpnResult, 'Готово. Скачивайте файл: ' + filename, false);

        const blob = new Blob([cfg], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        setResult(vpnResult, 'Ошибка сети: ' + (err && err.message ? err.message : String(err)), true);
      } finally {
        vpnBtn.disabled = false;
      }
    });
  }
});

