document.addEventListener('DOMContentLoaded', () => {
  // ── Email OTP flow ─────────────────────────────────────────────────────────
  (function initEmailFlow() {
    const stepEmail    = document.getElementById('stepEmail');
    const stepOtp      = document.getElementById('stepOtp');
    const stepPlatform = document.getElementById('stepPlatform');
    if (!stepEmail) return;

    const emailInput     = document.getElementById('authEmail');
    const btnSendOtp     = document.getElementById('btnSendOtp');
    const sendOtpResult  = document.getElementById('sendOtpResult');
    const codeInput      = document.getElementById('authCode');
    const btnVerifyOtp   = document.getElementById('btnVerifyOtp');
    const btnResendOtp   = document.getElementById('btnResendOtp');
    const verifyResult   = document.getElementById('verifyOtpResult');
    const platformResult = document.getElementById('platformResult');

    let sessionToken = '';
    let currentEmail = '';
    const vlessLinkWrap = document.getElementById('vlessLinkWrap');
    const vlessLinkCode = document.getElementById('vlessLinkCode');
    const btnCopyVlessLink = document.getElementById('btnCopyVlessLink');

    function setMsg(el, text, isError) {
      if (!el) return;
      el.textContent = text || '';
      el.style.color = isError ? '#b00020' : '#1b5e20';
    }

    function showStep(step) {
      [stepEmail, stepOtp, stepPlatform].forEach(s => { if (s) s.hidden = true; });
      if (step) step.hidden = false;
    }

    // Шаг 1 → Отправить OTP
    async function sendOtp() {
      currentEmail = (emailInput.value || '').trim().toLowerCase();
      if (!currentEmail || !currentEmail.includes('@')) {
        setMsg(sendOtpResult, 'Введи корректный email.', true);
        return;
      }
      btnSendOtp.disabled = true;
      setMsg(sendOtpResult, 'Отправляем код…', false);
      try {
        const resp = await fetch('/api/auth/send-otp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: currentEmail }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setMsg(sendOtpResult, 'Ошибка: ' + (data.error || resp.statusText), true);
          return;
        }
        showStep(stepOtp);
        setMsg(verifyResult, '', false);
        setTimeout(() => codeInput && codeInput.focus(), 100);
      } catch (err) {
        setMsg(sendOtpResult, 'Сетевая ошибка: ' + (err.message || err), true);
      } finally {
        btnSendOtp.disabled = false;
      }
    }

    btnSendOtp && btnSendOtp.addEventListener('click', sendOtp);
    emailInput && emailInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendOtp(); });
    btnResendOtp && btnResendOtp.addEventListener('click', () => {
      showStep(stepEmail);
      setMsg(sendOtpResult, '', false);
    });

    // Шаг 2 → Проверить OTP
    async function verifyOtp() {
      const code = (codeInput.value || '').trim().replace(/\s/g, '');
      if (!code || code.length < 4) {
        setMsg(verifyResult, 'Введи код из письма.', true);
        return;
      }
      btnVerifyOtp.disabled = true;
      setMsg(verifyResult, 'Проверяем код…', false);
      try {
        const resp = await fetch('/api/auth/verify-otp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: currentEmail, code }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setMsg(verifyResult, 'Ошибка: ' + (data.error || resp.statusText), true);
          return;
        }
        sessionToken = data.token || '';
        showStep(stepPlatform);
        if (vlessLinkWrap) vlessLinkWrap.hidden = true;
        setMsg(platformResult, 'Загружаем ссылку…', false);
        fetchVlessLink();
      } catch (err) {
        setMsg(verifyResult, 'Сетевая ошибка: ' + (err.message || err), true);
      } finally {
        btnVerifyOtp.disabled = false;
      }
    }

    btnVerifyOtp && btnVerifyOtp.addEventListener('click', verifyOtp);
    codeInput && codeInput.addEventListener('keydown', e => { if (e.key === 'Enter') verifyOtp(); });

    // Шаг 3 → Получение VLESS-ссылки (автоматически после OTP)
    async function fetchVlessLink() {
      try {
        const resp = await fetch('/api/recovery/vpn-by-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setMsg(platformResult, 'Ошибка: ' + (data.error || resp.statusText), true);
          return;
        }
        const link = data.vless_link || '';
        if (!link) {
          setMsg(platformResult, 'Сервер не вернул ссылку.', true);
          return;
        }
        setMsg(platformResult, '', false);
        if (vlessLinkCode) vlessLinkCode.textContent = link;
        if (vlessLinkWrap) vlessLinkWrap.hidden = false;

        if (btnCopyVlessLink) {
          btnCopyVlessLink.onclick = async () => {
            try {
              await navigator.clipboard.writeText(link);
              const prev = btnCopyVlessLink.textContent;
              btnCopyVlessLink.textContent = '✅ Скопировано!';
              setTimeout(() => { btnCopyVlessLink.textContent = prev; }, 2000);
            } catch {
              if (vlessLinkCode) vlessLinkCode.focus();
            }
          };
        }
      } catch (err) {
        setMsg(platformResult, 'Сетевая ошибка: ' + (err.message || err), true);
      }
    }
  })();


  const tgInput = document.getElementById('recoveryTelegramId');
  const tgResult = document.getElementById('recovery-result');
  const tgBtn = document.getElementById('btnRecoverTelegram');
  const btnShowProxyLink = document.getElementById('btnShowProxyLink');
  const btnCopyProxyLink = document.getElementById('btnCopyProxyLink');
  const proxyLinkDisplay = document.getElementById('proxy-link-display');
  let lastProxyLink = '';

  const vpnEu1Input = document.getElementById('vpnRecoveryTelegramIdEu1');
  const vpnEu1Result = document.getElementById('vpn-recovery-result-eu1');
  const vpnEu1Btn = document.getElementById('btnRecoverVpnEu1');

  const vpnEu2Input = document.getElementById('vpnRecoveryTelegramIdEu2');
  const vpnEu2Result = document.getElementById('vpn-recovery-result-eu2');
  const vpnEu2Btn = document.getElementById('btnRecoverVpnEu2');

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

  async function fetchAndShowProxyLink(telegramId, opts) {
    const silent = opts && opts.silent;
    if (!proxyLinkDisplay || !btnCopyProxyLink) return;
    if (!silent) {
      proxyLinkDisplay.hidden = false;
      setResult(proxyLinkDisplay, 'Загрузка ссылки...', false);
    }
    try {
      const resp = await fetch(
        '/api/recovery/proxy-link?telegram_id=' + encodeURIComponent(telegramId),
        { method: 'GET' }
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        if (!silent) {
          proxyLinkDisplay.hidden = false;
          setResult(proxyLinkDisplay, 'Ошибка: ' + (data.error || resp.statusText || 'unknown'), true);
        }
        lastProxyLink = '';
        btnCopyProxyLink.hidden = true;
        return;
      }
      const link = data.mtproto_proxy_link || '';
      const hint = data.hint || '';
      lastProxyLink = link;
      if (link) {
        proxyLinkDisplay.hidden = false;
        const text = (hint ? hint + '\n\n' : '') + link;
        setResult(proxyLinkDisplay, text, false);
        btnCopyProxyLink.hidden = false;
      } else if (!silent) {
        proxyLinkDisplay.hidden = false;
        setResult(proxyLinkDisplay, 'Сервер не вернул ссылку.', true);
        btnCopyProxyLink.hidden = true;
      }
    } catch (err) {
      if (!silent) {
        proxyLinkDisplay.hidden = false;
        setResult(
          proxyLinkDisplay,
          'Ошибка сети: ' + (err && err.message ? err.message : String(err)),
          true
        );
      }
      lastProxyLink = '';
      btnCopyProxyLink.hidden = true;
    }
  }

  if (btnShowProxyLink && tgInput && proxyLinkDisplay) {
    btnShowProxyLink.addEventListener('click', async () => {
      const telegramId = (tgInput.value || '').trim();
      if (!telegramId) {
        proxyLinkDisplay.hidden = false;
        setResult(proxyLinkDisplay, 'Сначала введите Telegram ID.', true);
        return;
      }
      localStorage.setItem('vpn_recovery_telegram_id', telegramId);
      btnShowProxyLink.disabled = true;
      await fetchAndShowProxyLink(telegramId, { silent: false });
      btnShowProxyLink.disabled = false;
    });
  }

  if (btnCopyProxyLink) {
    btnCopyProxyLink.addEventListener('click', async () => {
      if (!lastProxyLink) return;
      try {
        await navigator.clipboard.writeText(lastProxyLink);
        const prev = btnCopyProxyLink.textContent;
        btnCopyProxyLink.textContent = 'Скопировано';
        setTimeout(() => {
          btnCopyProxyLink.textContent = prev;
        }, 2000);
      } catch {
        setResult(proxyLinkDisplay, lastProxyLink + '\n\n(Копирование в буфер не удалось — выделите ссылку вручную.)', false);
      }
    });
  }

  if (savedId && tgInput && btnShowProxyLink) {
    fetchAndShowProxyLink(savedId, { silent: true });
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

  function bindVpnRecovery(serverId, inputEl, btnEl, resultEl) {
    if (!inputEl || !btnEl || !resultEl) return;

    btnEl.addEventListener('click', async () => {
      const telegramId = (inputEl.value || '').trim();
      const androidSafe = true; // один DNS — безопасно для всех платформ

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

  bindVpnRecovery('eu1', vpnEu1Input, vpnEu1Btn, vpnEu1Result);
  bindVpnRecovery('eu2', vpnEu2Input, vpnEu2Btn, vpnEu2Result);

  // ── Мобильный VPN (VLESS+REALITY) ─────────────────────────────────────────
  const mobileVpnInput = document.getElementById('mobileVpnTelegramId');
  const mobileVpnBtn = document.getElementById('btnGetMobileVpn');
  const mobileVpnResult = document.getElementById('mobile-vpn-result');

  if (savedId && mobileVpnInput) mobileVpnInput.value = savedId;

  if (mobileVpnInput && mobileVpnBtn && mobileVpnResult) {
    // Синхронизация ID с остальными полями
    mirrorVpnIds(vpnEu1Input, mobileVpnInput);
    mirrorVpnIds(mobileVpnInput, vpnEu1Input);
    mirrorVpnIds(mobileVpnInput, vpnEu2Input);

    mobileVpnBtn.addEventListener('click', async () => {
      const telegramId = (mobileVpnInput.value || '').trim();
      if (!telegramId) {
        setResult(mobileVpnResult, 'Введите Telegram ID.', true);
        return;
      }

      mobileVpnBtn.disabled = true;
      setResult(mobileVpnResult, 'Запрос ссылки...', false);

      try {
        localStorage.setItem('vpn_recovery_telegram_id', telegramId);

        const resp = await fetch(
          '/api/recovery/mobile-vpn?telegram_id=' + encodeURIComponent(telegramId),
          { method: 'GET' }
        );

        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setResult(mobileVpnResult, 'Ошибка: ' + (data.error || resp.statusText || 'unknown'), true);
          return;
        }

        const vlessUrl = data.vless_url || '';
        const hint = data.hint || '';
        if (!vlessUrl) {
          setResult(mobileVpnResult, 'Сервер не вернул ссылку.', true);
          return;
        }

        // Показываем ссылку + кнопку копирования
        mobileVpnResult.innerHTML = '';
        const hintEl = document.createElement('p');
        hintEl.style.color = '#1b5e20';
        hintEl.textContent = hint || 'Скопируйте ссылку ниже и импортируйте в приложение.';
        mobileVpnResult.appendChild(hintEl);

        const linkEl = document.createElement('code');
        linkEl.style.wordBreak = 'break-all';
        linkEl.style.display = 'block';
        linkEl.style.marginTop = '8px';
        linkEl.textContent = vlessUrl;
        mobileVpnResult.appendChild(linkEl);

        const copyBtn = document.createElement('button');
        copyBtn.textContent = 'Копировать ссылку';
        copyBtn.className = 'btn-recovery btn-recovery-secondary';
        copyBtn.style.marginTop = '8px';
        copyBtn.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(vlessUrl);
            copyBtn.textContent = 'Скопировано!';
            setTimeout(() => { copyBtn.textContent = 'Копировать ссылку'; }, 2000);
          } catch {
            linkEl.focus();
          }
        });
        mobileVpnResult.appendChild(copyBtn);
      } catch (err) {
        setResult(mobileVpnResult, 'Ошибка сети: ' + (err && err.message ? err.message : String(err)), true);
      } finally {
        mobileVpnBtn.disabled = false;
      }
    });
  }
});
