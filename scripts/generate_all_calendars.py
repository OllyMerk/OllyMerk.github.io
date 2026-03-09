from __future__ import annotations

import html
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BASE_URL = os.getenv("INFOBASKET_BASE_URL", "https://org.infobasket.su")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://ollymerk.github.io").rstrip("/")
LANG = os.getenv("INFOBASKET_LANG", "ru")

CALENDAR_URL = f"{BASE_URL}/Comp/GetCalendar/"
PERIODS_URL_TEMPLATE = f"{BASE_URL}/Comp/GetCalendarPeriods/{{comp_id}}"

OUTPUT_DIR = Path("site")

UTC = timezone.utc
REQUEST_TIMEOUT = 30
USER_AGENT = "VTB-Calendars-Bot/1.1"


@dataclass(slots=True)
class Competition:
    comp_id: str
    slug: str
    title: str
    ics_filename: str
    color_hex: str


@dataclass(slots=True)
class Event:
    uid: str
    summary: str
    start: datetime | date
    end: datetime | date
    all_day: bool
    location: str | None
    description: str | None
    url: str | None


COMPETITIONS: list[Competition] = [
    Competition(
        comp_id="50714",
        slug="vtb",
        title="Единая Лига ВТБ",
        ics_filename="vtb-united-league.ics",
        color_hex="#010070",
    ),
    Competition(
        comp_id="50719",
        slug="vtb-youth",
        title="Единая Молодежная Лига ВТБ",
        ics_filename="vtb-youth-league.ics",
        color_hex="#1D70B8",
    ),
    Competition(
        comp_id="52553",
        slug="winline-basket-cup",
        title="WINLINE Basket Cup",
        ics_filename="winline-basket-cup.ics",
        color_hex="#ff6a13",
    ),
]


def request_json(url: str, params: dict[str, Any]) -> Any:
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": USER_AGENT,
        },
    )
    response.raise_for_status()
    return response.json()


def norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_ms_ajax_date(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip()
    match = re.fullmatch(r"/Date\((\-?\d+)([+\-]\d{4})?\)/", text)
    if not match:
        return None

    millis = int(match.group(1))
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


def parse_date_ddmmyyyy(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def build_calendar_params(comp: Competition) -> dict[str, Any]:
    return {
        "comps": comp.comp_id,
        "format": "json",
    }


def build_periods_params() -> dict[str, Any]:
    return {
        "lang": LANG,
        "period": "m",
    }


def periods_url(comp: Competition) -> str:
    return PERIODS_URL_TEMPLATE.format(comp_id=comp.comp_id)


def comp_site_url(comp: Competition) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/"


def comp_ics_url(comp: Competition) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/{comp.ics_filename}"


def normalize_tv_line(tv: str | None) -> str | None:
    if not tv:
        return None
    if tv.startswith("ТВ"):
        return tv
    return f"ТВ: {tv}"


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        game_id = norm(row.get("GameID"))
        signature = game_id or json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(row)

    return unique


def build_event(row: dict[str, Any], comp: Competition) -> Event | None:
    game_id = norm(row.get("GameID"))
    if not game_id:
        return None

    team_a = norm(row.get("CompTeamNameAru")) or norm(row.get("ShortTeamNameAru")) or "Команда А"
    team_b = norm(row.get("CompTeamNameBru")) or norm(row.get("ShortTeamNameBru")) or "Команда Б"
    summary = f"{team_a} — {team_b}"

    dt_utc = parse_ms_ajax_date(norm(row.get("GameDateTime")))
    if dt_utc is None:
        dt_utc = parse_ms_ajax_date(norm(row.get("GameDateTimeMoscow")))

    has_time = bool(row.get("HasTime", False))
    game_date = parse_date_ddmmyyyy(norm(row.get("GameDate")))

    all_day = False
    if dt_utc is None:
        if game_date is None:
            return None
        all_day = True
        start_value: datetime | date = game_date
        end_value: datetime | date = game_date + timedelta(days=1)
    else:
        if has_time:
            start_value = dt_utc
            end_value = dt_utc + timedelta(hours=2)
        else:
            all_day = True
            start_value = game_date or dt_utc.date()
            end_value = start_value + timedelta(days=1)

    arena = norm(row.get("ArenaRu"))
    region = norm(row.get("RegionRu"))
    location = " / ".join(part for part in [arena, region] if part) or None

    description_lines: list[str] = []

    league_name = norm(row.get("LeagueNameRu"))
    comp_name = norm(row.get("CompNameRu"))
    game_number = norm(row.get("GameNumber"))
    tv = normalize_tv_line(norm(row.get("TvRu")))
    attendance = row.get("GameAttendance")
    display_local = norm(row.get("DisplayDateTimeLocal"))
    display_msk = norm(row.get("DisplayDateTimeMsk"))

    score_a_raw = row.get("ScoreA")
    score_b_raw = row.get("ScoreB")

    score_a: int | None = None
    score_b: int | None = None

    try:
        if score_a_raw is not None:
            score_a = int(score_a_raw)
    except (TypeError, ValueError):
        score_a = None

    try:
        if score_b_raw is not None:
            score_b = int(score_b_raw)
    except (TypeError, ValueError):
        score_b = None

    show_score = (
        score_a is not None
        and score_b is not None
        and not (score_a == 0 and score_b == 0)
    )

    if league_name:
        description_lines.append(f"Лига: {league_name}")
    if comp_name:
        description_lines.append(f"Этап: {comp_name}")
    if game_number:
        description_lines.append(f"Номер матча: {game_number}")
    if display_local:
        description_lines.append(f"Локальное время: {display_local}")
    if display_msk:
        description_lines.append(f"МСК: {display_msk}")
    if show_score:
        description_lines.append(f"Счет: {score_a}:{score_b}")
    if attendance:
        description_lines.append(f"Посещаемость: {attendance}")
    if tv:
        description_lines.append(tv)

    description = "\n".join(description_lines) if description_lines else None

    return Event(
        uid=f"{comp.slug}-{game_id}@ollymerk.github.io",
        summary=summary,
        start=start_value,
        end=end_value,
        all_day=all_day,
        location=location,
        description=description,
        url=None,
    )


def fetch_calendar_rows(comp: Competition, debug: dict[str, Any]) -> list[dict[str, Any]]:
    params = build_calendar_params(comp)
    payload = request_json(CALENDAR_URL, params)

    if not isinstance(payload, list):
        raise RuntimeError(
            f"Expected list from GetCalendar for comp {comp.comp_id}, got {type(payload).__name__}"
        )

    rows = [row for row in payload if isinstance(row, dict)]
    rows = dedupe_rows(rows)

    debug["calendar_params"] = params
    debug["calendar_rows_count"] = len(rows)
    debug["calendar_first_keys"] = list(rows[0].keys()) if rows else []

    return rows


def fetch_periods(comp: Competition, debug: dict[str, Any]) -> list[dict[str, Any]]:
    params = build_periods_params()
    payload = request_json(periods_url(comp), params)

    periods: list[dict[str, Any]] = []
    if isinstance(payload, list):
        periods = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            periods = [item for item in items if isinstance(item, dict)]

    debug["periods_params"] = params
    debug["periods_count"] = len(periods)
    debug["periods_preview"] = periods[:12]

    return periods


def build_events(rows: list[dict[str, Any]], comp: Competition, debug: dict[str, Any]) -> list[Event]:
    events: list[Event] = []
    skipped: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        event = build_event(row, comp)
        if event is None:
            skipped.append(
                {
                    "index": idx,
                    "GameID": row.get("GameID"),
                    "GameDate": row.get("GameDate"),
                    "GameDateTime": row.get("GameDateTime"),
                }
            )
            continue
        events.append(event)

    def sort_key(event: Event) -> tuple[datetime, str]:
        if isinstance(event.start, datetime):
            dt = event.start.astimezone(UTC)
        else:
            dt = datetime.combine(event.start, datetime.min.time(), tzinfo=UTC)
        return dt, event.summary

    events.sort(key=sort_key)

    debug["built_events"] = len(events)
    debug["skipped_examples"] = skipped[:10]
    return events


def ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def format_ics_datetime(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def format_ics_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def write_ics(events: list[Event], output_path: Path, calendar_name: str) -> None:
    dtstamp = format_ics_datetime(datetime.now(tz=UTC))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OpenAI//Basketball Calendars//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(calendar_name)}",
        "X-WR-TIMEZONE:Europe/Moscow",
    ]

    for event in events:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{ics_escape(event.uid)}",
                f"DTSTAMP:{dtstamp}",
            ]
        )

        if event.all_day:
            assert isinstance(event.start, date)
            assert isinstance(event.end, date)
            lines.append(f"DTSTART;VALUE=DATE:{format_ics_date(event.start)}")
            lines.append(f"DTEND;VALUE=DATE:{format_ics_date(event.end)}")
        else:
            assert isinstance(event.start, datetime)
            assert isinstance(event.end, datetime)
            lines.append(f"DTSTART:{format_ics_datetime(event.start)}")
            lines.append(f"DTEND:{format_ics_datetime(event.end)}")

        lines.append(f"SUMMARY:{ics_escape(event.summary)}")

        if event.location:
            lines.append(f"LOCATION:{ics_escape(event.location)}")
        if event.description:
            lines.append(f"DESCRIPTION:{ics_escape(event.description)}")
        if event.url:
            lines.append(f"URL:{ics_escape(event.url)}")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    output_path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def event_is_upcoming(event: Event, now_utc: datetime) -> bool:
    if event.all_day:
        assert isinstance(event.end, date)
        end_dt = datetime.combine(event.end, datetime.min.time(), tzinfo=UTC)
        return end_dt >= now_utc
    assert isinstance(event.end, datetime)
    return event.end >= now_utc


