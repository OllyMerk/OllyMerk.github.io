from __future__ import annotations

import html
import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

INFOBASKET_BASE_URL = os.getenv("INFOBASKET_BASE_URL", "https://org.infobasket.su").rstrip("/")
RUSSIABASKET_BASE_URL = os.getenv("RUSSIABASKET_BASE_URL", "https://pro.russiabasket.org").rstrip("/")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://ollymerk.github.io").rstrip("/")
LANG = os.getenv("INFOBASKET_LANG", "ru")

GITHUB_REPO_WEB_URL = os.getenv(
    "GITHUB_REPO_WEB_URL",
    "https://github.com/OllyMerk/OllyMerk.github.io",
).rstrip("/")
GITHUB_WORKFLOW_FILE = os.getenv("GITHUB_WORKFLOW_FILE", "update-calendars.yml")

INFOBASKET_CALENDAR_URL = f"{INFOBASKET_BASE_URL}/Comp/GetCalendar/"
INFOBASKET_PERIODS_URL_TEMPLATE = f"{INFOBASKET_BASE_URL}/Comp/GetCalendarPeriods/{{comp_id}}"
RUSSIABASKET_CALENDAR_URL = f"{RUSSIABASKET_BASE_URL}/api/abc/comps/calendar"

ROOT_DIR = Path(".")
ASSETS_DIR = ROOT_DIR / "assets"
LOGOS_DIR = ASSETS_DIR / "logos"

OUTPUT_DIR = Path("site")
OUTPUT_ASSETS_DIR = OUTPUT_DIR / "assets"
OUTPUT_LOGOS_DIR = OUTPUT_ASSETS_DIR / "logos"

UTC = timezone.utc
MSK = timezone(timedelta(hours=3), name="MSK")
REQUEST_TIMEOUT = 30
USER_AGENT = "Basketball-Calendars-Bot/4.0"
RUSSIABASKET_LANG = os.getenv("RUSSIABASKET_LANG", "ru")
RUSSIABASKET_PAGE_SIZE = int(os.getenv("RUSSIABASKET_PAGE_SIZE", "100"))

SOURCE_INFOBASKET_COMP = "infobasket_comp"
SOURCE_RUSSIABASKET_TAG_SEASON = "russiabasket_tag_season"
SOURCE_RUSSIABASKET_TAG_SEASONS = "russiabasket_tag_seasons"


@dataclass(slots=True)
class Competition:
    slug: str
    title: str
    short_title: str
    description: str
    ics_filename: str
    color_hex: str
    logo_filename: str | None
    source_type: str
    comp_id: str | None = None
    tag: str | None = None
    season: str | None = None
    seasons: tuple[str, ...] = ()
    calendar_type: int | None = None
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
    team_a_id: str | None = None
    team_b_id: str | None = None


RUSSIABASKET_DEFAULT_SEASON = os.getenv("RUSSIABASKET_DEFAULT_SEASON", "2026")
VTB_SUPERCUP_SEASON = os.getenv("VTB_SUPERCUP_SEASON", RUSSIABASKET_DEFAULT_SEASON)
VTB_SEASONS = tuple(
    season.strip()
    for season in os.getenv("VTB_SEASONS", "2026,2027").split(",")
    if season.strip()
)

COMPETITIONS: list[Competition] = [
    Competition(
        slug="vtb",
        title="Единая Лига ВТБ",
        short_title="VTB",
        description="Календарь матчей Единой Лиги ВТБ с автообновлением для Apple Calendar и Google Calendar.",
        ics_filename="vtb-united-league.ics",
        color_hex="#010070",
        logo_filename="vtb.png",
        source_type=SOURCE_RUSSIABASKET_TAG_SEASONS,
        tag="vtb",
        seasons=VTB_SEASONS,
        calendar_type=-1,
    ),
    Competition(
        slug="vtb-youth",
        title="Единая Молодежная Лига ВТБ",
        short_title="VTB Youth",
        description="Календарь матчей Единой Молодежной Лиги ВТБ с автообновлением для Apple Calendar и Google Calendar.",
        ics_filename="vtb-youth-league.ics",
        color_hex="#1D70B8",
        logo_filename="vtb-youth.png",
        source_type=SOURCE_INFOBASKET_COMP,
        comp_id="50719",
    ),
    Competition(
        slug="winline-basket-cup",
        title="WINLINE Basket Cup",
        short_title="WCB",
        description="Подписной календарь матчей WINLINE Basket Cup с ежедневным обновлением.",
        ics_filename="winline-basket-cup.ics",
        color_hex="#ff6a13",
        logo_filename="winline-basket-cup.png",
        source_type=SOURCE_INFOBASKET_COMP,
        comp_id="52553",
    ),
    Competition(
        slug="vtb-supercup",
        title="Суперкубок Единой Лиги ВТБ",
        short_title="Supercup",
        description="Подписной календарь матчей Суперкубка Единой Лиги ВТБ по официальному API РФБ.",
        ics_filename="vtb-supercup.ics",
        color_hex="#5A2CA0",
        logo_filename=None,
        source_type=SOURCE_RUSSIABASKET_TAG_SEASON,
        tag="vtb-supercup",
        season=VTB_SUPERCUP_SEASON,
        team_mode=True,
    ),
]

TEAM_SLUG_OVERRIDES: dict[str, dict[str, str]] = {
    "vtb": {
        "БЕТСИТИ ПАРМА": "parma",
        "Пари Нижний Новгород": "pari-nizhny-novgorod",
        "УНИКС": "unics",
        "ЦСКА": "cska",
    },
    "vtb-youth": {
        "МБА-МАИ-Юниор": "mba-mai-junior",
        "Нижний Новгород-Мещерский": "nizhny-novgorod-meshchersky",
        "УНИКС-2": "unics-2",
        "ЦСКА-Юниор": "cska-junior",
        "ЦСП-Химки-2": "csp-khimki-2",
    },
    "winline-basket-cup": {
        "Игокеа м:тел": "igokea-mtel",
        "УНИКС": "unics",
    },
    "vtb-supercup": {
        "УНИКС": "unics",
        "ЦСКА": "cska",
    },
}

