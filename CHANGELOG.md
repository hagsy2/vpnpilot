# Changelog

Все заметные изменения проекта. Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [0.2.0-beta] — 2026-06-15

### Добавлено
- Патчноут при обновлении: диалог обновления показывает список изменений
  (коммиты + секция CHANGELOG) перед установкой. Эндпоинт `/api/changelog`.

### Изменено
- Контейнер в Proxmox теперь по умолчанию называется `vpnpilot` (было `ha-vpn-auto`).

[0.2.0-beta]: https://github.com/hagsy2/vpnpilot/releases/tag/v0.2.0-beta

## [0.1.0-beta] — 2026-06-15

Первый публичный бета-релиз.

### Добавлено
- Веб-панель установки VPN по SSH (IP + пароль), авто-определение ОС.
- 7 протоколов: WireGuard, OpenVPN, VLESS+Reality, 3X-UI, Shadowsocks, Outline, IKEv2.
- QR-коды и конфиг-файлы сразу после установки.
- Управление клиентами (добавить/удалить) для поддерживаемых протоколов.
- Полный снос VPN с сервера.
- **Переустановка начисто** для сохранённых серверов (чинит зависшие установки).
- **Проверка обновлений** из UI: сверка с GitHub + `git pull` + перезапуск.
- CLI-команда `vpnpilot-update` как фолбэк.
- Мульти-провайдерный AI-помощник (Groq / Gemini / OpenRouter / DeepSeek).
- Установщики: `install.sh` (контейнер/VM) и `proxmox-install.sh` (создаёт LXC).

### Исправлено
- Зависание SSH: `run_command_stream` больше не блокируется навсегда после
  таймаута; добавлен idle-таймаут (прерывает молчащий установщик, как Outline).
- Outline: игнорируется ошибка Watchtower в unprivileged LXC, проверяется
  только Shadowbox.
- `/api/version` устойчив к приватному репозиторию (локальная версия не зависит
  от сетевой проверки); `GIT_TERMINAL_PROMPT=0` — git не виснет на запросе пароля.

[0.1.0-beta]: https://github.com/hagsy2/vpnpilot/releases/tag/v0.1.0-beta
