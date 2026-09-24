# Linux Admin — отчёт по аудиту безопасности

**Дата:** 2026-07-24  
**Объект:** репозиторий `/apps/linux-admin`  
**Метод:** статический анализ исходного кода, конфигураций развёртывания и документации  
**Ограничения:** разрушительные проверки на живом хосте не выполнялись; статус «подтверждена» означает подтверждение в коде/конфиге репозитория

---

# Часть A. Карта архитектуры (фаза 1)

## A.1 Краткое понимание архитектуры

Linux Admin — **локальная** веб-панель администрирования **одного** Linux-хоста.

```text
Браузер / интеграция
  → HTTP REST + WebSocket (/ws/metrics)
    → FastAPI (uvicorn)
      → JWT или API key (SHA-256 hash)
        → RBAC (none|read|full per module)
          → allow_mutations (PostgreSQL app_settings)
            → collectors (psutil / subprocess / sudo -n)
              → Linux: systemd, Fail2ban, ufw/firewalld, Docker CLI,
                       OS users, SSH tunnels, WireGuard, OpenVPN
```

Один процесс обслуживает API и production SPA (`src/frontend/dist`). Bind по умолчанию `127.0.0.1:8000`. Мутации **выключены по умолчанию**, но при включении и наличии sudo панель фактически даёт **ограниченный root через веб**.

## A.2 Найденные компоненты

| Компонент | Путь |
|-----------|------|
| Backend entry | `src/backend/app/main.py` → `create_app()` / `app` |
| Auth / JWT | `src/backend/app/core/auth.py` |
| Principal / API keys / RBAC deps | `src/backend/app/core/principal.py` |
| Permissions catalog | `src/backend/app/core/permissions.py` |
| Settings / modules | `src/backend/app/core/config.py`, `services/persistence.py` |
| Setup wizard | `src/backend/app/api/setup.py`, `core/setup_state.py` |
| Rate limit | `src/backend/app/core/rate_limit.py` |
| Collectors | `src/backend/app/collectors/*` |
| Privileged exec | `src/backend/app/collectors/_exec.py` |
| Worker / WS hub | `src/backend/app/services/worker.py`, `ws_hub.py` |
| Frontend | `src/frontend/src/*` |
| Deploy | `deploy/lnxadmin.service`, `deploy/nginx.example.conf` |
| Security check script | `scripts/check_security.py` |
| Docs | `README.md`, `SECURITY.md` |

**Отсутствует в репозитории:** готовый файл sudoers (только примеры в README), механизм audit-log в БД/коде.

## A.3 Модули RBAC

`overview`, `history`, `fail2ban`, `firewall`, `docker`, `network`, `disks`, `users`, `services`, `postgres`, `ssh_tunnel`, `wireguard`, `openvpn`, `settings`, `settings_modules`, `settings_connection`, `settings_access`.

Уровни: `none` / `read` / `full`. Superadmin обходит проверки (`Principal.can` → True).

## A.4 Административные функции (мутации хоста)

| Модуль | Операции |
|--------|----------|
| Fail2ban | ban/unban, reload, start/stop/restart, ignoreip, set-params + persist jail.d |
| Firewall | ufw enable/disable/reload/allow/deny/…; firewalld ports/services |
| Network | iface up/down, kill PID |
| Users | useradd/userdel, lock, shell, groups, password, groups CRUD |
| Services | systemctl start/stop/restart/reload/enable/disable |
| SSH Tunnel | useradd tun-*, sshd drop-in, authorized_keys + permitopen, keygen |
| WireGuard | apt/dnf install, wg-quick, peers, client conf+private key |
| OpenVPN | package install, server/clients, .ovpn + keys |
| Settings | allow_mutations, module options, DB connection, JWT rotate |
| Access | panel users/roles/API keys |
| Postgres monitor | connection settings (без allow_mutations) |

Docker в коде — **только чтение** (нет mutation endpoints).

## A.5 REST и WebSocket endpoints (инвентаризация)

### Без аутентификации