# Slugs already published for the 2025/26 VTB teams. For the multi-season VTB
# calendar the stable teamId is the primary identity, so a rename in a later
# season (for example, МБА-МАИ -> МБА) does not create a second team page or
# change an existing subscription URL.
TEAM_ID_SLUG_OVERRIDES: dict[str, dict[str, str]] = {
    "vtb": {
        "15": "cska",
        "468": "pari-nizhny-novgorod",
        "682": "avtodor",
        "688": "enisey",
        "697": "unics",
        "1390": "uralmash",
        "2650": "lokomotiv-kuban",
        "2747": "mba-mai",
        "2792": "samara",
        "2994": "zenit",
        "3059": "parma",
    }
}

TEAM_EXCLUDE_FROM_TEAM_PAGES: dict[str, set[str]] = {
    "winline-basket-cup": {
        "1A",
        "1B",
        "2A",
        "2B",
        "Победитель 1/2 финала (1)",
        "Победитель 1/2 финала (2)",
        "Проигравший в 1/2 финала (1)",
        "Проигравший в 1/2 финала (2)",
    }
}

TRANSLIT_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


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


def github_workflow_url() -> str:
    return f"{GITHUB_REPO_WEB_URL}/actions/workflows/{GITHUB_WORKFLOW_FILE}"


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


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MSK)
    return dt


def transliterate(text: str) -> str:
    return "".join(TRANSLIT_MAP.get(ch, ch) for ch in text.lower())


def slugify_team_name(name: str) -> str:
    text = transliterate(name)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "team"


def get_excluded_team_names(comp: Competition) -> set[str]:
    return TEAM_EXCLUDE_FROM_TEAM_PAGES.get(comp.slug, set())


def team_identity(comp: Competition, name: str, team_id: str | None) -> str:
    if comp.slug == "vtb" and team_id:
        return f"teamId:{team_id}"
    return name


def event_team_sides(comp: Competition, event: Event) -> list[tuple[str, str, str | None, str]]:
    excluded_names = get_excluded_team_names(comp)
    sides: list[tuple[str, str, str | None, str]] = []
    if event.team_a and event.team_a not in excluded_names:
        sides.append(
            (
                team_identity(comp, event.team_a, event.team_a_id),
                event.team_a,
                event.team_a_id,
                "home",
            )
        )
    if event.team_b and event.team_b not in excluded_names:
        sides.append(
            (
                team_identity(comp, event.team_b, event.team_b_id),
                event.team_b,
                event.team_b_id,
                "away",
            )
        )
    return sides


def build_infobasket_calendar_params(comp: Competition) -> dict[str, Any]:
    if not comp.comp_id:
        raise ValueError(f"comp_id is required for {comp.slug}")
    return {"comps": comp.comp_id, "format": "json"}


def build_infobasket_periods_params() -> dict[str, Any]:
    return {"lang": LANG, "period": "m"}


def build_russiabasket_calendar_params(comp: Competition) -> dict[str, Any]:
    if not comp.tag or not comp.season:
        raise ValueError(f"tag and season are required for {comp.slug}")
    params: dict[str, Any] = {"tag": comp.tag, "season": comp.season}
    if comp.calendar_type is not None:
        params["calendarType"] = comp.calendar_type
    return params


def build_russiabasket_paginated_calendar_params(
    comp: Competition,
    season: str,
    skip_count: int,
    max_result_count: int,
) -> dict[str, Any]:
    if not comp.tag:
        raise ValueError(f"tag is required for {comp.slug}")
    if skip_count < 0:
        raise ValueError("skip_count must not be negative")
    if max_result_count <= 0:
        raise ValueError("max_result_count must be positive")

    params: dict[str, Any] = {
        "tag": comp.tag,
        "season": season,
        "lang": RUSSIABASKET_LANG,
        "skipCount": skip_count,
        "maxResultCount": max_result_count,
    }
    if comp.calendar_type is not None:
        params["calendarType"] = comp.calendar_type
    return params


def infobasket_periods_url(comp: Competition) -> str:
    if not comp.comp_id:
        raise ValueError(f"comp_id is required for {comp.slug}")
    return INFOBASKET_PERIODS_URL_TEMPLATE.format(comp_id=comp.comp_id)


def comp_site_url(comp: Competition) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/"


def comp_ics_url(comp: Competition) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/{comp.ics_filename}"


def comp_teams_url(comp: Competition) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/teams/"


def team_page_url(comp: Competition, team_slug: str) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/teams/{team_slug}/"


def team_ics_url(comp: Competition, team_slug: str) -> str:
    return f"{SITE_BASE_URL}/{comp.slug}/teams/{team_slug}/{team_slug}.ics"


def logo_site_path(comp: Competition) -> str | None:
    if not comp.logo_filename:
        return None
    return f"/assets/logos/{comp.logo_filename}"


def normalize_tv_line(tv: str | None) -> str | None:
    if not tv:
        return None
    return tv if tv.startswith("ТВ") else f"ТВ: {tv}"


def dedupe_rows(rows: list[dict[str, Any]], key_fields: list[str] | None = None) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    key_fields = key_fields or ["GameID"]

    for row in rows:
        signature = None
        for key in key_fields:
            value = norm(row.get(key))
            if value:
                signature = f"{key}:{value}"
                break
        if not signature:
            signature = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(row)
    return unique


def russiabasket_game_id(item: dict[str, Any]) -> str | None:
    game = item.get("game") if isinstance(item.get("game"), dict) else {}
    return norm(game.get("id"))


def dedupe_russiabasket_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        game_id = russiabasket_game_id(row)
        signature = f"game.id:{game_id}" if game_id else json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(row)
    return unique


def format_russiabasket_season(value: Any) -> str | None:
    season = norm(value)
    if not season:
        return None
    try:
        end_year = int(season)
    except ValueError:
        return season
    return f"{end_year - 1}/{end_year % 100:02d}"


