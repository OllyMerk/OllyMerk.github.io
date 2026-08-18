from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


RUSSIABASKET_URL = "https://pro.russiabasket.org/api/abc/comps/calendar"
INFOBASKET_URL = "https://org.infobasket.su/Comp/GetCalendar/"

TIMEOUT = 30
USER_AGENT = "VTB-Calendars-Diagnostics/1.0"

OUTPUT_DIR = Path("diagnostics")
OUTPUT_FILE = OUTPUT_DIR / "calendar_sources.json"


def get_json(url: str, params: dict[str, Any]) -> Any:
    response = requests.get(
        url,
        params=params,
        timeout=TIMEOUT,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": USER_AGENT,
        },
    )

    print()
    print("=" * 80)
    print("REQUEST")
    print(response.url)
    print("HTTP:", response.status_code)

    response.raise_for_status()
    return response.json()


def rb_game_id(item: dict[str, Any]) -> str | None:
    game = item.get("game")
    if not isinstance(game, dict):
        return None

    value = game.get("id")
    return str(value) if value is not None else None


def rb_game_summary(item: dict[str, Any]) -> dict[str, Any]:
    game = item.get("game") if isinstance(item.get("game"), dict) else {}
    comp = item.get("comp") if isinstance(item.get("comp"), dict) else {}
    league = item.get("league") if isinstance(item.get("league"), dict) else {}
    team1 = item.get("team1") if isinstance(item.get("team1"), dict) else {}
    team2 = item.get("team2") if isinstance(item.get("team2"), dict) else {}
    arena = item.get("arena") if isinstance(item.get("arena"), dict) else {}
    region = item.get("region") if isinstance(item.get("region"), dict) else {}

    return {
        "game_id": game.get("id"),
        "number": game.get("number"),
        "scheduledTime": game.get("scheduledTime"),
        "defaultZoneDateTime": game.get("defaultZoneDateTime"),
        "localDate": game.get("localDate"),
        "localTime": game.get("localTime"),
        "team1": team1.get("name"),
        "team2": team2.get("name"),
        "arena": arena.get("name"),
        "region": region.get("name"),
        "comp_id": comp.get("id"),
        "comp_name": comp.get("name"),
        "comp_type": comp.get("compType"),
        "league_id": league.get("id"),
        "league_name": league.get("name"),
        "league_tag": league.get("tag"),
        "season": league.get("season"),
    }


def diagnose_russiabasket(
    *,
    label: str,
    tag: str,
    season: int,
) -> dict[str, Any]:

    payload = get_json(
        RUSSIABASKET_URL,
        {
            "tag": tag,
            "season": season,
        },
    )

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{label}: expected object, got {type(payload).__name__}"
        )

    items = payload.get("items")
    if not isinstance(items, list):
        items = []

    ids = [
        game_id
        for item in items
        if isinstance(item, dict)
        if (game_id := rb_game_id(item)) is not None
    ]

    total_count = payload.get("totalCount")
    items_count = len(items)

    pagination_required = (
        isinstance(total_count, int)
        and total_count > items_count
    )

    result = {
        "label": label,
        "endpoint": RUSSIABASKET_URL,
        "request": {
            "tag": tag,
            "season": season,
        },
        "status": payload.get("status"),
        "message": payload.get("message"),
        "index": payload.get("index"),
        "totalCount": total_count,
        "items_count": items_count,
        "pagination_required": pagination_required,
        "game_ids": ids,
        "games": [
            rb_game_summary(item)
            for item in items
            if isinstance(item, dict)
        ],
    }

    print()
    print(label)
    print("-" * len(label))
    print("tag:", tag)
    print("season:", season)
    print("status:", payload.get("status"))
    print("totalCount:", total_count)
    print("items_count:", items_count)
    print("pagination_required:", pagination_required)
    print("IDs:", ", ".join(ids) if ids else "—")

    return result


def diagnose_infobasket_2026() -> dict[str, Any]:
    payload = get_json(
        INFOBASKET_URL,
        {
            "comps": "50714",
            "format": "json",
        },
    )

    if not isinstance(payload, list):
        raise RuntimeError(
            f"InfoBasket: expected list, got {type(payload).__name__}"
        )

    rows = [
        row
        for row in payload
        if isinstance(row, dict)
    ]

    ids = {
        str(row["GameID"])
        for row in rows
        if row.get("GameID") is not None
    }

    dates = [
        row.get("GameDate")
        for row in rows
        if row.get("GameDate")
    ]

    result = {
        "label": "VTB old source / season 2025-26",
        "endpoint": INFOBASKET_URL,
        "request": {
            "comps": "50714",
            "format": "json",
        },
        "items_count": len(rows),
        "game_ids": sorted(ids),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
    }

    print()
    print("VTB old InfoBasket source")
    print("-------------------------")
    print("items_count:", len(rows))
    print("first_date:", result["first_date"])
    print("last_date:", result["last_date"])

    return result