| Метод | Путь | Риск |
|-------|------|------|
| GET | `/api/health` | Low (env/configured) |
| GET | `/api/setup/status` | Medium (bind, suggested DB user) |
| POST | `/api/setup/test-db` | High до завершения setup |
| POST | `/api/setup/complete` | Critical до завершения setup |
| POST | `/api/auth/login` | Auth surface |
| GET | `/`, SPA assets | — |
| GET | `/docs`, `/redoc`, `/openapi.json` | High если production docs включены |

### WebSocket

| Путь | Auth | Права |
|------|------|-------|
| `/ws/metrics` | первое сообщение `{"type":"auth","token"}` | `overview:read` |

### Защищённые (сводка)

Роутеры с `Depends(require_module(...))` на уровне router/handler:  
`/api/system/snapshot`, `/api/history/*`, `/api/security/*`, `/api/docker/*`, `/api/network/*`, `/api/disks/*`, `/api/users/*`, `/api/services/*`, `/api/postgres/*`, `/api/ssh-tunnel/*`, `/api/wireguard/*`, `/api/openvpn/*`, `/api/settings/*`, `/api/access/*`, `/api/setup/connection*`.

Критичные GET с секретами при одном только **read**:

- `GET /api/wireguard/peers/{id}/config` — PrivateKey в ответе  
- `GET /api/openvpn/clients/{id}/config` — клиентский конфиг с ключами  
- `GET /api/disks/browse?path=` — обзор ФС (метаданные)

## A.6 Системные бинарники (через subprocess / sudo -n)

`fail2ban-client`, `ufw`, `firewall-cmd`, `systemctl`, `ip`, `kill`, `docker`, `useradd`, `usermod`, `userdel`, `groupadd`, `groupdel`, `chpasswd`, `passwd`, `sshd`, `ssh-keygen`, `wg`, `wg-quick`, `openvpn`, `openssl`, `apt-get`/`dnf`/`yum`/`apk`/`pacman`/`zypper`, `sysctl`, `iptables`, `install`, `mkdir`, `chmod`, `chown`, `rm`, `du`, `journalctl`, `tee` (по путям в collectors).

Обёртка: `asyncio.create_subprocess_exec` / `subprocess.run` — **без shell=True** в просмотренном коде. Привилегии: `sudo -n <argv>`.

## A.7 Модель прав

```text
аутентификация (JWT | API key)
AND роль.module >= need (или is_superadmin)
AND (для мутаций) modules[module].allow_mutations == true
AND (для API key) permissions ∩ role  (ключ не расширяет права)
```

Права JWT **перечитываются из БД** на каждый запрос (`resolve_bearer` → User+Role). Claims JWT содержат только `sub` + `exp`.

## A.8 Предварительная модель угроз

| # | Нарушитель | Главный риск |
|---|------------|--------------|
| 1–2 | Сеть / открытый порт | Setup до complete; brute force login |
| 3 | Viewer (read) | VPN private keys; disks browse; host recon |
| 4–5 | Ограниченный full / API key | Модульные мутации при allow_mutations |
| 6 | Утечка API key | То же, что у владельца ключа |
| 9–11 | PostgreSQL / .env / backup | JWT secret, DB password, admin password plaintext |
| 12 | Docker socket на хосте | Вне панели — полный root (панель socket не мутирует) |
| 15 | Админ панели | Нет audit trail — сокрытие действий |
| 16–17 | Украденный WG/OVPN/SSH tunnel | Доступ во внутренние сети / permitopen targets |
| 18 | Setup wizard | Полный bootstrap + superadmin |

## A.9 План дальнейшего аудита

1. JWT / API keys / RBAC / allow_mutations / Setup — **выполнено**  
2. Command injection / sudoers examples / services / users — **выполнено**  
3. Docker / Firewall / Fail2ban / VPN / SSH — **выполнено**  
4. Frontend XSS / token storage — частично  
5. Цепочки атак + оценки + план исправлений — ниже  

---

# Часть B. Резюме для руководства

## 1. Общий вердикт

Продукт осознанно проектируется как **привилегированная ops-панель**: bind localhost, мутации off by default, RBAC, production refuse weak secrets, rate-limit login/setup — это сильная база.

