document.addEventListener('DOMContentLoaded', () => {
  const tgInput = document.getElementById('recoveryTelegramId');
  const tgResult = document.getElementById('recovery-result');
  const tgBtn = document.getElementById('btnRecoverTelegram');

  const vpnEu1Input = document.getElementById('vpnRecoveryTelegramIdEu1');
  const vpnEu1Result = document.getElementById('vpn-recovery-result-eu1');
  const vpnEu1Btn = document.getElementById('btnRecoverVpnEu1');
  const vpnEu1AndroidSafe = document.getElementById('vpnRecoveryAndroidSafeEu1');

  const vpnEu2Input = document.getElementById('vpnRecoveryTelegramIdEu2');
  const vpnEu2Result = document.getElementById('vpn-recovery-result-eu2');
  const vpnEu2Btn = document.getElementById('btnRecoverVpnEu2');
  const vpnEu2AndroidSafe = document.getElementById('vpnRecoveryAndroidSafeEu2');

  const hasAnyRecovery =
    !!(tgInput && tgBtn) ||
    !!(vpnEu1Input && vpnEu1Btn) ||
    !!(vpnEu2Input && vpnEu2Btn);
  if (!hasAnyRecovery) return;

  const savedId = localStorage.getItem('vpn_recovery_telegram_id');
  if (savedId) {
    if (tgInput) tgInput.value = savedId;
    if (vpnEu1Input) vpnEu1Input.value = savedId;
    if (vpnEu2Input) vpnEu2Input.value = savedId;
  }

  function mirrorVpnIds(from, to) {
    if (!from || !to) return;
    from.addEventListener('input', () => {
      to.value = from.value;
    });
  }
  mirrorVpnIds(vpnEu1Input, vpnEu2Input);
  mirrorVpnIds(vpnEu2Input, vpnEu1Input);

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

  function bindVpnRecovery(serverId, inputEl, btnEl, resultEl, androidSafeEl) {
    if (!inputEl || !btnEl || !resultEl || !androidSafeEl) return;

    btnEl.addEventListener('click', async () => {
      const telegramId = (inputEl.value || '').trim();
      const androidSafe = !!androidSafeEl.checked;

      if (!telegramId) {
        setResult(resultEl, 'Введите Telegram ID.', true);
        return;
      }

      btnEl.disabled = true;
      setResult(resultEl, 'Генерация VPN-конфига (' + serverId.toUpperCase() + ')...', false);

      try {
        localStorage.setItem('vpn_recovery_telegram_id', telegramId);

        const resp = await fetch('/api/recovery/vpn', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            telegram_id: telegramId,
            android_safe: androidSafe,
            server_id: serverId,
          }),
        });

        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setResult(resultEl, 'Ошибка: ' + (data.error || resp.statusText || 'unknown'), true);
          return;
        }

        const filename = data.filename || 'vpn.conf';
        const cfg = data.config || '';
        if (!cfg) {
          setResult(resultEl, 'Сервер не вернул конфиг.', true);
          return;
        }

        setResult(resultEl, 'Готово. Скачивайте файл: ' + filename, false);

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
        setResult(resultEl, 'Ошибка сети: ' + (err && err.message ? err.message : String(err)), true);
      } finally {
        btnEl.disabled = false;
      }
    });
  }

  bindVpnRecovery('eu1', vpnEu1Input, vpnEu1Btn, vpnEu1Result, vpnEu1AndroidSafe);
  bindVpnRecovery('eu2', vpnEu2Input, vpnEu2Btn, vpnEu2Result, vpnEu2AndroidSafe);
});
