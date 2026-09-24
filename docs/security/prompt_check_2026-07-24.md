Ты выступаешь в роли ведущего специалиста по информационной безопасности, аудитора веб-приложений, эксперта по Linux Security, Python, FastAPI, React, PostgreSQL, Docker, systemd, SSH, WireGuard, OpenVPN и безопасной разработке административных систем.

Проведи комплексный аудит безопасности проекта **Linux Admin** на основании предоставленного репозитория, исходного кода, конфигурационных файлов, документации и примеров развертывания.

Не ограничивайся поиском очевидных небезопасных функций и ключевых слов. Анализируй реальные потоки данных:

```text
HTTP-запрос или WebSocket-сообщение
→ аутентификация
→ определение пользователя, роли и API-ключа
→ проверка RBAC
→ проверка allow_mutations
→ валидация входных данных
→ вызов системного сервиса
→ sudo / системная утилита / Docker / systemd / VPN / файловая система
→ изменение состояния Linux-хоста
→ запись результата в аудит

```

Основная задача — определить, может ли компрометация панели, отдельного пользователя, API-ключа, WebSocket-соединения или внешней интеграции привести к:

- выполнению произвольных команд;
- получению root-доступа;
- обходу sudoers;
- изменению файрвола;
- отключению Fail2ban;
- остановке защитных или системных служб;
- управлению Docker и контейнерами;
- выходу из контейнера на хост;
- созданию SSH-доступа;
- созданию скрытых пользователей;
- изменению `sshd_config`;
- выдаче несанкционированного VPN-доступа;
- чтению чувствительных файлов;
- получению паролей, ключей и токенов;
- удалению или изменению журнала аудита;
- полной компрометации Linux-хоста.

# 1. Описание проекта

**Linux Admin** — локальная веб-панель для администрирования одного Linux-хоста.

Это не облачный оркестратор и не централизованный агент для большого количества машин. Приложение представляет собой локальный административный интерфейс для одного сервера.

Панель позволяет:

- просматривать состояние CPU, RAM, swap и load average;
- просматривать диски, разделы и показатели I/O;
- анализировать сетевые интерфейсы и соединения;
- просматривать процессы;
- собирать историю системных метрик;
- просматривать и ограниченно управлять systemd-службами;
- просматривать и изменять состояние Fail2ban;
- просматривать и изменять правила файрвола;
- контролировать Docker-контейнеры, образы, сети и тома;
- мониторить PostgreSQL;
- управлять ограниченными SSH-туннельными пользователями;
- управлять WireGuard и OpenVPN;
- создавать клиентские VPN-конфигурации;
- управлять пользователями панели;
- назначать роли;
- создавать API-ключи;
- предоставлять доступ через REST API и WebSocket.

Даже в режиме только чтения приложение раскрывает большое количество чувствительной информации о хосте.

При включённых мутациях Linux Admin фактически предоставляет ограниченный root-доступ через веб-интерфейс.

# 2. Технологический стек

## Backend

- Python 3.12 или новее;
- FastAPI;
- Uvicorn;
- REST API;
- WebSocket;
- фоновые workers;
- Setup Wizard;
- SQLAlchemy Async;
- asyncpg;
- Alembic;
- PostgreSQL;
- JWT;
- bcrypt;
- API keys;
- psutil;
- системные утилиты Linux;
- subprocess или аналогичные механизмы запуска процессов.

## Frontend

- React 19;
- TypeScript;
- Vite;
- Ant Design;
- Recharts;
- SPA-архитектура.

## Linux-интеграции

- `/proc`;
- `/sys`;
- systemd;
- `systemctl`;
- `journalctl`;
- Fail2ban;
- `fail2ban-client`;
- UFW;
- firewalld;
- nftables;
- iptables;
- Docker CLI;
- PostgreSQL;
- OpenSSH;
- `sshd_config`;
- SSH drop-in конфигурации;
- WireGuard;
- OpenVPN;
- локальные пользователи Linux;
- sudo;
- sudoers;
- файловая система Linux.

## Развертывание

Приложение может запускаться:

- напрямую через Uvicorn;
- как systemd-служба;
- за Nginx;
- за Caddy;
- за reverse proxy;
- через VPN;
- через SSH-туннель;
- локально на `127.0.0.1:8000`.

Frontend в production собирается в статические файлы и обслуживается backend-процессом с того же порта.

# 3. Основная цель аудита

Определи, может ли нарушитель:

- получить доступ без аутентификации;
- обойти JWT-аутентификацию;
- подделать или повторно использовать JWT;
- использовать отозванный API-ключ;
- повысить права через API-ключ;
- расширить права API-ключа сверх прав роли;
- обойти RBAC;
- обойти `allow_mutations`;
- вызвать административный endpoint напрямую;
- передать опасные параметры системной команде;
- выполнить shell injection;
- выполнить argument injection;
- изменить sudoers;
- запустить произвольную команду через разрешённый sudo-бинарник;
- использовать wildcard или небезопасные аргументы sudo;
- получить доступ к Docker socket;
- смонтировать файловую систему хоста через Docker;
- создать привилегированный контейнер;
- изменить сетевые правила;
- отключить Fail2ban;
- открыть административный порт;
- создать VPN-клиента с доступом к внутренним сетям;
- создать SSH-туннель к запрещённому адресу;
- изменить `PermitOpen`;
- получить закрытые SSH- или VPN-ключи;
- прочитать `/etc/shadow`;
- прочитать `.env`;
- получить секрет JWT;
- получить пароль PostgreSQL;
- удалить или изменить журнал аудита;
- использовать Setup Wizard повторно;
- получить root-доступ к Linux-хосту.

Учитывай, что компрометация Linux Admin может быть равнозначна полной компрометации операционной системы.

# 4. Ограничения аудита

Аудит проводится только для предоставленного проекта и разрешённого тестового стенда.

Запрещено без отдельного письменного разрешения:

- тестировать сторонние системы;
- выполнять действия на production-сервере;
- останавливать критические службы;
- перезагружать или выключать сервер;
- изменять действующий файрвол;
- блокировать административные IP-адреса;
- создавать реальные root-учётные записи;
- изменять рабочий `sshd_config`;
- отзывать рабочие VPN-конфигурации;
- удалять Docker-контейнеры, образы или тома;
- выполнять DoS-тесты;
- проводить массовый перебор паролей или ключей;
- удалять или изменять рабочие данные;
- публиковать обнаруженные секреты полностью.

Подтверждение уязвимостей должно выполняться безопасно, воспроизводимо и с минимальным воздействием.

# 5. Модель угроз

Рассмотри следующих нарушителей:

1. Неавторизованный пользователь локальной сети.
2. Внешний пользователь, получивший доступ к порту приложения.
3. Пользователь панели с ролью только на чтение.
4. Пользователь панели с ограниченными правами на отдельный модуль.
5. Владелец API-ключа с минимальными scopes.
6. Внешняя интеграция с компрометированным API-ключом.
7. Пользователь Linux без root-доступа.
8. Пользователь, имеющий локальный доступ к серверу.
9. Пользователь, имеющий доступ к PostgreSQL.
10. Пользователь, имеющий доступ к `.env`.
11. Пользователь, имеющий доступ к резервной копии БД.
12. Компрометированный Docker-контейнер.
13. Компрометированный reverse proxy.
14. Злоумышленник, контролирующий запись в системном журнале.
15. Администратор, пытающийся скрыть свои действия.
16. Злоумышленник, получивший VPN-конфигурацию.
17. Злоумышленник, получивший SSH-туннельную учётную запись.
18. Пользователь, получивший доступ к Setup Wizard.

Для каждого сценария укажи:

- защищаемый актив;
- точку входа;
- границу доверия;
- необходимые предварительные условия;
- доступные действия;
- возможный вектор атаки;
- потенциальные последствия;
- существующие меры защиты;
- отсутствующие меры защиты.

# 6. Анализ архитектуры

Перед поиском уязвимостей изучи структуру проекта.

Определи:

- точки запуска backend;
- конфигурацию FastAPI;
- порядок middleware;
- API routers;
- WebSocket endpoints;
- сервисы аутентификации;
- сервисы RBAC;
- механизм API-ключей;
- механизм `allow_mutations`;
- системные collectors;
- системные mutation services;
- использование subprocess;
- фоновые workers;
- механизм хранения истории;
- модели SQLAlchemy;
- миграции Alembic;
- механизм Setup Wizard;
- обработку `.env`;
- хранение настроек модулей;
- сервисы работы с Docker;
- сервисы systemd;
- сервисы Fail2ban;
- сервисы файрвола;
- сервисы SSH Tunnel;
- сервисы WireGuard;
- сервисы OpenVPN;
- сервисы PostgreSQL Monitoring;
- сервисы управления пользователями Linux;
- frontend API client;
- frontend WebSocket client;
- конфигурации Nginx, Caddy и systemd;
- Makefile и установочные скрипты;
- sudoers-конфигурацию.

Составь карту компонентов и границ доверия.

# 7. Инвентаризация API

Составь полный список REST endpoints и WebSocket endpoints.

Для каждого endpoint укажи:

```text
HTTP-метод или WebSocket
Маршрут
Назначение
Доступен без аутентификации
Тип аутентификации
Минимальная роль
Минимальный уровень модуля
Требует allow_mutations
Дополнительный scope API-ключа
Вызываемая системная операция
Уровень риска

```

Отдельно найди:

- endpoints без аутентификации;
- endpoints с необязательной аутентификацией;
- endpoints, доступные во время Setup Wizard;
- debug endpoints;
- health endpoints;
- документацию OpenAPI;
- endpoints для выдачи файлов;
- endpoints для QR-кодов;
- endpoints для скачивания VPN-конфигураций;
- endpoints для создания API-ключей;
- endpoints для изменения ролей;
- endpoints для изменения настроек модулей;
- endpoints, запускающие фоновые операции;
- endpoints, работающие с файловой системой;
- административные endpoints, доступные методом GET.

# 8. JWT-аутентификация

Проверь:

- алгоритм подписи JWT;
- длину и энтропию JWT secret;
- генерацию секрета;
- хранение секрета;
- попадание секрета в Git;
- попадание секрета в логи;
- обработку `alg=none`;
- algorithm confusion;
- проверку подписи;
- проверку `exp`;
- проверку `nbf`;
- проверку `iat`;
- проверку `iss`;
- проверку `aud`;
- проверку типа токена;
- срок действия access token;
- наличие refresh token;
- ротацию refresh token;
- отзыв токенов;
- завершение всех сессий пользователя;
- смену пароля;
- блокировку пользователя;
- удаление пользователя;
- повторное использование токена;
- использование токена после изменения роли;
- использование токена после отключения пользователя;
- использование токена после смены пароля;
- хранение токена во frontend;
- передачу токена в URL;
- передачу токена в WebSocket URL;
- попадание токена в Referer;
- попадание токена в access logs;
- попадание токена в browser history;
- утечку токена через frontend telemetry.

Отдельно проверь, перечитываются ли права пользователя из БД при каждом критическом запросе или полностью доверяются устаревшим claims JWT.

# 9. WebSocket-аутентификация

Особое внимание удели `/ws/metrics`.

Токен передаётся первым сообщением, а не в URL. Проверь:

- допускается ли получение данных до проверки токена;
- установлен ли таймаут ожидания первого сообщения;
- ограничен ли размер первого сообщения;
- закрывается ли соединение при неправильном токене;
- закрывается ли соединение при отсутствии токена;
- можно ли повторно аутентифицироваться;
- привязан ли principal к соединению;
- проверяется ли пользователь после блокировки;
- проверяется ли срок действия JWT во время долгой сессии;
- прекращается ли поток после истечения JWT;
- ограничено ли число соединений на пользователя;
- ограничено ли число соединений на IP;
- есть ли защита от WebSocket connection exhaustion;
- проверяется ли Origin;
- разрешены ли внешние сайты;
- можно ли открыть WebSocket с вредоносной страницы;
- содержат ли сообщения чувствительные данные;
- есть ли фильтрация по правам;
- может ли read-only пользователь подписаться на административные события;
- попадают ли токены в логи;
- корректно ли обрабатываются disconnect и исключения.

# 10. Пароли и bcrypt

Проверь:

- параметры bcrypt;
- минимальную стоимость хеширования;
- возможность слабых паролей;
- минимальную длину пароля;
- проверку скомпрометированных паролей;
- защиту от credential stuffing;
- rate limiting;
- lockout;
- длительность lockout;
- обход блокировки через IPv6;
- обход блокировки через прокси-заголовки;
- обход блокировки изменением регистра логина;
- user enumeration;
- различия в ответах для существующего и несуществующего пользователя;
- timing differences;
- смену пароля;
- сброс пароля;
- первоначальный пароль администратора;
- хранение временного пароля;
- вывод пароля в Setup Wizard;
- попадание пароля в логи;
- попадание пароля в frontend state;
- попадание пароля в browser autofill;
- очистку активных сессий после смены пароля.

# 11. API-ключи

Проведи отдельный аудит API keys.

Проверь:

- генерацию ключей;
- криптографическую стойкость;
- энтропию;
- формат;
- наличие префикса или идентификатора;
- хранение полного ключа;
- хранение хеша ключа;
- возможность восстановления ключа из БД;
- сравнение ключей;
- timing attacks;
- отображение полного ключа только один раз;
- логирование ключей;
- передачу через URL;
- передачу через заголовок;
- срок действия;
- отзыв;
- ротацию;
- дату последнего использования;
- владельца ключа;
- назначение ключа;
- IP allowlist;
- ограничение по модулю;
- ограничение по endpoint;
- ограничение по HTTP-методу;
- rate limit;
- аудит использования;
- возможность изменить собственные права;
- возможность создать ключ с правами выше роли;
- возможность расширить права через изменение JSON;
- mass assignment;
- повторную активацию отозванного ключа;
- использование удалённого ключа;
- использование ключа отключённого пользователя.

Подтверди правило:

```text
Эффективные права API-ключа
=
пересечение прав пользователя или роли
и разрешений самого API-ключа

```

API-ключ не должен расширять права роли.

# 12. RBAC

Проверь двухуровневую модель доступа:

```text
Роль пользователя
→ none / read / full для конкретного модуля

Настройка модуля
→ allow_mutations true / false

```

Для выполнения изменения должны одновременно выполняться условия:

```text
пользователь аутентифицирован
AND
роль имеет full для модуля
AND
allow_mutations включён
AND
API-ключ допускает операцию
AND
endpoint явно требует право изменения

```

Проверь:

- единообразие проверки прав;
- наличие централизованного dependency или middleware;
- применение проверки ко всем routers;
- обход через альтернативные endpoints;
- обход через WebSocket;
- обход через фоновые задачи;
- обход через импорт настроек;
- обход через Setup Wizard;
- обход через API документации;
- обход через изменение HTTP-метода;
- использование проверки только на frontend;
- доступ к данным отключённого модуля;
- доступ к mutation endpoint при выключенном модуле;
- кеширование старых прав;
- изменение роли во время активной сессии;
- race condition между проверкой и действием;
- fail-open при ошибке БД;
- разрешение операции при неизвестной роли;
- разрешение операции при неизвестном модуле;
- права по умолчанию для нового модуля;
- права по умолчанию для нового пользователя.