При этом обнаружены **подтверждённые** проблемы, из-за которых:

- пользователь с **read** на WireGuard/OpenVPN может скачать **приватные ключи клиентов**;
- в коде **нет журнала аудита** действий;
- рекомендуемый sudoers в README даёт фактически **неограниченный root** (`systemctl`, `apt-get` без аргументов);
- при включённых мутациях модуль OS Users позволяет добавить учётку в группу `sudo`/`docker`.

**Готовность к production:** допустима **только** за VPN/SSH-туннелем на `127.0.0.1`, с узким sudoers и выключенными мутациями, после исправления выдачи VPN-ключей по read.  
**Публикация в интернет:** **недопустима**.  
**Вероятность получения root при компрометации панели с мутациями + широким sudoers:** **высокая**.

## 2. Оценки (0–10)

| Область | Оценка | Комментарий |
|---------|--------|-------------|
| Архитектура | 7 | Чёткое разделение collectors/API/RBAC |
| JWT | 6 | HS256+DB reload OK; нет revoke/refresh |
| API-ключи | 7 | Hash+prefix; пересечение прав |
| RBAC | 7 | Централизовано; settings_access мощный |
| allow_mutations | 7 | Fail-closed на мутациях; не везде |
| Setup Wizard | 7 | localhost/token; race/legacy heuristics |
| FastAPI | 7 | Headers, CORS, docs off in prod |
| WebSocket | 5 | Auth OK; нет Origin/лимитов/re-auth |
| Системные команды | 7 | argv lists, валидация имён |
| sudoers | 2 | Только опасные примеры в README |
| systemd | 6 | Hardening есть; конфликт с sudo |
| Docker | 8 | Read-only API |
| Firewall | 6 | disable возможен при full+mutations |
| Fail2ban | 6 | stop возможен при full+mutations |
| SSH Tunnel | 7 | ForceCommand+permitopen; destinations произвольные |
| WireGuard | 4 | PrivateKey на GET read |
| OpenVPN | 4 | Config на GET read |
| PostgreSQL | 5 | settings PUT без allow_mutations |
| Frontend | 6 | sessionStorage; CSP с unsafe-inline |
| Аудит | 1 | Механизм отсутствует |
| Развёртывание | 6 | Хорошие defaults, слабые sudoers docs |
| Секреты | 5 | .env plaintext admin/DB password |
| Зависимости | 6 | Pinning заявлен; полный SCA не делался |

## 3. Статистика находок

| Severity | Count |
|----------|------:|
| Critical | 3 |
| High | 6 |
| Medium | 9 |
| Low | 5 |
| Informational | 3 |

## 4. Пять наиболее опасных проблем

1. **VPN private keys на read** — viewer скачивает WG/OVPN → сеть/VPN. Исправление: среднее.  
2. **Широкий sudoers из README** — `systemctl`/`apt-get` без аргументов → root. Исправление: документация + шаблон.  
3. **OS Users → sudo/docker group** — при mutations → root. Исправление: allowlist групп.  
4. **Нет audit log** — нельзя расследовать злоупотребления. Исправление: среднее–крупное.  
5. **Firewall disable / Fail2ban stop** — снятие защиты хоста. Исправление: отдельные права / deny list.

## 5. Цепочки атак (подтверждённые комбинации)

### C1. Viewer → VPN → внутренняя сеть

```text
Учётка с wireguard:read или openvpn:read
→ GET .../config
→ PrivateKey / .ovpn
→ подключение к VPN с маршрутами клиента
```

### C2. settings_access:full → суперправа без is_superadmin

```text
settings_access:full
→ POST /api/access/roles (все module:full)
→ назначить роль пользователю
→ включить allow_mutations (если есть settings_modules:full)
→ мутации хоста
```

### C3. users:full + allow_mutations + sudoers useradd/usermod → root

```text
POST /api/users (группы: sudo)
или POST .../groups с sudo
→ локальный privileged login / sudo
→ полный контроль хоста
```