def test_pagination(
    *,
    tag: str,
    season: int,
    original_ids: list[str],
) -> list[dict[str, Any]]:

    print()
    print("=" * 80)
    print("PAGINATION PROBE")
    print("=" * 80)

    probes = [
        ("index", 1),
        ("page", 1),
        ("pageIndex", 1),
        ("pageNumber", 2),
        ("offset", 10),
        ("skip", 10),
        ("start", 10),
        ("from", 10),
    ]

    results: list[dict[str, Any]] = []

    original_signature = tuple(original_ids)

    for key, value in probes:
        try:
            payload = get_json(
                RUSSIABASKET_URL,
                {
                    "tag": tag,
                    "season": season,
                    key: value,
                },
            )

            items = (
                payload.get("items", [])
                if isinstance(payload, dict)
                else []
            )

            if not isinstance(items, list):
                items = []

            ids = [
                game_id
                for item in items
                if isinstance(item, dict)
                if (game_id := rb_game_id(item)) is not None
            ]

            changed = tuple(ids) != original_signature

            probe_result = {
                "parameter": key,
                "value": value,
                "items_count": len(items),
                "ids": ids,
                "changed_page": changed,
            }

            results.append(probe_result)

            print()
            print(f"{key}={value}")
            print("changed_page:", changed)
            print("IDs:", ", ".join(ids) if ids else "—")

        except Exception as exc:
            results.append(
                {
                    "parameter": key,
                    "value": value,
                    "error": repr(exc),
                }
            )

            print()
            print(f"{key}={value}")
            print("ERROR:", repr(exc))

    return results


def compare_old_and_new_2026(
    old_source: dict[str, Any],
    rb_2026: dict[str, Any],
) -> dict[str, Any]:

    old_ids = set(old_source["game_ids"])
    new_ids = set(rb_2026["game_ids"])

    matching = sorted(old_ids & new_ids)
    missing_in_old = sorted(new_ids - old_ids)

    result = {
        "russiabasket_first_page_ids": sorted(new_ids),
        "matching_ids_in_old_infobasket": matching,
        "missing_in_old_infobasket": missing_in_old,
        "all_first_page_ids_match": (
            bool(new_ids)
            and new_ids.issubset(old_ids)
        ),
    }

    print()
    print("=" * 80)
    print("OLD ↔ NEW ID COMPARISON / SEASON 2026")
    print("=" * 80)
    print(
        "all_first_page_ids_match:",
        result["all_first_page_ids_match"],
    )
    print(
        "matching:",
        ", ".join(matching) if matching else "—",
    )
    print(
        "missing:",
        ", ".join(missing_in_old) if missing_in_old else "—",
    )

    return result


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()

    old_vtb_2026 = diagnose_infobasket_2026()

    new_vtb_2026 = diagnose_russiabasket(
        label="VTB / tag=vtb / season=2026",
        tag="vtb",
        season=2026,
    )

    new_vtb_2027 = diagnose_russiabasket(
        label="VTB / tag=vtb / season=2027",
        tag="vtb",
        season=2027,
    )

    supercup_2026 = diagnose_russiabasket(
        label="Supercup / tag=vtb-supercup / season=2026",
        tag="vtb-supercup",
        season=2026,
    )

    supercup_2027 = diagnose_russiabasket(
        label="Supercup / tag=vtb-supercup / season=2027",
        tag="vtb-supercup",
        season=2027,
    )

    comparison = compare_old_and_new_2026(
        old_vtb_2026,
        new_vtb_2026,
    )

    pagination_probe = []

    if new_vtb_2027["pagination_required"]:
        pagination_probe = test_pagination(
            tag="vtb",
            season=2027,
            original_ids=new_vtb_2027["game_ids"],
        )

    report = {
        "generated_at_utc": generated_at,
        "expected_reference": {
            "vtb_2027_first_stage_matches": 110,
            "supercup_2026_matches": 9,
        },
        "sources": {
            "old_vtb_2026": old_vtb_2026,
            "new_vtb_2026": new_vtb_2026,
            "new_vtb_2027": new_vtb_2027,
            "supercup_2026": supercup_2026,
            "supercup_2027": supercup_2027,
        },
        "comparison_old_vs_new_2026": comparison,
        "vtb_2027_pagination_probe": pagination_probe,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 80)
    print("DIAGNOSTICS COMPLETE")
    print("=" * 80)
    print("Report:", OUTPUT_FILE)

    print()
    print("REFERENCE CHECKS")

    vtb_total = new_vtb_2027.get("totalCount")
    print(
        "VTB 2027 totalCount:",
        vtb_total,
        "(official first-stage reference: 110)",
    )

    supercup_total = supercup_2027.get("totalCount")
    print(
        "Supercup 2027 totalCount:",
        supercup_total,
    )


if __name__ == "__main__":
    main()