# 13. allow_mutations

Проверь механизм `allow_mutations` отдельно.

Определи:

- где хранится параметр;
- кто может его менять;
- требуется ли отдельное административное право;
- записывается ли изменение в аудит;
- можно ли изменить настройку через API;
- можно ли подменить ID модуля;
- можно ли включить мутации через mass assignment;
- можно ли изменить параметр напрямую в PostgreSQL;
- обновляется ли значение без перезапуска;
- кешируется ли значение;
- возможна ли рассинхронизация worker и API;
- применяется ли параметр ко всем опасным операциям;
- проверяется ли параметр непосредственно перед системным вызовом;
- проверяется ли параметр внутри background worker;
- можно ли поставить опасную задачу в очередь, выключить мутации и всё равно выполнить её;
- прерываются ли ожидающие mutation-задачи после выключения;
- разрешаются ли изменения при недоступности PostgreSQL.

При ошибках механизм должен работать по принципу fail-closed.

# 14. Setup Wizard

Setup Wizard является критической частью системы.

Проверь:

- условия запуска мастера;
- значение `LNXADMIN_SETUP_COMPLETE`;
- поведение при отсутствии БД;
- поведение при недоступности БД;
- привязку к localhost;
- корректность определения IP клиента;
- доверие к `X-Forwarded-For`;
- доверие к `X-Real-IP`;
- trusted proxies;
- возможность подмены localhost через proxy headers;
- IPv4 и IPv6 loopback;
- Unix socket;
- `LNXADMIN_SETUP_TOKEN`;
- генерацию setup token;
- длину setup token;
- хранение setup token;
- логирование setup token;
- передачу токена через URL;
- срок действия токена;
- одноразовость;
- возможность повторного запуска мастера;
- возможность сбросить флаг завершения;
- race condition при параллельном запуске;
- создание нескольких администраторов;
- слабый JWT secret;
- слабый пароль администратора;
- SSRF или подключение к произвольной PostgreSQL;
- SQL-инъекции через параметры подключения;
- сохранение пароля PostgreSQL;
- отображение connection string;
- утечку конфигурации в frontend;
- доступ к мастеру после завершения настройки.

Production не должен доверять только значению IP из непроверенных proxy headers.

# 15. Запуск системных команд

Найди все использования:

- `subprocess.run`;
- `subprocess.Popen`;
- `asyncio.create_subprocess_exec`;
- `asyncio.create_subprocess_shell`;
- `os.system`;
- `os.popen`;
- `commands`;
- `pexpect`;
- shell-обёрток;
- собственного command runner;
- sudo;
- `sh -c`;
- `bash -c`.

Для каждого вызова укажи:

```text
HTTP-параметр или значение БД
→ обработка
→ валидация
→ список аргументов
→ sudo
→ исполняемый бинарник
→ системное действие

```

Проверь:

- использование `shell=True`;
- использование `bash -c`;
- конкатенацию строк;
- f-string;
- `.format`;
- небезопасный join аргументов;
- command injection;
- argument injection;
- option injection;
- передачу значения, начинающегося с `-`;
- использование `--`;
- wildcard expansion;
- globbing;
- environment variable injection;
- PATH hijacking;
- запуск бинарников без абсолютного пути;
- подмену working directory;
- подмену locale;
- подмену `HOME`;
- подмену `PYTHONPATH`;
- подмену `LD_PRELOAD`;
- подмену `LD_LIBRARY_PATH`;
- наследование опасных переменных окружения;
- отсутствие timeout;
- отсутствие ограничения вывода;
- deadlock stdout/stderr;
- зависшие процессы;
- zombie processes;
- возврат чувствительных данных пользователю.

Предпочтительный вариант:

```python
await asyncio.create_subprocess_exec(
    "/usr/bin/systemctl",
    "status",
    validated_unit_name,
)

```

Недопустимый вариант:

```python
await asyncio.create_subprocess_shell(
    f"systemctl status {user_input}"
)

```

# 16. sudoers

Проведи глубокую проверку sudoers.

Изучи:

- пользователя systemd-службы;
- группы пользователя;
- доступные команды sudo;
- использование `NOPASSWD`;
- абсолютные пути к бинарникам;
- допустимые аргументы;
- wildcard в sudoers;
- возможность передать дополнительные аргументы;
- возможность использовать альтернативные конфиги;
- возможность указать произвольный файл;
- возможность указать произвольный namespace;
- возможность использовать shell escape;
- возможность вызвать editor;
- возможность вызвать pager;
- возможность загрузить plugin;
- возможность выполнить hook;
- возможность использовать `--root`;
- возможность использовать `--config`;
- возможность использовать `--output`;
- возможность создать или перезаписать файл;
- возможность использовать symlink;
- переменные окружения;
- `SETENV`;
- `env_keep`;
- `secure_path`;
- `NOEXEC`;
- `sudoedit`;
- порядок правил;
- конфликт правил;
- include-файлы;
- права на `/etc/sudoers.d`;
- владельца и режим файлов.

Определи, могут ли разрешённые команды привести к root shell.

Особое внимание удели:

- `systemctl`;
- `journalctl`;
- `docker`;
- `nft`;
- `iptables`;
- `ufw`;
- `firewall-cmd`;
- `wg`;
- `wg-quick`;
- `openvpn`;
- `fail2ban-client`;
- `useradd`;
- `usermod`;
- `passwd`;
- `chpasswd`;
- `tee`;
- `cp`;
- `mv`;
- `chmod`;
- `chown`;
- `sed`;
- `awk`;
- `find`;
- `tar`;
- текстовым редакторам;
- интерпретаторам Python, Perl, Ruby, Bash.

Не считай ограничение по имени бинарника достаточной защитой. Анализируй допустимые аргументы и возможности самой программы.

# 17. systemd

Проверь модуль Services.

Определи поддерживаемые операции:

- просмотр статуса;
- просмотр unit-файла;
- просмотр journal;
- start;
- stop;
- restart;
- reload;
- enable;
- disable;
- mask;
- unmask;
- daemon-reload;
- изменение unit-файлов;
- создание drop-in.

Проверь:

- валидацию имени unit;
- символы `/`, `\`, `..`, `@`, `-`, `.`;
- template units;
- instance units;
- system и user units;
- возможность управлять произвольным unit;
- возможность остановить Linux Admin;
- возможность остановить SSH;
- возможность остановить PostgreSQL;
- возможность остановить reverse proxy;
- возможность остановить firewall;
- возможность остановить Fail2ban;
- возможность остановить Docker;
- возможность остановить auditd;
- возможность управлять rescue или emergency target;
- возможность запускать transient units;
- возможность использовать `systemd-run`;
- возможность изменять `ExecStart`;
- возможность создавать drop-in;
- возможность загрузить изменённый unit;
- deny-list критических unit;
- обход deny-list через alias;
- обход через template unit;
- обход через `.service`;
- обход через регистр;
- обход через symlink;
- обход через DBus;
- TOCTOU между проверкой и выполнением.

Deny-list не должна быть единственным механизмом защиты.

# 18. Пользователи Linux

Проверь модуль Users.

Определи поддерживаемые действия:

- чтение `/etc/passwd`;
- чтение shadow-информации;
- создание пользователя;
- удаление пользователя;
- изменение shell;
- изменение home;
- изменение UID;
- изменение GID;
- изменение групп;
- блокировка;
- разблокировка;
- смена пароля;
- управление SSH-ключами.

Проверь возможность:

- создать UID 0;
- изменить UID существующего пользователя на 0;
- добавить пользователя в `sudo`;
- добавить пользователя в `wheel`;
- добавить пользователя в `docker`;
- добавить пользователя в `lxd`;
- добавить пользователя в `adm`;
- добавить пользователя в `systemd-journal`;
- добавить пользователя в чувствительные группы;
- изменить root;
- разблокировать root;
- установить пустой пароль;
- установить небезопасный shell;
- использовать `/bin/bash` для tunnel-only пользователя;
- подменить home directory;
- указать home внутри системного каталога;
- перезаписать `authorized_keys`;
- использовать symlink;
- создать пользователя с именем, похожим на системное;
- использовать Unicode;
- использовать управляющие символы;
- передать дополнительные аргументы;
- внедрить команды через имя пользователя;
- удалить пользователя, под которым работает Linux Admin;
- изменить права пользователя сервиса.

# 19. SSH Tunnel

Проведи отдельный аудит модуля SSH Tunnel.

Проверь:

- допустимый префикс пользователей;
- создание tunnel-only пользователей;
- shell пользователя;
- блокировку пароля;
- `authorized_keys`;
- `command=`;
- `restrict`;
- `no-agent-forwarding`;
- `no-X11-forwarding`;
- `no-pty`;
- `no-user-rc`;
- `permitopen`;
- `permitlisten`;
- TCP forwarding;
- streamlocal forwarding;
- GatewayPorts;
- AllowTcpForwarding;
- PermitTunnel;
- ForceCommand;
- Match User;
- Match Group;
- sshd drop-in;
- порядок drop-in файлов;
- права на конфигурационные файлы;
- проверку `sshd -t`;
- атомарное обновление конфигурации;
- rollback при ошибке;
- reload SSH;
- риск потерять административный доступ;
- live sessions;
- завершение сессий;
- аудит подключений;
- историю подключений.

Проверь обход `PermitOpen` через:

- IPv4 и IPv6;
- localhost;
- альтернативные представления IP;
- DNS;
- DNS rebinding;
- CNAME;
- Unix sockets;
- wildcard;
- порт `0`;
- диапазоны портов;
- IPv4-mapped IPv6;
- внутренние адреса;
- metadata endpoints;
- PostgreSQL;
- Docker socket proxy;
- административные сервисы.

Закрытые SSH-ключи не должны генерироваться или храниться без защищённого механизма.

# 20. WireGuard

Проверь:

- генерацию private key;
- генерацию preshared key;
- использование `wg genkey`;
- хранение private key;
- права на файлы;
- вывод ключей в API;
- вывод ключей в логи;
- одноразовое скачивание;
- QR-коды;
- кеширование QR;
- browser history;
- временные файлы;
- очистку временных файлов;
- список AllowedIPs;
- full tunnel;
- split tunnel;
- custom routes;
- пересечение маршрутов;
- дублирование адресов;
- выдачу адресов клиентам;
- отзыв клиента;
- удаление peer;
- применение конфигурации;
- перезапуск интерфейса;
- PostUp и PostDown;
- command injection;
- изменение произвольного интерфейса;
- изменение произвольного файла;
- возможность указать произвольный путь;
- возможность добавить маршрут к management-сети;
- возможность добавить `0.0.0.0/0`;
- возможность добавить `::/0`;
- DNS-настройки;
- MTU;
- PersistentKeepalive;
- аудит создания и скачивания конфигурации.

Проверь, можно ли получить конфигурацию другого клиента через IDOR.

# 21. OpenVPN

Проверь:

- PKI;
- CA private key;
- server key;
- client private keys;
- хранение ключей;
- права файлов;
- генерацию сертификатов;
- Easy-RSA;
- OpenSSL;
- срок действия;
- отзыв;
- CRL;
- обновление CRL;
- serial numbers;
- duplicate-cn;
- CCD;
- client-config-dir;
- push routes;
- redirect-gateway;
- DNS;
- scripts;
- `script-security`;
- `up`;
- `down`;
- `client-connect`;
- `client-disconnect`;
- плагины;
- пути к конфигурации;
- command injection;
- аргументы OpenVPN;
- скачивание `.ovpn`;
- embedding private keys;
- кеширование;
- повторное скачивание;
- IDOR;
- логирование конфигурации;
- удаление временных файлов;
- аудит выдачи клиента.

# 22. Fail2ban

Проверь:

- получение jail;
- получение banned IP;
- ban;
- unban;
- изменение параметров;
- чтение логов;
- jail name validation;
- IP validation;
- IPv4;
- IPv6;
- CIDR;
- hostname;
- option injection;
- command injection;
- вызов `fail2ban-client`;
- возможность выполнить произвольную action;
- возможность изменить actionban;
- возможность изменить banaction;
- возможность изменить logpath;
- возможность изменить filter;
- возможность заблокировать административный IP;
- возможность разблокировать атакующий IP;
- возможность отключить jail;
- возможность остановить Fail2ban;
- защиту от массовых операций;
- аудит ban и unban;
- автоматический rollback.

# 23. Firewall

Определи поддерживаемые backend-стеки:

- UFW;
- firewalld;
- nftables;
- iptables.

Проверь механизм автодетекта.

Определи, можно ли:

- подменить определённый backend;
- вызвать другой firewall tool;
- смешать правила разных стеков;
- обойти RBAC через альтернативный backend.

Проверь:

- создание правил;
- удаление правил;
- изменение policy;
- flush;
- reload;
- enable;
- disable;
- allow;
- deny;
- reject;
- source;
- destination;
- port;
- protocol;
- interface;
- IPv4;
- IPv6;
- NAT;
- forwarding;
- таблицы;
- chains;
- priority;
- raw expressions;
- comments.

Особое внимание:

- command injection;
- option injection;
- arbitrary nft expression;
- пользовательскому raw rule;
- открытию панели наружу;
- удалению SSH-правила;
- блокировке администратора;
- отключению файрвола;
- разрешению `0.0.0.0/0`;
- разрешению `::/0`;
- изменению default policy;
- очистке ruleset;
- созданию NAT в management-сеть;
- созданию redirect;
- атомарности изменений;
- предварительной проверке;
- автоматическому rollback;
- сохранению правил после перезагрузки;
- race condition;
- конфликтам нескольких администраторов;
- журналированию до и после изменения.

# 24. Docker

Модуль Docker относится к критическим, поскольку доступ к Docker часто эквивалентен root-доступу.

Проверь способ взаимодействия:

- Docker CLI;
- Docker socket;
- Docker SDK;
- rootful Docker;
- rootless Docker;
- Podman fallback.

Проверь права сервисного пользователя:

- членство в группе `docker`;
- доступ к `/var/run/docker.sock`;
- sudo на `/usr/bin/docker`.

Определи доступные операции:

- list;
- inspect;
- logs;
- stats;
- start;
- stop;
- restart;
- kill;
- pause;
- unpause;
- remove;
- exec;
- create;
- run;
- pull;
- build;
- compose;
- управление images;
- управление volumes;
- управление networks;
- prune.

Особое внимание удели:

- `docker exec`;
- созданию контейнера;
- bind mount `/`;
- bind mount `/etc`;
- bind mount `/var/run/docker.sock`;
- `--privileged`;
- `--pid=host`;
- `--network=host`;
- `--userns=host`;
- `--cap-add`;
- `--device`;
- `--security-opt`;
- AppArmor;
- seccomp;
- environment variables;
- secrets;
- labels;
- container logs;
- registry credentials;
- image pull;
- malicious image;
- command injection;
- подмене container ID;
- prefix matching ID;
- TOCTOU;
- возможности управлять контейнером Linux Admin;
- возможности управлять PostgreSQL;
- возможности удалить volumes;
- возможности выполнить prune;
- возможности получить секреты через inspect;
- возможности прочитать environment variables контейнеров;
- возможности прочитать mounted secrets;
- stored XSS через container names, labels и logs.

Даже read-only Docker-функции могут раскрывать пароли, токены и внутреннюю архитектуру.

# 25. Network

Проверь:

- получение интерфейсов;
- listening sockets;
- established connections;
- PID сопоставление;
- имена процессов;
- адреса;
- DNS;
- MAC;
- маршруты;
- ARP или neighbor table;
- поднятие интерфейса;
- отключение интерфейса;
- завершение процесса;
- завершение соединения;
- изменение маршрута.

Проверь риски:

- раскрытие внутренней сети;
- раскрытие служебных портов;
- утечку PID;
- раскрытие командных строк;
- отключение management-интерфейса;
- отключение loopback;
- отключение VPN;
- отключение default route;
- потерю связи с сервером;
- command injection через имя интерфейса;
- race condition;
- IPv6;
- network namespace;
- интерфейсы контейнеров;
- возможность управлять интерфейсом другого namespace.

# 26. Processes

Проверь:

- список процессов;
- PID;
- PPID;
- user;
- command line;
- environment;
- open files;
- sockets;
- CPU;
- memory;
- kill;
- terminate;
- signal.

Определи, какие сигналы разрешены.

Проверь:

- PID reuse;
- TOCTOU;
- negative PID;
- PID 0;
- PID 1;
- process groups;
- завершение Linux Admin;
- завершение PostgreSQL;
- завершение SSH;
- завершение auditd;
- завершение Docker;
- завершение reverse proxy;
- завершение security agents;
- завершение ядровых потоков;
- просмотр `/proc/<pid>/environ`;
- утечку секретов;
- утечку аргументов командной строки;
- раскрытие других пользователей;
- отправку произвольного сигнала;
- массовое завершение процессов.

# 27. Disks и файловая система

Проверь browse внутри разрешённых mount points.

Особое внимание:

- path traversal;
- `..`;
- URL encoding;
- double encoding;
- absolute paths;
- null byte;
- symlink;
- hardlink;
- bind mount;
- mount namespace;
- overlayfs;
- `/proc`;
- `/sys`;
- `/dev`;
- `/etc`;
- `/root`;
- `/home`;
- `/var/lib`;
- `/var/run`;
- Docker volumes;
- PostgreSQL data directory;
- SSH keys;
- VPN keys;
- `.env`;
- systemd credentials;
- socket-файлы.

Проверь:

- канонизацию пути;
- `Path.resolve`;
- проверку после resolve;
- TOCTOU;
- смену symlink после проверки;
- ограничение глубины;
- ограничение количества файлов;
- ограничение размера;
- запрет чтения содержимого чувствительных файлов;
- запрет скачивания;
- stored XSS через имена файлов;
- Unicode normalization;
- права сервисного пользователя.

# 28. PostgreSQL приложения

Проверь:

- connection string;
- пароль;
- SSL;
- проверку сертификата;
- `sslmode`;
- права пользователя БД;
- superuser;
- CREATEDB;
- CREATEROLE;
- ownership;
- доступ по сети;
- pg_hba.conf;
- разделение БД панели и monitored PostgreSQL;
- SQLAlchemy models;
- raw SQL;
- `text()`;
- динамические запросы;
- SQL injection;
- migrations;
- seed;
- создание первого администратора;
- хранение API-ключей;
- хранение JWT или refresh tokens;
- хранение module settings;
- хранение credentials модулей;
- хранение истории;
- хранение аудита;
- backup;
- restore;
- encryption at rest;
- права на dump;
- утечку через ошибки;
- pool exhaustion;
- connection leaks;
- transaction isolation;
- race conditions;
- async session handling.

Проверь, может ли пользователь с доступом к БД:

- создать администратора;
- изменить пароль;
- изменить роль;
- включить `allow_mutations`;
- добавить API-ключ;
- расширить права ключа;
- повторно активировать ключ;
- изменить настройки sudo;
- изменить пути модулей;
- удалить аудит;
- подменить автора операции.

# 29. Мониторинг PostgreSQL

Проверь модуль мониторинга PostgreSQL.

Убедись, что роль мониторинга не требует superuser и по возможности ограничивается `pg_monitor`.

Проверь:

- хранение учётных данных;
- шифрование пароля;
- вывод пароля в UI;
- вывод в API;
- логирование;
- connection string injection;
- произвольный host;
- произвольный port;
- произвольный database;
- SSRF;
- доступ к localhost services;
- Unix socket;
- DNS rebinding;
- TLS;
- проверку сертификата;
- таймаут соединения;
- statement timeout;
- максимальное количество подключений;
- SQL injection;
- пользовательские SQL-запросы;
- чтение `pg_stat_activity`;
- раскрытие текстов SQL;
- раскрытие паролей в SQL;
- раскрытие application_name;
- раскрытие client_addr;
- доступ к `pg_stat_statements`;
- доступ к replication info;
- доступ к конфиденциальным данным.

# 30. Исторические метрики и workers

Проверь:

- периодичность сбора;
- фоновые задачи;
- количество workers;
- дублирование workers;
- запуск нескольких экземпляров Uvicorn;
- race condition;
- advisory locks;
- retention;
- очистку старых данных;
- размер таблиц;
- индексы;
- time zone;
- UTC;
- доверие системному времени;
- резкий скачок времени;
- отрицательные значения;
- переполнение;
- NaN;
- infinity;
- большие значения;
- batch inserts;
- обработку недоступности PostgreSQL;
- накопление памяти;
- retry;
- exponential backoff;
- бесконечные retry;
- log flooding;
- завершение worker;
- разделение прав API и worker.

# 31. Логи и журнал аудита

Аудит должен фиксировать:

- timestamp в UTC;
- request ID;
- correlation ID;
- пользователя;
- роль;
- идентификатор API-ключа;
- IP;
- User-Agent;
- модуль;
- операцию;
- целевой объект;
- параметры без секретов;
- результат;
- ошибку;
- старое значение;
- новое значение;
- длительность;
- идентификатор background task.

Обязательно должны фиксироваться:

- вход;
- неуспешный вход;
- lockout;
- создание пользователя панели;
- изменение роли;
- создание API-ключа;
- отзыв API-ключа;
- изменение scopes;
- включение и выключение модуля;
- изменение `allow_mutations`;
- запуск и остановка служб;
- изменение файрвола;
- ban и unban;
- действия Docker;
- действия с Linux-пользователями;
- создание SSH-туннельного пользователя;
- изменение SSH-конфигурации;
- создание VPN-клиента;
- скачивание VPN-конфигурации;
- отзыв VPN-клиента;
- изменение системных файлов;
- отказ в авторизации.

Проверь:

- возможность log injection;
- CRLF;
- ANSI escape sequences;
- forged JSON;
- отсутствие секретов;
- отсутствие паролей;
- отсутствие JWT;
- отсутствие полных API-ключей;
- отсутствие private keys;
- права на лог-файлы;
- logrotate;
- ротацию;
- заполнение диска;
- централизованный сбор;
- journald;
- rsyslog;
- SIEM;
- tamper resistance;
- append-only;
- удалённую отправку;
- HMAC chaining;
- возможность удалить записи из PostgreSQL;
- возможность отключить аудит;
- поведение при отказе аудита.

Для критических операций оцени необходимость fail-closed при невозможности записать событие аудита.

# 32. FastAPI

Проверь:

- зависимости FastAPI;
- global dependencies;
- router dependencies;
- middleware;
- exception handlers;
- CORS;
- TrustedHostMiddleware;
- ProxyHeaders;
- gzip;
- static files;
- OpenAPI;
- Swagger;
- ReDoc;
- health endpoints;
- response models;
- Pydantic schemas;
- ORM models;
- mass assignment;
- `extra="forbid"`;
- типизацию;
- Optional fields;
- default values;
- enum;
- ограничение длины;
- числовые диапазоны;
- validation aliases;
- serialization;
- response filtering;
- раскрытие внутренних полей;
- background tasks;
- lifespan;
- startup;
- shutdown;
- dependency cleanup;
- async blocking calls;
- threadpool exhaustion.

Проверь неправильное применение:

- `Depends`;
- security dependencies;
- OAuth2PasswordBearer;
- HTTPBearer;
- APIKeyHeader;
- middleware order;
- exception fallback;
- permissive default;
- catch-all exceptions;
- `except Exception: pass`.

# 33. Валидация входных данных

Найди все входные данные:

- path parameters;
- query parameters;
- JSON;
- form data;
- headers;
- cookies;
- JWT claims;
- WebSocket messages;
- module settings;
- значения из PostgreSQL;
- имена systemd unit;
- имена Docker-объектов;
- имена пользователей;
- имена интерфейсов;
- IP-адреса;
- CIDR;
- порты;
- пути;
- VPN routes;
- SSH PermitOpen;
- имена jail;
- firewall rules;
- monitored database connections.

Проверь:

- command injection;
- shell injection;
- argument injection;
- SQL injection;
- path traversal;
- SSRF;
- open redirect;
- CRLF injection;
- log injection;
- stored XSS;
- reflected XSS;
- DOM XSS;
- HTML injection;
- regex DoS;
- Unicode normalization;
- integer overflow;
- отрицательные значения;
- слишком большие лимиты;
- слишком длинные строки;
- списки без ограничения количества элементов;
- неправильные IP;
- IPv4-mapped IPv6;
- hostname вместо IP;
- DNS rebinding;
- localhost bypass;
- metadata IP;
- Unix socket paths.

# 34. Frontend React

Проверь:

- хранение JWT;
- localStorage;
- sessionStorage;
- cookies;
- IndexedDB;
- React state;
- console logs;
- error reporting;
- telemetry;
- URL;
- browser history;
- sourcemaps;
- `VITE_*`;
- frontend bundle;
- API keys;
- Setup token.

Проверь XSS через:

- systemd journal;
- Docker logs;
- container names;
- image tags;
- volume names;
- network names;
- process names;
- process command line;
- usernames;
- filenames;
- mount points;
- Fail2ban logs;
- firewall logs;
- PostgreSQL activity;
- SSH session history;
- VPN client names;
- системные сообщения.

Найди:

- `dangerouslySetInnerHTML`;
- небезопасные markdown renderers;
- небезопасные HTML parsers;
- прямую вставку HTML;
- unsafe URL;
- `javascript:`;
- open redirects;
- динамические links;
- скачивание файлов без проверки Content-Type;
- clickjacking;
- кеширование чувствительных страниц;
- отображение private key;
- возможность повторно показать секрет.

Frontend не должен считаться механизмом авторизации.

# 35. Vite

Проверь:

- dev server;
- bind address;
- `host: true`;
- allowedHosts;
- CORS;
- proxy;
- `/api`;
- `/ws`;
- HTTPS;
- HMR;
- доступ dev server из сети;
- раскрытие файлов проекта;
- source maps;
- production source maps;
- переменные `VITE_*`;
- env files;
- bundle;
- base URL;
- public directory;
- случайно опубликованные конфигурации;
- debug pages.

# 36. CORS, Origin и proxy headers

Проверь:

- разрешённые origins;
- wildcard;
- credentials;
- динамическое отражение Origin;
- regex;
- `Origin: null`;
- localhost origins;
- IP origins;
- HTTP и HTTPS;
- trailing slash;
- смешение port;
- development origins в production;
- WebSocket Origin;
- private network access.

Проверь обработку:

- `X-Forwarded-For`;
- `X-Real-IP`;
- `Forwarded`;
- `X-Forwarded-Proto`;
- `X-Forwarded-Host`;
- `X-Forwarded-Port`.

Убедись, что proxy headers принимаются только от доверенного reverse proxy.

Проверь возможность:

- обхода localhost restriction;
- обхода rate limit;
- обхода lockout;
- подмены адреса в аудите;
- обхода IP allowlist;
- генерации неправильного HTTPS URL;
- host header injection;
- password reset poisoning, если такая функция существует.

# 37. Security headers

Проверь наличие и корректность:

- Content-Security-Policy;
- `default-src`;
- `script-src`;
- `style-src`;
- `connect-src`;
- WebSocket origins;
- `img-src`;
- `object-src 'none'`;
- `base-uri`;
- `frame-ancestors`;
- `form-action`;
- X-Frame-Options;
- X-Content-Type-Options;
- Referrer-Policy;
- Permissions-Policy;
- Cross-Origin-Opener-Policy;
- Cross-Origin-Resource-Policy;
- HSTS;
- Cache-Control;
- Pragma;
- Expires.

HSTS должен включаться только при корректном HTTPS-развертывании.

# 38. systemd unit

Проверь unit-файл Linux Admin:

- `User`;
- `Group`;
- `WorkingDirectory`;
- `ExecStart`;
- абсолютные пути;
- EnvironmentFile;
- права на `.env`;
- Restart;
- RestartSec;
- TimeoutStopSec;
- KillMode;
- UMask;
- LimitNOFILE;
- RuntimeDirectory;
- StateDirectory;
- LogsDirectory;
- ReadWritePaths;
- ReadOnlyPaths;
- InaccessiblePaths;
- PrivateTmp;
- PrivateDevices;
- ProtectSystem;
- ProtectHome;
- NoNewPrivileges;
- CapabilityBoundingSet;
- AmbientCapabilities;
- RestrictAddressFamilies;
- RestrictNamespaces;
- RestrictSUIDSGID;
- LockPersonality;
- MemoryDenyWriteExecute;
- SystemCallFilter;
- ProtectKernelTunables;
- ProtectKernelModules;
- ProtectControlGroups;
- ProtectProc;
- ProcSubset;
- PrivateUsers;
- DevicePolicy.

Определи, какие hardening-параметры совместимы с функциональностью проекта.

Не рекомендуй запуск от root без доказанной необходимости.

# 39. Reverse proxy

Проверь примеры Nginx и Caddy:

- TLS;
- версии TLS;
- cipher suites;
- сертификаты;
- HTTP to HTTPS;
- proxy_pass;
- WebSocket upgrade;
- timeouts;
- body size;
- rate limit;
- buffering;
- forwarded headers;
- trusted proxy;
- Host;
- X-Forwarded-Proto;
- X-Forwarded-For;
- доступ к `/docs`;
- доступ к Setup Wizard;
- IP allowlist;
- Basic Auth;
- mTLS;
- кеширование;
- security headers;
- static assets;
- path normalization;
- double slash;
- encoded path;
- request smuggling;
- несовпадение обработки путей proxy и Uvicorn;
- доступ к backend в обход proxy.

# 40. `.env` и конфигурация

Проверь:

- `.env` в Git;
- `.env.example`;
- слабые значения по умолчанию;
- JWT secret;
- admin password;
- setup token;
- PostgreSQL password;
- CORS;
- bind host;
- debug;
- environment;
- OpenAPI;
- trusted proxies;
- пути;
- названия бинарников;
- module switches;
- logging;
- временные каталоги.

Проверь права:

```text
Владелец: пользователь сервиса или root
Режим: 0600 или минимально необходимый