### C4. services/firewall/fail2ban:full + mutations → снятие защиты

```text
POST firewall/action disable
и/или fail2ban/action stop
и/или systemctl stop ssh/fail2ban
→ упрощение дальнейшей эксплуатации
```

### C5. Компрометация .env / PostgreSQL

```text
Чтение .env (LNXADMIN_JWT_SECRET, DB password, admin password)
→ подделка JWT или вход
→ полный доступ к панели
```

### C6. Setup до завершения на reachable host

```text
LNXADMIN_SETUP_COMPLETE=false, нет SETUP_TOKEN, не production loopback-only bypass
→ POST /api/setup/complete
→ свой superadmin + JWT secret
```

## 6. Блокирующие проблемы до production

1. Запретить выдачу VPN/SSH private material на `read` (нужен `full` + ideally re-auth).  
2. Не использовать README-sudoers as-is; поставить argument-restricted sudoers.  
3. Allowlist групп/shells для OS Users.  
4. Панель только `127.0.0.1` + VPN/SSH; не публиковать `:8000`.  
5. Установить `LNXADMIN_SETUP_TOKEN` до первого открытия, если хост доступен.  
6. Добавить audit log хотя бы для мутаций и access/settings.  
7. Убрать plaintext `LNXADMIN_ADMIN_PASSWORD` из `.env` после создания пользователя (или не хранить).

## 7. План исправлений

### Немедленно

- Ограничить `GET` VPN configs правом `full` (+ аудит).  
- Заменить примеры sudoers на argument-scoped.  
- Deny-list групп `sudo`, `wheel`, `docker`, `root` в users API.  
- Убедиться: bind `127.0.0.1`, mutations off, setup complete + token.

### 7 дней

- Audit log (кто/что/когда/результат/IP).  
- JWT revoke / version / shorter TTL; инвалидация при смене пароля.  
- WebSocket: Origin allowlist, лимит соединений, периодическая re-auth.  
- `allow_mutations` для postgres settings PUT.  
- Default-deny для `systemctl` на критичных unit'ах.

### 30 дней

- MFA для панели.  
- Step-up auth для VPN key download / user create / firewall disable.  
- Внешний SIEM sink для аудита.  
- Автотесты negative RBAC в CI.

### Следующие версии

- Capability-based sudo helpers вместо broad sudo.  
- Отдельный unprivileged collector + privileged agent с allowlist IPC.  
- mTLS к панели.

## 8. Рекомендуемая схема размещения

```text
Администратор
  → VPN или SSH tunnel
    → Nginx/Caddy TLS (+ IP allowlist / mTLS)
      → Linux Admin 127.0.0.1:8000 (OS user lnxadmin)
        → узкий sudoers (команды+аргументы)
          → подсистемы Linux
PostgreSQL: localhost only, отдельный роль без SUPERUSER
Audit: PostgreSQL + опционально syslog/remote
.env: 0600, владелец сервиса; без долгоживущего plaintext admin password
Docker: socket только если нужен read; не давать панели привилегированный docker без нужды
```

## 9–10. Матрицы прав / sudoers

См. приложение в конце отчёта.

## 11. План повторного тестирования

- Unit: RBAC на каждом mutation endpoint; VPN config requires full.  
- Integration: setup token, login lockout, API key narrowing.  
- Negative: viewer не получает PrivateKey; нельзя usermod -G sudo.  
- CI: `make check`, grep на `shell=True`, OpenAPI auth coverage.  
- Pre-release: `visudo -c`, bind address, SETUP_COMPLETE, docs disabled.  

---

# Часть C. Находки

## [LNXADMIN-001] Выдача WireGuard PrivateKey при праве read

**Статус:** Подтверждена  
**Критичность:** Critical  
**CWE:** CWE-862 / CWE-200  
**OWASP:** API1 Broken Object Level Authorization / A01 Broken Access Control  
**Компонент:** API / WireGuard  

**Расположение:**

