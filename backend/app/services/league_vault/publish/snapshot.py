"""Materialize one public JSON snapshot per vault site."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session, load_only

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
from app.services.league_vault.branding import (
    public_manager_display_name,
    sanitize_site_display_name,
)
from app.services.league_vault.publish.players import (
    apply_player_labels_to_picks,
    normalize_draft_player_id,
    resolve_player_labels,
)
from app.services.league_vault.title_annotations import apply_title_annotations


def _manager_public(m: LvManager) -> dict[str, Any]:
    return {
        "id": m.id,
        "slug": _slugify(m.display_name or m.canonical_name or str(m.id)),
        "display_name": public_manager_display_name(
            m.display_name, canonical=m.canonical_name
        ),
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


def _transaction_public(
    db: Session, *, season_id: int, teams: list[LvTeam]
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Type counts + a short recent ledger (no raw platform payloads)."""
    summary: dict[str, int] = defaultdict(int)
    recent: list[dict[str, Any]] = []
    roster_to_team = {
        str(t.platform_roster_id): t for t in teams if t.platform_roster_id
    }
    try:
        rows = (
            db.query(LvTransaction)
            .options(
                load_only(
                    LvTransaction.id,
                    LvTransaction.season_id,
                    LvTransaction.week,
                    LvTransaction.type,
                    LvTransaction.status,
                    LvTransaction.created_at_ts,
                    LvTransaction.team_ids,
                )
            )
            .filter_by(season_id=season_id)
            .order_by(LvTransaction.id.desc())
            .all()
        )
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return {}, []

    for tx in rows:
        key = str(tx.type or "unknown")
        summary[key] += 1

    for tx in rows[:40]:
        team_names: list[str] = []
        for rid in tx.team_ids or []:
            t = roster_to_team.get(str(rid))
            if t and t.team_name:
                team_names.append(t.team_name)
        recent.append(
            {
                "week": tx.week,
                "type": tx.type,
                "status": tx.status,
                "team_names": team_names,
            }
        )
    return dict(summary), recent