```

Определи:

- может ли frontend получить `.env`;
- может ли static file handler отдать `.env`;
- попадает ли `.env` в Docker image;
- попадает ли `.env` в backup;
- попадает ли `.env` в diagnostics;
- выводится ли `.env` через `make check`;
- раскрываются ли значения при ошибке старта.

# 41. Секреты

Выполни поиск:

- JWT secrets;
- API keys;
- setup tokens;
- admin passwords;
- PostgreSQL credentials;
- Docker registry credentials;
- WireGuard private keys;
- OpenVPN private keys;
- CA private keys;
- SSH private keys;
- preshared keys;
- webhook secrets;
- proxy credentials;
- тестовые пароли;
- демонстрационные ключи.

Ищи секреты в:

- Python-коде;
- TypeScript;
- `.env`;
- `.env.example`;
- YAML;
- JSON;
- TOML;
- INI;
- systemd units;
- sudoers;
- Makefile;
- shell scripts;
- migrations;
- tests;
- fixtures;
- docs;
- frontend bundle;
- source maps;
- Git history;
- CI/CD;
- логах;
- backup-файлах;
- временных файлах.

Никогда не показывай обнаруженные секреты полностью.

Используй маскирование:

```text
abcd********************************wxyz

```

# 42. Зависимости и supply chain

## Python

Проверь:

- `requirements.txt`;
- `requirements-dev.txt`;
- `pyproject.toml`;
- `poetry.lock`;
- `uv.lock`;
- `Pipfile.lock`;
- editable dependencies;
- Git dependencies;
- локальные paths;
- unpinned versions;
- hashes;
- private indexes;
- extra indexes;
- dependency confusion;
- typosquatting;
- post-install behavior;
- устаревшие библиотеки;
- известные CVE;
- вымышленные ИИ-пакеты.

## Frontend

Проверь:

- `package.json`;
- `package-lock.json`;
- `yarn.lock`;
- `pnpm-lock.yaml`;
- npm scripts;
- preinstall;
- install;
- postinstall;
- prepare;
- Git dependencies;
- local dependencies;
- unpinned versions;
- overrides;
- resolutions;
- abandoned packages;
- известные CVE;
- typosquatting;
- dependency confusion;
- вымышленные ИИ-пакеты.

## Системные зависимости

Проверь использование:

- systemctl;
- journalctl;
- sudo;
- Docker;
- Fail2ban;
- nftables;
- iptables;
- ufw;
- firewalld;
- WireGuard;
- OpenVPN;
- OpenSSH;
- PostgreSQL client.

Определи, как приложение реагирует на неожиданную версию или подменённый бинарник.

# 43. Защита от DoS

Проверь возможность перегрузки через:

- частые login requests;
- WebSocket connections;
- live metrics;
- psutil;
- `/proc`;
- history queries;
- Docker stats;
- Docker logs;
- systemd journal;
- Fail2ban logs;
- firewall logs;
- PostgreSQL activity;
- disk browser;
- network connections;
- большие временные диапазоны;
- большие page size;
- отсутствие пагинации;
- сложные фильтры;
- большое количество API-ключей;
- большое количество пользователей;
- большое количество VPN-клиентов;
- массовую генерацию ключей;
- массовое скачивание конфигураций;
- фоновые задачи;
- subprocess;
- зависшие команды;
- заполнение stdout;
- заполнение диска логами;
- заполнение PostgreSQL;
- pool exhaustion;
- threadpool exhaustion;
- блокирующие вызовы внутри async endpoint.

Проверь наличие:

- rate limiting;
- per-user limit;
- per-key limit;
- per-IP limit;
- WebSocket limit;
- timeout;
- cancellation;
- output size limit;
- pagination;
- retention;
- semaphore;
- queue;
- backpressure;
- circuit breaker;
- graceful shutdown.

# 44. Безопасность кода, созданного ИИ

Отдельно проверь типичные ошибки ИИ-генерируемого кода:

- вымышленные Python-пакеты;
- вымышленные npm-пакеты;
- несуществующие команды Linux;
- неверные флаги команд;
- небезопасное использование `shell=True`;
- фиктивная валидация;
- проверки только во frontend;
- middleware, объявленный, но не зарегистрированный;
- неправильный порядок middleware;
- dependency, созданный, но не применённый к router;
- `allow_mutations`, проверяемый не во всех endpoints;
- RBAC, проверяемый после системного действия;
- fail-open при исключении;
- пустые `except`;
- широкие `except Exception`;
- возврат success при ошибке команды;
- игнорирование exit code;
- доверие stdout вместо exit code;
- небезопасный fallback;
- запуск команды через shell ради удобства;
- автоматическое создание слабого администратора;
- тестовый bypass;
- hardcoded API key;
- debug backdoor;
- mock authentication;
- административный endpoint без защиты;
- самодельная криптография;
- использование `random` для секретов;
- использование UUID как единственной защиты секрета;
- небезопасные временные файлы;
- отсутствие атомарной записи конфигураций;
- отсутствие rollback;
- комментарии о безопасности без реальной реализации.

# 45. Возможные цепочки атак

Попытайся подтвердить или опровергнуть следующие цепочки.

## Цепочка 1

```text
Утечка API-ключа
→ отсутствие срока действия
→ чрезмерные scopes
→ включение allow_mutations
→ изменение SSH Tunnel
→ создание постоянного SSH-доступа