```text
Файл: src/backend/app/api/wireguard.py
Функция: peer_config
Строки: ~172–180
API endpoint: GET /api/wireguard/peers/{peer_id}/config
Файл: src/backend/app/collectors/wireguard.py
Функция: build_client_config
Строки: ~760–762
```

**Описание:**  
Endpoint защищён только router-level `wireguard:read`. Ответ включает `PrivateKey` клиента. Роль Viewer по умолчанию имеет `wireguard:read`.

**Поток данных:**

```text
JWT viewer
→ require_module(wireguard, read)
→ get_peer_config
→ build_client_config (PrivateKey = ...)
→ клиент получает полный VPN-доступ согласно AllowedIPs
```

**Условия:** аутентифицированный пользователь с `wireguard:read`, модуль enabled, существующий peer.  
**Последствия:** компрометация VPN, доступ к внутренним сетям.  
**Рекомендация:** требовать `wireguard:full` (и желательно step-up); логировать скачивание; не отдавать ключ роли viewer.

```python
async def peer_config(
    peer_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("wireguard", "full")),
):
    ...
```

---

## [LNXADMIN-002] Выдача OpenVPN client config (ключи) при праве read

**Статус:** Подтверждена  
**Критичность:** Critical  
**CWE:** CWE-862  
**Компонент:** API / OpenVPN  

**Расположение:**

```text
Файл: src/backend/app/api/openvpn.py
Функция: client_config
Строки: ~171–179
API endpoint: GET /api/openvpn/clients/{client_id}/config
```

**Описание:** Аналогично WG — только `openvpn:read`.  
**Рекомендация:** `require_module("openvpn", "full")` + audit.

---

## [LNXADMIN-003] Рекомендуемый sudoers фактически даёт root

**Статус:** Подтверждена (в документации развёртывания)  
**Критичность:** Critical  
**CWE:** CWE-250 / CWE-269  
**Компонент:** sudoers / README  

**Расположение:**

```text
Файл: README.md
Строки: ~177–194
```

**Описание:**  
Примеры содержат:

- `NOPASSWD: /usr/bin/systemctl` без ограничений аргументов;  
- `NOPASSWD: /usr/bin/apt-get, /usr/bin/dnf, /usr/bin/yum` без ограничений;  
- широкие `useradd`/`usermod` без ограничений групп.