def build_infobasket_event(row: dict[str, Any], comp: Competition) -> Event | None:
    game_id = norm(row.get("GameID"))
    if not game_id:
        return None

    team_a = norm(row.get("CompTeamNameAru")) or norm(row.get("ShortTeamNameAru")) or "Команда А"
    team_b = norm(row.get("CompTeamNameBru")) or norm(row.get("ShortTeamNameBru")) or "Команда Б"
    team_a_id = norm(row.get("TeamAid"))
    team_b_id = norm(row.get("TeamBid"))
    summary = f"{team_a} — {team_b}"

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

    score_a = None
    score_b = None
    try:
        if row.get("ScoreA") is not None:
            score_a = int(row.get("ScoreA"))
    except (TypeError, ValueError):
        score_a = None
    try:
        if row.get("ScoreB") is not None:
            score_b = int(row.get("ScoreB"))
    except (TypeError, ValueError):
        score_b = None

    show_score = score_a is not None and score_b is not None and not (score_a == 0 and score_b == 0)

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
        team_a_id=team_a_id,
        team_b_id=team_b_id,
    )


def build_russiabasket_event(item: dict[str, Any], comp: Competition) -> Event | None:
    game = item.get("game") if isinstance(item.get("game"), dict) else {}
    league = item.get("league") if isinstance(item.get("league"), dict) else {}
    comp_info = item.get("comp") if isinstance(item.get("comp"), dict) else {}
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    arena = item.get("arena") if isinstance(item.get("arena"), dict) else {}
    region = item.get("region") if isinstance(item.get("region"), dict) else {}
    team1 = item.get("team1") if isinstance(item.get("team1"), dict) else {}
    team2 = item.get("team2") if isinstance(item.get("team2"), dict) else {}

    game_id = norm(game.get("id"))
    if not game_id:
        return None

    team_a = norm(team1.get("name")) or norm(team1.get("shortName")) or "Команда А"
    team_b = norm(team2.get("name")) or norm(team2.get("shortName")) or "Команда Б"
    team_a_id = norm(team1.get("teamId"))
    team_b_id = norm(team2.get("teamId"))
    summary = f"{team_a} — {team_b}"

    has_time = bool(game.get("hasTime", True))
    local_date = parse_date_ddmmyyyy(norm(game.get("localDate")))
    dt_local: datetime | None = None

    if not has_time:
        # A midnight placeholder carries an arena offset and can point to the
        # previous day elsewhere. Until tip-off time is published, localDate
        # is the authoritative calendar date.
        if local_date is None:
            return None
        all_day = True
        start_value: datetime | date = local_date
        end_value: datetime | date = local_date + timedelta(days=1)
    else:
        dt_local = (
            parse_iso_datetime(norm(game.get("scheduledTime")))
            or parse_iso_datetime(norm(game.get("defaultZoneDateTime")))
            or parse_iso_datetime(norm(game.get("startTime")))
        )
        if dt_local is not None:
            all_day = False
            start_value = dt_local.astimezone(UTC)
            end_value = start_value + timedelta(hours=2)
        else:
            if local_date is None:
                return None
            all_day = True
            start_value = local_date
            end_value = local_date + timedelta(days=1)

    arena_name = norm(arena.get("name")) or norm(arena.get("shortName"))
    region_name = norm(region.get("name"))
    location = " / ".join(part for part in [arena_name, region_name] if part) or None

    description_lines: list[str] = []
    league_name = norm(league.get("name"))
    season_name = format_russiabasket_season(league.get("season"))
    comp_name = norm(comp_info.get("name"))
    game_number = norm(game.get("number"))
    status_name = norm(status.get("displayName"))
    attendance = game.get("attendance")
    tv = normalize_tv_line(norm(game.get("tv")))
    local_date_str = norm(game.get("localDate"))
    local_time_str = norm(game.get("localTime"))
    score = norm(game.get("score"))
    show_score = bool(game.get("showScore")) and score and score != "0:0"

    if league_name:
        description_lines.append(f"Лига: {league_name}")
    if season_name:
        description_lines.append(f"Сезон: {season_name}")
    if comp_name:
        description_lines.append(f"Этап: {comp_name}")
    if game_number:
        description_lines.append(f"Номер матча: {game_number}")
    if status_name:
        description_lines.append(f"Статус: {status_name}")
    if local_date_str or local_time_str:
        description_lines.append(
            f"Локальное время: {' '.join(part for part in [local_date_str, local_time_str] if part)}"
        )
    if dt_local is not None and has_time:
        description_lines.append(f"МСК: {dt_local.astimezone(MSK).strftime('%a, %d %b %Y %H:%M мск')}")
    if show_score:
        description_lines.append(f"Счет: {score}")
    full_score = norm(game.get("fullScore"))
    if full_score and show_score:
        description_lines.append(f"По четвертям: {full_score}")
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
        team_a_id=team_a_id,
        team_b_id=team_b_id,
    )


def fetch_russiabasket_season_rows(
    comp: Competition,
    season: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    seen_page_signatures: set[str] = set()
    skip_count = 0
    total_count: int | None = None

    while True:
        params = build_russiabasket_paginated_calendar_params(
            comp,
            season,
            skip_count,
            RUSSIABASKET_PAGE_SIZE,
        )
        payload = request_json(RUSSIABASKET_CALENDAR_URL, params)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Expected dict from RussiaBasket calendar for {comp.slug} season {season}, "
                f"got {type(payload).__name__}"
            )

        items = payload.get("items")
        if not isinstance(items, list):
            raise RuntimeError(
                f"No items list in RussiaBasket response for {comp.slug} season {season}"
            )
        page_rows = [row for row in items if isinstance(row, dict)]

        total_count_raw = payload.get("totalCount")
        try:
            total_count = int(total_count_raw) if total_count_raw is not None else None
        except (TypeError, ValueError):
            total_count = None

        page_signature = json.dumps(
            [
                russiabasket_game_id(row)
                or json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                for row in page_rows
            ],
            ensure_ascii=False,
        )
        if page_rows and page_signature in seen_page_signatures:
            raise RuntimeError(
                f"RussiaBasket repeated a page for {comp.slug} season {season} "
                f"at skipCount={skip_count}"
            )
        seen_page_signatures.add(page_signature)

        unique_before = len(dedupe_russiabasket_rows(rows))
        rows.extend(page_rows)
        unique_after = len(dedupe_russiabasket_rows(rows))
        pages.append(
            {
                "skipCount": skip_count,
                "maxResultCount": RUSSIABASKET_PAGE_SIZE,
                "items_count": len(items),
                "dict_items_count": len(page_rows),
                "unique_games_added": unique_after - unique_before,
                "status": payload.get("status"),
                "totalCount": total_count_raw,
            }
        )

        if not items:
            break
        skip_count += len(items)
        if total_count is not None and skip_count >= total_count:
            break
        if total_count is None and len(items) < RUSSIABASKET_PAGE_SIZE:
            break

    unique_rows = dedupe_russiabasket_rows(rows)
    season_debug = {
        "season": season,
        "pages_count": len(pages),
        "pages": pages,
        "reported_total_count": total_count,
        "fetched_rows_count": len(rows),
        "unique_game_ids_count": len(unique_rows),
    }
    return unique_rows, season_debug