def render_comp_index(comp: Competition, events: list[Event], debug: dict[str, Any]) -> str:
    updated = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")
    now_utc = datetime.now(tz=UTC)
    upcoming = [event for event in events if event_is_upcoming(event, now_utc)]
    ics_url = comp_ics_url(comp)
    color_hex = comp.color_hex

    rows: list[str] = []
    for event in upcoming[:30]:
        if event.all_day:
            assert isinstance(event.start, date)
            local_start = event.start.strftime("%d.%m.%Y")
        else:
            assert isinstance(event.start, datetime)
            local_start = event.start.astimezone().strftime("%d.%m.%Y %H:%M")

        rows.append(
            "<tr>"
            f"<td>{html.escape(local_start)}</td>"
            f"<td>{html.escape(event.summary)}</td>"
            f"<td>{html.escape(event.location or '')}</td>"
            "</tr>"
        )

    rows_html = "\n".join(rows) if rows else "<tr><td colspan='3'>Нет ближайших матчей</td></tr>"

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(comp.title)}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 40px auto;
      max-width: 1000px;
      padding: 0 18px;
      line-height: 1.6;
    }}
    .card {{
      border: 1px solid #ddd;
      border-radius: 14px;
      padding: 18px;
      margin: 18px 0;
    }}
    a.button, button.copy-button {{
      display: inline-block;
      padding: 12px 16px;
      border-radius: 10px;
      text-decoration: none;
      border: 1px solid #222;
      margin-right: 10px;
      margin-bottom: 10px;
      color: inherit;
      background: #fff;
      cursor: pointer;
      font: inherit;
    }}
    button.copy-button:hover {{
      background: #f7f7f7;
    }}
    .inline-tools {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-top: 8px;
    }}
    .copy-status {{
      color: #666;
      font-size: 14px;
    }}
    .color-row {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 8px;
      flex-wrap: wrap;
    }}
    .color-swatch {{
      width: 22px;
      height: 22px;
      border-radius: 6px;
      border: 1px solid rgba(0,0,0,0.15);
      background: {html.escape(color_hex)};
      display: inline-block;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
    }}
    th, td {{
      border-bottom: 1px solid #eee;
      text-align: left;
      padding: 10px 8px;
      vertical-align: top;
    }}
    code {{
      background: #f4f4f4;
      padding: 2px 6px;
      border-radius: 6px;
      word-break: break-all;
    }}
    .muted {{
      color: #666;
    }}
    h3 {{
      margin-top: 0;
    }}
  </style>
