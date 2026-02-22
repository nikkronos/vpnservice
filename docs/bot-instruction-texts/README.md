# Тексты инструкций для VPN-бота

Короткие пошаговые инструкции для отправки пользователю в Telegram (plain text).

## Файлы

- **instruction_pc_short.txt** — подключение на ПК (Windows): WireGuard, импорт конфига, подключение.
- **instruction_ios_short.txt** — подключение на iPhone/iPad: WireGuard, импорт конфига, включение туннеля.
- **instruction_android_short.txt** — подключение на Android: WireGuard (Россия) или AmneziaVPN/AmneziaWG (Европа).
- **instruction_mtproto_short.txt** — как добавить MTProto-прокси в Telegram (без VPN).

## Использование в боте

1. Читать файлы при старте бота или по требованию (например, по команде «Инструкция» или после выдачи конфига).
2. Ссылку MTProto подставлять из переменной окружения `MTPROTO_PROXY_LINK` (формат: `tg://proxy?server=...&port=443&secret=...`).
3. При выборе платформы (ПК / iPhone–iPad / Android) отправлять соответствующий текст; при необходимости отправлять все варианты.

## Обновление

При изменении шагов в `docs/client-instructions-pc.md`, `docs/client-instructions-ios.md` или `docs/client-instructions-android.md` обновить соответствующий `instruction_*_short.txt` и задеплоить бота.