def fetch_source_rows(comp: Competition, debug: dict[str, Any]) -> list[dict[str, Any]]:
    if comp.source_type == SOURCE_INFOBASKET_COMP:
        params = build_infobasket_calendar_params(comp)
        payload = request_json(INFOBASKET_CALENDAR_URL, params)
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Expected list from InfoBasket GetCalendar for {comp.slug}, got {type(payload).__name__}"
            )
        rows = [row for row in payload if isinstance(row, dict)]
        rows = dedupe_rows(rows, key_fields=["GameID"])
        debug["source_endpoint"] = INFOBASKET_CALENDAR_URL
        debug["source_params"] = params
        debug["source_rows_count"] = len(rows)
        debug["source_first_keys"] = list(rows[0].keys()) if rows else []

        periods_payload = request_json(infobasket_periods_url(comp), build_infobasket_periods_params())
        periods = periods_payload if isinstance(periods_payload, list) else []
        debug["periods_endpoint"] = infobasket_periods_url(comp)
        debug["periods_params"] = build_infobasket_periods_params()
        debug["periods_count"] = len(periods)
        return rows

    if comp.source_type == SOURCE_RUSSIABASKET_TAG_SEASONS:
        if not comp.seasons:
            raise ValueError(f"seasons are required for {comp.slug}")

        rows: list[dict[str, Any]] = []
        seasons_debug: list[dict[str, Any]] = []
        for season in comp.seasons:
            season_rows, season_debug = fetch_russiabasket_season_rows(comp, season)
            rows.extend(season_rows)
            seasons_debug.append(season_debug)

        rows = dedupe_russiabasket_rows(rows)
        debug["source_endpoint"] = RUSSIABASKET_CALENDAR_URL
        debug["source_seasons"] = seasons_debug
        debug["source_rows_count"] = len(rows)
        debug["source_first_keys"] = list(rows[0].keys()) if rows else []
        return rows

    if comp.source_type == SOURCE_RUSSIABASKET_TAG_SEASON:
        params = build_russiabasket_calendar_params(comp)
        payload = request_json(RUSSIABASKET_CALENDAR_URL, params)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Expected dict from RussiaBasket calendar for {comp.slug}, got {type(payload).__name__}"
            )
        items = payload.get("items")
        if not isinstance(items, list):
            raise RuntimeError(f"No items list in RussiaBasket response for {comp.slug}")
        rows = [row for row in items if isinstance(row, dict)]
        rows = dedupe_russiabasket_rows(rows)
        debug["source_endpoint"] = RUSSIABASKET_CALENDAR_URL
        debug["source_params"] = params
        debug["source_status"] = payload.get("status")
        debug["source_total_count"] = payload.get("totalCount")
        debug["source_rows_count"] = len(rows)
        debug["source_first_keys"] = list(rows[0].keys()) if rows else []
        return rows

    raise ValueError(f"Unsupported source_type: {comp.source_type}")


def build_events(rows: list[dict[str, Any]], comp: Competition, debug: dict[str, Any]) -> list[Event]:
    events: list[Event] = []
    skipped: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        if comp.source_type == SOURCE_INFOBASKET_COMP:
            event = build_infobasket_event(row, comp)
        elif comp.source_type in {
            SOURCE_RUSSIABASKET_TAG_SEASON,
            SOURCE_RUSSIABASKET_TAG_SEASONS,
        }:
            event = build_russiabasket_event(row, comp)
        else:
            raise ValueError(f"Unsupported source_type: {comp.source_type}")

        if event is None:
            skipped.append({"index": idx, "preview": json.dumps(row, ensure_ascii=False, default=str)[:400]})
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
    return value.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


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
        lines.extend(["BEGIN:VEVENT", f"UID:{ics_escape(event.uid)}", f"DTSTAMP:{dtstamp}"])
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


def format_event_start_for_site(event: Event) -> str:
    if event.all_day:
        assert isinstance(event.start, date)
        return event.start.strftime("%d.%m.%Y")
    assert isinstance(event.start, datetime)
    return event.start.astimezone(MSK).strftime("%d.%m.%Y %H:%M МСК")


def format_next_game_for_site(utc_iso: str | None) -> str:
    if not utc_iso:
        return "—"
    return datetime.fromisoformat(utc_iso).astimezone(MSK).strftime("%d.%m.%Y %H:%M МСК")


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
        f"</div>"
    )