def _scores_close(a: Any, b: Any, *, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def enrich_record_matchup_context(
    context: dict[str, Any],
    season_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fill manager/team ids on matchup records from season scoreboard data.

    Older compute rows only stored season/week/scores; resolve the pairing so
    the Record Book can render \"A vs B\" without a full recompute.
    """
    ctx = dict(context or {})
    if ctx.get("manager_a_id") is not None and ctx.get("manager_b_id") is not None:
        return ctx
    season = ctx.get("season")
    week = ctx.get("week")
    if season is None or week is None:
        return ctx
    season_row = next((s for s in season_payloads if s.get("season") == season), None)
    if not season_row:
        return ctx
    team_by_id = {t["id"]: t for t in season_row.get("teams") or []}
    score_a = ctx.get("team_a_score")
    score_b = ctx.get("team_b_score")
    team_id = ctx.get("team_id")
    match = None
    for m in season_row.get("matchups") or []:
        if m.get("week") != week:
            continue
        if score_a is not None and score_b is not None:
            if _scores_close(m.get("team_a_score"), score_a) and _scores_close(
                m.get("team_b_score"), score_b
            ):
                match = m
                break
        if team_id is not None and (
            m.get("team_a_id") == team_id or m.get("team_b_id") == team_id
        ):
            match = m
            break
    if not match:
        return ctx
    ta = team_by_id.get(match.get("team_a_id"))
    tb = team_by_id.get(match.get("team_b_id"))
    ctx["team_a_id"] = match.get("team_a_id")
    ctx["team_b_id"] = match.get("team_b_id")
    if ta:
        ctx["manager_a_id"] = ta.get("manager_id")
        ctx["team_a_name"] = ta.get("team_name")
    if tb:
        ctx["manager_b_id"] = tb.get("manager_id")
        ctx["team_b_name"] = tb.get("team_name")
    return ctx


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
    draft_player_ids: set[str] = set()
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
            if m.team_a_score is not None and m.team_b_score is not None:
                if m.team_a_score > m.team_b_score:
                    h2h[ka][kb]["wins"] += 1
                    h2h[kb][ka]["losses"] += 1
                elif m.team_b_score > m.team_a_score:
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

        draft_payload: list[dict[str, Any]] = []
        try:
            drafts = (
                db.query(LvDraft)
                .options(
                    load_only(
                        LvDraft.id,
                        LvDraft.season_id,
                        LvDraft.draft_type,
                    )
                )
                .filter_by(season_id=season.id)
                .all()
            )
            for d in drafts:
                # team_id / player_id are on the original P1 table; load them so
                # draft boards can show who picked whom (was hard-null'd during
                # early prod schema-drift hardening).
                picks = (
                    db.query(LvDraftPick)
                    .options(
                        load_only(
                            LvDraftPick.id,
                            LvDraftPick.draft_id,
                            LvDraftPick.round,
                            LvDraftPick.pick_no,
                            LvDraftPick.draft_slot,
                            LvDraftPick.team_id,
                            LvDraftPick.player_id,
                        )
                    )
                    .filter_by(draft_id=d.id)
                    .order_by(LvDraftPick.round, LvDraftPick.pick_no)
                    .all()
                )
                rounds = max((p.round for p in picks), default=None)
                pick_rows: list[dict[str, Any]] = []
                for p in picks:
                    pid = normalize_draft_player_id(p.player_id)
                    if pid:
                        draft_player_ids.add(pid)
                    pick_rows.append(
                        {
                            "round": p.round,
                            "pick_no": p.pick_no,
                            "draft_slot": p.draft_slot,
                            "team_id": p.team_id,
                            "player_id": pid,
                            "platform_roster_id": None,
                            "is_keeper": None,
                            "auction_amount": None,
                        }
                    )
                picks_made = sum(1 for row in pick_rows if row["player_id"])
                total = len(pick_rows)
                if total == 0:
                    status = "empty"
                elif picks_made == 0:
                    # ESPN often publishes snake order before the draft runs
                    # (playerId=-1 on every row).
                    status = "pending"
                elif picks_made >= max(1, int(total * 0.8)):
                    # A few blank ESPN slots are normal; treat as complete.
                    status = "complete"
                else:
                    status = "in_progress"
                draft_payload.append(
                    {
                        "draft_type": d.draft_type,
                        "status": status,
                        "rounds": rounds,
                        "picks_made": picks_made,
                        "picks": pick_rows,
                    }
                )
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            draft_payload = []

        tx_count = db.query(LvTransaction).filter_by(season_id=season.id).count()
        tx_summary, tx_recent = _transaction_public(
            db, season_id=season.id, teams=teams
        )

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
                        "team_a_score": m.team_a_score,
                        "team_b_score": m.team_b_score,
                        "winner_team_id": m.winner_team_id,
                        "margin": m.margin,
                    }
                    for m in matchups
                ],
                "drafts": draft_payload,
                "transaction_count": tx_count,
                "transaction_summary": tx_summary,
                "transactions_recent": tx_recent,
            }
        )

    player_labels = resolve_player_labels(db, draft_player_ids)
    for season_row in season_payloads:
        for draft in season_row.get("drafts") or []:
            apply_player_labels_to_picks(draft.get("picks") or [], player_labels)

    records = db.query(LvRecord).filter_by(lineage_id=lineage_id).all()
    record_payload = [
        {
            "record_key": r.record_key,
            "scope": r.scope,
            "season": r.season,
            "manager_id": r.manager_id,
            "team_id": r.team_id,
            "value": r.value,
            "context": enrich_record_matchup_context(r.context or {}, season_payloads),
        }
        for r in records
    ]

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
    for season in reversed(seasons):
        if season.champion_manager_id and season.champion_manager_id in managers:
            reigning = {
                **_manager_public(managers[season.champion_manager_id]),
                "season": season.season,
            }
            break

    return apply_title_annotations(
        {
            "slug": site.slug,
            "display_name": sanitize_site_display_name(
                site.display_name, slug=site.slug
            ),
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
    )


def write_snapshot_file(snapshot: dict[str, Any], path: str) -> str:
    import json
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot, indent=2, default=str))
    return str(p)
