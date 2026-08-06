"""
Normalize Sleeper / ESPN payloads into lv_* tables (idempotent per season).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.league_vault_models import (
    LvDraft,
    LvDraftPick,
    LvLeagueLineage,
    LvManager,
    LvMatchup,
    LvSeason,
    LvSite,
    LvTeam,
    LvTransaction,
)

logger = logging.getLogger(__name__)

SLEEPER_AVATAR_THUMB = "https://sleepercdn.com/avatars/thumbs/{avatar_id}"


def _sleeper_fpts(settings: dict[str, Any] | None) -> float:
    """Sleeper stores fpts as whole + decimal/100."""
    if not settings:
        return 0.0
    whole = float(settings.get("fpts", 0) or 0)
    dec = float(settings.get("fpts_decimal", 0) or 0) / 100.0
    return whole + dec


def _sleeper_avatar_url(user: dict[str, Any] | None) -> str | None:
    avatar = (user or {}).get("avatar")
    if not avatar:
        return None
    return SLEEPER_AVATAR_THUMB.format(avatar_id=avatar)


def _delete_season(db: Session, lineage_id: int, season: int) -> None:
    """Remove existing season row (cascades children via ORM delete)."""
    row = (
        db.query(LvSeason)
        .filter(LvSeason.lineage_id == lineage_id, LvSeason.season == season)
        .first()
    )
    if row:
        db.delete(row)
        db.flush()


def get_or_create_lineage_and_site(
    db: Session,
    *,
    platform: str,
    root_platform_league_id: str,
    slug: str,
    display_name: str,
    tagline: str | None = None,
    last_place_label: str | None = None,
) -> tuple[LvLeagueLineage, LvSite]:
    lineage = (
        db.query(LvLeagueLineage)
        .filter(
            LvLeagueLineage.platform == platform,
            LvLeagueLineage.root_platform_league_id == root_platform_league_id,
        )
        .first()
    )
    if not lineage:
        lineage = LvLeagueLineage(
            platform=platform,
            root_platform_league_id=root_platform_league_id,
            season_league_ids={},
        )
        db.add(lineage)
        db.flush()

    site = db.query(LvSite).filter(LvSite.lineage_id == lineage.id).first()
    if not site:
        site = LvSite(
            lineage_id=lineage.id,
            slug=slug,
            display_name=display_name,
            tagline=tagline,
            last_place_label=last_place_label,
            is_public=True,
        )
        db.add(site)
        db.flush()
    else:
        # Do not clobber a real ESPN/Sleeper name with a placeholder default.
        from app.services.league_vault.branding import is_placeholder_site_name

        incoming = (display_name or "").strip()
        if incoming:
            if is_placeholder_site_name(site.display_name):
                site.display_name = incoming
            elif not is_placeholder_site_name(incoming):
                site.display_name = incoming
        if tagline is not None:
            site.tagline = tagline
        if last_place_label is not None:
            site.last_place_label = last_place_label
        site.updated_at = datetime.utcnow()

    return lineage, site


def _get_or_create_manager(
    db: Session,
    *,
    lineage_id: int,
    platform_user_id: str,
    display_name: str,
    season: int,
) -> LvManager:
    mgr = (
        db.query(LvManager)
        .filter(
            LvManager.lineage_id == lineage_id,
            LvManager.platform_user_id == platform_user_id,
        )
        .first()
    )
    canonical = display_name.strip() or platform_user_id
    if not mgr:
        mgr = LvManager(
            lineage_id=lineage_id,
            platform_user_id=platform_user_id,
            canonical_name=canonical,
            display_name=display_name,
            aliases=[display_name] if display_name else [],
            first_season=season,
            last_season=season,
            is_active=True,
        )
        db.add(mgr)
        db.flush()
        return mgr

    if display_name and display_name not in (mgr.aliases or []):
        mgr.aliases = list(mgr.aliases or []) + [display_name]
    if mgr.first_season is None or season < mgr.first_season:
        mgr.first_season = season
    if mgr.last_season is None or season > mgr.last_season:
        mgr.last_season = season
    if display_name:
        mgr.display_name = display_name
    return mgr


def _pair_sleeper_matchups(
    week_rows: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], str | None]]:
    """Group Sleeper matchup rows by matchup_id into pairs."""
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in week_rows:
        mid = row.get("matchup_id")
        grouped.setdefault(mid, []).append(row)

    pairs: list[tuple[dict[str, Any], dict[str, Any], str | None]] = []
    for mid, rows in grouped.items():
        if len(rows) != 2:
            logger.debug(
                "Skipping unmatched sleeper matchup_id=%s count=%s", mid, len(rows)
            )
            continue
        pairs.append((rows[0], rows[1], str(mid) if mid is not None else None))
    return pairs


def _bracket_champ_runner_up(
    winners_bracket: list[dict[str, Any]] | None,
    roster_to_team: dict[str, LvTeam],
) -> tuple[LvTeam | None, LvTeam | None]:
    """Champion from winners_bracket entry with p==1; runner-up from p==2 if present."""
    if not winners_bracket:
        return None, None

    champ_roster: str | None = None
    runner_roster: str | None = None
    for entry in winners_bracket:
        p = entry.get("p")
        rid = str(entry.get("r") or entry.get("roster_id") or "")
        if p == 1 and rid:
            champ_roster = rid
        elif p == 2 and rid:
            runner_roster = rid

    champ_team = roster_to_team.get(champ_roster) if champ_roster else None
    runner_team = roster_to_team.get(runner_roster) if runner_roster else None
    return champ_team, runner_team


def normalize_sleeper_season(
    db: Session,
    *,
    lineage: LvLeagueLineage,
    site: LvSite,
    season: int,
    platform_league_id: str,
    league: dict[str, Any],
    rosters: list[dict[str, Any]],
    users: list[dict[str, Any]],
    matchups_by_week: dict[int, list[dict[str, Any]]],
    drafts: list[dict[str, Any]] | None = None,
    transactions: list[dict[str, Any]] | None = None,
    winners_bracket: list[dict[str, Any]] | None = None,
    losers_bracket: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Idempotent delete+rewrite of one Sleeper season into lv_* tables.
    """
    _delete_season(db, lineage.id, season)

    season_league_ids = dict(lineage.season_league_ids or {})
    season_league_ids[str(season)] = platform_league_id
    lineage.season_league_ids = season_league_ids
    lineage.last_synced = datetime.utcnow()

    users_by_id = {u["user_id"]: u for u in users if u and u.get("user_id")}

    settings = league.get("settings") or {}
    lv_season = LvSeason(
        lineage_id=lineage.id,
        season=season,
        platform_league_id=platform_league_id,
        team_count=league.get("total_rosters") or len(rosters),
        playoff_teams=settings.get("playoff_teams"),
        regular_season_weeks=settings.get("reg_season_count"),
        scoring_settings=league.get("scoring_settings")
        or settings.get("scoring_settings"),
        roster_positions=league.get("roster_positions"),
    )
    db.add(lv_season)
    db.flush()

    roster_to_team: dict[str, LvTeam] = {}
    manager_count = 0

    for roster in rosters:
        owner_id = str(roster.get("owner_id") or "")
        user = users_by_id.get(roster.get("owner_id"), {})
        display = (
            user.get("display_name")
            or user.get("metadata", {}).get("team_name")
            or user.get("username")
            or owner_id
        )
        mgr = _get_or_create_manager(
            db,
            lineage_id=lineage.id,
            platform_user_id=owner_id or str(roster.get("roster_id")),
            display_name=display,
            season=season,
        )
        manager_count += 1

        rs = roster.get("settings") or {}
        roster_id = str(roster["roster_id"])
        team = LvTeam(
            season_id=lv_season.id,
            manager_id=mgr.id,
            platform_roster_id=roster_id,
            team_name=display,
            avatar_url=_sleeper_avatar_url(user),
            wins=int(rs.get("wins", 0) or 0),
            losses=int(rs.get("losses", 0) or 0),
            ties=int(rs.get("ties", 0) or 0),
            points_for=_sleeper_fpts(rs),
            points_against=_sleeper_fpts(
                {
                    "fpts": rs.get("fpts_against", 0),
                    "fpts_decimal": rs.get("fpts_against_decimal", 0),
                }
            ),
            final_rank=rs.get("rank"),
            playoff_seed=rs.get("playoff_seed"),
            all_play_wins=rs.get("fpts_against_rank"),
            moves=rs.get("moves"),
        )
        db.add(team)
        db.flush()
        roster_to_team[roster_id] = team

    matchup_count = 0
    reg_weeks = lv_season.regular_season_weeks or max(
        matchups_by_week.keys(), default=0
    )

    for week, week_rows in sorted(matchups_by_week.items()):
        is_playoff = week > reg_weeks if reg_weeks else False
        for a, b, mid in _pair_sleeper_matchups(week_rows):
            team_a_score = float(a.get("points") or 0)
            team_b_score = float(b.get("points") or 0)
            team_a = roster_to_team.get(str(a["roster_id"]))
            team_b = roster_to_team.get(str(b["roster_id"]))
            if not team_a or not team_b:
                continue
            winner_id = None
            margin = None
            if team_a_score > team_b_score:
                winner_id = team_a.id
                margin = team_a_score - team_b_score
            elif team_b_score > team_a_score:
                winner_id = team_b.id
                margin = team_b_score - team_a_score

            db.add(
                LvMatchup(
                    season_id=lv_season.id,
                    week=week,
                    platform_matchup_id=mid,
                    is_playoff=is_playoff,
                    team_a_id=team_a.id,
                    team_b_id=team_b.id,
                    team_a_score=team_a_score,
                    team_b_score=team_b_score,
                    winner_team_id=winner_id,
                    margin=margin,
                )
            )
            matchup_count += 1

    # Playoff bracket matchups (optional)
    for bracket_name, bracket_rows in (
        ("winners", winners_bracket),
        ("losers", losers_bracket),
    ):
        if not bracket_rows:
            continue
        for entry in bracket_rows:
            t1 = roster_to_team.get(str(entry.get("t1") or ""))
            t2 = roster_to_team.get(str(entry.get("t2") or ""))
            if not t1 or not t2:
                continue
            w = entry.get("w")
            team_a_score = float(entry.get("p1") or 0) if "p1" in entry else None
            team_b_score = float(entry.get("p2") or 0) if "p2" in entry else None
            winner_id = None
            margin = None
            if w is not None:
                w_team = roster_to_team.get(str(w))
                if w_team:
                    winner_id = w_team.id
            if team_a_score is not None and team_b_score is not None:
                margin = abs(team_a_score - team_b_score)
            db.add(
                LvMatchup(
                    season_id=lv_season.id,
                    week=int(entry.get("r") or entry.get("p") or 0),
                    platform_matchup_id=str(
                        entry.get("m") or entry.get("matchup_id") or ""
                    ),
                    is_playoff=True,
                    playoff_round=entry.get("p"),
                    bracket=bracket_name,
                    team_a_id=t1.id,
                    team_b_id=t2.id,
                    team_a_score=team_a_score,
                    team_b_score=team_b_score,
                    winner_team_id=winner_id,
                    margin=margin,
                )
            )
            matchup_count += 1

    draft_pick_count = 0
    for draft in drafts or []:
        lv_draft = LvDraft(
            season_id=lv_season.id,
            platform_draft_id=str(draft.get("draft_id") or ""),
            draft_type=draft.get("type"),
            settings={
                **(draft.get("settings") or {}),
                **(
                    {"status": draft.get("status")}
                    if draft.get("status") is not None
                    else {}
                ),
            },
        )
        db.add(lv_draft)
        db.flush()
        for pick in draft.get("picks") or draft.get("draft_order") or []:
            if not isinstance(pick, dict):
                continue
            roster_id = str(pick.get("roster_id") or pick.get("picked_by") or "")
            db.add(
                LvDraftPick(
                    draft_id=lv_draft.id,
                    round=int(pick.get("round") or 0),
                    pick_no=int(pick.get("pick_no") or pick.get("pick") or 0),
                    draft_slot=pick.get("draft_slot"),
                    player_id=str(pick.get("player_id") or "") or None,
                    team_id=(
                        roster_to_team.get(roster_id).id
                        if roster_id in roster_to_team
                        else None
                    ),
                )
            )
            draft_pick_count += 1

    tx_count = 0
    for tx in transactions or []:
        tx_id = str(tx.get("transaction_id") or tx.get("id") or tx_count)
        db.add(
            LvTransaction(
                season_id=lv_season.id,
                week=tx.get("leg") or tx.get("week"),
                platform_transaction_id=tx_id,
                type=str(tx.get("type") or "unknown"),
                status=tx.get("status"),
                created_at_ts=tx.get("created"),
                payload=tx,
                team_ids=tx.get("roster_ids"),
            )
        )
        tx_count += 1

    champ_team, runner_team = _bracket_champ_runner_up(winners_bracket, roster_to_team)
    if champ_team:
        lv_season.champion_manager_id = champ_team.manager_id
    if runner_team:
        lv_season.runner_up_manager_id = runner_team.manager_id

    # Last place = lowest rank
    ranked = sorted(
        roster_to_team.values(),
        key=lambda t: (t.final_rank is None, -(t.final_rank or 0)),
        reverse=True,
    )
    if ranked:
        lv_season.last_place_manager_id = ranked[-1].manager_id

    if site.first_season is None or season < site.first_season:
        site.first_season = season
    if site.latest_season is None or season > site.latest_season:
        site.latest_season = season
    site.updated_at = datetime.utcnow()

    db.flush()

    return {
        "season": season,
        "team_count": len(roster_to_team),
        "manager_count": manager_count,
        "matchup_count": matchup_count,
        "draft_pick_count": draft_pick_count,
        "transaction_count": tx_count,
        "platform_league_id": platform_league_id,
    }