def render_card_css() -> str:
    return """
    body { font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f5f7fb; color: #101828; }
    .wrap { max-width: 1120px; margin: 0 auto; padding: 32px 20px 56px; }
    .hero { border-radius: 24px; padding: 28px; margin-bottom: 24px; background: linear-gradient(135deg, #ffffff 0%, #eef2ff 100%); border: 1px solid rgba(16, 24, 40, 0.08); box-shadow: 0 10px 30px rgba(16, 24, 40, 0.06); }
    .hero h1 { margin: 0 0 8px; font-size: 42px; line-height: 1.05; }
    .hero p { margin: 0; color: #475467; font-size: 18px; }
    .hero-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
    .card { border-radius: 24px; padding: 22px; margin: 18px 0; background: #ffffff; border: 1px solid rgba(16, 24, 40, 0.08); box-shadow: 0 10px 26px rgba(16, 24, 40, 0.05); }
    .muted { color: #667085; }
    .button, button.copy-button { display: inline-block; padding: 12px 16px; border-radius: 12px; text-decoration: none; border: 1px solid rgba(16, 24, 40, 0.12); background: #fff; color: inherit; cursor: pointer; font: inherit; font-weight: 600; transition: 0.18s ease; }
    .button:hover, button.copy-button:hover { transform: translateY(-1px); background: #f9fafb; }
    .button.primary { color: #fff; border: none; }
    .nav-buttons { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    th, td { border-bottom: 1px solid #eaecf0; text-align: left; padding: 12px 8px; vertical-align: top; }
    code { background: #f2f4f7; padding: 4px 8px; border-radius: 8px; word-break: break-all; font-size: 14px; }
    .inline-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 8px; }
    .copy-status { color: #667085; font-size: 14px; }
    .color-row { display: flex; align-items: center; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
    .color-swatch { width: 22px; height: 22px; border-radius: 6px; border: 1px solid rgba(0,0,0,0.15); display: inline-block; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }
    .comp-card { border-radius: 24px; padding: 22px; color: #fff; position: relative; overflow: hidden; box-shadow: 0 14px 30px rgba(16, 24, 40, 0.14); }
    .comp-card .overlay { position: absolute; inset: 0; background: linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.00) 52%); pointer-events: none; }
    .comp-card-top { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; position: relative; z-index: 1; }
    .comp-card h2 { margin: 0; font-size: 28px; line-height: 1.1; }
    .comp-card p { margin: 8px 0 0; opacity: 0.95; position: relative; z-index: 1; }
    .comp-card-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; position: relative; z-index: 1; }
    .comp-card .button { background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.18); color: #fff; backdrop-filter: blur(6px); }
    .comp-card .button:hover { background: rgba(255,255,255,0.22); }
    .pill { display: inline-block; padding: 6px 10px; border-radius: 999px; background: rgba(255,255,255,0.14); font-size: 13px; font-weight: 600; margin-right: 8px; margin-top: 8px; }
    .section-title { margin: 0 0 10px; font-size: 28px; }
    .subtle-link { color: inherit; text-decoration: none; border-bottom: 1px solid rgba(16, 24, 40, 0.12); }
    .teams-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-top: 18px; }
    .team-card { border: 1px solid rgba(16, 24, 40, 0.08); border-radius: 18px; padding: 16px; background: #fff; }
    .team-card h3 { margin: 0 0 8px; font-size: 20px; line-height: 1.2; }
    .team-meta { font-size: 14px; color: #667085; margin-top: 6px; }
    .team-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    .search-bar { width: 100%; max-width: 420px; padding: 12px 14px; border-radius: 12px; border: 1px solid rgba(16, 24, 40, 0.12); font: inherit; font-size: 16px; box-sizing: border-box; background: #fff; }
    .search-meta { margin-top: 10px; color: #667085; font-size: 14px; }
    .empty-search { display: none; margin-top: 18px; padding: 18px; border-radius: 16px; background: #fff; border: 1px dashed rgba(16, 24, 40, 0.16); color: #667085; }
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


def render_team_search_script() -> str:
    return """
    <script>
      function initTeamSearch() {
        const input = document.getElementById("team-search");
        const cards = Array.from(document.querySelectorAll(".team-card[data-team-name]"));
        const countEl = document.getElementById("teams-visible-count");
        const emptyEl = document.getElementById("teams-empty-state");
        const total = cards.length;

        function applyFilter() {
          const query = (input.value || "").trim().toLowerCase();
          let visible = 0;
          cards.forEach((card) => {
            const teamName = card.dataset.teamName || "";
            const teamSlug = card.dataset.teamSlug || "";
            const haystack = `${teamName} ${teamSlug}`.toLowerCase();
            const show = query === "" || haystack.includes(query);
            card.style.display = show ? "" : "none";
            if (show) visible += 1;
          });
          if (countEl) countEl.textContent = `${visible} из ${total}`;
          if (emptyEl) emptyEl.style.display = visible === 0 ? "block" : "none";
        }

        if (input) {
          input.addEventListener("input", applyFilter);
          applyFilter();
        }
      }
      document.addEventListener("DOMContentLoaded", initTeamSearch);
    </script>
    """


def render_comp_index(comp: Competition, events: list[Event], team_stats: list[dict[str, Any]], debug: dict[str, Any]) -> str:
    updated = datetime.now().astimezone().strftime("%d.%m.%Y %H:%М")
    upcoming = [event for event in events if event_is_upcoming(event, datetime.now(tz=UTC))]
    ics_url = comp_ics_url(comp)
    color_hex = comp.color_hex
    workflow_url = github_workflow_url()
    logo_html = render_logo(comp, size=60)
    source_note = ""
    if comp.source_type == SOURCE_RUSSIABASKET_TAG_SEASON and comp.tag and comp.season:
        source_note = f"<p class='muted'>Источник: tag={html.escape(comp.tag)}, season={html.escape(comp.season)}</p>"
    elif comp.source_type == SOURCE_RUSSIABASKET_TAG_SEASONS and comp.tag and comp.seasons:
        seasons_text = ", ".join(comp.seasons)
        source_note = (
            f"<p class='muted'>Источник: tag={html.escape(comp.tag)}, "
            f"seasons={html.escape(seasons_text)}</p>"
        )

    rows = []
    for event in upcoming[:30]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(format_event_start_for_site(event))}</td>"
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
    .hero.comp-hero {{ background: linear-gradient(135deg, {html.escape(color_hex)} 0%, #ffffff 240%); color: #fff; position: relative; overflow: hidden; }}
    .hero.comp-hero p, .hero.comp-hero .muted {{ color: rgba(255,255,255,0.9); }}
    .hero-row {{ display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
    .hero-row .title-block {{ flex: 1; min-width: 240px; }}
    .hero-row h1 {{ margin-bottom: 10px; }}
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
          <p class="muted">Обновлено: {html.escape(updated)}. Событий: {len(events)}. Команд: {len(team_stats)}.</p>
          {source_note}
        </div>
      </div>
    </div>

    <div class="card">
      <h2 class="section-title">Обновление календаря</h2>
      <p>Календари обновляются автоматически раз в час через GitHub Actions.</p>
      <p><a class="button" href="{html.escape(workflow_url)}" target="_blank" rel="noopener noreferrer">Открыть GitHub Actions</a></p>
      <p class="muted">Если подстраница внезапно дала 404, в первую очередь проверь, что workflow завершился успешно и в артефакте Pages есть папка <code>{html.escape(comp.slug)}</code>.</p>
    </div>

    <div class="card">
      <p><a class="button primary" style="background:{html.escape(color_hex)};" href="./{html.escape(comp.ics_filename)}">Открыть .ics файл</a></p>
      <p><strong>Прямая ссылка для подписки:</strong></p>
      <div class="inline-tools">
        <code>{html.escape(ics_url)}</code>
        <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status')">Скопировать</button>
        <span class="copy-status" id="copy-status"></span>
      </div>
    </div>

    <div class="card">
      <h2 class="section-title">Рекомендуемый цвет календаря</h2>
      <div class="color-row">
        <span class="color-swatch" style="background:{html.escape(color_hex)};"></span>
        <code>{html.escape(color_hex)}</code>
      </div>
      <p class="muted">Автоматически через .ics цвет не назначается — это ограничение клиентов Apple / Google Calendar.</p>
    </div>

    <div class="card">
      <h2 class="section-title">Как подписаться</h2>
      <p><strong>Apple Calendar</strong></p>
      <div class="inline-tools">
        <code>{html.escape(ics_url)}</code>
        <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status-apple')">Скопировать</button>
        <span class="copy-status" id="copy-status-apple"></span>
      </div>
      <p><strong>Google Calendar</strong></p>
      <div class="inline-tools">
        <code>{html.escape(ics_url)}</code>
        <button class="copy-button" onclick="copyText('{html.escape(ics_url)}', 'copy-status-google')">Скопировать</button>
        <span class="copy-status" id="copy-status-google"></span>
      </div>
    </div>

    <div class="card">
      <h2 class="section-title">Календари по командам</h2>
      <p>Для каждой команды есть отдельная страница и отдельный .ics-файл.</p>
      <p><a class="button" href="./teams/">Открыть раздел команд</a></p>
    </div>

    <div class="card">
      <h2 class="section-title">Ближайшие матчи</h2>
      <table>
        <thead><tr><th>Дата / время</th><th>Матч</th><th>Место</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>

    <div class="card">
      <h2 class="section-title">Диагностика</h2>
      <p>Workflow: <code>{html.escape(workflow_url)}</code></p>
      <p><a class="subtle-link" href="./debug.json">Открыть debug.json</a></p>
      <p><a class="subtle-link" href="./teams_debug.json">Открыть teams_debug.json</a></p>
    </div>
  </div>
  {render_copy_script()}
</body>
</html>"""


