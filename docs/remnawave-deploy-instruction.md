# Пошаговая установка Remnawave на VPS

Инструкция для развёртывания Remnawave (панель + Xray VLESS/Reality) на сервере. Используется скрипт из репозитория [eGamesAPI/remnawave-reverse-proxy](https://github.com/eGamesAPI/remnawave-reverse-proxy).

**Требования:** Ubuntu или Debian; root или sudo; **домен** с возможностью создать 3 поддомена (panel, sub, node). Порты 80 и 443 должны быть свободны.

**Сервер:** Развёртывание на **eu1 (Fornex, 185.21.8.91)** — один оплаченный VPS; порты 80/443 должны быть свободны для NGINX/Xray (проверить перед установкой).

---

## Где взять домен

| Вариант | Описание |
|--------|----------|
| **Свой домен** | Если уже есть домен (.ru, .com и т.д.) — создать 3 поддомена (panel, sub, node) и направить их на IP eu1 (185.21.8.91). |
| **Дёшево** | Reg.ru, Timeweb, Beget, Namecheap — .ru от ~100–200 ₽/год, .com от ~500–800 ₽/год. |
| **Cloudflare** | Регистрация/перенос домена по себестоимости (~$10–12/год), плюс бесплатный DNS. |
| **Бесплатно (для теста)** | **DuckDNS** — бесплатный поддомен вида `твой-ник.duckdns.org`. В панели DuckDNS можно добавить несколько поддоменов и привязать их к одному IP (185.21.8.91). Тогда использовать, например: `panel.твой-ник.duckdns.org`, `sub.твой-ник.duckdns.org`, `node.твой-ник.duckdns.org`. |
| **Freenom** | Бесплатные .tk, .ml, .ga — нестабильны, могут отобрать; только для быстрой проверки. |

**Рекомендация:** Свой домен или недорогой .ru — лучше для долгой работы. Для быстрого старта — DuckDNS (бесплатно, один раз настроил поддомены и ставишь Remnawave).

---

## 1. Подготовка домена

Перед установкой нужны DNS-записи. Пример для домена `vpn.example.com` и сервера с IP `185.21.8.91`:

| Тип  | Имя   | Значение     | Прокси (Cloudflare) |
|------|--------|--------------|----------------------|
| A    | vpn   | 185.21.8.91  | DNS only             |
| CNAME| panel | vpn.example.com | DNS only          |
| CNAME| sub   | vpn.example.com | DNS only          |
| CNAME| node  | vpn.example.com | DNS only          |

Или три отдельных A-записи: `panel.vpn.example.com`, `sub.vpn.example.com`, `node.vpn.example.com` → IP сервера.

**Важно:** Скрипт спросит домены для панели, подписок и ноды — подготовьте их (например, `panel.vpn.example.com`, `sub.vpn.example.com`, `node.vpn.example.com`).

---

## 2. Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 3. Установка Remnawave

Запуск установочного скрипта:

```bash
sudo bash -c "bash <(curl -Ls https://raw.githubusercontent.com/eGamesAPI/remnawave-reverse-proxy/refs/heads/main/install_remnawave.sh)"
```

В процессе выбора:

1. Выбрать **«Install Remnawave Components»** (или эквивалент установки компонентов Remnawave).
2. Режим: **«Install panel and node on one server»** (панель и нода на одном сервере).
3. **Сертификат:** выбрать **вариант 2 — ACME** (без Cloudflare API).
4. Ввести запрошенные домены (panel, sub, node) согласно подготовленным DNS.

Дождаться окончания установки. Скрипт выведет данные для входа в панель — **сохранить логин и пароль**.

---

## 4. (По желанию) Отключение IPv6

Чтобы геолокация была единой (только IPv4), можно отключить IPv6:

```bash
cat << 'EOF' | sudo tee /etc/systemd/system/disable-ipv6.service > /dev/null
[Unit]
Description=Disable IPv6
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/sysctl -w net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now disable-ipv6.service
```

---

## 5. Проверка после установки

1. Войти в панель по URL вида `https://panel.vpn.example.com` (с параметром доступа, если скрипт его настроил — см. документацию репозитория).
2. Создать тестового пользователя: **Users → Create user** — указать имя, лимит трафика, срок подписки, назначить Squad.
3. Скопировать **subscription URL** (иконка ссылки у пользователя или через Edit user).
4. Открыть ссылку в браузере — должна открыться страница подписки (JSON или список конфигов).
5. Импортировать подписку в клиент (например, Clash Verge Rev, Nekoray) и проверить подключение с ПК и с телефона (iOS/Android).

---

## 6. Интеграция с ботом

- **Вариант с API:** Получить API token в панели (если доступен) и прописать в `env_vars.txt` на сервере бота: `REMNAWAVE_PANEL_URL`, `REMNAWAVE_API_TOKEN`. Бот будет создавать пользователей и получать subscription URL по API.
- **Вариант без API (одна ссылка):** Создать в панели одного пользователя (или общий Squad), скопировать его subscription URL и прописать в `env_vars.txt`: `REMNAWAVE_SUBSCRIPTION_URL`. Бот будет отправлять эту ссылку всем при /get_config для Европы.

Подробнее: **`docs/specs/spec-06-remnawave-eu1-bot.md`**.

---

## 7. Полезные ссылки

- Репозиторий скрипта: https://github.com/eGamesAPI/remnawave-reverse-proxy  
- Документация Remnawave: https://docs.rw  
- Спек бота и Европы: `docs/specs/spec-06-remnawave-eu1-bot.md`