Любая RCE/компрометация процесса панели или злоупотребление API при таких правах = root (произвольные unit'ы, установка пакетов, пользователь в sudo).

**Рекомендация:** argument-restricted sudoers / wrapper scripts; удалить package managers из sudoers в production; запретить `systemctl` для произвольных unit.

```sudoers
# Пример направления (не копировать слепо — сгенерировать под реальные пути)
lnxadmin ALL=(root) NOPASSWD: /usr/bin/fail2ban-client set * banip *, \
  /usr/bin/fail2ban-client set * unbanip *, \
  /usr/bin/fail2ban-client reload
# НЕ давать голый systemctl / apt-get
```

---

## [LNXADMIN-004] Отсутствие журнала аудита действий панели

**Статус:** Подтверждена  
**Критичность:** High  
**CWE:** CWE-778  
**Компонент:** Backend  

**Расположение:** поиск по `src/backend` — нет `audit` / `AuditLog` / записи мутаций.

**Описание:** Мутации хоста, смена ролей, скачивание VPN-конфигов, создание API keys не оставляют неизменяемого audit trail в приложении.

**Последствия:** невозможно расследовать инцидент; админ может скрыть действия.  
**Рекомендация:** таблица `audit_events` (append-only), запись до/после системного вызова, remote syslog.

---

## [LNXADMIN-005] OS Users: произвольные группы (sudo/docker)

**Статус:** Подтверждена  
**Критичность:** High  
**CWE:** CWE-269  
**Компонент:** Users  

**Расположение:**

```text
Файл: src/backend/app/collectors/users.py
Функции: create_user, set_user_groups, group membership
Строки: ~230–260, ~350+
API: POST /api/users, POST /api/users/{u}/groups, group members
```

**Описание:** Валидация имени группы — формат, не allowlist. При `users:full` + `allow_mutations` + sudoers на usermod/useradd возможен `usermod -G sudo,docker ...`.

**Рекомендация:** deny-list (`root`,`sudo`,`wheel`,`docker`,`adm`,…) и/или явный allowlist; запрет изменения групп с admin capabilities.

---

## [LNXADMIN-006] JWT не отзывается при смене пароля

**Статус:** Подтверждена  
**Критичность:** High  
**CWE:** CWE-613  
**Компонент:** JWT  

**Расположение:**

```text
Файл: src/backend/app/core/auth.py — create_access_token (только sub, exp)
Файл: src/backend/app/core/principal.py — resolve_bearer (is_active, не password version)
```

**Описание:** После смены пароля старый JWT валиден до `exp` (по умолчанию до 480 минут). Блокировка `is_active=false` работает.

**Рекомендация:** `token_version` / `password_changed_at` в User и проверка в `resolve_bearer`; короткий TTL + refresh.

---

## [LNXADMIN-007] Firewall disable / Fail2ban stop через API

**Статус:** Подтверждена  
**Критичность:** High  
**CWE:** CWE-693  
**Компонент:** Firewall / Fail2ban  

**Расположение:**

```text
src/backend/app/collectors/firewall.py — action disable / systemctl stop firewalld
src/backend/app/collectors/fail2ban.py — systemctl stop/restart fail2ban
```

**Условия:** `full` + `allow_mutations`.  
**Рекомендация:** отдельные permission flags (`allow_disable_firewall`); step-up; audit; deny в UI по умолчанию.

---

## [LNXADMIN-008] settings_access:full создаёт роли с полными правами

**Статус:** Подтверждена  
**Критичность:** High  
**CWE:** CWE-269  
**Компонент:** Access / RBAC  

**Расположение:** `src/backend/app/api/access.py` — `create_role` / `update_user`.

**Описание:** Не-superadmin с `settings_access:full` может выдать себе/другим `module:full` на все модули (кроме флага `is_superadmin`). Это почти эквивалент superadmin для host ops.

**Рекомендация:** нельзя назначать права выше собственных; отдельный permission на управление ролями; только superadmin меняет `settings_*`.

---

## [LNXADMIN-009] PostgreSQL monitor settings без allow_mutations

**Статус:** Подтверждена  
**Критичность:** High  
**CWE:** CWE-862  
**Компонент:** PostgreSQL  

**Расположение:**

```text
Файл: src/backend/app/api/postgres.py
Функция: put_postgres_settings
Строки: ~188–198
```

**Описание:** `postgres:full` может менять host/user/password монитора без `allow_mutations`. Позволяет перенаправить мониторинг на другой сервер (утечка запросов/учётных данных монитора) и хранить новые секреты.

**Рекомендация:** `_require_mutations` + ограничение host (localhost / allowlist).

---

## [LNXADMIN-010] Disks browse: широкий обзор ФС при read

**Статус:** Подтверждена  
**Критичность:** Medium  
**CWE:** CWE-548  
**Компонент:** Disks  

**Расположение:** `disks.py` browse — deny только `/proc`,`/sys`,`/dev`,`/run/user`; корень `/` разрешён. Содержимое файлов не читается, но структура `/etc`, `/home`, `/var/lib/lnxadmin` раскрывается при правах процесса.

**Рекомендация:** allowlist корней; default `allow_browse=false`; отдельное право `disks:full` для browse.

---

## [LNXADMIN-011] WebSocket: нет Origin / лимитов / re-validation JWT

**Статус:** Подтверждена  
**Критичность:** Medium  
**CWE:** CWE-1385 / CWE-770  
**Компонент:** WebSocket  

**Расположение:** `src/backend/app/api/system.py` `ws_metrics`.

**Описание:** После auth токен не перепроверяется; нет лимита соединений; Origin не проверяется (риск при XSS на разрешённом origin / mis-CORS). Timeout первого сообщения 10s — хорошо. Token не в URL — хорошо.

**Рекомендация:** Origin allowlist = CORS; max connections per user/IP; periodic `resolve_bearer`.

---

## [LNXADMIN-012] Admin password plaintext в `.env`

**Статус:** Подтверждена  
**Критичность:** Medium  
**CWE:** CWE-256  
**Компонент:** Secrets / Setup  

**Расположение:** `setup_state.apply_bootstrap` пишет `LNXADMIN_ADMIN_PASSWORD`; `public_connection_view` не отдаёт пароль, но файл на диске хранит.

**Рекомендация:** после upsert пользователя удалять/очищать пароль из `.env`; хранить только bcrypt в БД.

---

## [LNXADMIN-013] Setup: legacy heuristic «уже настроено»

**Статус:** Подтверждена  
**Критичность:** Medium  
**CWE:** CWE-697  
**Компонент:** Setup Wizard  

**Расположение:** `setup_state.is_setup_complete` — если флаг не false и есть db_password + jwt≥32, считается complete.

**Риск:** неоднозначные состояния `.env` при миграции.  
**Рекомендация:** единственный источник истины — явный `LNXADMIN_SETUP_COMPLETE`.

---

## [LNXADMIN-014] Setup / login: доверие к X-Forwarded-For при TRUST_PROXY

**Статус:** Подтверждена (by design, опасна при misconfig)  
**Критичность:** Medium  
**CWE:** CWE-290  
**Компонент:** Rate limit  

**Расположение:** `rate_limit.client_ip`.  

**Рекомендация:** `TRUST_PROXY=true` только за прокси, который перезаписывает XFF; в systemd уже `forwarded-allow-ips=127.0.0.1`.

---

## [LNXADMIN-015] Production setup: проверка loopback по peer, не по XFF

**Статус:** Подтверждена (положительная находка / Informational+)  
**Критичность:** Informational  
**Компонент:** Setup  

В `assert_setup_access` для production без token используется `request.client.host` (peer), а не `client_ip()` — правильно против XFF spoof. Rate-limit key всё же может использовать XFF при trust_proxy.

---

## [LNXADMIN-016] CSP: style unsafe-inline; connect-src ws: wss:

**Статус:** Подтверждена  
**Критичность:** Low  
**Компонент:** Frontend / middleware  

**Расположение:** `main.py` SecurityHeadersMiddleware.  
**Рекомендация:** сузить `connect-src` до `'self'`; nonces для стилей где возможно.

---

## [LNXADMIN-017] API key без permissions наследует полную роль

**Статус:** Подтверждена (by design)  
**Критичность:** Medium  
**CWE:** CWE-1220  
**Компонент:** API keys  

**Расположение:** `principal_from_user` — сужение только если `key_perms` задан.  
**Рекомендация:** default deny all modules for new keys; explicit grant.

---

## [LNXADMIN-018] systemd NoNewPrivileges vs sudo mutations

**Статус:** Вероятна / требует проверки на стенде  
**Критичность:** Medium  
**Компонент:** systemd  

**Расположение:** `deploy/lnxadmin.service` — `NoNewPrivileges=true`.  

Может блокировать `sudo` из сервиса. Операторы могут ослабить unit → потеря hardening.  
**Рекомендация:** документировать совместимый профиль; capability helpers вместо sudo.

---

## [LNXADMIN-019] Services denied_units — точное совпадение имени

**Статус:** Подтверждена  
**Критичность:** Low  
**Компонент:** Services  

`unit in denied` без нормализации (`ssh` vs `ssh.service`).  
**Рекомендация:** нормализовать к unit имени systemd.

---

## [LNXADMIN-020] Collector ACTION_ALLOW шире API (mask/unmask)

**Статус:** Informational  
**Компонент:** Services  

API режет действия до start/stop/restart/reload/enable/disable — хорошо. Collector всё ещё допускает mask при прямом вызове.

---

## [LNXADMIN-021] Docker API только read — снижение риска

**Статус:** Informational (положительная)  
Нет start/stop/exec/run через панель — снижает риск container escape через UI.

---

## [LNXADMIN-022] SSH Tunnel: ForceCommand + permitopen

**Статус:** Informational (положительная конструкция)  
Drop-in и authorized_keys options выглядят корректно. Риск — администратор может назначить опасные destinations (например, metadata IP / internal DB). Нужен allowlist сетей для destinations.

---

## [LNXADMIN-023] Shell injection через shell=True не найдена

**Статус:** Informational (положительная)  
Используется `create_subprocess_exec` / list argv. Риск — argument injection при недостаточной валидации (частично закрыта regex'ами).

---

## [LNXADMIN-024] OpenAPI docs в development / при отключённом флаге

**Статус:** Low  
В production docs выключены по умолчанию — хорошо. Утечка поверхности API при `LNXADMIN_DISABLE_DOCS=false`.

---

## [LNXADMIN-025] WireGuard/OpenVPN package install через панель

**Статус:** Medium (при mutations + широком sudoers → Critical цепочка)  
`install_tools` вызывает apt/dnf — при широком sudoers это путь к root. Даже с узким sudo на фиксированные пакеты риск supply-chain.

---

## [LNXADMIN-026] Path traversal в peer_id / client_id (WG / OpenVPN)

**Статус:** Подтверждена  
**Критичность:** Medium (High при наличии мутаций и записи)  
**CWE:** CWE-22  
**Компонент:** WireGuard / OpenVPN  

**Расположение:**

```text
Файл: src/backend/app/collectors/wireguard.py
Функции: update_peer, delete_peer, get_peer_config
Строки: path = _peers_dir(opts) / f"{peer_id}.json" (~672, ~734, ~794)
Файл: src/backend/app/collectors/openvpn.py
Аналогично: f"{client_id}.json" без проверки формата hex
```

**Описание:**  
ID генерируется как `secrets.token_hex(8)`, но на чтении/обновлении/удалении формат не проверяется. Значение вроде `../../server` или пути с `..` может выйти за каталог `peers/` / `clients/` в пределах `data_dir` (и потенциально дальше, в зависимости от `_load_json` / записи).

**Рекомендация:**

```python
PEER_ID_RE = re.compile(r"^[0-9a-f]{16}$")
if not PEER_ID_RE.fullmatch(peer_id or ""):
    return {"ok": False, "error": "Invalid peer id"}
path = (_peers_dir(opts) / f"{peer_id}.json").resolve()
if not str(path).startswith(str(_peers_dir(opts).resolve()) + os.sep):
    return {"ok": False, "error": "Invalid peer id"}
```

---

# Приложение: рекомендуемая матрица прав (фрагмент)

| Модуль | Операция | Min role | allow_mutations | Step-up | Риск |
|--------|----------|----------|-----------------|---------|------|
| wireguard | download config | full | no* | yes | Critical |
| openvpn | download config | full | no* | yes | Critical |
| fail2ban | ban/unban | full | yes | no | High |
| fail2ban | stop service | full | yes | yes | Critical |
| firewall | allow rule | full | yes | no | High |
| firewall | disable | full | yes | yes | Critical |
| users | create / set groups | full | yes | yes | Critical |
| services | stop unit | full | yes | no | High |
| disks | browse | full | — | no | Medium |
| settings_modules | allow_mutations toggle | full | — | yes | Critical |
| access | create role | full | — | yes | High |

\*скачивание ключа — отдельное чувствительное действие, даже без изменения хоста.

# Приложение: направление sudoers

| Функция | Бинарник | Аргументы | Без sudo? | Root risk |
|---------|----------|-----------|-----------|-----------|
| Fail2ban ban | fail2ban-client | `set <jail> banip <ip>` only | нет | Medium |
| UFW allow | ufw | allow/deny с валидированным spec | нет | High |
| systemctl module | systemctl | только allowlist unit+action | нет | Critical если * |
| WG apply | wg-quick | `up|down wg0` only | нет | High |
| Package install | — | **запретить в prod** | — | Critical |
| useradd tunnel | useradd | фиксированные флаги + prefix tun- | нет | High |
| docker | docker | **только если нужен read; без** | socket | Critical |

---

*Конец отчёта. Все Critical/High подтверждены чтением кода/документации репозитория; эксплуатация на production не выполнялась.*