def render_teams_index(comp: Competition, team_stats: list[dict[str, Any]]) -> str:
    logo_html = render_logo(comp, size=56)
    cards = []
    for item in team_stats:
        cards.append(
            f"""
            <div class="team-card" data-team-name="{html.escape(item['name'].lower())}" data-team-slug="{html.escape(item['slug'].lower())}">
              <h3>{html.escape(item['name'])}</h3>
              <div class="team-meta">slug: <code>{html.escape(item['slug'])}</code></div>
              <div class="team-meta">Матчей: {item['games_count']}</div>
              <div class="team-meta">Домашних: {item['home_games_count']} · Гостевых: {item['away_games_count']}</div>
              <div class="team-meta">Будущих: {item['upcoming_games_count']}</div>
              <div class="team-meta">Ближайший матч: {html.escape(format_next_game_for_site(item.get('next_game_start_utc')))}</div>
              <div class="team-actions">
                <a class="button" href="/{html.escape(comp.slug)}/teams/{html.escape(item['slug'])}/">Страница команды</a>
                <a class="button" href="/{html.escape(comp.slug)}/teams/{html.escape(item['slug'])}/{html.escape(item['slug'])}.ics">Подписаться (.ics)</a>
              </div>
            </div>
            """
        )
    cards_html = "\n".join(cards) if cards else "<p>Команды не найдены.</p>"
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Команды — {html.escape(comp.title)}</title><style>{render_card_css()}</style></head>
<body><div class="wrap">
<p><a class="subtle-link" href="/{html.escape(comp.slug)}/">← Назад к календарю соревнования</a></p>
<div class="hero comp-hero" style="background: linear-gradient(135deg, {html.escape(comp.color_hex)} 0%, #ffffff 240%); color:#fff;">
  <div class="hero-row">{logo_html}<div><h1>Команды</h1><p style="color:rgba(255,255,255,0.9)">{html.escape(comp.title)}</p></div></div>
</div>
<div class="card"><p>Для каждой команды подготовлена отдельная страница и отдельный подписной календарь.</p><p><a class="subtle-link" href="../teams_debug.json">Открыть teams_debug.json</a></p></div>
<div class="card">
  <h2 class="section-title">Поиск по командам</h2>
  <input id="team-search" class="search-bar" type="text" placeholder="Начни вводить название команды..." autocomplete="off">
  <div class="search-meta">Найдено: <span id="teams-visible-count">{len(team_stats)} из {len(team_stats)}</span></div>
</div>
<div class="teams-grid" id="teams-grid">{cards_html}</div>
<div class="empty-search" id="teams-empty-state">По этому запросу команды не найдены.</div>
</div>{render_team_search_script()}</body></html>"""


def render_team_page(comp: Competition, team_info: dict[str, Any], team_events: list[Event]) -> str:
    color_hex = comp.color_hex
    logo_html = render_logo(comp, size=56)
    team_name = team_info["name"]
    team_slug = team_info["slug"]
    team_ics_filename = f"{team_slug}.ics"
    team_ics_public_url = team_info["ics_url"]
    updated = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")
    upcoming = [event for event in team_events if event_is_upcoming(event, datetime.now(tz=UTC))]
    rows = []
    for event in upcoming[:30]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(format_event_start_for_site(event))}</td>"
            f"<td>{html.escape(event.summary)}</td>"
            f"<td>{html.escape(event.location or '')}</td>"
            "</tr>"
        )
    rows_html = "\n".join(rows) if rows else "<tr><td colspan='3'>Нет ближайших матчей</td></tr>"
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(team_name)} — {html.escape(comp.title)}</title><style>{render_card_css()}</style></head>
<body><div class="wrap">
<div class="nav-buttons"><a class="button" href="/{html.escape(comp.slug)}/">Назад к турниру</a><a class="button" href="/{html.escape(comp.slug)}/teams/">Все команды</a></div>
<div class="hero team-hero" style="background: linear-gradient(135deg, {html.escape(color_hex)} 0%, #ffffff 240%); color:#fff;">
  <div class="hero-row">{logo_html}<div><h1>{html.escape(team_name)}</h1><p style="color:rgba(255,255,255,0.9)">{html.escape(comp.title)}</p><p class="muted">Обновлено: {html.escape(updated)}. Матчей в календаре: {len(team_events)}.</p></div></div>
</div>
<div class="card">
  <h2 class="section-title">Подписка на календарь команды</h2>
  <p><a class="button primary" style="background:{html.escape(color_hex)};" href="./{html.escape(team_ics_filename)}">Открыть .ics файл команды</a></p>
  <p><strong>Прямая ссылка на календарь команды:</strong></p>
  <div class="inline-tools"><code>{html.escape(team_ics_public_url)}</code><button class="copy-button" onclick="copyText('{html.escape(team_ics_public_url)}', 'copy-status')">Скопировать</button><span class="copy-status" id="copy-status"></span></div>
</div>
<div class="card"><h2 class="section-title">Ближайшие матчи команды</h2><table><thead><tr><th>Дата / время</th><th>Матч</th><th>Место</th></tr></thead><tbody>{rows_html}</tbody></table></div>
<div class="card"><h2 class="section-title">Диагностика</h2><p>slug: <code>{html.escape(team_slug)}</code></p><p><a class="subtle-link" href="./debug.json">Открыть debug.json</a></p></div>
</div>{render_copy_script()}</body></html>"""


