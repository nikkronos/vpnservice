document.addEventListener('DOMContentLoaded', () => {
  // ── DOM ───────────────────────────────────────────────────────────────────
  const stepEmail    = document.getElementById('stepEmail');
  const stepOtp      = document.getElementById('stepOtp');
  const stepMenu     = document.getElementById('stepMenu');
  const stepPlatform = document.getElementById('stepPlatform');
  const stepOperator = document.getElementById('stepOperator');
  const stepProxy    = document.getElementById('stepProxy');

  const emailInput    = document.getElementById('authEmail');
  const btnSendOtp    = document.getElementById('btnSendOtp');
  const sendOtpResult = document.getElementById('sendOtpResult');

  const codeInput      = document.getElementById('authCode');
  const btnVerifyOtp   = document.getElementById('btnVerifyOtp');
  const btnResendOtp   = document.getElementById('btnResendOtp');
  const verifyResult   = document.getElementById('verifyOtpResult');

  const awgResult    = document.getElementById('awgResult');
  const mobileResult = document.getElementById('mobileResult');
  const proxyResult  = document.getElementById('proxyResult');

  // ── State ─────────────────────────────────────────────────────────────────
  let sessionToken = '';
  let currentEmail = '';

  // ── Helpers ───────────────────────────────────────────────────────────────
  function setMsg(el, text, isError) {
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? '#b00020' : '#1b5e20';
  }

  function showStep(step) {
    [stepEmail, stepOtp, stepMenu, stepPlatform, stepOperator, stepProxy].forEach(s => {
      if (s) s.hidden = true;
    });
    if (step) step.hidden = false;
  }

  function renderLinkBlock(container, link, hintText, copyLabel) {
    container.innerHTML = '';
    if (hintText) {
      const p = document.createElement('p');
      p.className = 'section-hint';
      p.style.marginTop = '0';
      p.textContent = hintText;
      container.appendChild(p);
    }
    const code = document.createElement('code');
    code.style.wordBreak = 'break-all';
    code.style.display = 'block';
    code.style.margin = '8px 0';
    code.style.fontSize = '13px';
    code.textContent = link;
    container.appendChild(code);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = copyLabel || '📋 Копировать ссылку';
    btn.className = 'btn-recovery btn-recovery-secondary';
    btn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(link);
        const prev = btn.textContent;
        btn.textContent = '✅ Скопировано!';
        setTimeout(() => { btn.textContent = prev; }, 2000);
      } catch {
        code.focus();
      }
    });
    container.appendChild(btn);
  }

  function downloadFile(filename, content) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // ── Шаг 1: Email → отправить OTP ─────────────────────────────────────────
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

  if (btnSendOtp) btnSendOtp.addEventListener('click', sendOtp);
  if (emailInput) emailInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendOtp(); });
  if (btnResendOtp) btnResendOtp.addEventListener('click', () => {
    showStep(stepEmail);
    setMsg(sendOtpResult, '', false);
  });

  // ── Шаг 2: Проверить OTP → главное меню ──────────────────────────────────
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
      showStep(stepMenu);
    } catch (err) {
      setMsg(verifyResult, 'Сетевая ошибка: ' + (err.message || err), true);
    } finally {
      btnVerifyOtp.disabled = false;
    }
  }

  if (btnVerifyOtp) btnVerifyOtp.addEventListener('click', verifyOtp);
  if (codeInput) codeInput.addEventListener('keydown', e => { if (e.key === 'Enter') verifyOtp(); });

  // ── Шаг 3: Меню (выбор канала) ───────────────────────────────────────────
  document.querySelectorAll('[data-channel]').forEach(btn => {
    btn.addEventListener('click', () => {
      const ch = btn.dataset.channel;
      if (ch === 'awg') {
        if (awgResult) awgResult.innerHTML = '';
        showStep(stepPlatform);
      } else if (ch === 'mobile') {
        if (mobileResult) mobileResult.innerHTML = '';
        showStep(stepOperator);
      } else if (ch === 'mtproxy') {
        showStep(stepProxy);
        fetchProxyLink();
      }
    });
  });

  // Кнопки «Назад» в подстраницах
  document.querySelectorAll('[data-back]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.back;
      if (target === 'menu') showStep(stepMenu);
    });
  });

  // ── Шаг 4a: Платформа → AmneziaWG ───────────────────────────────────────
  document.querySelectorAll('[data-platform]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const platform = btn.dataset.platform;
      if (!awgResult) return;
      awgResult.innerHTML = '';
      const status = document.createElement('p');
      status.style.color = '#1b5e20';
      status.textContent = 'Генерируем конфиг…';
      awgResult.appendChild(status);

      // Блокируем кнопки на время запроса
      document.querySelectorAll('[data-platform]').forEach(b => b.disabled = true);
      try {
        const resp = await fetch('/api/recovery/awg-config-by-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken, platform }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setMsg(status, 'Ошибка: ' + (data.error || resp.statusText), true);
          return;
        }

        const cfg = data.config || '';
        const filename = data.filename || 'awg_eu1.conf';

        if (platform === 'android' && data.vpn_url) {
          // Android — vpn:// deep link
          status.remove();
          const blockHint = (
            'Нажми на ссылку с устройства с установленным AmneziaVPN — приложение откроется и импортирует конфиг автоматически. ' +
            'Если AmneziaVPN не установлен — скачай его в Google Play.'
          );
          renderLinkBlock(awgResult, data.vpn_url, blockHint, '📋 Копировать vpn://');

          // Опционально — ссылка как кликабельная
          const aWrap = document.createElement('p');
          aWrap.style.marginTop = '10px';
          const a = document.createElement('a');
          a.href = data.vpn_url;
          a.textContent = '👆 Открыть в AmneziaVPN';
          a.className = 'btn-recovery';
          a.style.display = 'inline-block';
          aWrap.appendChild(a);
          awgResult.appendChild(aWrap);
        } else {
          // PC / iOS — скачать файл
          downloadFile(filename, cfg);
          status.textContent = 'Готово. Файл ' + filename + ' скачан.';
          status.style.color = '#1b5e20';

          const hint = document.createElement('p');
          hint.className = 'section-hint';
          hint.style.marginTop = '10px';
          if (platform === 'ios') {
            hint.innerHTML = (
              '<b>iPhone / iPad:</b> открой файл → значок «Поделиться» → выбери ' +
              '<b>AmneziaWG</b> → «Создать из файла». Если AmneziaWG не установлен — поставь его в App Store.'
            );
          } else {
            hint.innerHTML = (
              '<b>ПК:</b> установи <a href="https://amnezia.org" target="_blank">AmneziaVPN</a> ' +
              'или <a href="https://github.com/amnezia-vpn/amneziawg-windows-client" target="_blank">AmneziaWG</a>, ' +
              'затем импортируй файл <code>' + filename + '</code>.'
            );
          }
          awgResult.appendChild(hint);
        }

        // Ошибка-103 fallback
        const fallback = document.createElement('p');
        fallback.className = 'section-hint';
        fallback.style.marginTop = '12px';
        fallback.style.opacity = '0.85';
        fallback.innerHTML = (
          '⚠️ <b>Если AmneziaVPN на ПК выдаёт Error 103 «Фоновая служба не запущена»</b> — ' +
          'запусти приложение «Запуск от имени администратора», либо переустанови AmneziaVPN. ' +
          'Альтернативный клиент: <a href="https://hiddify.com" target="_blank">Hiddify</a> — поддерживает тот же конфиг.'
        );
        awgResult.appendChild(fallback);
      } catch (err) {
        setMsg(status, 'Сетевая ошибка: ' + (err.message || err), true);
      } finally {
        document.querySelectorAll('[data-platform]').forEach(b => b.disabled = false);
      }
    });
  });

  // ── Шаг 4b: Оператор → VLESS ─────────────────────────────────────────────
  document.querySelectorAll('[data-operator]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const operator = btn.dataset.operator;
      if (!mobileResult) return;
      mobileResult.innerHTML = '';
      const status = document.createElement('p');
      status.style.color = '#1b5e20';
      status.textContent = 'Запрашиваем ссылку…';
      mobileResult.appendChild(status);

      document.querySelectorAll('[data-operator]').forEach(b => b.disabled = true);
      try {
        const resp = await fetch('/api/recovery/mobile-link-by-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken, operator }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setMsg(status, 'Ошибка: ' + (data.error || resp.statusText), true);
          return;
        }

        const link = data.vless_url || '';
        const hint = data.hint || '';
        if (!link) {
          setMsg(status, 'Сервер не вернул ссылку.', true);
          return;
        }

        status.remove();
        renderLinkBlock(mobileResult, link, hint, '📋 Копировать ссылку');

        const apps = document.createElement('p');
        apps.className = 'section-hint';
        apps.style.marginTop = '10px';
        apps.innerHTML = (
          '<b>Android:</b> <a href="https://hiddify.com" target="_blank">Hiddify</a> или v2rayNG — «+» → «Импорт из буфера».<br>' +
          '<b>iOS:</b> <a href="https://apps.apple.com/app/foxray/id6448898396" target="_blank">FoXray</a>, ' +
          '<a href="https://apps.apple.com/app/v2box/id6446814690" target="_blank">V2Box</a>, ' +
          '<a href="https://apps.apple.com/app/streisand/id6450534064" target="_blank">Streisand</a> или Hiddify — импорт ссылки.'
        );
        mobileResult.appendChild(apps);
      } catch (err) {
        setMsg(status, 'Сетевая ошибка: ' + (err.message || err), true);
      } finally {
        document.querySelectorAll('[data-operator]').forEach(b => b.disabled = false);
      }
    });
  });

  // ── Шаг 4c: MTProxy ──────────────────────────────────────────────────────
  async function fetchProxyLink() {
    if (!proxyResult) return;
    proxyResult.innerHTML = '';
    const status = document.createElement('p');
    status.style.color = '#1b5e20';
    status.textContent = 'Загружаем ссылку…';
    proxyResult.appendChild(status);

    try {
      const resp = await fetch('/api/recovery/proxy-link-by-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: sessionToken }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMsg(status, 'Ошибка: ' + (data.error || resp.statusText), true);
        return;
      }

      const link = data.mtproto_proxy_link || '';
      const hint = data.hint || '';
      if (!link) {
        setMsg(status, 'Сервер не вернул ссылку.', true);
        return;
      }

      status.remove();
      const desc = document.createElement('p');
      desc.className = 'section-hint';
      desc.style.marginTop = '0';
      desc.textContent = hint;
      proxyResult.appendChild(desc);

      const openA = document.createElement('a');
      openA.href = link;
      openA.textContent = '👆 Открыть в Telegram';
      openA.className = 'btn-recovery';
      openA.style.display = 'inline-block';
      openA.style.marginRight = '8px';
      proxyResult.appendChild(openA);

      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.textContent = '📋 Копировать tg://';
      copyBtn.className = 'btn-recovery btn-recovery-secondary';
      copyBtn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(link);
          copyBtn.textContent = '✅ Скопировано!';
          setTimeout(() => { copyBtn.textContent = '📋 Копировать tg://'; }, 2000);
        } catch {}
      });
      proxyResult.appendChild(copyBtn);

      const code = document.createElement('code');
      code.style.wordBreak = 'break-all';
      code.style.display = 'block';
      code.style.marginTop = '12px';
      code.style.fontSize = '13px';
      code.textContent = link;
      proxyResult.appendChild(code);
    } catch (err) {
      setMsg(status, 'Сетевая ошибка: ' + (err.message || err), true);
    }
  }
});
