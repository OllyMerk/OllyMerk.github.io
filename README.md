# Basketball calendars for Apple / Google

Готовый проект для GitHub Pages + GitHub Actions, который автоматически публикует сайты и подписные `.ics`-календари для трёх соревнований:

- Единая Лига ВТБ
- Единая Молодежная Лига ВТБ
- WINLINE Basket Cup

## Что делает проект

- раз в сутки запускает Python-скрипт в GitHub Actions;
- берёт календари соревнований из `org.infobasket.su`;
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

## Источники данных

### Единая Лига ВТБ
- `https://org.infobasket.su/Comp/GetCalendar/?comps=50714&format=json`
- `https://org.infobasket.su/Comp/GetCalendarPeriods/50714?lang=ru&period=m`

### Единая Молодежная Лига ВТБ
- `https://org.infobasket.su/Comp/GetCalendar/?comps=50719&format=json`
- `https://org.infobasket.su/Comp/GetCalendarPeriods/50719?lang=ru&period=m`

### WINLINE Basket Cup
- `https://org.infobasket.su/Comp/GetCalendar/?comps=52553&format=json`
- `https://org.infobasket.su/Comp/GetCalendarPeriods/52553?lang=ru&period=m`

## Что внутри репозитория

- `scripts/generate_all_calendars.py` — генератор всех трёх календарей и HTML-страниц
- `.github/workflows/update-calendars.yml` — ежедневный запуск и публикация через GitHub Pages
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