def render_root_index(results: list[dict[str, Any]]) -> str:
    updated = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")
    workflow_url = github_workflow_url()
    cards = []
    for result in results:
        comp: Competition = result["comp"]
        logo_html = render_logo(comp, size=56)
        extra = ""
        if comp.source_type == SOURCE_RUSSIABASKET_TAG_SEASON and comp.season:
            extra = f"<p>Сезон: {html.escape(comp.season)}</p>"
        elif comp.source_type == SOURCE_RUSSIABASKET_TAG_SEASONS and comp.seasons:
            extra = f"<p>Сезоны: {html.escape(', '.join(comp.seasons))}</p>"
        cards.append(
            f"""
            <div class="comp-card" style="background: linear-gradient(135deg, {html.escape(comp.color_hex)} 0%, rgba(0,0,0,0.78) 100%);">
              <div class="overlay"></div>
              <div class="comp-card-top">
                {logo_html}
                <div>
                  <h2>{html.escape(comp.title)}</h2>
                  <p>{html.escape(comp.description)}</p>
                  {extra}
                </div>
              </div>
              <div style="position:relative;z-index:1;">
                <span class="pill">Событий: {result['events_count']}</span>
                <span class="pill">Ближайших / будущих: {result['upcoming_count']}</span>
              </div>
              <div class="comp-card-actions">
                <a class="button" href="/{html.escape(comp.slug)}/">Открыть сайт календаря</a>
                <a class="button" href="/{html.escape(comp.slug)}/{html.escape(comp.ics_filename)}">Подписаться (.ics)</a>
              </div>
            </div>
            """
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Баскетбольные календари</title><style>{render_card_css()}</style></head>
<body><div class="wrap">
<div class="hero">
  <h1>Баскетбольные календари</h1>
  <p>Подписные календари с автообновлением для Apple Calendar и Google Calendar.</p>
  <p class="muted" style="margin-top:10px;">Обновлено: {html.escape(updated)}.</p>
  <div class="hero-actions"><a class="button" href="{html.escape(workflow_url)}" target="_blank" rel="noopener noreferrer">Запустить обновление</a></div>
  <p class="muted" style="margin-top:12px;">Кнопка ведёт на GitHub Actions. Ручной запуск доступен пользователю с правами на репозиторий.</p>
</div>
<div class="grid">{''.join(cards)}</div>
</div></body></html>"""


def ensure_clean_site() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")


def copy_assets() -> dict[str, Any]:
    assets_debug = {"assets_dir_exists": ASSETS_DIR.exists(), "logos_dir_exists": LOGOS_DIR.exists(), "copied_files": []}
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


def generate_team_pages(comp: Competition, events: list[Event], team_stats: list[dict[str, Any]], comp_dir: Path) -> None:
    teams_dir = comp_dir / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)
    (teams_dir / "index.html").write_text(render_teams_index(comp, team_stats), encoding="utf-8")
    for team_info in team_stats:
        team_name = team_info["name"]
        team_slug = team_info["slug"]
        team_key = team_info["team_key"]
        team_events = [
            event
            for event in events
            if any(side_key == team_key for side_key, _, _, _ in event_team_sides(comp, event))
        ]
        team_dir = teams_dir / team_slug
        team_dir.mkdir(parents=True, exist_ok=True)
        write_ics(team_events, team_dir / f"{team_slug}.ics", f"{team_name} — {comp.title}")
        (team_dir / "index.html").write_text(render_team_page(comp, team_info, team_events), encoding="utf-8")
        team_debug_payload = {
            "generated_at_utc": datetime.now(tz=UTC).isoformat(),
            "competition_slug": comp.slug,
            "competition_title": comp.title,
            "team_name": team_name,
            "team_id": team_info.get("team_id"),
            "team_names": team_info.get("names", [team_name]),
            "team_slug": team_slug,
            "team_page_url": team_info["page_url"],
            "team_ics_url": team_info["ics_url"],
            "events_count": len(team_events),
            "first_events": [
                {
                    "uid": event.uid,
                    "summary": event.summary,
                    "start": event.start.isoformat(),
                    "end": event.end.isoformat(),
                    "all_day": event.all_day,
                    "location": event.location,
                    "description": event.description,
                    "team_a": event.team_a,
                    "team_b": event.team_b,
                    "team_a_id": event.team_a_id,
                    "team_b_id": event.team_b_id,
                }
                for event in team_events[:10]
            ],
        }
        (team_dir / "debug.json").write_text(json.dumps(team_debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_team_slug_map(comp: Competition, events: list[Event]) -> dict[str, str]:
    profiles: dict[str, dict[str, Any]] = {}
    for event in events:
        for team_key, team_name, team_id, _ in event_team_sides(comp, event):
            profile = profiles.setdefault(
                team_key,
                {"name": team_name, "team_id": team_id, "names": set()},
            )
            profile["name"] = team_name
            profile["team_id"] = team_id or profile["team_id"]
            profile["names"].add(team_name)

    name_overrides = TEAM_SLUG_OVERRIDES.get(comp.slug, {})
    id_overrides = TEAM_ID_SLUG_OVERRIDES.get(comp.slug, {})
    slug_map: dict[str, str] = {}
    used_slugs: set[str] = set()
    for team_key, profile in sorted(profiles.items(), key=lambda item: item[1]["name"]):
        team_name = profile["name"]
        team_id = profile["team_id"]
        name_override = next(
            (
                name_overrides[name]
                for name in [team_name, *sorted(profile["names"])]
                if name in name_overrides
            ),
            None,
        )
        base_slug = id_overrides.get(team_id or "") or name_override or slugify_team_name(team_name)
        slug = base_slug
        idx = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{idx}"
            idx += 1
        slug_map[team_key] = slug
        used_slugs.add(slug)
    return slug_map


def collect_team_stats(comp: Competition, events: list[Event], slug_map: dict[str, str]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}

    def ensure_team(team_key: str, name: str, team_id: str | None) -> dict[str, Any]:
        if team_key not in stats:
            team_slug = slug_map[team_key]
            stats[team_key] = {
                "team_key": team_key,
                "team_id": team_id,
                "name": name,
                "names": [],
                "slug": team_slug,
                "page_url": team_page_url(comp, team_slug),
                "ics_url": team_ics_url(comp, team_slug),
                "games_count": 0,
                "home_games_count": 0,
                "away_games_count": 0,
                "upcoming_games_count": 0,
                "latest_game_start_utc": None,
                "next_game_start_utc": None,
                "sample_matchups": [],
            }
        item = stats[team_key]
        item["name"] = name
        item["team_id"] = team_id or item["team_id"]
        if name not in item["names"]:
            item["names"].append(name)
        return item

    now_utc = datetime.now(tz=UTC)
    for event in events:
        start_dt_utc = event.start.astimezone(UTC) if isinstance(event.start, datetime) else None
        for team_key, team_name, team_id, side in event_team_sides(comp, event):
            item = ensure_team(team_key, team_name, team_id)
            item["games_count"] += 1
            item["home_games_count"] += side == "home"
            item["away_games_count"] += side == "away"
            if len(item["sample_matchups"]) < 5:
                item["sample_matchups"].append(event.summary)
            if start_dt_utc is not None:
                latest = item["latest_game_start_utc"]
                if latest is None or start_dt_utc > datetime.fromisoformat(latest):
                    item["latest_game_start_utc"] = start_dt_utc.isoformat()
                if event_is_upcoming(event, now_utc):
                    item["upcoming_games_count"] += 1
                    next_game = item["next_game_start_utc"]
                    if next_game is None or start_dt_utc < datetime.fromisoformat(next_game):
                        item["next_game_start_utc"] = start_dt_utc.isoformat()
            elif event_is_upcoming(event, now_utc):
                item["upcoming_games_count"] += 1
    return sorted(stats.values(), key=lambda x: x["name"])


def generate_for_comp(comp: Competition) -> dict[str, Any]:
    excluded_names = sorted(get_excluded_team_names(comp))
    debug = {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "site_url": comp_site_url(comp),
        "ics_url": comp_ics_url(comp),
        "teams_url": comp_teams_url(comp),
        "workflow_url": github_workflow_url(),
        "source_type": comp.source_type,
        "slug": comp.slug,
        "title": comp.title,
        "tag": comp.tag,
        "season": comp.season,
        "seasons": list(comp.seasons),
        "comp_id": comp.comp_id,
        "calendar_type": comp.calendar_type,
        "excluded_team_names": excluded_names,
    }
    rows = fetch_source_rows(comp, debug)
    events = build_events(rows, comp, debug)
    slug_map = build_team_slug_map(comp, events)
    team_stats = collect_team_stats(comp, events, slug_map)

    comp_dir = OUTPUT_DIR / comp.slug
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "index.html").write_text(render_comp_index(comp, events, team_stats, debug), encoding="utf-8")
    write_ics(events, comp_dir / comp.ics_filename, comp.title)
    generate_team_pages(comp, events, team_stats, comp_dir)

    (comp_dir / "debug.json").write_text(json.dumps({
        **debug,
        "rows_count": len(rows),
        "events_count": len(events),
        "teams_detected_count": len(team_stats),
        "first_events": [
            {
                "uid": event.uid,
                "summary": event.summary,
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
                "all_day": event.all_day,
                "location": event.location,
                "description": event.description,
                "team_a": event.team_a,
                "team_b": event.team_b,
                "team_a_id": event.team_a_id,
                "team_b_id": event.team_b_id,
            } for event in events[:10]
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    (comp_dir / "teams_debug.json").write_text(json.dumps({
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "comp_id": comp.comp_id,
        "tag": comp.tag,
        "season": comp.season,
        "seasons": list(comp.seasons),
        "slug": comp.slug,
        "title": comp.title,
        "excluded_team_names": excluded_names,
        "teams_count": len(team_stats),
        "teams": team_stats,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "comp": comp,
        "events_count": len(events),
        "upcoming_count": sum(1 for event in events if event_is_upcoming(event, datetime.now(tz=UTC))),
        "teams_detected_count": len(team_stats),
        "page_exists": (comp_dir / "index.html").exists(),
    }


def main() -> None:
    ensure_clean_site()
    assets_debug = copy_assets()
    results = [generate_for_comp(comp) for comp in COMPETITIONS]
    (OUTPUT_DIR / "index.html").write_text(render_root_index(results), encoding="utf-8")
    (OUTPUT_DIR / "debug.json").write_text(json.dumps({
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "site_base_url": SITE_BASE_URL,
        "workflow_url": github_workflow_url(),
        "assets_debug": assets_debug,
        "competitions": [
            {
                "slug": result["comp"].slug,
                "title": result["comp"].title,
                "source_type": result["comp"].source_type,
                "tag": result["comp"].tag,
                "season": result["comp"].season,
                "seasons": list(result["comp"].seasons),
                "comp_id": result["comp"].comp_id,
                "site_url": comp_site_url(result["comp"]),
                "ics_url": comp_ics_url(result["comp"]),
                "teams_url": comp_teams_url(result["comp"]),
                "events_count": result["events_count"],
                "upcoming_count": result["upcoming_count"],
                "teams_detected_count": result["teams_detected_count"],
                "page_exists": result["page_exists"],
            }
            for result in results
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(results)} calendars into {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