</head>
<body>
  <p><a href="/">← Все календари</a></p>
  <h1>{html.escape(comp.title)}</h1>
  <p class="muted">Обновлено: {html.escape(updated)}. Событий: {len(events)}.</p>

  <div class="card">
    <p><a class="button" href="./{html.escape(comp.ics_filename)}">Открыть .ics файл</a></p>
    <p><strong>Прямая ссылка для подписки:</strong></p>
    <div class="inline-tools">
      <code id="ics-url">{html.escape(ics_url)}</code>
      <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status')">Скопировать</button>
      <span class="copy-status" id="copy-status"></span>
    </div>
  </div>

  <div class="card">
    <h2>Рекомендуемый цвет календаря</h2>
    <p>При желании можно вручную задать этот цвет в приложении календаря:</p>
    <div class="color-row">
      <span class="color-swatch" aria-hidden="true"></span>
      <code>{html.escape(color_hex)}</code>
    </div>
    <p class="muted">Автоматически через .ics цвет не назначается — это ограничение клиентов Apple / Google Calendar.</p>
  </div>

  <div class="card">
    <h2>Как подписаться</h2>

    <h3>Apple Calendar</h3>
    <p><strong>На iPhone / iPad:</strong></p>
    <p>
      Открой Настройки → Приложения → Календарь → Учетные записи календарей →
      Добавить учетную запись → Другое → Добавить подписной календарь
    </p>
    <p>Вставь ссылку:</p>
    <div class="inline-tools">
      <code>{html.escape(ics_url)}</code>
      <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status-apple')">Скопировать</button>
      <span class="copy-status" id="copy-status-apple"></span>
    </div>
    <p>Нажми Далее → Сохранить</p>

    <p><strong>На Mac:</strong></p>
    <p>Открой Calendar → File → New Calendar Subscription</p>
    <p>Вставь ссылку:</p>
    <div class="inline-tools">
      <code>{html.escape(ics_url)}</code>
      <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status-mac')">Скопировать</button>
      <span class="copy-status" id="copy-status-mac"></span>
    </div>
    <p>Подтверди подписку</p>

    <h3>Google Calendar</h3>
    <p>Добавлять такой календарь удобнее через веб-версию Google Calendar:</p>
    <p>
      Открой Google Calendar в браузере → слева у блока «Другие календари» нажми «+» →
      выбери «По URL»
    </p>
    <p>Вставь ссылку:</p>
    <div class="inline-tools">
      <code>{html.escape(ics_url)}</code>
      <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status-google')">Скопировать</button>
      <span class="copy-status" id="copy-status-google"></span>
    </div>
    <p>Нажми «Добавить календарь»</p>
  </div>

  <div class="card">
    <h2>Ближайшие матчи</h2>
    <table>
      <thead>
        <tr><th>Дата / время</th><th>Матч</th><th>Место</th></tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Диагностика</h2>
    <p>Источник календаря: <code>{html.escape(CALENDAR_URL)}</code></p>
    <p>Параметры: <code>{html.escape(json.dumps(build_calendar_params(comp), ensure_ascii=False))}</code></p>
    <p><a href="./debug.json">Открыть debug.json</a></p>
  </div>

  <script>
    async function copyText(text, statusId) {{
      const status = document.getElementById(statusId);
      try {{
        await navigator.clipboard.writeText(text);
        if (status) {{
          status.textContent = "Скопировано";
          setTimeout(() => {{
            status.textContent = "";
          }}, 2000);
        }}
      }} catch (err) {{
        if (status) {{
          status.textContent = "Не удалось скопировать";
          setTimeout(() => {{
            status.textContent = "";
          }}, 2500);
        }}
      }}
    }}
  </script>
