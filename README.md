# Basketball calendars for Apple / Google

Готовый проект для GitHub Pages + GitHub Actions, который автоматически публикует сайты и подписные `.ics`-календари для четырёх соревнований:

- Единая Лига ВТБ
- Единая Молодежная Лига ВТБ
- WINLINE Basket Cup
- Суперкубок Единой Лиги ВТБ

## Что делает проект

- раз в час запускает Python-скрипт в GitHub Actions;
- загружает несколько сезонов из официального API РФБ с пагинацией;
- объединяет командные календари между сезонами по `teamId`;
- генерирует отдельные `.ics`-файлы;
- публикует отдельные страницы для каждого календаря;
- публикует главную страницу-хаб со ссылками на все соревнования;
- даёт прямые ссылки для подписки из Apple Calendar и Google Calendar;
- показывает рекомендуемый цвет календаря для ручной настройки;
- добавляет кнопку копирования ссылки подписки на страницах каждого календаря.

## Публичные ссылки

### Главная страница
- `https://ollymerk.github.io/`

### Единая Лига ВТБ
- страница: `https://ollymerk.github.io/vtb/`
- календарь: `https://ollymerk.github.io/vtb/vtb-united-league.ics`

### Единая Молодежная Лига ВТБ
- страница: `https://ollymerk.github.io/vtb-youth/`
- календарь: `https://ollymerk.github.io/vtb-youth/vtb-youth-league.ics`

### WINLINE Basket Cup
- страница: `https://ollymerk.github.io/winline-basket-cup/`
- календарь: `https://ollymerk.github.io/winline-basket-cup/winline-basket-cup.ics`

### Суперкубок Единой Лиги ВТБ
- страница: `https://ollymerk.github.io/vtb-supercup/`
- календарь: `https://ollymerk.github.io/vtb-supercup/vtb-supercup.ics`

## Источники данных

Все четыре календаря используют:

- endpoint: `https://pro.russiabasket.org/api/abc/comps/calendar`;
- сезоны: `2026,2027`;
- параметры: `calendarType=-1`, `lang=ru`, `skipCount`, `maxResultCount`;
- теги: `vtb`, `vtbyouth`, `wbc`, `vtb-supercup`.

События дедуплицируются по `game.id`. Для матчей без опубликованного времени создаются all-day события строго по `localDate`.

## Что внутри репозитория

- `scripts/generate_all_calendars.py` — генератор всех четырёх календарей и HTML-страниц
- `.github/workflows/update-calendars.yml` — ежечасный запуск и публикация через GitHub Pages
- `requirements.txt` — Python-зависимости
- `site/` — итоговая собранная статика, которая публикуется на GitHub Pages

## Структура публикуемого сайта

```text
site/
  index.html
  debug.json
  .nojekyll

  vtb/
    index.html
    debug.json
    vtb-united-league.ics

  vtb-youth/
    index.html
    debug.json
    vtb-youth-league.ics

  winline-basket-cup/
    index.html
    debug.json
    winline-basket-cup.ics

  vtb-supercup/
    index.html
    debug.json
    vtb-supercup.ics
```
