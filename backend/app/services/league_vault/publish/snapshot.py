"""Materialize one public JSON snapshot per vault site."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.league_vault_models import (
    LvDraft,
    LvDraftPick,
    LvManager,
    LvMatchup,
    LvRecord,
    LvSeason,
    LvSite,
    LvTeam,
    LvTransaction,
)


def _manager_public(m: LvManager) -> dict[str, Any]:
    return {
        "id": m.id,
        "slug": _slugify(m.display_name or m.canonical_name or str(m.id)),
        "display_name": m.display_name,
        "canonical_name": m.canonical_name,
        "aliases": m.aliases or [],
        "first_season": m.first_season,
        "last_season": m.last_season,
        "is_active": m.is_active,
        # Intentionally omit platform_user_id / SWID
    }


def _slugify(name: str) -> str:
    import re

    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "manager"


def build_site_snapshot(db: Session, *, slug: str) -> dict[str, Any]:
    site = db.query(LvSite).filter_by(slug=slug).one()
    lineage_id = site.lineage_id
    managers = {
        m.id: m for m in db.query(LvManager).filter_by(lineage_id=lineage_id).all()
    }
    seasons = (
        db.query(LvSeason)
        .filter_by(lineage_id=lineage_id)
        .order_by(LvSeason.season)
        .all()
    )
    season_payloads = []
    all_teams: list[LvTeam] = []
    h2h: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0})
    )

    for season in seasons:
        teams = db.query(LvTeam).filter_by(season_id=season.id).all()
        all_teams.extend(teams)
        team_by_id = {t.id: t for t in teams}
        matchups = (
            db.query(LvMatchup)
            .filter_by(season_id=season.id)
            .order_by(LvMatchup.week)
            .all()
        )
        for m in matchups:
            if not m.team_a_id or not m.team_b_id:
                continue
            a = team_by_id.get(m.team_a_id)
            b = team_by_id.get(m.team_b_id)
            if not a or not b:
                continue
            ka = str(a.manager_id)
            kb = str(b.manager_id)
            if m.score_a is not None and m.score_b is not None:
                if m.score_a > m.score_b:
                    h2h[ka][kb]["wins"] += 1
                    h2h[kb][ka]["losses"] += 1
                elif m.score_b > m.score_a:
                    h2h[kb][ka]["wins"] += 1
                    h2h[ka][kb]["losses"] += 1
                else:
                    h2h[ka][kb]["ties"] += 1
                    h2h[kb][ka]["ties"] += 1

        champ = (
            managers.get(season.champion_manager_id)
            if season.champion_manager_id
            else None
        )
        runner = (
            managers.get(season.runner_up_manager_id)
            if season.runner_up_manager_id
            else None
        )
        last = (
            managers.get(season.last_place_manager_id)
            if season.last_place_manager_id
            else None
        )

        drafts = db.query(LvDraft).filter_by(season_id=season.id).all()
        draft_payload = []
        for d in drafts:
            picks = (
                db.query(LvDraftPick)
                .filter_by(draft_id=d.id)
                .order_by(LvDraftPick.pick_no)
                .all()
            )
            draft_payload.append(
                {
                    "draft_type": d.draft_type,
                    "rounds": d.rounds,
                    "picks": [
                        {
                            "round": p.round,
                            "pick_no": p.pick_no,
                            "draft_slot": p.draft_slot,
                            "team_id": p.team_id,
                            "player_id": p.player_id,
                            "is_keeper": p.is_keeper,
                            "auction_amount": p.auction_amount,
                        }
                        for p in picks
                    ],
                }
            )

        tx_count = db.query(LvTransaction).filter_by(season_id=season.id).count()

        season_payloads.append(
            {
                "season": season.season,
                "team_count": season.team_count,
                "playoff_teams": season.playoff_teams,
                "regular_season_weeks": season.regular_season_weeks,
                "champion": _manager_public(champ) if champ else None,
                "runner_up": _manager_public(runner) if runner else None,
                "last_place": _manager_public(last) if last else None,
                "teams": [
                    {
                        "id": t.id,
                        "manager_id": t.manager_id,
                        "team_name": t.team_name,
                        "avatar_url": t.avatar_url,
                        "wins": t.wins,
                        "losses": t.losses,
                        "ties": t.ties,
                        "points_for": t.points_for,
                        "points_against": t.points_against,
                        "final_rank": t.final_rank,
                        "playoff_seed": t.playoff_seed,
                        "all_play_wins": t.all_play_wins,
                        "all_play_losses": t.all_play_losses,
                        "luck_differential": t.luck_differential,
                        "moves": t.moves,
                    }
                    for t in sorted(
                        teams, key=lambda x: (x.final_rank is None, x.final_rank or 999)
                    )
                ],
                "matchups": [
                    {
                        "week": m.week,
                        "is_playoff": m.is_playoff,
                        "team_a_id": m.team_a_id,
                        "team_b_id": m.team_b_id,
                        "score_a": m.score_a,
                        "score_b": m.score_b,
                        "winner_team_id": m.winner_team_id,
                        "margin": m.margin,
                    }
                    for m in matchups
                ],
                "drafts": draft_payload,
                "transaction_count": tx_count,
            }
        )

    records = db.query(LvRecord).filter_by(lineage_id=lineage_id).all()
    record_payload = [
        {
            "record_key": r.record_key,
            "scope": r.scope,
            "season": r.season,
            "manager_id": r.manager_id,
            "team_id": r.team_id,
            "value": r.value,
            "context": r.context or {},
        }
        for r in records
    ]

    # Career lines for managers page
    career: dict[int, dict[str, Any]] = {}
    for t in all_teams:
        c = career.setdefault(
            t.manager_id,
            {"wins": 0, "losses": 0, "ties": 0, "points_for": 0.0, "titles": 0},
        )
        c["wins"] += t.wins or 0
        c["losses"] += t.losses or 0
        c["ties"] += t.ties or 0
        c["points_for"] += t.points_for or 0.0
    for s in seasons:
        if s.champion_manager_id and s.champion_manager_id in career:
            career[s.champion_manager_id]["titles"] += 1

    reigning = None
    if seasons:
        latest = seasons[-1]
        if latest.champion_manager_id and latest.champion_manager_id in managers:
            reigning = {
                **_manager_public(managers[latest.champion_manager_id]),
                "season": latest.season,
            }

    return {
        "slug": site.slug,
        "display_name": site.display_name,
        "tagline": site.tagline,
        "first_season": site.first_season,
        "latest_season": site.latest_season,
        "last_place_label": site.last_place_label or "Last Place",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "reigning_champion": reigning,
        "managers": [_manager_public(m) for m in managers.values()],
        "manager_careers": {str(mid): data for mid, data in career.items()},
        "seasons": season_payloads,
        "records": record_payload,
        "h2h": {a: dict(b) for a, b in h2h.items()},
        "dynasty_timeline": [
            {
                "season": s["season"],
                "champion": s["champion"],
            }
            for s in season_payloads
        ],
    }


def write_snapshot_file(snapshot: dict[str, Any], path: str) -> str:
    import json
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot, indent=2, default=str))
    return str(p)
