# Проблемы деплоя Linux Admin (хост `/apps/linux-admin`)

Дата: 2026-08-06  
Хост: `192.168.130.25` (Ubuntu 24.04 / noble)

Краткий журнал того, что мешало установке и запуску, и как это обошли.

**Источник кода (актуально):** `https://github.com/iSmartyPRO/linuxadmin`  
(раньше — приватный GitLab `git.ismarty.pro`; remote `origin` переключён на GitHub 2026-08-06.)

---

## 1. Приватный GitLab — клон без credentials не работает

**Симптом**

```text
fatal: could not read Username for 'https://git.ismarty.pro': No such device or address
```

HTTPS к [git.ismarty.pro/Ilias.Aidar/linux-admin](https://git.ismarty.pro/Ilias.Aidar/linux-admin.git) редиректит на Sign in; API отвечает `404 Project Not Found` без токена. SSH-ключей для GitLab на хосте не было.

**Что сделать**

- Клонировать по SSH с ключом, добавленным в GitLab, **или**
- HTTPS с Personal Access Token:  
  `git clone https://oauth2:<TOKEN>@git.ismarty.pro/Ilias.Aidar/linux-admin.git /apps/linux-admin`

Репозиторий в итоге оказался в `/apps/linux-admin` (клон выполнен отдельно с доступом).

---

## 2. Нет Node.js 20+ (обязателен для сборки UI)

**Симптом**

- `node` / `npm` отсутствуют в PATH  
- В Ubuntu noble из apt доступен только Node **18.19**, а проект требует **Node.js 20+** (`Makefile`, README)

**Что сделали**

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs   # получилось v20.20.2 / npm 10.8.2
```

Без этого `make install-frontend` / `make build` невозможны.

---

## 3. Frontend не был установлен и не собран

**Симптом**

Отсутствовали `src/frontend/node_modules` и `src/frontend/dist`. Backend venv уже был, процесс приложения — нет.

**Что сделали**

```bash
cd /apps/linux-admin
make install-frontend build
```

---

## 4. На хосте нет клиента `psql`

**Симптом**

```text
Command 'psql' not found
```

PostgreSQL крутится в Docker (`postgres:18.4-alpine`, порт `5432`), клиент на хосте не установлен.

**Обход**

Проверка БД через контейнер:

```bash
docker exec -e PGPASSWORD='…' postgres psql -U linuxadmin -d linuxadmin -c '\dt'
```

Для миграций приложения `psql` на хосте не нужен — Alembic ходит в БД по TCP из `.env`.

---

## 5. `LNXADMIN_SETUP_COMPLETE=false` при уже заполненном `.env`

**Симптом**

После `make run`:

```json
{"status":"ok","app":"Linux Admin","env":"production","configured":false}
```

В логе: `Setup mode: open the UI wizard…` — хотя `LNXADMIN_DB_*`, JWT и admin уже заданы.

**Что сделали**

В `.env` выставили:

```env
LNXADMIN_SETUP_COMPLETE=true
```

и перезапустили (`make restart`). После этого `configured: true`, логин `POST /api/auth/login` успешен.

---

## 6. Предупреждение passlib / bcrypt (не блокирует старт)

**Симптом** (в `.run/logs/app.log` при старте):

```text
WARNING:passlib.handlers.bcrypt:(trapped) error reading bcrypt version
AttributeError: module 'bcrypt' has no attribute '__about__'
```

Логин при этом работает (JWT выдаётся). Имеет смысл позже зафиксировать совместимые версии `passlib` / `bcrypt` в `requirements.txt`, но на деплой это не остановило.

---

## 7. Путаница с `LNXADMIN_ENV` в выводе `make start`

**Симптом**

`make restart` печатает `env=development`, хотя в `.env` стоит `production`, и `/api/health` отвечает `"env":"production"`.

**Причина**

В `Makefile` по умолчанию `LNXADMIN_ENV ?= development` — это только для echo/CLI override. Реальный режим берёт pydantic из `.env`.

**Не ошибка**, но при отладке вводит в заблуждение. Явно:  
`LNXADMIN_ENV=production make run`.

---

## Итоговый рабочий поток на этом хосте

```bash
# зависимости ОС
# - Python 3.12 (уже был)
# - Node.js 20+ (NodeSource)
# - PostgreSQL (Docker container "postgres", БД/роль linuxadmin уже созданы)

cd /apps/linux-admin
# .env уже настроен (DB, JWT, admin)
make install          # backend venv + npm ci
make build            # frontend → src/frontend/dist
make migrate          # Alembic → head
LNXADMIN_ENV=production make run
make status
```

**Проверка**

| Проверка | Результат |
|----------|-----------|
| Процесс | `make status` → running |
| Health | `http://127.0.0.1:8000/api/health` → `configured: true` |
| UI | `http://127.0.0.1:8000/` → HTTP 200 |
| Login | `POST /api/auth/login` → 200 + JWT |

Слушает только `127.0.0.1:8000` (как в `.env`). Снаружи — через SSH tunnel / VPN / reverse proxy.

Логи: `make logs` или `/apps/linux-admin/.run/logs/app.log`.
