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

  const authPassword     = document.getElementById('authPassword');
  const btnLoginPassword = document.getElementById('btnLoginPassword');
  const btnToggleLogin   = document.getElementById('btnToggleLogin');
  const loginHint        = document.getElementById('loginHint');

  const codeInput      = document.getElementById('authCode');
  const btnVerifyOtp   = document.getElementById('btnVerifyOtp');
  const btnResendOtp   = document.getElementById('btnResendOtp');
  const verifyResult   = document.getElementById('verifyOtpResult');

  const awgResult    = document.getElementById('awgResult');
  const mobileResult = document.getElementById('mobileResult');
  const proxyResult  = document.getElementById('proxyResult');

  const accountStatus  = document.getElementById('accountStatus');
  const trialBlock     = document.getElementById('trialBlock');
  const referralBlock  = document.getElementById('referralBlock');
  const passwordBlock  = document.getElementById('passwordBlock');
  const subBlock       = document.getElementById('subBlock');

  // ── State ─────────────────────────────────────────────────────────────────
  let sessionToken = '';
  let currentEmail = '';
  const refCode = new URLSearchParams(location.search).get('ref') || '';

  // ── Helpers ───────────────────────────────────────────────────────────────
  function setMsg(el, text, isError) {
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--green)';
  }

  function showStep(step) {
    [stepEmail, stepOtp, stepMenu, stepPlatform, stepOperator, stepProxy].forEach(s => {
      if (s) s.hidden = true;
    });
    if (step) step.hidden = false;
  }

  // Заметная кнопка «копировать» + сама ссылка под ней.
  // clear=true очищает контейнер (когда блок единственный).
  function renderLinkBlock(container, link, hintText, copyLabel, clear) {
    if (clear) container.innerHTML = '';
    if (hintText) {
      const p = document.createElement('p');
      p.className = 'section-hint';
      p.style.marginTop = '0';
      p.textContent = hintText;
      container.appendChild(p);
    }
    const code = document.createElement('code');
    code.className = 'link-code';
    code.textContent = link;

    const label = copyLabel || '📋 Копировать';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = label;
    btn.className = 'btn-recovery copy-primary';
    btn.addEventListener('click', async () => {
      const ok = await copyToClipboard(link);
      btn.textContent = ok ? '✅ Скопировано!' : '⚠️ Выдели и скопируй вручную';
      if (!ok) selectText(code);
      setTimeout(() => { btn.textContent = label; }, 2200);
    });
    container.appendChild(btn);
    container.appendChild(code);
  }

  // QR-код (PNG data-URI с бэкенда) — для скана с телефона.
  function renderQr(container, dataUri, caption) {
    if (!dataUri) return;
    const box = document.createElement('div');
    box.className = 'qr-box';
    const img = document.createElement('img');
    img.src = dataUri;
    img.alt = 'QR';
    box.appendChild(img);
    if (caption) {
      const c = document.createElement('div');
      c.className = 'qr-caption';
      c.textContent = caption;
      box.appendChild(c);
    }
    container.appendChild(box);
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

  function selectText(el) {
    try {
      const r = document.createRange();
      r.selectNodeContents(el);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
    } catch (e) {}
  }

  // Копирование с fallback: navigator.clipboard только в secure context (HTTPS).
  // На HTTP используем устаревший, но рабочий execCommand('copy').
  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {}
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (e) {
      return false;
    }
  }

  function fmtDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
      return d.toLocaleDateString('ru-RU');
    } catch { return ''; }
  }

  // ── «Мой аккаунт»: статус, триал, реферал ───────────────────────────────────
  async function loadAccount() {
    if (!accountStatus) return;
    accountStatus.textContent = 'Загружаем…';
    try {
      const resp = await fetch('/api/account/info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: sessionToken }),
      });
      const d = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        accountStatus.textContent = 'Не удалось загрузить аккаунт: ' + (d.error || resp.statusText);
        return;
      }
      renderAccount(d);
    } catch (err) {
      accountStatus.textContent = 'Сетевая ошибка при загрузке аккаунта.';
    }
  }

  function renderAccount(d) {
    if (!accountStatus) return;
    // Статус-карточка
    let label = 'Доступ', value = '', cls = 'acc-ok', sub = '';
    if (d.grandfathered) {
      value = 'Бессрочный';
    } else if (d.status === 'trial' && (d.days_left || 0) > 0) {
      label = 'Пробный период'; value = `${d.days_left} дн`;
      sub = `до ${fmtDate(d.expires_at)}`;
    } else if ((d.days_left || 0) > 0) {
      label = 'Подписка'; value = `${d.days_left} дн`;
      cls = d.days_left <= 3 ? 'acc-warn' : 'acc-ok';
      sub = `активна до ${fmtDate(d.expires_at)}`;
    } else {
      label = 'Подписка'; value = 'Неактивна'; cls = 'acc-bad';
    }
    accountStatus.innerHTML = '';
    const line = document.createElement('div'); line.className = 'acc-line';
    const l = document.createElement('span'); l.className = 'acc-label'; l.textContent = label;
    const v = document.createElement('span'); v.className = 'acc-value ' + cls; v.textContent = value;
    line.appendChild(l); line.appendChild(v);
    accountStatus.appendChild(line);
    if (sub) {
      const s = document.createElement('div'); s.className = 'acc-sub'; s.textContent = sub;
      accountStatus.appendChild(s);
    }

    // Пробный период
    if (trialBlock) {
      trialBlock.innerHTML = '';
      if (d.trial_available) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn-recovery copy-primary';
        b.textContent = `🎁 Активировать ${d.trial_days} дней бесплатно`;
        b.addEventListener('click', () => startTrial(b));
        trialBlock.appendChild(b);
      }
    }

    // Подписка — одна ссылка на все устройства (спайк)
    if (subBlock) {
      if (d.sub_link_path) {
        subBlock.hidden = false;
        subBlock.innerHTML = '';
        const t = document.createElement('div');
        t.className = 'acc-subtitle';
        t.textContent = '🔗 Подписка — рекомендуется';
        const note = document.createElement('p');
        note.className = 'section-hint';
        note.textContent = 'Одна ссылка для всех устройств. Импортируй в HAPP (или Streisand / V2Box / Hiddify): «+» → по ссылке или из буфера. Приложение само выберет рабочий сервер и подтянет обновления.';
        subBlock.appendChild(t);
        subBlock.appendChild(note);
        renderQr(subBlock, d.sub_qr, 'Сканируй в приложении (HAPP и др.)');
        renderLinkBlock(subBlock, location.origin + d.sub_link_path, '', '📋 Скопировать ссылку подписки');
      } else {
        subBlock.hidden = true;
      }
    }

    // Управление паролем
    renderPasswordBlock(!!d.has_password);

    // Реферальный блок
    if (referralBlock) {
      if (d.referral_code) {
        referralBlock.hidden = false;
        referralBlock.innerHTML = '';
        const t = document.createElement('div');
        t.className = 'acc-subtitle';
        t.textContent = '👥 Приглашай друзей';
        const note = document.createElement('p');
        note.className = 'section-hint';
        note.textContent = `Когда друг оплатит — вы оба получите +${d.referral_reward_days} дней. Приглашено: ${d.invited_count}.`;
        referralBlock.appendChild(t);
        referralBlock.appendChild(note);
        const link = location.origin + d.referral_link_path;
        renderLinkBlock(referralBlock, link, '', '📋 Скопировать ссылку-приглашение');
      } else {
        referralBlock.hidden = true;
      }
    }
  }

  async function startTrial(btn) {
    btn.disabled = true;
    const prev = btn.textContent;
    btn.textContent = 'Активируем…';
    try {
      const resp = await fetch('/api/account/start-trial', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: sessionToken }),
      });
      const d = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        btn.textContent = prev; btn.disabled = false;
        alert(d.error || 'Не удалось активировать пробный период.');
        return;
      }
      loadAccount();
    } catch (err) {
      btn.textContent = prev; btn.disabled = false;
    }
  }

  // Блок «Добавить/Изменить пароль» — раскрывает инлайн-форму
  function renderPasswordBlock(hasPassword) {
    if (!passwordBlock) return;
    passwordBlock.innerHTML = '';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-recovery btn-recovery-secondary copy-primary';
    btn.textContent = hasPassword ? '🔑 Изменить пароль' : '🔑 Добавить пароль';

    const form = document.createElement('div');
    form.className = 'recovery-form';
    form.style.marginTop = '12px';
    form.hidden = true;

    const inp = document.createElement('input');
    inp.type = 'password';
    inp.placeholder = 'Новый пароль (мин. 8 символов)';
    inp.autocomplete = 'new-password';

    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'btn-recovery';
    save.textContent = 'Сохранить пароль';

    const msg = document.createElement('div');
    msg.className = 'section-hint';

    btn.addEventListener('click', () => { form.hidden = !form.hidden; });

    save.addEventListener('click', async () => {
      const pw = (inp.value || '').trim();
      if (pw.length < 8) {
        msg.style.color = 'var(--red)';
        msg.textContent = 'Минимум 8 символов.';
        return;
      }
      save.disabled = true;
      msg.style.color = 'var(--green)';
      msg.textContent = 'Сохраняем…';
      try {
        const r = await fetch('/api/account/set-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken, password: pw }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) {
          msg.style.color = 'var(--red)';
          msg.textContent = d.error || 'Ошибка';
          save.disabled = false;
          return;
        }
        msg.style.color = 'var(--green)';
        msg.textContent = 'Пароль сохранён ✅';
        inp.value = '';
        setTimeout(() => loadAccount(), 800);
      } catch (e) {
        msg.style.color = 'var(--red)';
        msg.textContent = 'Сетевая ошибка';
        save.disabled = false;
      }
    });

    form.appendChild(inp);
    form.appendChild(save);
    form.appendChild(msg);
    passwordBlock.appendChild(btn);
    passwordBlock.appendChild(form);
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

  // ── Вход по паролю (альтернатива OTP) ──────────────────────────────────────
  let passwordMode = false;
  function setLoginMode(pw) {
    passwordMode = pw;
    if (authPassword) authPassword.hidden = !pw;
    if (btnSendOtp) btnSendOtp.hidden = pw;
    if (btnLoginPassword) btnLoginPassword.hidden = !pw;
    if (loginHint) loginHint.textContent = pw
      ? 'Введи email и пароль.'
      : 'Введи email — пришлём одноразовый код для входа.';
    if (btnToggleLogin) btnToggleLogin.textContent = pw ? '📧 Войти по коду' : '🔑 Войти по паролю';
    setMsg(sendOtpResult, '', false);
  }

  async function loginPassword() {
    const email = (emailInput.value || '').trim().toLowerCase();
    const password = (authPassword && authPassword.value) || '';
    if (!email || !email.includes('@') || !password) {
      setMsg(sendOtpResult, 'Введи email и пароль.', true);
      return;
    }
    btnLoginPassword.disabled = true;
    setMsg(sendOtpResult, 'Входим…', false);
    try {
      const resp = await fetch('/api/auth/login-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMsg(sendOtpResult, data.error || 'Ошибка входа', true);
        return;
      }
      sessionToken = data.token || '';
      currentEmail = email;
      setMsg(sendOtpResult, '', false);
      showStep(stepMenu);
      loadAccount();
    } catch (err) {
      setMsg(sendOtpResult, 'Сетевая ошибка: ' + (err.message || err), true);
    } finally {
      btnLoginPassword.disabled = false;
    }
  }

  if (btnToggleLogin) btnToggleLogin.addEventListener('click', () => setLoginMode(!passwordMode));
  if (btnLoginPassword) btnLoginPassword.addEventListener('click', loginPassword);
  if (authPassword) authPassword.addEventListener('keydown', e => { if (e.key === 'Enter') loginPassword(); });

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
        body: JSON.stringify({ email: currentEmail, code, ref: refCode }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMsg(verifyResult, 'Ошибка: ' + (data.error || resp.statusText), true);
        return;
      }
      sessionToken = data.token || '';
      showStep(stepMenu);
      loadAccount();
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
      status.style.color = 'var(--green)';
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
          const a = document.createElement('a');
          a.href = data.vpn_url;
          a.textContent = '👆 Открыть в AmneziaVPN';
          a.className = 'btn-recovery';
          a.style.display = 'inline-block';
          aWrap.appendChild(a);
          awgResult.appendChild(aWrap);
          renderQr(awgResult, data.qr, 'Или сканируй QR в приложении AmneziaVPN (импорт конфига)');
        } else {
          // PC / iOS — скачать файл
          downloadFile(filename, cfg);
          status.textContent = 'Готово. Файл ' + filename + ' скачан.';
          status.style.color = 'var(--green)';

          const hint = document.createElement('p');
          hint.className = 'section-hint';
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
          renderQr(awgResult, data.qr, 'Или сканируй QR в приложении AmneziaWG (импорт конфига)');
        }

        // Ошибка-103 fallback
        const fallback = document.createElement('p');
        fallback.className = 'section-hint';
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
      status.style.color = 'var(--green)';
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
        renderQr(mobileResult, data.qr, 'Сканируй QR в приложении (Hiddify / v2rayNG)');
        renderLinkBlock(mobileResult, link, hint, '📋 Копировать ссылку');

        const apps = document.createElement('p');
        apps.className = 'section-hint';
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
    status.style.color = 'var(--green)';
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
      renderQr(proxyResult, data.qr, 'Сканируй QR или нажми кнопку — откроется в Telegram');

      const openA = document.createElement('a');
      openA.href = link;
      openA.textContent = '👆 Открыть в Telegram';
      openA.className = 'btn-recovery copy-primary';
      openA.style.display = 'block';
      openA.style.textAlign = 'center';
      openA.style.textDecoration = 'none';
      openA.style.marginBottom = '8px';
      proxyResult.appendChild(openA);

      renderLinkBlock(proxyResult, link, '', '📋 Копировать tg://');
    } catch (err) {
      setMsg(status, 'Сетевая ошибка: ' + (err.message || err), true);
    }
  }
});
