# VTB United League calendar for Apple / Google

Готовый минимальный проект для GitHub Pages + GitHub Actions.

Что делает проект:
- раз в сутки запускает Python-скрипт в GitHub Actions;
- берет календарь Единой Лиги ВТБ из API РФБ (`AbcComp`) по тегу соревнования `vtb`;
- собирает файл `vtb-united-league.ics`;
- публикует его через GitHub Pages;
- дает одну постоянную ссылку, на которую можно подписаться из Apple Calendar и Google Calendar.

## Что внутри

- `scripts/generate_vtb_calendar.py` — генератор `.ics`
- `.github/workflows/update-vtb-calendar.yml` — ежедневный запуск и публикация
- `requirements.txt` — зависимости Python
- `site/` — папка, куда GitHub Actions кладет готовый сайт и `.ics`

## Что тебе сделать на GitHub

### Вариант попроще
Создай публичный репозиторий с именем:

```text
<твой_логин>.github.io
```

Это даст самый короткий адрес сайта:

```text
https://<твой_логин>.github.io/
```

И тогда календарь будет лежать по адресу:

```text
https://<твой_логин>.github.io/vtb-united-league.ics
```

### Загрузка проекта
1. Скачай архив проекта.
2. Распакуй его у себя на компьютере.
3. В GitHub открой свой репозиторий.
4. Нажми **Add file → Upload files**.
5. Перетащи внутрь **все файлы и папки из архива**, а не сам `.zip`.
6. Нажми **Commit changes**.

### Включение публикации
1. Открой **Settings → Pages**.
2. В разделе **Build and deployment** выбери **Source = GitHub Actions**.
3. Сохрани настройки.

### Первый запуск
1. Открой вкладку **Actions**.
2. Слева выбери workflow **Update VTB League calendar**.
3. Нажми **Run workflow**.
4. После успешного выполнения открой:
   - главную страницу сайта;
   - файл `vtb-united-league.ics`.

## Ссылки после публикации

### Если репозиторий называется `<логин>.github.io`

```text
Сайт:      https://<логин>.github.io/
ICS файл:  https://<логин>.github.io/vtb-united-league.ics
```

### Если репозиторий называется иначе, например `vtb-calendar`

```text
Сайт:      https://<логин>.github.io/vtb-calendar/
ICS файл:  https://<логин>.github.io/vtb-calendar/vtb-united-league.ics
```

## Подписка в Apple Calendar
Используй прямую ссылку на `.ics`.

На Mac обычно это делается через:
- **Calendar → File → New Calendar Subscription**

На iPhone/iPad:
- можно открыть ссылку на `.ics` или добавить подписной календарь через системные настройки/сам календарный клиент, в зависимости от версии iOS.

## Подписка в Google Calendar
Используй:
- **Add calendar → From URL**

И вставь прямую ссылку на `.ics`.

## Что важно знать

### 1. Проект берет данные не с HTML-страницы, а из API
Это надежнее, чем парсить визуальную верстку сайта.

Скрипт использует:
- `tag = vtb`
- раздел `AbcComp`
- endpoint для типов календаря
- endpoint самого календаря

### 2. Скрипт специально сделан с запасом по совместимости
Так как схема ответа API может отличаться по ключам, скрипт:
- пробует несколько вариантов query-параметров;
- сначала запрашивает `calendar-types`;
- потом пытается получить календарь с разными комбинациями параметров;
- сохраняет диагностику в `site/debug.json`.

### 3. Если API чуть изменится
Смотри файл:

```text
site/debug.json
```

Там будет видно:
- какие параметры сработали;
- какие запросы вернули ошибки;
- сколько событий удалось извлечь.

## Настройка расписания
По умолчанию workflow запускается раз в сутки:

```yaml
schedule:
  - cron: "17 3 * * *"
```

Это `03:17 UTC` каждый день.

Если хочешь, поменяй время в файле:

```text
.github/workflows/update-vtb-calendar.yml
```

## Ручная настройка переменных
Если когда-нибудь понадобится поменять базовый URL или тег, можно задать их через environment variables в workflow:

```yaml
env:
  RBF_BASE_URL: https://pro.russiabasket.org
  RBF_COMP_TAG: vtb
```

Сейчас это уже зашито в коде по умолчанию, так что отдельная настройка не обязательна.
