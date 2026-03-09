from __future__ import annotations

import hashlib
import html
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from zoneinfo import ZoneInfo

BASE_URL = os.getenv("RBF_BASE_URL", "https://pro.russiabasket.org")
TAG = os.getenv("RBF_COMP_TAG", "vtb")
CALENDAR_TYPES_ENDPOINT = f"{BASE_URL}/api/abc/comps/calendar-types"
CALENDAR_ENDPOINT = f"{BASE_URL}/api/abc/comps/calendar"
OUTPUT_DIR = Path("site")
ICS_FILENAME = "vtb-united-league.ics"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
UTC = timezone.utc
REQUEST_TIMEOUT = 30
USER_AGENT = "VTB-Calendar-Bot/1.0 (+GitHub Actions)"


@dataclass(slots=True)
class Event:
    uid: str
    summary: str
    start: datetime
    end: datetime
    location: str | None
    description: str | None
    url: str | None
    source_params: dict[str, Any]


class FetchError(RuntimeError):
    pass


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


def normalize_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        s = re.sub(r"\s+", " ", value).strip()
        return s or None
    return None


def walk(node: Any) -> Iterable[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def keys_lower(d: dict[str, Any]) -> dict[str, Any]:
    return {str(k).lower(): v for k, v in d.items()}


def pick_any(d: dict[str, Any], candidate_keys: Iterable[str]) -> Any:
    lower = keys_lower(d)
    for key in candidate_keys:
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def nested_name(value: Any) -> str | None:
    if isinstance(value, str):
        return normalize_string(value)
    if isinstance(value, dict):
        return normalize_string(
            pick_any(
                value,
                [
                    "name",
                    "title",
                    "fullName",
                    "full_name",
                    "shortName",
                    "short_name",
                    "nickname",
                ],
            )
        )
    return None


_DATE_KEYS = [
    "date",
    "gameDate",
    "game_date",
    "datetime",
    "dateTime",
    "date_time",
    "beginDate",
    "begin_date",
    "startDate",
    "start_date",
    "utcDate",
    "utc_date",
]

_HOME_KEYS = [
    "home",
    "homeTeam",
    "home_team",
    "teamHome",
    "team_home",
    "localTeam",
    "local_team",
    "team1",
    "team_1",
    "teamA",
    "team_a",
]

_AWAY_KEYS = [
    "away",
    "awayTeam",
    "away_team",
    "teamAway",
    "team_away",
    "guestTeam",
    "guest_team",
    "visitorTeam",
    "visitor_team",
    "team2",
    "team_2",
    "teamB",
    "team_b",
]

_LOCATION_KEYS = [
    "arena",
    "venue",
    "place",
    "location",
    "hall",
    "gym",
]

_URL_KEYS = ["url", "link", "matchUrl", "match_url", "gameUrl", "game_url"]

_ID_KEYS = ["id", "gameId", "game_id", "matchId", "match_id"]


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Heuristic: treat big integers as Unix timestamps in ms.
        num = float(value)
        if num > 10_000_000_000:
            num /= 1000.0
        return datetime.fromtimestamp(num, tz=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    try:
        dt = dtparser.isoparse(text)
    except Exception:
        dt = None

    if dt is None:
        for fmt in (
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue

    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MOSCOW_TZ)
    return dt


def looks_like_event_dict(d: dict[str, Any]) -> bool:
    lower = keys_lower(d)
    has_date = any(key.lower() in lower for key in _DATE_KEYS)
    has_teams = any(key.lower() in lower for key in _HOME_KEYS) or any(
        key.lower() in lower for key in _AWAY_KEYS
    )
    has_title = "title" in lower or "name" in lower
    return has_date and (has_teams or has_title)


def extract_event_from_dict(d: dict[str, Any], source_params: dict[str, Any]) -> Event | None:
    dt = parse_dt(pick_any(d, _DATE_KEYS))
    if dt is None:
        return None

    home = nested_name(pick_any(d, _HOME_KEYS))
    away = nested_name(pick_any(d, _AWAY_KEYS))

    title = normalize_string(pick_any(d, ["title", "name"]))
    if not title and home and away:
        title = f"{home} — {away}"
    if not title:
        return None

    location = nested_name(pick_any(d, _LOCATION_KEYS))
    url = normalize_string(pick_any(d, _URL_KEYS))
    raw_id = normalize_string(pick_any(d, _ID_KEYS))
    if not raw_id:
        digest = hashlib.sha1((title + dt.isoformat()).encode("utf-8")).hexdigest()[:16]
        raw_id = digest

    summary = title
    description_parts = [
        "Официальный календарь Единой Лиги ВТБ / РФБ API.",
        f"Источник параметров: {json.dumps(source_params, ensure_ascii=False, sort_keys=True)}",
    ]
    if url:
        description_parts.append(f"Ссылка: {url}")
    description = "\n".join(description_parts)

    end = dt + timedelta(hours=2)
    return Event(
        uid=f"vtb-{raw_id}@calendar",
        summary=summary,
        start=dt,
        end=end,
        location=location,
        description=description,
        url=url,
        source_params=source_params,
    )


def extract_event_candidates(payload: Any, source_params: dict[str, Any]) -> list[Event]:
    events: list[Event] = []
    for node in walk(payload):
        if isinstance(node, dict) and looks_like_event_dict(node):
            event = extract_event_from_dict(node, source_params)
            if event:
                events.append(event)
    return dedupe_events(events)


def extract_calendar_type_values(payload: Any) -> list[Any]:
    candidates: list[Any] = []
    seen: set[str] = set()

    for node in walk(payload):
        if isinstance(node, dict):
            value = pick_any(node, ["id", "value", "code", "slug", "key", "type", "calendarType", "calendar_type"])
            label = normalize_string(pick_any(node, ["name", "title", "label"]))
            if value is None:
                continue
            signature = json.dumps({"value": value, "label": label}, ensure_ascii=False, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append(value)

    return candidates


def additional_context_params(payload: Any) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = [{}]
    seen: set[str] = {json.dumps({}, sort_keys=True)}

    candidate_key_sets = [
        ("season_id", "seasonId", "season"),
        ("comp_id", "compId", "competition_id", "tournament_id"),
    ]

    for node in walk(payload):
        if not isinstance(node, dict):
            continue
        ctx: dict[str, Any] = {}
        season_value = pick_any(node, candidate_key_sets[0])
        comp_value = pick_any(node, candidate_key_sets[1])
        if season_value is not None:
            ctx["season_id"] = season_value
        if comp_value is not None:
            ctx["comp_id"] = comp_value
        if ctx:
            signature = json.dumps(ctx, ensure_ascii=False, sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                contexts.append(ctx)

    return contexts


def candidate_param_sets() -> list[dict[str, Any]]:
    return [
        {"tag": TAG},
        {"comp_tag": TAG},
        {"competition_tag": TAG},
        {"slug": TAG},
        {},
    ]


def fetch_calendar_types(debug: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    last_error = None
    for params in candidate_param_sets():
        try:
            payload = request_json(CALENDAR_TYPES_ENDPOINT, params)
            debug.setdefault("calendar_types_attempts", []).append({"params": params, "ok": True})
            return payload, params
        except Exception as exc:
            last_error = exc
            debug.setdefault("calendar_types_attempts", []).append(
                {"params": params, "ok": False, "error": str(exc)}
            )
    raise FetchError(f"Could not fetch calendar types: {last_error}")


def build_calendar_param_candidates(
    calendar_type_values: list[Any],
    contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    base_variants = [
        {"tag": TAG},
        {"comp_tag": TAG},
        {"competition_tag": TAG},
        {},
    ]

    type_keys = ["calendarType", "calendar_type", "type", "calendar"]

    for base in base_variants:
        for ctx in contexts:
            merged_base = {**base, **ctx}
            signature = json.dumps(merged_base, ensure_ascii=False, sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                candidates.append(merged_base)

            for value in calendar_type_values:
                for type_key in type_keys:
                    params = {**merged_base, type_key: value}
                    signature = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
                    if signature not in seen:
                        seen.add(signature)
                        candidates.append(params)
    return candidates


def fetch_all_calendars(debug: dict[str, Any]) -> list[Event]:
    types_payload, types_params = fetch_calendar_types(debug)
    calendar_type_values = extract_calendar_type_values(types_payload)
    contexts = additional_context_params(types_payload)
    param_candidates = build_calendar_param_candidates(calendar_type_values, contexts)

    all_events: list[Event] = []
    successful_calls = 0

    for params in param_candidates:
        try:
            payload = request_json(CALENDAR_ENDPOINT, params)
        except Exception as exc:
            debug.setdefault("calendar_attempts", []).append(
                {"params": params, "ok": False, "error": str(exc)}
            )
            continue

        events = extract_event_candidates(payload, source_params={"endpoint": "calendar", **params})
        debug.setdefault("calendar_attempts", []).append(
            {
                "params": params,
                "ok": True,
                "event_candidates": len(events),
            }
        )
        if not events:
            continue

        successful_calls += 1
        all_events.extend(events)

    # Last fallback: direct request with tag-only if the discovered types produced nothing.
    if not all_events:
        for params in ({"tag": TAG}, {"comp_tag": TAG}, {}):
            try:
                payload = request_json(CALENDAR_ENDPOINT, params)
            except Exception as exc:
                debug.setdefault("calendar_direct_fallback", []).append(
                    {"params": params, "ok": False, "error": str(exc)}
                )
                continue
            events = extract_event_candidates(payload, source_params={"endpoint": "calendar", **params})
            debug.setdefault("calendar_direct_fallback", []).append(
                {"params": params, "ok": True, "event_candidates": len(events)}
            )
            all_events.extend(events)

    debug["calendar_types_params_used"] = types_params
    debug["calendar_type_values_found"] = calendar_type_values[:50]
    debug["successful_calendar_calls"] = successful_calls
    return dedupe_events(all_events)


def dedupe_events(events: list[Event]) -> list[Event]:
    unique: dict[tuple[str, str], Event] = {}
    for event in events:
        key = (event.uid, event.start.isoformat())
        if key not in unique:
            unique[key] = event
    return sorted(unique.values(), key=lambda item: (item.start, item.summary))


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
    updated = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M MSK")
    future_events = [event for event in events if event.start >= datetime.now(tz=UTC) - timedelta(days=1)]
    upcoming_rows = []
    for event in future_events[:20]:
        start_local = event.start.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")
        upcoming_rows.append(
            f"<tr><td>{html.escape(start_local)}</td><td>{html.escape(event.summary)}</td><td>{html.escape(event.location or '')}</td></tr>"
        )

    rows_html = "\n".join(upcoming_rows) if upcoming_rows else "<tr><td colspan='3'>Нет ближайших матчей</td></tr>"

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Календарь Единой Лиги ВТБ</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px auto; max-width: 1000px; padding: 0 18px; line-height: 1.5; }}
    h1 {{ margin-bottom: 8px; }}
    .card {{ border: 1px solid #ddd; border-radius: 14px; padding: 18px; margin: 18px 0; }}
    a.button {{ display: inline-block; padding: 12px 16px; border-radius: 10px; text-decoration: none; border: 1px solid #222; margin-right: 10px; margin-bottom: 10px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ border-bottom: 1px solid #eee; text-align: left; padding: 10px 8px; vertical-align: top; }}
    code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 6px; }}
    .muted {{ color: #666; }}
  </style>
</head>
<body>
  <h1>Календарь Единой Лиги ВТБ</h1>
  <p class="muted">Обновлено: {html.escape(updated)}. Событий в файле: {len(events)}.</p>

  <div class="card">
    <p><a class="button" href="/{ICS_FILENAME}">Открыть .ics файл</a></p>
    <p>Для Apple Calendar: <strong>Файл → Новая подписка на календарь</strong> и вставить прямую ссылку на <code>{ICS_FILENAME}</code>.</p>
    <p>Для Google Calendar: <strong>Add calendar → From URL</strong> и вставить прямую ссылку на этот же файл.</p>
  </div>

  <div class="card">
    <h2>Ближайшие матчи</h2>
    <table>
      <thead>
        <tr><th>Дата / время (МСК)</th><th>Матч</th><th>Место</th></tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Техническая информация</h2>
    <p>Источник: API РФБ / раздел <code>AbcComp</code> для соревнования <code>{html.escape(TAG)}</code>.</p>
    <p>Диагностика последнего запуска: <a href="/debug.json">debug.json</a></p>
  </div>
</body>
</html>
"""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    debug: dict[str, Any] = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "base_url": BASE_URL,
        "tag": TAG,
    }

    events = fetch_all_calendars(debug)
    if not events:
        debug["fatal"] = "No events were extracted from the API responses."
        (OUTPUT_DIR / "debug.json").write_text(
            json.dumps(debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise SystemExit("No events extracted. Check site/debug.json in the Pages artifact.")

    write_ics(events, OUTPUT_DIR / ICS_FILENAME)
    (OUTPUT_DIR / "index.html").write_text(render_index(events, debug), encoding="utf-8")
    (OUTPUT_DIR / "debug.json").write_text(
        json.dumps(
            {
                **debug,
                "events_count": len(events),
                "first_events": [
                    {
                        **asdict(event),
                        "start": event.start.isoformat(),
                        "end": event.end.isoformat(),
                    }
                    for event in events[:10]
                ],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(f"Generated {len(events)} events into {OUTPUT_DIR / ICS_FILENAME}")


if __name__ == "__main__":
    main()
