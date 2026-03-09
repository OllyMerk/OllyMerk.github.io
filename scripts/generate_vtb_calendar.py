from __future__ import annotations

import html
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BASE_URL = os.getenv("RBF_BASE_URL", "https://pro.russiabasket.org")
TAG = os.getenv("RBF_COMP_TAG", "vtb")
SEASON = os.getenv("RBF_SEASON", "2026")
CALENDAR_TYPE = os.getenv("RBF_CALENDAR_TYPE", "").strip()

CALENDAR_ENDPOINT = f"{BASE_URL}/api/abc/comps/calendar"
OUTPUT_DIR = Path("site")
ICS_FILENAME = "vtb-united-league.ics"

UTC = timezone.utc
REQUEST_TIMEOUT = 30
USER_AGENT = "VTB-Calendar-Bot/2.0"


@dataclass(slots=True)
class Event:
    uid: str
    summary: str
    start: datetime
    end: datetime
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
    s = str(value).strip()
    return s or None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip()
    if not text:
        return None

    try:
        # Пример: 2025-09-28T14:00:00+03:00
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return dt


def build_params() -> dict[str, Any]:
    params: dict[str, Any] = {
        "tag": TAG,
        "season": SEASON,
    }
    if CALENDAR_TYPE:
        params["calendarType"] = CALENDAR_TYPE
    return params


def build_event(item: dict[str, Any]) -> Event | None:
    game = item.get("game") or {}
    team1 = item.get("team1") or {}
    team2 = item.get("team2") or {}
    arena = item.get("arena") or {}
    status = item.get("status") or {}
    comp = item.get("comp") or {}
    league = item.get("league") or {}
    region = item.get("region") or {}

    game_id = norm(game.get("id"))
    if not game_id:
        return None

    dt = parse_dt(game.get("scheduledTime")) or parse_dt(game.get("defaultZoneDateTime"))
    if dt is None:
        return None

    team1_name = norm(team1.get("name")) or norm(team1.get("shortName")) or "Team 1"
    team2_name = norm(team2.get("name")) or norm(team2.get("shortName")) or "Team 2"
    summary = f"{team1_name} — {team2_name}"

    arena_name = norm(arena.get("name")) or norm(arena.get("shortName"))
    region_name = norm(region.get("name"))
    location = " / ".join(part for part in [arena_name, region_name] if part) or None

    league_name = norm(league.get("name"))
    comp_name = norm(comp.get("name"))
    status_name = norm(status.get("displayName"))
    tv = norm(game.get("tv"))
    score = norm(game.get("score"))
    full_score = norm(game.get("fullScore"))
    game_number = norm(game.get("number"))
    local_date = norm(game.get("localDate"))
    local_time = norm(game.get("localTime"))

    description_lines = []
    if league_name:
        description_lines.append(f"Лига: {league_name}")
    if comp_name:
        description_lines.append(f"Этап: {comp_name}")
    if game_number:
        description_lines.append(f"Номер матча: {game_number}")
    if status_name:
        description_lines.append(f"Статус: {status_name}")
    if local_date or local_time:
        description_lines.append(
            f"Локальное время: {' '.join(part for part in [local_date, local_time] if part)}"
        )
    if score:
        description_lines.append(f"Счет: {score}")
    if full_score:
        description_lines.append(f"По четвертям: {full_score}")
    if tv:
        description_lines.append(f"ТВ / видео: {tv}")

    description = "\n".join(description_lines) if description_lines else None

    # Для баскетбольного календаря ставим длительность 2 часа по умолчанию
    end = dt + timedelta(hours=2)

    return Event(
        uid=f"vtb-{game_id}@ollymerk.github.io",
        summary=summary,
        start=dt,
        end=end,
        location=location,
        description=description,
        url=None,
    )


def fetch_events(debug: dict[str, Any]) -> list[Event]:
    params = build_params()
    payload = request_json(CALENDAR_ENDPOINT, params)

    debug["request_params"] = params
    debug["top_level_keys"] = list(payload.keys()) if isinstance(payload, dict) else []
    debug["status"] = payload.get("status") if isinstance(payload, dict) else None
    debug["message"] = payload.get("message") if isinstance(payload, dict) else None
    debug["totalCount"] = payload.get("totalCount") if isinstance(payload, dict) else None

    items = payload.get("items", []) if isinstance(payload, dict) else []
    debug["items_count"] = len(items)

    events: list[Event] = []
    skipped: list[dict[str, Any]] = []

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            skipped.append({"index": idx, "reason": "item is not dict"})
            continue

        event = build_event(item)
        if event is None:
            skipped.append(
                {
                    "index": idx,
                    "reason": "could not build event",
                    "keys": list(item.keys()),
                    "game_id": ((item.get("game") or {}).get("id")),
                }
            )
            continue

        events.append(event)

    debug["built_events"] = len(events)
    debug["skipped_examples"] = skipped[:10]

    return sorted(events, key=lambda e: (e.start, e.summary))


def ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def format_ics_datetime(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


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
                f"DTSTART:{format_ics_datetime(event.start)}",
                f"DTEND:{format_ics_datetime(event.end)}",
                f"SUMMARY:{ics_escape(event.summary)}",
            ]
        )

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
    upcoming = [event for event in events if event.end >= datetime.now(tz=UTC)]

    rows = []
    for event in upcoming[:30]:
        local_start = event.start.astimezone().strftime("%d.%m.%Y %H:%M")
        rows.append(
            "<tr>"
            f"<td>{html.escape(local_start)}</td>"
            f"<td>{html.escape(event.summary)}</td>"
            f"<td>{html.escape(event.location or '')}</td>"
            "</tr>"
        )

    rows_html = "\n".join(rows) if rows else "<tr><td colspan='3'>Нет матчей</td></tr>"

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
    <p>Источник: <code>{html.escape(CALENDAR_ENDPOINT)}</code></p>
    <p>Параметры: <code>{html.escape(json.dumps(build_params(), ensure_ascii=False))}</code></p>
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
        "endpoint": CALENDAR_ENDPOINT,
        "tag": TAG,
        "season": SEASON,
        "calendarType": CALENDAR_TYPE or None,
    }

    events = fetch_events(debug)

    debug_payload = {
        **debug,
        "events_count": len(events),
        "first_events": [
            {
                "uid": event.uid,
                "summary": event.summary,
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
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