def _espn_record_overall(team: dict[str, Any]) -> dict[str, Any]:
    for rec in team.get("record", {}).get("overall", []):
        if rec.get("type") == "total":
            return rec
    overall = team.get("record", {}).get("overall")
    if isinstance(overall, dict):
        return overall
    return {}


def normalize_espn_season(
    db: Session,
    *,
    lineage: LvLeagueLineage,
    site: LvSite,
    season: int,
    platform_league_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize ESPN season payload (teams, members, schedule, draftDetail, transactions).
    """
    _delete_season(db, lineage.id, season)

    season_league_ids = dict(lineage.season_league_ids or {})
    season_league_ids[str(season)] = platform_league_id
    lineage.season_league_ids = season_league_ids
    lineage.last_synced = datetime.utcnow()

    settings = payload.get("settings") or {}
    schedule_settings = settings.get("scheduleSettings") or {}
    reg_weeks = schedule_settings.get("matchupPeriodCount")

    teams_raw = payload.get("teams") or []
    members = {
        m["id"]: m for m in (payload.get("members") or []) if m.get("id") is not None
    }

    lv_season = LvSeason(
        lineage_id=lineage.id,
        season=season,
        platform_league_id=platform_league_id,
        team_count=len(teams_raw),
        playoff_teams=(settings.get("scheduleSettings") or {}).get("playoffTeamCount"),
        regular_season_weeks=reg_weeks,
        scoring_settings=settings.get("scoringSettings"),
        roster_positions=settings.get("rosterSettings"),
    )
    db.add(lv_season)
    db.flush()

    espn_team_to_lv: dict[int, LvTeam] = {}
    manager_count = 0

    for team in teams_raw:
        team_id = team.get("id")
        primary_owner = str(team.get("primaryOwner") or "")
        member = members.get(team.get("primaryOwner"), {})
        display = (
            team.get("name")
            or member.get("displayName")
            or member.get("firstName", "") + " " + member.get("lastName", "")
        ).strip()
        mgr = _get_or_create_manager(
            db,
            lineage_id=lineage.id,
            platform_user_id=primary_owner or str(team_id),
            display_name=display,
            season=season,
        )
        manager_count += 1

        rec = _espn_record_overall(team)
        logo = team.get("logo") or team.get("logoType") or ""
        avatar = logo if isinstance(logo, str) and logo.startswith("http") else None

        lv_team = LvTeam(
            season_id=lv_season.id,
            manager_id=mgr.id,
            platform_roster_id=str(team_id),
            team_name=team.get("name") or display,
            avatar_url=avatar,
            wins=int(rec.get("wins", 0) or 0),
            losses=int(rec.get("losses", 0) or 0),
            ties=int(rec.get("ties", 0) or 0),
            points_for=float(rec.get("pointsFor", 0) or 0),
            points_against=float(rec.get("pointsAgainst", 0) or 0),
            final_rank=team.get("rank"),
            playoff_seed=team.get("playoffSeed"),
        )
        db.add(lv_team)
        db.flush()
        espn_team_to_lv[int(team_id)] = lv_team

    matchup_count = 0
    for period in payload.get("schedule") or []:
        week = period.get("matchupPeriodId") or period.get("week") or 0
        home = period.get("home") or {}
        away = period.get("away") or {}
        home_id = home.get("teamId")
        away_id = away.get("teamId")
        if home_id is None or away_id is None:
            continue
        team_a = espn_team_to_lv.get(int(home_id))
        team_b = espn_team_to_lv.get(int(away_id))
        if not team_a or not team_b:
            continue
        team_a_score = float(home.get("totalPoints") or 0)
        team_b_score = float(away.get("totalPoints") or 0)
        winner_id = None
        margin = None
        if team_a_score > team_b_score:
            winner_id = team_a.id
            margin = team_a_score - team_b_score
        elif team_b_score > team_a_score:
            winner_id = team_b.id
            margin = team_b_score - team_a_score

        is_playoff = bool(reg_weeks and week > reg_weeks)
        db.add(
            LvMatchup(
                season_id=lv_season.id,
                week=int(week),
                platform_matchup_id=str(period.get("id") or ""),
                is_playoff=is_playoff,
                team_a_id=team_a.id,
                team_b_id=team_b.id,
                team_a_score=team_a_score,
                team_b_score=team_b_score,
                winner_team_id=winner_id,
                margin=margin,
            )
        )
        matchup_count += 1

    draft_pick_count = 0
    draft_detail = payload.get("draftDetail") or {}
    if draft_detail:
        lv_draft = LvDraft(
            season_id=lv_season.id,
            platform_draft_id=str(draft_detail.get("draftId") or ""),
            draft_type="snake",
            settings={
                **draft_detail,
                "status": ("complete" if draft_detail.get("drafted") else "pending"),
            },
        )
        db.add(lv_draft)
        db.flush()
        for pick in draft_detail.get("picks") or []:
            team_id = pick.get("teamId")
            lv_team = espn_team_to_lv.get(int(team_id)) if team_id is not None else None
            player_id = pick.get("playerId")
            db.add(
                LvDraftPick(
                    draft_id=lv_draft.id,
                    round=int(pick.get("roundId") or 0),
                    pick_no=int(pick.get("roundPickNumber") or 0),
                    draft_slot=pick.get("overallPickNumber"),
                    player_id=str(player_id) if player_id is not None else None,
                    team_id=lv_team.id if lv_team else None,
                )
            )
            draft_pick_count += 1

    tx_count = 0
    for tx in payload.get("transactions") or []:
        tx_id = str(tx.get("id") or tx_count)
        team_ids = [
            str(m.get("teamId")) for m in tx.get("items", []) if m.get("teamId")
        ]
        db.add(
            LvTransaction(
                season_id=lv_season.id,
                week=tx.get("scoringPeriodId"),
                platform_transaction_id=tx_id,
                type=str(tx.get("type") or "unknown"),
                status=tx.get("status"),
                created_at_ts=tx.get("date") or tx.get("processedDate"),
                payload=tx,
                team_ids=team_ids,
            )
        )
        tx_count += 1

    if site.first_season is None or season < site.first_season:
        site.first_season = season
    if site.latest_season is None or season > site.latest_season:
        site.latest_season = season
    site.updated_at = datetime.utcnow()
    db.flush()

    return {
        "season": season,
        "team_count": len(espn_team_to_lv),
        "manager_count": manager_count,
        "matchup_count": matchup_count,
        "draft_pick_count": draft_pick_count,
        "transaction_count": tx_count,
        "platform_league_id": platform_league_id,
    }
