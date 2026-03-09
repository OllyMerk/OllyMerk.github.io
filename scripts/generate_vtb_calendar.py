from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BASE_URL = os.getenv("INFOBASKET_BASE_URL", "https://org.infobasket.su")
COMP_ID = os.getenv("INFOBASKET_COMP_ID", "50714")
LANG = os.getenv("INFOBASKET_LANG", "ru")

CALENDAR_URL = f"{BASE_URL}/Comp/GetCalendar/"
PERIODS_URL = f"{BASE_URL}/Comp/GetCalendarPeriods/{COMP_ID}"

OUTPUT_DIR = Path("site")
ICS_FILENAME = "vtb-united-league.ics"

UTC = timezone.utc
REQUEST_TIMEOUT = 30
USER_AGENT = "VTB-Calendar-Bot/5.1"


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
    """
    Parses strings like /Date(1759057200000)/ or /Date(1759057200000+0300)/
    into UTC-aware datetime.
    """
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


def build_calendar_params() -> dict[str, Any]:
    return {
        "comps": COMP_ID,
        "format": "json",
    }


def build_periods_params() -> dict[str, Any]:
    return {
        "lang": LANG,
        "period": "m",
    }


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


def build_event(row: dict[str, Any]) -> Event | None:
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
    tv = norm(row.get("TvRu"))
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
        description_lines.append(f"ТВ: {tv}")

    description = "\n".join(description_lines) if description_lines else None

    return Event(
        uid=f"vtb-{game_id}@ollymerk.github.io",
        summary=summary,
        start=start_value,
        end=end_value,
        all_day=all_day,
        location=location,
        description=description,
        url=None,
    )


def fetch_calendar_rows(debug: dict[str, Any]) -> list[dict[str, Any]]:
    params = build_calendar_params()
    payload = request_json(CALENDAR_URL, params)

    if not isinstance(payload, list):
        raise RuntimeError(f"Expected list from GetCalendar, got {type(payload).__name__}")

    rows = [row for row in payload if isinstance(row, dict)]
    rows = dedupe_rows(rows)

    debug["calendar_params"] = params
    debug["calendar_rows_count"] = len(rows)
    debug["calendar_first_keys"] = list(rows[0].keys()) if rows else []

    return rows


def fetch_periods(debug: dict[str, Any]) -> list[dict[str, Any]]:
    params = build_periods_params()
    payload = request_json(PERIODS_URL, params)

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


def build_events(rows: list[dict[str, Any]], debug: dict[str, Any]) -> list[Event]:
    events: list[Event] = []
    skipped: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        event = build_event(row)
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


def write_ics(events: list[Event], output_path: Path) -> None:
    dtstamp = format_ics_datetime(datetime.now(tz=UTC))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OpenAI//VTB United League Calendar//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Единая Лига ВТБ",
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


def render_index(events: list[Event], debug: dict[str, Any]) -> str:
    updated = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")
    now_utc = datetime.now(tz=UTC)

    def is_upcoming(event: Event) -> bool:
        if event.all_day:
            assert isinstance(event.end, date)
            end_dt = datetime.combine(event.end, datetime.min.time(), tzinfo=UTC)
            return end_dt >= now_utc
        assert isinstance(event.end, datetime)
        return event.end >= now_utc

    upcoming = [event for event in events if is_upcoming(event)]

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
  <title>Календарь Единой Лиги ВТБ</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 40px auto;
      max-width: 1000px;
      padding: 0 18px;
      line-height: 1.5;
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
    }}
    .muted {{
      color: #666;
    }}
  </style>
</head>
<body>
  <h1>Календарь Единой Лиги ВТБ</h1>
  <p class="muted">Обновлено: {html.escape(updated)}. Событий: {len(events)}.</p>

  <div class="card">
    <p><a class="button" href="/{ICS_FILENAME}">Открыть .ics файл</a></p>
    <p>Apple Calendar: подпишись по прямой ссылке на <code>{ICS_FILENAME}</code>.</p>
    <p>Google Calendar: Add calendar → From URL → та же ссылка.</p>
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
    <p>Параметры: <code>{html.escape(json.dumps(build_calendar_params(), ensure_ascii=False))}</code></p>
    <p><a href="/debug.json">Открыть debug.json</a></p>
  </div>
</body>
</html>
"""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    debug: dict[str, Any] = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "base_url": BASE_URL,
        "calendar_url": CALENDAR_URL,
        "periods_url": PERIODS_URL,
        "comp_id": COMP_ID,
        "lang": LANG,
    }

    rows = fetch_calendar_rows(debug)
    fetch_periods(debug)
    events = build_events(rows, debug)

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

    write_ics(events, OUTPUT_DIR / ICS_FILENAME)
    (OUTPUT_DIR / "index.html").write_text(render_index(events, debug), encoding="utf-8")
    (OUTPUT_DIR / "debug.json").write_text(
        json.dumps(debug_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Generated {len(events)} events into {OUTPUT_DIR / ICS_FILENAME}")


if __name__ == "__main__":
    main()