</body>
</html>
"""


def render_root_index(results: list[dict[str, Any]]) -> str:
    updated = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")

    cards: list[str] = []
    for result in results:
        comp: Competition = result["comp"]
        events_count: int = result["events_count"]
        upcoming_count: int = result["upcoming_count"]

        cards.append(
            f"""
            <div class="card">
              <h2>{html.escape(comp.title)}</h2>
              <p class="muted">Событий: {events_count}. Ближайших / будущих: {upcoming_count}.</p>
              <p>
                <a class="button" href="/{html.escape(comp.slug)}/">Открыть сайт календаря</a>
                <a class="button" href="/{html.escape(comp.slug)}/{html.escape(comp.ics_filename)}">Подписаться (.ics)</a>
              </p>
            </div>
            """
        )

    cards_html = "\n".join(cards)

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Баскетбольные календари</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 40px auto;
      max-width: 1000px;
      padding: 0 18px;
      line-height: 1.6;
    }}
    .card {{
      border: 1px solid #ddd;
      border-radius: 14px;
      padding: 18px;
      margin: 18px 0;
    }}
    a.button {{
      display: inline-block;
      padding: 12px 16px;
      border-radius: 10px;
      text-decoration: none;
      border: 1px solid #222;
      margin-right: 10px;
      margin-bottom: 10px;
      color: inherit;
    }}
    .muted {{
      color: #666;
    }}
  </style>
</head>
<body>
  <h1>Баскетбольные календари</h1>
  <p class="muted">Обновлено: {html.escape(updated)}.</p>
  <p>Выбери соревнование, открой его страницу и подпишись на календарь на iPhone, Mac или в Google Calendar.</p>
  {cards_html}
</body>
</html>
"""


def ensure_clean_site() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")


def generate_for_comp(comp: Competition) -> dict[str, Any]:
    debug: dict[str, Any] = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "base_url": BASE_URL,
        "calendar_url": CALENDAR_URL,
        "periods_url": periods_url(comp),
        "comp_id": comp.comp_id,
        "lang": LANG,
        "slug": comp.slug,
        "title": comp.title,
        "ics_filename": comp.ics_filename,
        "site_url": comp_site_url(comp),
        "ics_url": comp_ics_url(comp),
        "color_hex": comp.color_hex,
    }

    rows = fetch_calendar_rows(comp, debug)
    fetch_periods(comp, debug)
    events = build_events(rows, comp, debug)

    comp_dir = OUTPUT_DIR / comp.slug
    comp_dir.mkdir(parents=True, exist_ok=True)

    write_ics(events, comp_dir / comp.ics_filename, comp.title)
    (comp_dir / "index.html").write_text(render_comp_index(comp, events, debug), encoding="utf-8")

    debug_payload = {
        **debug,
        "events_count": len(events),
        "first_events": [
            {
                "uid": event.uid,
                "summary": event.summary,
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
                "all_day": event.all_day,
                "location": event.location,
                "description": event.description,
                "url": event.url,
            }
            for event in events[:10]
        ],
    }
    (comp_dir / "debug.json").write_text(
        json.dumps(debug_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    now_utc = datetime.now(tz=UTC)
    upcoming_count = sum(1 for event in events if event_is_upcoming(event, now_utc))

    return {
        "comp": comp,
        "events_count": len(events),
        "upcoming_count": upcoming_count,
    }


def main() -> None:
    ensure_clean_site()

    results: list[dict[str, Any]] = []
    for comp in COMPETITIONS:
        result = generate_for_comp(comp)
        results.append(result)

    (OUTPUT_DIR / "index.html").write_text(render_root_index(results), encoding="utf-8")

    summary = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "site_base_url": SITE_BASE_URL,
        "competitions": [
            {
                "comp_id": result["comp"].comp_id,
                "slug": result["comp"].slug,
                "title": result["comp"].title,
                "ics_filename": result["comp"].ics_filename,
                "color_hex": result["comp"].color_hex,
                "site_url": comp_site_url(result["comp"]),
                "ics_url": comp_ics_url(result["comp"]),
                "events_count": result["events_count"],
                "upcoming_count": result["upcoming_count"],
            }
            for result in results
        ],
    }
    (OUTPUT_DIR / "debug.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_events = sum(result["events_count"] for result in results)
    print(f"Generated {len(results)} calendars and {total_events} total events into {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
