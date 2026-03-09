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

ROOT_DIR = Path(".")
ASSETS_DIR = ROOT_DIR / "assets"
LOGOS_DIR = ASSETS_DIR / "logos"

OUTPUT_DIR = Path("site")
OUTPUT_ASSETS_DIR = OUTPUT_DIR / "assets"
OUTPUT_LOGOS_DIR = OUTPUT_ASSETS_DIR / "logos"

UTC = timezone.utc
REQUEST_TIMEOUT = 30
USER_AGENT = "Basketball-Calendars-Bot/2.0"


@dataclass(slots=True)
class Competition:
    comp_id: str
    slug: str
    title: str
    short_title: str
    description: str
    ics_filename: str
    color_hex: str
    logo_filename: str | None
    team_mode: bool = True


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
    team_a: str | None
    team_b: str | None


COMPETITIONS: list[Competition] = [
    Competition(
        comp_id="50714",
        slug="vtb",
        title="Единая Лига ВТБ",
        short_title="VTB",
        description="Календарь матчей Единой Лиги ВТБ с автообновлением для Apple Calendar и Google Calendar.",
        ics_filename="vtb-united-league.ics",
        color_hex="#010070",
        logo_filename="vtb.png",
    ),
    Competition(
        comp_id="50719",
        slug="vtb-youth",
        title="Единая Молодежная Лига ВТБ",
        short_title="VTB Youth",
        description="Календарь матчей Единой Молодежной Лиги ВТБ с автообновлением для Apple Calendar и Google Calendar.",
        ics_filename="vtb-youth-league.ics",
        color_hex="#1D70B8",
        logo_filename="vtb-youth.png",
    ),
    Competition(
        comp_id="52553",
        slug="winline-basket-cup",
        title="WINLINE Basket Cup",
        short_title="WCB",
        description="Подписной календарь матчей WINLINE Basket Cup с ежедневным обновлением.",
        ics_filename="winline-basket-cup.ics",
        color_hex="#ff6a13",
        logo_filename="winline-basket-cup.png",
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


def comp_teams_url(comp: Competition) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/teams/"


def logo_site_path(comp: Competition) -> str | None:
    if not comp.logo_filename:
        return None
    return f"/assets/logos/{comp.logo_filename}"


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

    # Используем московское время как нормализованную временную точку.
    dt_utc = parse_ms_ajax_date(norm(row.get("GameDateTimeMoscow")))
    if dt_utc is None:
        dt_utc = parse_ms_ajax_date(norm(row.get("GameDateTime")))

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
        team_a=team_a,
        team_b=team_b,
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
                    "GameDateTimeMoscow": row.get("GameDateTimeMoscow"),
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


def extract_team_names(events: list[Event]) -> list[str]:
    teams: set[str] = set()
    for event in events:
        if event.team_a:
            teams.add(event.team_a)
        if event.team_b:
            teams.add(event.team_b)
    return sorted(teams)


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


def render_logo(comp: Competition, size: int = 52) -> str:
    logo_path = logo_site_path(comp)
    if logo_path and comp.logo_filename and (LOGOS_DIR / comp.logo_filename).exists():
        return (
            f'<img src="{html.escape(logo_path)}" alt="{html.escape(comp.title)}" '
            f'style="width:{size}px;height:{size}px;object-fit:contain;border-radius:12px;background:#fff;padding:6px;">'
        )

    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:14px;'
        f'background:{html.escape(comp.color_hex)};color:#fff;display:flex;align-items:center;'
        f'justify-content:center;font-weight:700;font-size:16px;">'
        f'{html.escape(comp.short_title[:3])}'
        f'</div>'
    )


def render_card_css() -> str:
    return """
    body {
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      background: #f5f7fb;
      color: #101828;
    }
    .wrap {
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }
    .hero {
      border-radius: 24px;
      padding: 28px;
      margin-bottom: 24px;
      background: linear-gradient(135deg, #ffffff 0%, #eef2ff 100%);
      border: 1px solid rgba(16, 24, 40, 0.08);
      box-shadow: 0 10px 30px rgba(16, 24, 40, 0.06);
    }
    .hero h1 {
      margin: 0 0 8px;
      font-size: 42px;
      line-height: 1.05;
    }
    .hero p {
      margin: 0;
      color: #475467;
      font-size: 18px;
    }
    .card {
      border-radius: 24px;
      padding: 22px;
      margin: 18px 0;
      background: #ffffff;
      border: 1px solid rgba(16, 24, 40, 0.08);
      box-shadow: 0 10px 26px rgba(16, 24, 40, 0.05);
    }
    .muted {
      color: #667085;
    }
    .button, button.copy-button {
      display: inline-block;
      padding: 12px 16px;
      border-radius: 12px;
      text-decoration: none;
      border: 1px solid rgba(16, 24, 40, 0.12);
      background: #fff;
      color: inherit;
      cursor: pointer;
      font: inherit;
      font-weight: 600;
      transition: 0.18s ease;
    }
    .button:hover, button.copy-button:hover {
      transform: translateY(-1px);
      background: #f9fafb;
    }
    .button.primary {
      color: #fff;
      border: none;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
    }
    th, td {
      border-bottom: 1px solid #eaecf0;
      text-align: left;
      padding: 12px 8px;
      vertical-align: top;
    }
    code {
      background: #f2f4f7;
      padding: 4px 8px;
      border-radius: 8px;
      word-break: break-all;
      font-size: 14px;
    }
    .inline-tools {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-top: 8px;
    }
    .copy-status {
      color: #667085;
      font-size: 14px;
    }
    .color-row {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 8px;
      flex-wrap: wrap;
    }
    .color-swatch {
      width: 22px;
      height: 22px;
      border-radius: 6px;
      border: 1px solid rgba(0,0,0,0.15);
      display: inline-block;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 18px;
    }
    .comp-card {
      border-radius: 24px;
      padding: 22px;
      color: #fff;
      position: relative;
      overflow: hidden;
      box-shadow: 0 14px 30px rgba(16, 24, 40, 0.14);
    }
    .comp-card .overlay {
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.00) 52%);
      pointer-events: none;
    }
    .comp-card-top {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 18px;
      position: relative;
      z-index: 1;
    }
    .comp-card h2 {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }
    .comp-card p {
      margin: 8px 0 0;
      opacity: 0.95;
      position: relative;
      z-index: 1;
    }
    .comp-card-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
      position: relative;
      z-index: 1;
    }
    .comp-card .button {
      background: rgba(255,255,255,0.14);
      border: 1px solid rgba(255,255,255,0.18);
      color: #fff;
      backdrop-filter: blur(6px);
    }
    .comp-card .button:hover {
      background: rgba(255,255,255,0.22);
    }
    .pill {
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.14);
      font-size: 13px;
      font-weight: 600;
      margin-right: 8px;
      margin-top: 8px;
    }
    .section-title {
      margin: 0 0 10px;
      font-size: 28px;
    }
    .subtle-link {
      color: inherit;
      text-decoration: none;
      border-bottom: 1px solid rgba(16, 24, 40, 0.12);
    }
    """
    

def render_copy_script() -> str:
    return """
    <script>
      async function copyText(text, statusId) {
        const status = document.getElementById(statusId);
        try {
          await navigator.clipboard.writeText(text);
          if (status) {
            status.textContent = "Скопировано";
            setTimeout(() => { status.textContent = ""; }, 2000);
          }
        } catch (err) {
          if (status) {
            status.textContent = "Не удалось скопировать";
            setTimeout(() => { status.textContent = ""; }, 2500);
          }
        }
      }
    </script>
    """


def render_comp_index(comp: Competition, events: list[Event], debug: dict[str, Any]) -> str:
    updated = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")
    now_utc = datetime.now(tz=UTC)
    upcoming = [event for event in events if event_is_upcoming(event, now_utc)]
    ics_url = comp_ics_url(comp)
    color_hex = comp.color_hex
    logo_html = render_logo(comp, size=60)

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
    {render_card_css()}
    .hero.comp-hero {{
      background: linear-gradient(135deg, {html.escape(color_hex)} 0%, #ffffff 240%);
      color: #fff;
      position: relative;
      overflow: hidden;
    }}
    .hero.comp-hero p,
    .hero.comp-hero .muted {{
      color: rgba(255,255,255,0.9);
    }}
    .hero-row {{
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .hero-row .title-block {{
      flex: 1;
      min-width: 240px;
    }}
    .hero-row h1 {{
      margin-bottom: 10px;
    }}
    .teams-card {{
      border-style: dashed;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <p><a class="subtle-link" href="/">← Все календари</a></p>

    <div class="hero comp-hero">
      <div class="hero-row">
        {logo_html}
        <div class="title-block">
          <h1>{html.escape(comp.title)}</h1>
          <p>{html.escape(comp.description)}</p>
          <p class="muted">Обновлено: {html.escape(updated)}. Событий: {len(events)}.</p>
        </div>
      </div>
    </div>

    <div class="card">
      <p><a class="button primary" style="background:{html.escape(color_hex)};" href="./{html.escape(comp.ics_filename)}">Открыть .ics файл</a></p>
      <p><strong>Прямая ссылка для подписки:</strong></p>
      <div class="inline-tools">
        <code id="ics-url">{html.escape(ics_url)}</code>
        <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status')">Скопировать</button>
        <span class="copy-status" id="copy-status"></span>
      </div>
    </div>

    <div class="card">
      <h2 class="section-title">Рекомендуемый цвет календаря</h2>
      <p>При желании можно вручную задать этот цвет в приложении календаря:</p>
      <div class="color-row">
        <span class="color-swatch" style="background:{html.escape(color_hex)};"></span>
        <code>{html.escape(color_hex)}</code>
      </div>
      <p class="muted">Автоматически через .ics цвет не назначается — это ограничение клиентов Apple / Google Calendar.</p>
    </div>

    <div class="card">
      <h2 class="section-title">Как подписаться</h2>

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

    <div class="card teams-card">
      <h2 class="section-title">Календари по командам</h2>
      <p>Этот раздел подготовлен для следующего этапа. Здесь появятся отдельные страницы и .ics-файлы по командам внутри турнира.</p>
      <p><a class="button" href="./teams/">Открыть раздел команд</a></p>
    </div>

    <div class="card">
      <h2 class="section-title">Ближайшие матчи</h2>
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
      <h2 class="section-title">Диагностика</h2>
      <p>Источник календаря: <code>{html.escape(CALENDAR_URL)}</code></p>
      <p>Параметры: <code>{html.escape(json.dumps(build_calendar_params(comp), ensure_ascii=False))}</code></p>
      <p><a class="subtle-link" href="./debug.json">Открыть debug.json</a></p>
    </div>
  </div>

  {render_copy_script()}
</body>
</html>
"""


def render_teams_placeholder(comp: Competition, team_names: list[str]) -> str:
    team_list_html = ""
    if team_names:
        preview = "".join(f"<li>{html.escape(name)}</li>" for name in team_names[:30])
        team_list_html = f"""
        <p class="muted">Ниже — предварительный список команд, найденных в календаре:</p>
        <ul>
          {preview}
        </ul>
        """

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Команды — {html.escape(comp.title)}</title>
  <style>
    {render_card_css()}
  </style>
</head>
<body>
  <div class="wrap">
    <p><a class="subtle-link" href="/{html.escape(comp.slug)}/">← Назад к календарю соревнования</a></p>
    <div class="hero">
      <h1>Командные календари</h1>
      <p>{html.escape(comp.title)}</p>
    </div>
    <div class="card">
      <p>Этот раздел уже подготовлен технически. Следующим этапом здесь появятся отдельные календари по командам.</p>
      {team_list_html}
    </div>
  </div>
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
        logo_html = render_logo(comp, size=56)

        cards.append(
            f"""
            <div class="comp-card" style="background: linear-gradient(135deg, {html.escape(comp.color_hex)} 0%, rgba(0,0,0,0.78) 100%);">
              <div class="overlay"></div>
              <div class="comp-card-top">
                {logo_html}
                <div>
                  <h2>{html.escape(comp.title)}</h2>
                  <p>{html.escape(comp.description)}</p>
                </div>
              </div>

              <div style="position:relative;z-index:1;">
                <span class="pill">Событий: {events_count}</span>
                <span class="pill">Ближайших / будущих: {upcoming_count}</span>
              </div>

              <div class="comp-card-actions">
                <a class="button" href="/{html.escape(comp.slug)}/">Открыть сайт календаря</a>
                <a class="button" href="/{html.escape(comp.slug)}/{html.escape(comp.ics_filename)}">Подписаться (.ics)</a>
              </div>
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
    {render_card_css()}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Баскетбольные календари</h1>
      <p>Подписные календари с автообновлением для Apple Calendar и Google Calendar.</p>
      <p class="muted" style="margin-top:10px;">Обновлено: {html.escape(updated)}.</p>
    </div>

    <div class="grid">
      {cards_html}
    </div>
  </div>
</body>
</html>
"""


def ensure_clean_site() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")


def copy_assets() -> dict[str, Any]:
    assets_debug: dict[str, Any] = {
        "assets_dir_exists": ASSETS_DIR.exists(),
        "logos_dir_exists": LOGOS_DIR.exists(),
        "copied_files": [],
    }

    if OUTPUT_ASSETS_DIR.exists():
        shutil.rmtree(OUTPUT_ASSETS_DIR)
    OUTPUT_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_LOGOS_DIR.mkdir(parents=True, exist_ok=True)

    if LOGOS_DIR.exists():
        for file_path in LOGOS_DIR.iterdir():
            if file_path.is_file():
                target = OUTPUT_LOGOS_DIR / file_path.name
                shutil.copy2(file_path, target)
                assets_debug["copied_files"].append(file_path.name)

    return assets_debug


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
        "short_title": comp.short_title,
        "description": comp.description,
        "ics_filename": comp.ics_filename,
        "site_url": comp_site_url(comp),
        "ics_url": comp_ics_url(comp),
        "teams_url": comp_teams_url(comp),
        "color_hex": comp.color_hex,
        "logo_filename": comp.logo_filename,
    }

    rows = fetch_calendar_rows(comp, debug)
    fetch_periods(comp, debug)
    events = build_events(rows, comp, debug)
    team_names = extract_team_names(events)

    comp_dir = OUTPUT_DIR / comp.slug
    comp_dir.mkdir(parents=True, exist_ok=True)

    write_ics(events, comp_dir / comp.ics_filename, comp.title)
    (comp_dir / "index.html").write_text(render_comp_index(comp, events, debug), encoding="utf-8")

    teams_dir = comp_dir / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)
    (teams_dir / "index.html").write_text(
        render_teams_placeholder(comp, team_names),
        encoding="utf-8",
    )

    debug_payload = {
        **debug,
        "teams_detected_count": len(team_names),
        "teams_detected_preview": team_names[:50],
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
                "team_a": event.team_a,
                "team_b": event.team_b,
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
        "teams_detected_count": len(team_names),
    }


def main() -> None:
    ensure_clean_site()
    assets_debug = copy_assets()

    results: list[dict[str, Any]] = []
    for comp in COMPETITIONS:
        result = generate_for_comp(comp)
        results.append(result)

    (OUTPUT_DIR / "index.html").write_text(render_root_index(results), encoding="utf-8")

    summary = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "site_base_url": SITE_BASE_URL,
        "assets_debug": assets_debug,
        "competitions": [
            {
                "comp_id": result["comp"].comp_id,
                "slug": result["comp"].slug,
                "title": result["comp"].title,
                "short_title": result["comp"].short_title,
                "ics_filename": result["comp"].ics_filename,
                "color_hex": result["comp"].color_hex,
                "logo_filename": result["comp"].logo_filename,
                "site_url": comp_site_url(result["comp"]),
                "ics_url": comp_ics_url(result["comp"]),
                "teams_url": comp_teams_url(result["comp"]),
                "events_count": result["events_count"],
                "upcoming_count": result["upcoming_count"],
                "teams_detected_count": result["teams_detected_count"],
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
