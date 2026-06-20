document.addEventListener('DOMContentLoaded', () => {
  // ── DOM ───────────────────────────────────────────────────────────────────
  const stepEmail        = document.getElementById('stepEmail');
  const stepOtp          = document.getElementById('stepOtp');
  const stepMenu         = document.getElementById('stepMenu');
  const stepBilling      = document.getElementById('stepBilling');
  const stepManualPay    = document.getElementById('stepManualPay');
  const stepConnect      = document.getElementById('stepConnect');
  const stepReferral     = document.getElementById('stepReferral');
  const stepSettings     = document.getElementById('stepSettings');
  const stepPlatform     = document.getElementById('stepPlatform');
  const stepAwgResult    = document.getElementById('stepAwgResult');
  const stepOperator     = document.getElementById('stepOperator');
  const stepMobileResult = document.getElementById('stepMobileResult');
  const stepProxy        = document.getElementById('stepProxy');
  const stepDevices       = document.getElementById('stepDevices');
  const stepDeviceResult  = document.getElementById('stepDeviceResult');
  const devicesList       = document.getElementById('devicesList');
  const deviceResult      = document.getElementById('deviceResult');
  const deviceResultTitle = document.getElementById('deviceResultTitle');
  const awgResultTitle    = document.getElementById('awgResultTitle');
  const mobileResultTitle = document.getElementById('mobileResultTitle');

  // Карта родительских шагов — для TG BackButton и наших «« Назад».
  // Шаги без родителя — корни (email/otp/menu) — назад скрывается.
  const stepParent = new Map();
  let currentStep = null;

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

  const accountStatus    = document.getElementById('accountStatus');
  const trialBlock       = document.getElementById('trialBlock');
  const referralBlock    = document.getElementById('referralBlock');
  const passwordBlock    = document.getElementById('passwordBlock');
  const subBlock         = document.getElementById('subBlock');
  const payBlock         = document.getElementById('payBlock');
  const manualPayContent = document.getElementById('manualPayContent');

  // ── State ─────────────────────────────────────────────────────────────────
  let sessionToken = '';
  let currentEmail = '';
  const refCode = new URLSearchParams(location.search).get('ref') || '';
  // Выбор тарифа в payBlock (устройства × срок) + тарифная сетка с бэка.
  let payDevices = 3;
  let payMonths = 1;
  let acctTariffs = [];
  // «Не работает» под выданным конфигом: замыкание, повторяющее последнюю генерацию.
  let lastConfigRetry = null;

  // ── Telegram WebApp context ───────────────────────────────────────────────
  // SDK telegram-web-app.js хостится у нас локально (telegram.org из РФ нестабилен).
  // Скрипт sync, поэтому к моменту запуска recovery.js window.Telegram.WebApp уже определён —
  // но на всякий случай оставлен polling-фолбэк (см. ниже).
  let tg = window.Telegram && window.Telegram.WebApp;
  let inTelegram = !!(tg && tg.initData);

  // Нативные TG-диалоги (showAlert) — fallback на browser alert вне TG.
  function notify(message) {
    if (inTelegram && tg.showAlert) {
      try { tg.showAlert(message); return; } catch (e) {}
    }
    alert(message);
  }

  // Тактильный отклик: 'success'|'error'|'warning' (notification) или 'light'|'medium'|'heavy' (impact).
  function haptic(type) {
    if (!inTelegram || !tg.HapticFeedback) return;
    try {
      if (type === 'success' || type === 'error' || type === 'warning') {
        tg.HapticFeedback.notificationOccurred(type);
      } else {
        tg.HapticFeedback.impactOccurred(type || 'light');
      }
    } catch (e) {}
  }

  // ── Telegram WebApp init + auto-login (если открыто из бота) ─────────────
  // telegram-web-app.js грузится async — может появиться позже нашего кода.
  // Поэтому: 1) выполняем сразу если уже доступен, 2) иначе поллим до 3с.
  // В обычном браузере SDK тоже подгрузится, но initData останется пустой →
  // флоу падает на email/пароль, как и было.
  let tgFeaturesSetup = false;

  function setupTelegramFeatures() {
    if (tgFeaturesSetup || !inTelegram) return;
    tgFeaturesSetup = true;
    document.body.classList.add('tg-mode');
    try { tg.ready(); tg.expand(); } catch (e) {}
    // BackButton: регистрируем onClick один раз; видимость пересчитывается в showStep().
    if (tg.BackButton) {
      try {
        tg.BackButton.onClick(() => {
          const p = stepParent.get(currentStep);
          if (p) showStep(p);
        });
        // Если уже на substep (например, после showStep до инициализации TG) — показываем стрелку.
        if (currentStep && stepParent.has(currentStep)) tg.BackButton.show();
      } catch (e) {}
    }
    runAutoLogin();
  }

  function runAutoLogin() {
    if (!inTelegram) return;
    (async () => {
      try {
        const r = await fetch('/api/auth/tg-webapp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ init_data: tg.initData }),
        });
        if (!r.ok) {
          console.warn('TG WebApp auth failed: HTTP', r.status);
          return;
        }
        const d = await r.json();
        sessionToken = d.token || '';
        showStep(stepMenu);
        loadAccount();
      } catch (e) {
        console.warn('TG WebApp auth error:', e);
      }
    })();
  }

  // Отложенный запуск: stepParent/showStep/currentStep объявлены ниже в этом же
  // обработчике DOMContentLoaded; setTimeout(0) гарантирует, что они уже инициализированы.
  // Polling — defensive: если SDK по какой-то причине не определил Telegram.WebApp сразу.
  if (inTelegram) {
    setTimeout(setupTelegramFeatures, 0);
  } else {
    const pollStart = Date.now();
    const tgPoll = setInterval(() => {
      tg = window.Telegram && window.Telegram.WebApp;
      inTelegram = !!(tg && tg.initData);
      if (inTelegram) {
        clearInterval(tgPoll);
        setupTelegramFeatures();
      } else if (Date.now() - pollStart > 3000) {
        clearInterval(tgPoll);
      }
    }, 100);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function setMsg(el, text, isError) {
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--green)';
  }

  const allSteps = [
    stepEmail, stepOtp, stepMenu,
    stepBilling, stepManualPay, stepConnect, stepReferral, stepSettings,
    stepDevices, stepDeviceResult,
    stepPlatform, stepAwgResult, stepOperator, stepMobileResult, stepProxy,
  ];

  // Иерархия шагов: главное меню — корень, разделы ведут к нему,
  // выбор канала/платформы/оператора возвращает в stepConnect.
  // stepAwgResult/stepMobileResult — результат выбора платформы/оператора,
  // возвращают на step выбора (чтобы можно было выбрать другое устройство/оператора).
  stepParent.set(stepBilling,      stepMenu);
  stepParent.set(stepManualPay,    stepBilling);
  stepParent.set(stepConnect,      stepMenu);
  stepParent.set(stepReferral,     stepMenu);
  stepParent.set(stepSettings,     stepMenu);
  stepParent.set(stepPlatform,     stepConnect);
  stepParent.set(stepAwgResult,    stepPlatform);
  stepParent.set(stepOperator,     stepConnect);
  stepParent.set(stepMobileResult, stepOperator);
  // stepProxy теперь доступен прямо из главного меню (по запросу владельца 2026-05-27),
  // а не через stepConnect — Telegram-прокси логически независим от VPN.
  stepParent.set(stepProxy,        stepMenu);
  stepParent.set(stepDevices,      stepMenu);
  stepParent.set(stepDeviceResult, stepDevices);

  function showStep(step) {
    allSteps.forEach(s => { if (s) s.hidden = true; });
    if (step) step.hidden = false;
    currentStep = step;
    try { window.scrollTo(0, 0); } catch (e) {}
    // TG BackButton (нативная стрелка в TG-хроме): показываем, если у шага есть родитель.
    if (inTelegram && tg.BackButton) {
      const hasParent = stepParent.has(step);
      try { hasParent ? tg.BackButton.show() : tg.BackButton.hide(); } catch (e) {}
    }
  }

  // TG BackButton onClick регистрируется в setupTelegramFeatures() (когда SDK реально доступен).

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
      haptic(ok ? 'success' : 'warning');
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

    // Inline «Продлить» — когда срок поджимает или истёк (не показываем grandfather).
    if (!d.grandfathered && (d.days_left || 0) <= 3) {
      const renewBtn = document.createElement('button');
      renewBtn.type = 'button';
      renewBtn.className = 'btn-recovery copy-primary';
      renewBtn.style.marginTop = '12px';
      renewBtn.textContent = '💳 Продлить подписку';
      renewBtn.addEventListener('click', () => {
        haptic('light');
        showStep(stepBilling);
      });
      accountStatus.appendChild(renewBtn);
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

    // Оплата подписки (продление) + страница ручной оплаты
    renderPayBlock(d);
    renderManualPay(d);

    // Доступ к VPN — одна ссылка для всех устройств
    if (subBlock) {
      const accessActive = d.grandfathered || (d.days_left || 0) > 0;
      if (d.sub_link_path && accessActive) {
        subBlock.hidden = false;
        subBlock.innerHTML = '';
        const t = document.createElement('div');
        t.className = 'acc-subtitle';
        t.textContent = '🔗 Подключить VPN.';
        const note = document.createElement('p');
        note.className = 'section-hint';
        note.textContent = 'Одна ссылка для всех устройств. Импортируй в Happ (happ.su): «+» → по ссылке или из буфера обмена. Приложение само выберет рабочий сервер и подтянет обновления.';
        subBlock.appendChild(t);
        subBlock.appendChild(note);
        // Дополнительный пробел над QR для воздуха
        const qrSpacer = document.createElement('div');
        qrSpacer.style.height = '8px';
        subBlock.appendChild(qrSpacer);
        renderQr(subBlock, d.sub_qr, 'Сканируй в приложении');
        renderLinkBlock(subBlock, location.origin + d.sub_link_path, '', 'Скопировать ссылку');
      } else if (!accessActive) {
        // Подписка неактивна — не показываем мёртвую ссылку, ведём на продление.
        subBlock.hidden = false;
        subBlock.innerHTML = '';
        const t = document.createElement('div');
        t.className = 'acc-subtitle';
        t.textContent = '🔗 Подключить VPN.';
        const note = document.createElement('p');
        note.className = 'section-hint';
        note.textContent = 'Подписка неактивна — продли её выше, и здесь снова появится ссылка для подключения всех устройств.';
        subBlock.appendChild(t);
        subBlock.appendChild(note);
      } else {
        subBlock.hidden = true;
      }
    }

    // Управление паролем
    renderPasswordBlock(!!d.has_password);

    // Реферальный блок: ссылка-приглашение + TG share + счётчик
    if (referralBlock) {
      if (d.referral_code) {
        referralBlock.hidden = false;
        referralBlock.innerHTML = '';
        const t = document.createElement('div');
        t.className = 'acc-subtitle';
        t.textContent = '👥 Приглашай друзей';
        referralBlock.appendChild(t);

        const note = document.createElement('p');
        note.className = 'section-hint';
        note.innerHTML = (
          `+${d.referral_reward_days} дней тебе, +${d.referral_reward_days} другу — `
          + 'когда он <b>впервые оплатит</b> подписку. '
          + 'Бонус один раз за каждого приглашённого.'
        );
        referralBlock.appendChild(note);

        if (typeof d.invited_count === 'number') {
          const counter = document.createElement('p');
          counter.className = 'section-hint';
          counter.style.marginTop = '6px';
          counter.innerHTML = `Приглашено: <b>${d.invited_count}</b>`;
          referralBlock.appendChild(counter);
        }

        // Реф-ссылка: Mini App deeplink (`?startapp=ref_X`).
        // Требует Direct Link Mini App URL в BotFather (настроено владельцем
        // 2026-06-01). Открывает Mini App сразу с start_param, который ловится
        // в /api/auth/tg-webapp → db_set_referred_by + уведомление пригласителю.
        // Fallback `?start=ref_X` (cmd_start в bot/main.py) тоже работает —
        // на случай если юзер откроет ссылку нестандартно.
        const refLink = `https://t.me/vpnkronos_bot?startapp=ref_${d.referral_code}`;

        renderLinkBlock(referralBlock, refLink, '', '📋 Скопировать ссылку');

        // TG-share — открывает нативный share-dialog Telegram.
        const shareBtn = document.createElement('button');
        shareBtn.type = 'button';
        shareBtn.className = 'btn-recovery btn-recovery-secondary';
        shareBtn.style.marginTop = '8px';
        shareBtn.style.width = '100%';
        shareBtn.textContent = '💬 Поделиться через Telegram';
        shareBtn.addEventListener('click', () => {
          haptic('light');
          // Нейтральный текст — без УТП (УТП отложен, см. ROADMAP).
          // Когда УТП будет утверждено, поменяем здесь.
          const shareText = (
            `Реферальная ссылка на VPN-сервис. `
            + `При твоей первой оплате — бонус +${d.referral_reward_days} дней нам обоим.`
          );
          const httpsShare = `https://t.me/share/url?url=${encodeURIComponent(refLink)}&text=${encodeURIComponent(shareText)}`;
          if (window.Telegram?.WebApp?.openTelegramLink) {
            window.Telegram.WebApp.openTelegramLink(httpsShare);
          } else {
            window.location.href = httpsShare;
          }
        });
        referralBlock.appendChild(shareBtn);
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
        haptic('error');
        notify(d.error || 'Не удалось активировать пробный период.');
        return;
      }
      haptic('success');
      loadAccount();
    } catch (err) {
      btn.textContent = prev; btn.disabled = false;
      haptic('error');
    }
  }

  // Блок «Продлить подписку» — Telegram Stars (нативно) + ручной СБП/карта.
  // Показываем ВСЕМ (включая grandfather/owner) — пусть видят, что доступно.
  function findTariff(devices, months) {
    return (acctTariffs || []).find(t => t.devices === devices && t.months === months) || null;
  }

  // Сегментированный выбор: подпись + варианты-кнопки (выбранный подсвечен).
  function _payChooserRow(label, options, selected, onPick) {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-top:10px;';
    const cap = document.createElement('div');
    cap.className = 'section-hint';
    cap.style.cssText = 'margin:0 0 4px;';
    cap.textContent = label + ':';
    wrap.appendChild(cap);
    const row = document.createElement('div');
    row.style.cssText = 'display:flex; gap:8px; flex-wrap:wrap;';
    options.forEach(opt => {
      const b = document.createElement('button');
      b.type = 'button';
      const active = opt.val === selected;
      b.className = 'btn-recovery' + (active ? ' copy-primary' : ' btn-recovery-secondary');
      b.style.cssText = 'flex:1 1 auto; min-width:120px; margin-top:0;' + (active ? '' : ' opacity:0.7;');
      b.textContent = (active ? '✓ ' : '') + opt.label;
      b.addEventListener('click', () => { haptic('light'); onPick(opt.val); });
      row.appendChild(b);
    });
    wrap.appendChild(row);
    return wrap;
  }

  // Кнопка Stars (one-time / recurring) — несёт текущий тариф (devices, months).
  function _starsBtn(label, recurring, secondary) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-recovery copy-primary' + (secondary ? ' btn-recovery-secondary' : '');
    btn.style.marginTop = '8px';
    btn.textContent = label;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      haptic('light');
      try {
        const r = await fetch('/api/billing/create-stars-invoice', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken, devices: payDevices, months: payMonths, recurring }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.invoice_link) {
          haptic('error'); notify(data.error || 'Не удалось создать счёт.'); btn.disabled = false; return;
        }
        if (!tg.openInvoice) {
          haptic('error'); notify('Эта версия Telegram не поддерживает Stars-оплату.'); btn.disabled = false; return;
        }
        tg.openInvoice(data.invoice_link, (status) => {
          btn.disabled = false;
          if (status === 'paid') {
            haptic('success');
            notify(recurring
              ? 'Подписка оформлена. Будет продлеваться автоматически каждый месяц.'
              : 'Оплата получена. Подписка продлена.');
            loadAccount();
          } else if (status === 'cancelled') {
            haptic('warning');
          } else if (status === 'failed') {
            haptic('error'); notify('Платёж не прошёл.');
          }
        });
      } catch (e) {
        haptic('error'); btn.disabled = false;
      }
    });
    return btn;
  }

  function renderPayBlock(d) {
    if (!payBlock) return;
    payBlock.hidden = false;
    payBlock.innerHTML = '';
    acctTariffs = d.tariffs || [];

    const title = document.createElement('div');
    title.className = 'acc-subtitle';
    title.textContent = '💳 Оформить подписку';
    payBlock.appendChild(title);

    // ── Pending-режим: заявка уже отправлена владельцу, ждём решения ─────────
    if (d.pending_claim) {
      const pendingNote = document.createElement('p');
      pendingNote.className = 'section-hint';
      pendingNote.innerHTML = (
        '✅ <b>Заявка на оплату отправлена владельцу.</b> ' +
        'Жди подтверждения — придёт сообщение в этот бот, как только проверит поступление. ' +
        'Обычно в течение часа.'
      );
      payBlock.appendChild(pendingNote);
      return;
    }

    // Fallback на простую ручную оплату, если бэк не прислал тарифы.
    if (!acctTariffs.length) {
      const mbtn = document.createElement('button');
      mbtn.type = 'button';
      mbtn.className = 'btn-recovery copy-primary';
      mbtn.textContent = '💳 Оплатить СБП / картой (Т-Банк)';
      mbtn.addEventListener('click', () => { haptic('light'); renderManualPay(d); showStep(stepManualPay); });
      payBlock.appendChild(mbtn);
      return;
    }

    // Шаг 1: устройства. Шаг 2: срок. Выбор перерисовывает блок (цены/кнопки).
    payBlock.appendChild(_payChooserRow('Устройства', [
      { label: '3 устройства', val: 3 },
      { label: '5 устройств', val: 5 },
    ], payDevices, (v) => { payDevices = v; renderPayBlock(d); }));
    payBlock.appendChild(_payChooserRow('Срок', [
      { label: '1 месяц', val: 1 },
      { label: '3 месяца', val: 3 },
    ], payMonths, (v) => { payMonths = v; renderPayBlock(d); }));

    const t = findTariff(payDevices, payMonths);
    if (!t) return;
    const per = payMonths === 1 ? '' : ` (${Math.round(t.price_rub / payMonths)} ₽/мес)`;
    const priceLine = document.createElement('p');
    priceLine.className = 'section-hint';
    priceLine.style.marginTop = '10px';
    priceLine.innerHTML = `Итого: <b>${t.price_rub} ₽</b>${per} · ${payDevices} устр. · ${t.days} дней`
      + (inTelegram ? ` · или ${t.price_stars} ⭐` : '');
    payBlock.appendChild(priceLine);

    // Stars — только в TG WebApp. Авто-продление — только для 1-месячного тарифа.
    if (inTelegram) {
      payBlock.appendChild(_starsBtn(`⭐ Оплатить ${t.price_stars} ⭐`, false, false));
      if (payMonths === 1) {
        payBlock.appendChild(_starsBtn(`⭐ Подписка ${t.price_stars} ⭐/мес (авто)`, true, true));
      }
    }

    const manualBtn = document.createElement('button');
    manualBtn.type = 'button';
    manualBtn.className = 'btn-recovery btn-recovery-secondary copy-primary';
    manualBtn.style.marginTop = '8px';
    manualBtn.textContent = `💳 Оплатить ${t.price_rub} ₽ СБП / картой`;
    manualBtn.addEventListener('click', () => { haptic('light'); renderManualPay(d); showStep(stepManualPay); });
    payBlock.appendChild(manualBtn);

    // Платный тест «в реальной жизни» — отдельной кнопкой (3 устр., 7 дней, 49 ₽).
    // Разовый: скрываем, если уже использован.
    if (findTariff(3, 0) && !d.test_used) {
      const testBtn = document.createElement('button');
      testBtn.type = 'button';
      testBtn.className = 'btn-recovery btn-recovery-secondary';
      testBtn.style.marginTop = '8px';
      testBtn.style.opacity = '0.85';
      testBtn.textContent = '🧪 Сначала тест — 7 дней за 49 ₽';
      testBtn.addEventListener('click', () => { haptic('light'); renderManualPay(d, 3, 0); showStep(stepManualPay); });
      payBlock.appendChild(testBtn);
    }
  }

  // Отдельный substep stepManualPay: реквизиты + кнопка «✅ Я перевёл деньги».
  // Заполняется в renderAccount (когда d уже есть) — навигация просто показывает заполненный контент.
  function renderManualPay(d, oDev, oMonths) {
    if (!manualPayContent) return;
    manualPayContent.innerHTML = '';
    const mp = d.manual_pay || {};
    const dev = oDev || payDevices;
    const months = (oMonths === 0 || oMonths) ? oMonths : payMonths;
    const t = findTariff(dev, months);
    const rub = t ? t.price_rub : (d.subscription_rub_price || mp.rub || 200);
    const periodTxt = months === 0 ? 'тест 7 дней' : `${months} мес`;

    // Если есть pending-заявка — показываем «ждём подтверждения» вместо реквизитов,
    // чтобы юзер случайно не нажал «Я перевёл» второй раз и не плодил уведомлений.
    if (d.pending_claim) {
      const pendingNote = document.createElement('p');
      pendingNote.className = 'section-hint';
      pendingNote.innerHTML = (
        '✅ <b>Заявка на оплату отправлена владельцу.</b> ' +
        'Жди подтверждения — придёт сообщение в этот бот, как только проверит поступление. ' +
        'Обычно в течение часа.'
      );
      manualPayContent.appendChild(pendingNote);
      return;
    }

    const intro = document.createElement('p');
    intro.className = 'section-hint';
    intro.style.marginTop = '0';
    intro.innerHTML = (
      `Тариф: <b>${dev} устр., ${periodTxt} — ${rub} ₽</b>.<br>` +
      `1. Переведи <b>ровно ${rub} ₽</b> на номер или карту ниже.<br>` +
      `2. Нажми <b>«✅ Я перевёл деньги»</b> — владельцу придёт уведомление.<br>` +
      `3. Он проверит поступление и зачислит подписку (обычно в течение часа).`
    );
    manualPayContent.appendChild(intro);

    if (mp.sbp_phone) {
      const sbpTitle = document.createElement('div');
      sbpTitle.className = 'manual-pay-title';
      sbpTitle.innerHTML = `<b>📱 СБП по телефону</b> — <span class="muted">${mp.sbp_bank || ''}</span>`;
      manualPayContent.appendChild(sbpTitle);
      renderLinkBlock(manualPayContent, mp.sbp_phone, '', 'Скопировать номер');
    }

    if (mp.card) {
      const cardTitle = document.createElement('div');
      cardTitle.className = 'manual-pay-title';
      cardTitle.style.marginTop = '10px';
      cardTitle.innerHTML = `<b>💳 Карта</b> — <span class="muted">${mp.card_bank || ''}</span>`;
      manualPayContent.appendChild(cardTitle);
      const cardDigits = String(mp.card).replace(/\s/g, '');
      renderLinkBlock(manualPayContent, cardDigits, '', 'Скопировать номер карты');
    }

    const claimBtn = document.createElement('button');
    claimBtn.type = 'button';
    claimBtn.className = 'btn-recovery copy-primary';
    claimBtn.style.marginTop = '14px';
    claimBtn.textContent = `✅ Я перевёл ${rub} ₽, подтверди`;
    claimBtn.addEventListener('click', async () => {
      claimBtn.disabled = true;
      haptic('light');
      const prev = claimBtn.textContent;
      claimBtn.textContent = 'Отправляем…';
      try {
        const r = await fetch('/api/billing/claim-payment', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken, source: 'webapp', devices: dev, months: months }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          haptic('error');
          notify(data.error || 'Не удалось отправить заявку.');
          claimBtn.textContent = prev;
          claimBtn.disabled = false;
          return;
        }
        haptic('success');
        notify('Заявка отправлена. Жди подтверждение в этом боте.');
        // Возвращаемся на stepBilling — там pending уже отрисуется
        loadAccount();
        showStep(stepBilling);
      } catch (e) {
        haptic('error');
        notify('Сетевая ошибка.');
        claimBtn.textContent = prev;
        claimBtn.disabled = false;
      }
    });
    manualPayContent.appendChild(claimBtn);
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
        haptic('warning');
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
          haptic('error');
          return;
        }
        msg.style.color = 'var(--green)';
        msg.textContent = 'Пароль сохранён ✅';
        haptic('success');
        inp.value = '';
        setTimeout(() => loadAccount(), 800);
      } catch (e) {
        msg.style.color = 'var(--red)';
        msg.textContent = 'Сетевая ошибка';
        save.disabled = false;
        haptic('error');
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

  // ── Главное меню: 5 разделов (Продлить / Разблокировка TG / Резервные конфиги / Реферал / Настройки)
  const substepMap = {
    billing:  stepBilling,
    proxy:    stepProxy,
    connect:  stepConnect,
    referral: stepReferral,
    settings: stepSettings,
    devices:  stepDevices,
  };
  document.querySelectorAll('[data-substep]').forEach(btn => {
    btn.addEventListener('click', () => {
      haptic('light');
      const key = btn.dataset.substep;
      const target = substepMap[key];
      if (!target) return;
      showStep(target);
      if (key === 'proxy') fetchProxyLink();
      if (key === 'devices') loadDevices();
    });
  });

  // ── Кнопка «🆘 Поддержка» — теперь <a target=_blank>, не <button>.
  // В браузере: нативный клик по ссылке (popup-blocker не работает на user-initiated links).
  // В TG WebApp: перехватываем JS-ом и зовём tg.openTelegramLink — без выхода из TG.
  const btnSupportLink = document.getElementById('btnSupportLink');
  if (btnSupportLink) {
    btnSupportLink.addEventListener('click', (e) => {
      haptic('light');
      if (inTelegram && tg.openTelegramLink) {
        e.preventDefault();
        const supportLink = 'https://t.me/vpnkronos_bot?start=support';
        try { tg.openTelegramLink(supportLink); } catch (_) {}
      }
      // В браузере — preventDefault НЕ вызывается, href сработает естественно.
    });
  }

  // ── «Мои устройства» (Фаза 2 B4 — именованные AmneziaWG-слоты) ─────────────
  // Зеркало бот-флоу callback_devices: список / добавить / обновить / удалить /
  // переименовать. Бэкенд: /api/recovery/devices|device-add|device-regen|
  // device-delete|device-rename (все принимают {token}). Конфиг отдаётся тем же
  // форматом, что awg-config-by-email → renderAwgPayload зеркалит выдачу.
  const _osLabel = { pc: '💻 ПК', ios: '🍎 iOS', android: '🤖 Android' };
  const DEVICE_CAP = 5;

  // Рендер выданного конфига (config/qr/vpn_url) — та же логика, что в
  // [data-platform]-флоу (android → vpn://+QR; в TG → QR+копия; браузер → файл).
  // Кнопка «Не работает» под выданным конфигом (ЛК-аналог бот-флоу «Не работает»):
  // повторяет последнюю генерацию (пересоздаёт устройство / переотдаёт конфиг).
  function appendRetryButton(container) {
    if (!lastConfigRetry) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-recovery btn-recovery-secondary';
    b.style.marginTop = '14px';
    b.textContent = '🔄 Не работает — обновить конфиг';
    b.addEventListener('click', () => { haptic('light'); if (lastConfigRetry) lastConfigRetry(); });
    container.appendChild(b);
  }

  function renderAwgPayload(container, data) {
    const cfg = data.config || '';
    const filename = data.filename || 'awg_eu1.conf';
    const os = data.os || 'pc';
    if (os === 'android' && data.vpn_url) {
      const blockHint = (
        'Тапни ссылку — AmneziaVPN откроет и импортирует конфиг автоматически. ' +
        'Если приложение ещё не установлено — поставь AmneziaVPN из Google Play (amnezia.org).'
      );
      renderLinkBlock(container, data.vpn_url, blockHint, 'Копировать vpn://');
      const aWrap = document.createElement('p');
      aWrap.style.textAlign = 'center';
      aWrap.style.marginTop = '12px';
      const a = document.createElement('a');
      a.href = data.vpn_url;
      a.textContent = '👆 Открыть в AmneziaVPN';
      a.className = 'btn-recovery';
      a.style.display = 'inline-block';
      aWrap.appendChild(a);
      container.appendChild(aWrap);
      const qrSpacer = document.createElement('div');
      qrSpacer.style.height = '20px';
      container.appendChild(qrSpacer);
      renderQr(container, data.qr, 'Или сканируй QR в AmneziaVPN');
    } else if (inTelegram) {
      // PC / iOS в Mini App: скачивание файла не работает → QR + копия конфига.
      const hint = document.createElement('p');
      hint.className = 'section-hint';
      if (os === 'ios') {
        hint.innerHTML = '<b>iPhone / iPad:</b> поставь <b>AmneziaWG</b> из App Store → отсканируй QR ниже. Или скопируй конфиг и добавь вручную.';
      } else {
        hint.innerHTML = '<b>ПК:</b> поставь <b>AmneziaVPN</b> (amnezia.org) → «+» → «Импорт из буфера обмена» (скопируй конфиг ниже).';
      }
      container.appendChild(hint);
      renderQr(container, data.qr, 'Сканируй QR в AmneziaWG');
      renderLinkBlock(container, cfg, '', '📋 Скопировать конфиг');
    } else {
      // Браузер — обычное скачивание файла работает.
      downloadFile(filename, cfg);
      const done = document.createElement('p');
      done.style.color = 'var(--green)';
      done.textContent = 'Готово. Файл ' + filename + ' скачан.';
      container.appendChild(done);
      const hint = document.createElement('p');
      hint.className = 'section-hint';
      if (os === 'ios') {
        hint.innerHTML = '<b>iPhone / iPad:</b> поставь <b>AmneziaWG</b> из App Store, открой файл → «Поделиться» → AmneziaWG → «Создать из файла».';
      } else {
        hint.innerHTML = '<b>ПК:</b> поставь <a href="https://amnezia.org" target="_blank">AmneziaVPN</a>: «+» → «Импорт из файла» → выбери <code>' + filename + '</code>.';
      }
      container.appendChild(hint);
      renderQr(container, data.qr, 'Или сканируй QR в AmneziaWG');
    }
  }

  function _devBtn(label, primary, onClick) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-recovery' + (primary ? ' copy-primary' : ' btn-recovery-secondary');
    b.textContent = label;
    b.addEventListener('click', () => { haptic('light'); onClick(); });
    return b;
  }

  // Нативный confirm: tg.showConfirm в Mini App, window.confirm в браузере.
  function confirmAction(message, cb) {
    if (inTelegram && tg.showConfirm) {
      try { tg.showConfirm(message, (ok) => { if (ok) cb(); }); return; } catch (e) {}
    }
    if (window.confirm(message)) cb();
  }

  async function loadDevices() {
    if (!devicesList) return;
    devicesList.textContent = 'Загружаем…';
    try {
      const r = await fetch('/api/recovery/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: sessionToken }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        devicesList.textContent = 'Не удалось загрузить устройства: ' + (d.error || r.statusText);
        return;
      }
      renderDevicesList(d.devices || [], d.cap || DEVICE_CAP);
    } catch (e) {
      devicesList.textContent = 'Сетевая ошибка при загрузке устройств.';
    }
  }

  function renderDevicesList(devices, cap) {
    devicesList.innerHTML = '';
    if (!devices.length) {
      const p = document.createElement('p');
      p.className = 'section-hint';
      p.style.marginTop = '0';
      p.textContent = 'Пока нет устройств. Добавь первое — каждому девайсу свой независимый конфиг.';
      devicesList.appendChild(p);
    } else {
      const count = document.createElement('p');
      count.className = 'section-hint';
      count.style.marginTop = '0';
      count.textContent = `Устройств: ${devices.length} из ${cap}.`;
      devicesList.appendChild(count);
      devices.forEach((dev) => devicesList.appendChild(renderDeviceRow(dev)));
    }
    if (devices.length < cap) {
      const add = _devBtn('➕ Добавить устройство', true, showAddDeviceChooser);
      add.style.marginTop = '12px';
      devicesList.appendChild(add);
    } else {
      const lim = document.createElement('p');
      lim.className = 'section-hint';
      lim.textContent = `Достигнут лимит ${cap} устройств. Удали лишнее, чтобы добавить новое.`;
      devicesList.appendChild(lim);
    }
  }

  function renderDeviceRow(dev) {
    const row = document.createElement('div');
    row.style.cssText = 'border-top:1px solid rgba(255,255,255,0.1); padding:10px 0;';
    const title = document.createElement('div');
    title.style.cssText = 'font-weight:600; margin-bottom:6px;';
    title.textContent = `${_osLabel[dev.os] || dev.os} · ${dev.name}`;
    row.appendChild(title);
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex; gap:8px; flex-wrap:wrap;';
    [
      _devBtn('✏️ Имя', false, () => renameDevice(dev)),
      _devBtn('🔄 Обновить', false, () => regenDevice(dev)),
      _devBtn('🗑 Удалить', false, () => deleteDevice(dev)),
    ].forEach((b) => {
      b.style.cssText += 'flex:1 1 auto; min-width:96px; margin-top:0; padding:9px 6px; font-size:0.85em;';
      actions.appendChild(b);
    });
    row.appendChild(actions);
    return row;
  }

  function showAddDeviceChooser() {
    devicesList.innerHTML = '';
    const p = document.createElement('p');
    p.className = 'section-hint';
    p.style.marginTop = '0';
    p.textContent = 'Тип нового устройства (определяет формат конфига):';
    devicesList.appendChild(p);
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex; gap:8px; flex-wrap:wrap;';
    [['pc', '💻 ПК'], ['ios', '🍎 iOS'], ['android', '🤖 Android']].forEach(([os, label]) => {
      const b = _devBtn(label, true, () => addDevice(os));
      b.style.cssText += 'flex:1 1 auto; min-width:96px;';
      wrap.appendChild(b);
    });
    devicesList.appendChild(wrap);
    const cancel = _devBtn('« Отмена', false, loadDevices);
    cancel.style.marginTop = '10px';
    devicesList.appendChild(cancel);
  }

  function _showDeviceResult(title, statusText) {
    if (deviceResultTitle) deviceResultTitle.textContent = title;
    showStep(stepDeviceResult);
    deviceResult.innerHTML = '';
    if (statusText) {
      const s = document.createElement('p');
      s.style.color = 'var(--green)';
      s.textContent = statusText;
      deviceResult.appendChild(s);
    }
  }

  function _deviceResultError(msg) {
    deviceResult.innerHTML = '';
    const e = document.createElement('p');
    e.style.color = 'var(--red)';
    e.textContent = 'Ошибка: ' + msg;
    deviceResult.appendChild(e);
  }

  async function addDevice(os) {
    _showDeviceResult('📲 Новое устройство', 'Создаём конфиг…');
    try {
      const r = await fetch('/api/recovery/device-add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: sessionToken, os }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _deviceResultError(d.error || r.statusText); haptic('error'); return; }
      haptic('success');
      deviceResult.innerHTML = '';
      const ok = document.createElement('p');
      ok.style.color = 'var(--green)';
      ok.textContent = `✅ Добавлено устройство «${d.name || ''}». Импортируй конфиг в AmneziaWG / AmneziaVPN.`;
      deviceResult.appendChild(ok);
      renderAwgPayload(deviceResult, d);
      lastConfigRetry = () => regenDevice({ device_id: d.device_id, os: d.os, name: d.name });
      appendRetryButton(deviceResult);
      loadDevices();  // обновить скрытый список к моменту «« Назад»
    } catch (e) {
      _deviceResultError((e && e.message) || e);
    }
  }

  async function regenDevice(dev) {
    _showDeviceResult(`🔄 ${dev.name}`, 'Пересоздаём конфиг…');
    try {
      const r = await fetch('/api/recovery/device-regen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: sessionToken, device_id: dev.device_id }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { _deviceResultError(d.error || r.statusText); haptic('error'); return; }
      haptic('success');
      deviceResult.innerHTML = '';
      const ok = document.createElement('p');
      ok.style.color = 'var(--green)';
      ok.textContent = `🔄 Конфиг «${dev.name}» пересоздан. Старый перестал работать — импортируй новый.`;
      deviceResult.appendChild(ok);
      renderAwgPayload(deviceResult, d);
      lastConfigRetry = () => regenDevice(dev);
      appendRetryButton(deviceResult);
      loadDevices();
    } catch (e) {
      _deviceResultError((e && e.message) || e);
    }
  }

  function deleteDevice(dev) {
    confirmAction(`Удалить устройство «${dev.name}»? Его конфиг перестанет работать.`, async () => {
      try {
        const r = await fetch('/api/recovery/device-delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken, device_id: dev.device_id }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { notify('Не удалось удалить: ' + (d.error || r.statusText)); return; }
        haptic('success');
        loadDevices();
      } catch (e) {
        notify('Сетевая ошибка при удалении.');
      }
    });
  }

  function renameDevice(dev) {
    // Inline-форма (window.prompt недоступен в TG Mini App).
    devicesList.innerHTML = '';
    const p = document.createElement('p');
    p.className = 'section-hint';
    p.style.marginTop = '0';
    p.textContent = `Новое имя для «${dev.name}»:`;
    devicesList.appendChild(p);
    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 40;
    input.value = dev.name;
    input.style.cssText = 'width:100%; box-sizing:border-box; padding:10px; margin-bottom:10px; border-radius:8px; border:1px solid rgba(255,255,255,0.2); background:rgba(255,255,255,0.05); color:inherit; font-size:1em;';
    devicesList.appendChild(input);
    const save = _devBtn('💾 Сохранить', true, async () => {
      const name = (input.value || '').trim().slice(0, 40);
      if (!name) { notify('Имя не может быть пустым.'); return; }
      save.disabled = true;
      try {
        const r = await fetch('/api/recovery/device-rename', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: sessionToken, device_id: dev.device_id, name }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { notify('Не удалось переименовать: ' + (d.error || r.statusText)); save.disabled = false; return; }
        haptic('success');
        loadDevices();
      } catch (e) {
        notify('Сетевая ошибка при переименовании.');
        save.disabled = false;
      }
    });
    devicesList.appendChild(save);
    const cancel = _devBtn('« Отмена', false, loadDevices);
    cancel.style.marginTop = '8px';
    devicesList.appendChild(cancel);
    try { input.focus(); } catch (e) {}
  }

  // ── Резервные конфиги: выбор канала (в stepConnect) — только VPN-каналы.
  // MTProxy переехал в главное меню (см. data-substep="proxy").
  document.querySelectorAll('[data-channel]').forEach(btn => {
    btn.addEventListener('click', () => {
      const ch = btn.dataset.channel;
      if (ch === 'awg') {
        if (awgResult) awgResult.innerHTML = '';
        showStep(stepPlatform);
      } else if (ch === 'mobile') {
        if (mobileResult) mobileResult.innerHTML = '';
        showStep(stepOperator);
      }
    });
  });

  // Кнопки «« Назад» в подстраницах — возвращают на родительский шаг.
  document.querySelectorAll('[data-back]').forEach(btn => {
    btn.addEventListener('click', () => {
      const p = stepParent.get(currentStep);
      if (p) showStep(p);
    });
  });

  // ── Шаг 4a: Платформа → AmneziaWG (открывается в substep stepAwgResult) ──
  const _platformLabels = { pc: 'ПК', ios: 'iPhone / iPad', android: 'Android' };
  document.querySelectorAll('[data-platform]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const platform = btn.dataset.platform;
      if (!awgResult) return;

      // Переходим на новую страницу-результат, заголовок — по выбранному устройству.
      if (awgResultTitle) {
        awgResultTitle.textContent = `📲 Основной VPN — ${_platformLabels[platform] || platform}`;
      }
      showStep(stepAwgResult);
      awgResult.innerHTML = '';
      const status = document.createElement('p');
      status.style.color = 'var(--green)';
      status.textContent = 'Генерируем конфиг…';
      awgResult.appendChild(status);

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
          // Android: vpn:// deep link → копи-кнопка + центрированная кнопка «Открыть» + QR
          status.remove();
          // Plain-text hint (renderLinkBlock использует textContent — HTML-теги бы показались сырым текстом).
          const blockHint = (
            'Тапни ссылку — AmneziaVPN откроет и импортирует конфиг автоматически. ' +
            'Если приложение ещё не установлено — поставь AmneziaVPN из Google Play (amnezia.org).'
          );
          renderLinkBlock(awgResult, data.vpn_url, blockHint, 'Копировать vpn://');

          const aWrap = document.createElement('p');
          aWrap.style.textAlign = 'center';
          aWrap.style.marginTop = '12px';
          const a = document.createElement('a');
          a.href = data.vpn_url;
          a.textContent = '👆 Открыть в AmneziaVPN';
          a.className = 'btn-recovery';
          a.style.display = 'inline-block';
          aWrap.appendChild(a);
          awgResult.appendChild(aWrap);

          // Больший пробел между кнопкой и QR
          const qrSpacer = document.createElement('div');
          qrSpacer.style.height = '20px';
          awgResult.appendChild(qrSpacer);

          renderQr(awgResult, data.qr, 'Или сканируй QR в AmneziaVPN');
        } else if (inTelegram) {
          // PC / iOS в Telegram Mini App: скачивание файла НЕ работает (WebApp открывает
          // файл, а не качает). Даём QR (скан в приложении) + копию конфига текстом.
          status.remove();
          const hint = document.createElement('p');
          hint.className = 'section-hint';
          if (platform === 'ios') {
            hint.innerHTML = '<b>iPhone / iPad:</b> поставь <b>AmneziaWG</b> из App Store → отсканируй QR ниже в приложении. Или скопируй конфиг и добавь вручную.';
          } else {
            hint.innerHTML = '<b>ПК:</b> поставь <b>AmneziaVPN</b> (amnezia.org) → отсканируй QR, либо скопируй конфиг и в приложении «+» → «Импорт из буфера обмена».';
          }
          awgResult.appendChild(hint);
          renderQr(awgResult, data.qr, 'Сканируй QR в AmneziaWG');
          renderLinkBlock(awgResult, cfg, '', '📋 Скопировать конфиг');
        } else {
          // Браузер — обычное скачивание файла работает.
          downloadFile(filename, cfg);
          status.textContent = 'Готово. Файл ' + filename + ' скачан.';
          status.style.color = 'var(--green)';

          const hint = document.createElement('p');
          hint.className = 'section-hint';
          if (platform === 'ios') {
            hint.innerHTML = (
              '<b>iPhone / iPad:</b> поставь <b>AmneziaWG</b> из App Store, открой файл → «Поделиться» → AmneziaWG → «Создать из файла» → включи туннель.'
            );
          } else {
            hint.innerHTML = (
              '<b>ПК:</b> поставь <a href="https://amnezia.org" target="_blank">AmneziaVPN</a>, в приложении: «+» → «Импорт из файла» → выбери <code>' + filename + '</code> → включи туннель.'
            );
          }
          awgResult.appendChild(hint);
          renderQr(awgResult, data.qr, 'Или сканируй QR в AmneziaWG');
        }
        lastConfigRetry = () => btn.click();
        appendRetryButton(awgResult);
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

      // Переход на substep с заголовком по оператору.
      const _operatorLabels = {
        yota: 'Yota', megafon: 'Мегафон', mts: 'МТС', beeline: 'Билайн',
        tele2: 'Т2', tmobile: 'Т-Мобайл', other: 'Другой оператор',
      };
      if (mobileResultTitle) {
        mobileResultTitle.textContent = `📡 VPN при блокировках — ${_operatorLabels[operator] || operator}`;
      }
      showStep(stepMobileResult);
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
        if (!link) {
          setMsg(status, 'Сервер не вернул ссылку.', true);
          return;
        }

        status.remove();
        // Унифицированный порядок и тексты для всех операторов:
        // 1. QR + caption
        // 2. spacer
        // 3. инструкция «Скопируй vless://...»
        // 4. ссылка-блок
        renderQr(mobileResult, data.qr, 'Сканируй QR в приложении');

        const spacer = document.createElement('div');
        spacer.style.height = '12px';
        mobileResult.appendChild(spacer);

        const inst = document.createElement('p');
        inst.className = 'section-hint';
        inst.innerHTML = (
          'Скопируй <code>vless://</code>... целиком.<br>' +
          'Импортируй в <b>Happ</b> (happ.su): «+» → «Импорт из буфера».'
        );
        mobileResult.appendChild(inst);

        renderLinkBlock(mobileResult, link, '', 'Копировать ссылку');
        lastConfigRetry = () => btn.click();
        appendRetryButton(mobileResult);
      } catch (err) {
        setMsg(status, 'Сетевая ошибка: ' + (err.message || err), true);
      } finally {
        document.querySelectorAll('[data-operator]').forEach(b => b.disabled = false);
      }
    });
  });

  // ── Шаг 4c: MTProxy (прокси для Telegram) ─────────────────────────────────
  // Возвращён 2026-06-09 (РКН-волна по прокси спала). + фолбэк-подсказка на VPN.
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
      openA.addEventListener('click', (e) => {
        haptic('light');
        if (inTelegram && tg.openTelegramLink) {
          e.preventDefault();
          try { tg.openTelegramLink(link); } catch (_) {}
        }
      });
      proxyResult.appendChild(openA);
      renderLinkBlock(proxyResult, link, '', '📋 Копировать tg://');

      const fb = document.createElement('p');
      fb.className = 'section-hint';
      fb.style.marginTop = '10px';
      fb.textContent = 'Если прокси не подключается у оператора — используй «Подключить VPN»: он тоже открывает Telegram.';
      proxyResult.appendChild(fb);
    } catch (err) {
      setMsg(status, 'Сетевая ошибка: ' + (err.message || err), true);
    }
  }
});