```

## Цепочка 2

```text
Read-only пользователь
→ обход RBAC
→ вызов firewall mutation
→ открытие административного порта
→ удалённый доступ к панели

```

## Цепочка 3

```text
Command injection в systemctl или Fail2ban
→ выполнение команды через sudo
→ root shell
→ полная компрометация хоста

```

## Цепочка 4

```text
Доступ к Docker CLI или Docker socket
→ запуск privileged-контейнера
→ bind mount /
→ изменение файлов хоста
→ root-доступ

```

## Цепочка 5

```text
Path traversal в Disks
→ чтение .env
→ получение JWT secret
→ выпуск административного JWT
→ выполнение системных мутаций

```

## Цепочка 6

```text
Доступ к PostgreSQL панели
→ изменение роли
→ включение allow_mutations
→ создание VPN-клиента
→ доступ к внутренней сети

```

## Цепочка 7

```text
Stored XSS через Docker logs или journal
→ выполнение JavaScript в браузере администратора
→ кража JWT
→ административные операции

```

## Цепочка 8

```text
Подмена X-Forwarded-For
→ представление запроса как localhost
→ доступ к Setup Wizard
→ создание нового администратора

```

## Цепочка 9

```text
Небезопасный sudoers для systemctl
→ запуск изменённого или пользовательского unit
→ выполнение команды от root

```

## Цепочка 10

```text
IDOR при скачивании WireGuard/OpenVPN конфигурации
→ получение чужого private key
→ несанкционированное VPN-подключение

```

Не называй цепочку подтверждённой, пока не подтверждены все её этапы.

# 46. Автоматические инструменты

Предложи безопасные проверки.

## Python

```text
ruff
mypy
bandit
semgrep
pip-audit
Safety
CodeQL
SonarQube или SonarCloud
Gitleaks
TruffleHog
detect-secrets

```

## Frontend

```text
npm audit
npm outdated
ESLint
Semgrep
CodeQL
Gitleaks

```

## Infrastructure

```text
systemd-analyze security <service>
sudo -l -U <service-user>
visudo -c
sshd -t
nginx -t
caddy validate
nft --check
iptables-restore --test

```

## Dynamic testing

```text
OWASP ZAP
Burp Suite
Nuclei с безопасными шаблонами
testssl.sh

```

Не запускай разрушительные шаблоны, DoS, массовый перебор или автоматическую эксплуатацию.

# 47. Формат найденной уязвимости

Каждую проблему оформляй отдельно.

## `[LNXADMIN-XXX] Название проблемы`

**Статус:**  
Подтверждена / вероятна / требует ручной проверки / рекомендация по усилению

**Критичность:**  
Critical / High / Medium / Low / Informational

**CVSS:**  
Оценка и вектор, если применимо.

**CWE:**  
Соответствующий идентификатор.

**OWASP:**  
OWASP Top 10, OWASP API Security Top 10 или OWASP ASVS.

**MITRE ATT&CK:**  
Соответствующая техника, если применимо.

**Компонент:**  
Backend / frontend / API / WebSocket / PostgreSQL / systemd / sudoers / Docker / Firewall / Fail2ban / SSH / WireGuard / OpenVPN.

**Расположение:**

```text
Файл:
Класс или функция:
Номера строк:
API endpoint:
Системная команда:

```

**Описание:**  
Технически точное описание проблемы.

**Поток данных:**

```text
Источник
→ обработка
→ проверка безопасности
→ системный вызов
→ результат

```

**Условия эксплуатации:**  
Какие права и предварительные условия нужны.

**Безопасный сценарий подтверждения:**  
Минимально необходимая неразрушительная проверка.

**Последствия:**  
Оцени влияние на:

- конфиденциальность;
- целостность;
- доступность;
- root-доступ;
- сеть;
- VPN;
- Docker;
- SSH;
- журнал аудита.

**Доказательства:**  
Фрагмент кода, конфигурации или результат безопасной проверки.

Не показывай секреты полностью.

**Причина:**  
Почему возникла проблема.

**Рекомендация:**  
Конкретное исправление.

**Безопасный пример исправления:**

```python
# Исправленный пример Python

```

или:

```typescript
// Исправленный пример TypeScript

```

или:

```ini
# Исправленный systemd или sudoers

```

**Проверка после исправления:**  
Как подтвердить устранение проблемы.

**Возможные регрессии:**  
Какие функции необходимо проверить после исправления.

# 48. Итоговый отчёт

Подготовь отчёт со следующей структурой.

## 1. Резюме для руководства

Укажи:

- общий уровень защищённости;
- готовность к production;
- допустимость использования в локальной сети;
- допустимость публикации в интернет;
- вероятность получения root;
- вероятность компрометации VPN или SSH;
- основные блокирующие риски.

## 2. Оценка безопасности

Поставь оценку от 0 до 10 отдельно для:

- архитектуры;
- JWT-аутентификации;
- API-ключей;
- RBAC;
- `allow_mutations`;
- Setup Wizard;
- FastAPI;
- WebSocket;
- системных команд;
- sudoers;
- systemd;
- Docker;
- Firewall;
- Fail2ban;
- SSH Tunnel;
- WireGuard;
- OpenVPN;
- PostgreSQL;
- frontend;
- аудита;
- развертывания;
- управления секретами;
- зависимостей.

## 3. Статистика

Укажи количество:

- Critical;
- High;
- Medium;
- Low;
- Informational.

## 4. Пять наиболее опасных проблем

Для каждой кратко укажи:

- сценарий;
- необходимые права;
- последствия;
- сложность исправления.

## 5. Возможные цепочки атак

Покажи подтверждённые комбинации уязвимостей, способные привести к:

- root-доступу;
- созданию постоянного SSH-доступа;
- компрометации Docker;
- отключению файрвола;
- получению VPN-доступа;
- удалению следов;
- полной компрометации Linux-хоста.

## 6. Блокирующие проблемы

Укажи, что необходимо исправить до production-развертывания.

## 7. План исправлений

Раздели рекомендации:

### Немедленно

Проблемы, блокирующие эксплуатацию.

### В течение 7 дней

Высокоприоритетные исправления.

### В течение 30 дней

Плановое усиление.

### В следующих версиях

Архитектурные изменения.

## 8. Рекомендуемая архитектура размещения

Предложи безопасную схему:

```text
Администратор
    ↓
VPN или SSH tunnel
    ↓
Nginx / Caddy с TLS или mTLS
    ↓
Linux Admin на 127.0.0.1:8000
    ↓
Отдельный непривилегированный OS-пользователь
    ↓
Узкий sudoers на конкретные команды и аргументы
    ↓
Linux-подсистемы

```

Укажи:

- допустимый bind address;
- firewall-правила;
- необходимость VPN;
- необходимость mTLS;
- необходимость MFA;
- сервисного пользователя;
- минимальный sudoers;
- права на `.env`;
- права на VPN- и SSH-ключи;
- размещение PostgreSQL;
- внешний журнал аудита;
- резервное копирование;
- мониторинг;
- ограничения доступа к Docker.

## 9. Матрица прав

Сформируй рекомендуемую матрицу:

```text
Модуль
Операция
Минимальный уровень роли
Требует allow_mutations
Дополнительный API scope
Требует повторного подтверждения
Требует усиленного аудита
Уровень риска

```

## 10. Матрица sudoers

Сформируй таблицу или структурированный список:

```text
Функция панели
Разрешённый бинарник
Абсолютный путь
Разрешённые аргументы
Запрещённые аргументы
Необходимые Linux capabilities
Можно ли выполнить без sudo
Риск получения root

```

## 11. План повторного тестирования

Укажи:

- какие проблемы проверить повторно;
- какие unit security tests добавить;
- какие integration tests добавить;
- какие negative tests добавить;
- какие проверки включить в CI/CD;
- какие результаты должны блокировать merge;
- какие проверки выполнять перед release;
- какие конфигурации проверять после установки.

# 49. Обязательные правила достоверности

Соблюдай следующие требования:

- не придумывай уязвимости;
- не придумывай файлы, функции и endpoints;
- не придумывай используемые системные команды;
- не называй проблему подтверждённой без доказательства;
- отделяй факты от предположений;
- указывай точные файлы и строки;
- анализируй реальные потоки данных;
- проверяй RBAC на backend;
- проверяй `allow_mutations` непосредственно перед действием;
- проверяй права внутри background worker;
- проверяй exit code системной команды;
- не считай наличие sudoers доказательством безопасности;
- анализируй допустимые аргументы sudo;
- не считай bind на localhost достаточным при неправильных proxy headers;
- не считай frontend-защиту механизмом авторизации;
- не считай наличие CSP доказательством отсутствия XSS;
- не считай использование bcrypt доказательством сильной парольной политики;
- не раскрывай секреты полностью;
- не выполняй опасные операции;
- при недостатке данных указывай, что именно нельзя подтвердить;
- не выдавай универсальные рекомендации вместо анализа кода.

# 50. Порядок выполнения

Выполняй аудит последовательно.

1. Изучи README и документацию.
2. Изучи структуру репозитория.
3. Найди точки запуска backend и frontend.
4. Изучи `.env.example`.
5. Изучи systemd unit, proxy и sudoers.
6. Составь перечень REST и WebSocket endpoints.
7. Определи все системные mutation-операции.
8. Проверь JWT и API keys.
9. Проверь RBAC.
10. Проверь `allow_mutations`.
11. Проверь Setup Wizard.
12. Найди все вызовы subprocess и sudo.
13. Проследи ввод пользователя до системной команды.
14. Проверь Docker.
15. Проверь systemd.
16. Проверь Firewall и Fail2ban.
17. Проверь Linux Users и SSH Tunnel.
18. Проверь WireGuard и OpenVPN.
19. Проверь PostgreSQL.
20. Проверь WebSocket.
21. Проверь frontend.
22. Проверь аудит и логирование.
23. Проверь зависимости и секреты.
24. Построй подтверждённые цепочки атак.
25. Подготовь отчёт и план исправлений.

Сначала выведи:

- краткое понимание архитектуры;
- найденные компоненты;
- перечень модулей;
- список административных функций;
- список REST и WebSocket endpoints;
- перечень системных бинарников;
- модель прав;
- предварительную модель угроз;
- план дальнейшего аудита.

После этого переходи к анализу исходного кода.

Не начинай с универсальных рекомендаций. Сначала исследуй фактическую реализацию проекта.