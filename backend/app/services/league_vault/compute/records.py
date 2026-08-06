"""Record book computation (pilot set — no roster-spot records)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.league_vault_models import (
    LvManager,
    LvMatchup,
    LvRecord,
    LvSeason,
    LvTeam,
)


def _clear_records(db: Session, lineage_id: int) -> None:
    db.query(LvRecord).filter_by(lineage_id=lineage_id).delete()
    db.flush()


def _add(
    db: Session,
    *,
    lineage_id: int,
    record_key: str,
    value: float,
    scope: str = "all_time",
    season: Optional[int] = None,
    manager_id: Optional[int] = None,
    team_id: Optional[int] = None,
    context: Optional[dict] = None,
) -> LvRecord:
    row = LvRecord(
        lineage_id=lineage_id,
        record_key=record_key,
        scope=scope,
        season=season,
        manager_id=manager_id,
        team_id=team_id,
        value=float(value),
        context=context or {},
        computed_at=datetime.utcnow(),
    )
    db.add(row)
    return row


def compute_records_for_lineage(db: Session, lineage_id: int) -> list[LvRecord]:
    _clear_records(db, lineage_id)
    seasons = db.query(LvSeason).filter_by(lineage_id=lineage_id).all()
    if not seasons:
        db.commit()
        return []

    season_ids = [s.id for s in seasons]
    season_by_id = {s.id: s for s in seasons}
    teams = db.query(LvTeam).filter(LvTeam.season_id.in_(season_ids)).all()
    team_by_id = {t.id: t for t in teams}
    matchups = (
        db.query(LvMatchup)
        .filter(LvMatchup.season_id.in_(season_ids))
        .order_by(LvMatchup.season_id, LvMatchup.week)
        .all()
    )

    # --- scoring extremes from matchups ---
    best_week: Optional[tuple[float, LvMatchup, int]] = None  # score, matchup, team_id
    worst_week: Optional[tuple[float, LvMatchup, int]] = None
    biggest_blowout: Optional[tuple[float, LvMatchup]] = None
    closest: Optional[tuple[float, LvMatchup]] = None
    most_in_loss: Optional[tuple[float, LvMatchup, int]] = None
    fewest_in_win: Optional[tuple[float, LvMatchup, int]] = None
    highest_combined: Optional[tuple[float, LvMatchup]] = None

    for m in matchups:
        if m.team_a_score is None or m.team_b_score is None:
            continue
        if not m.team_a_id or not m.team_b_id:
            continue
        sa, sb = float(m.team_a_score), float(m.team_b_score)
        for tid, sc in ((m.team_a_id, sa), (m.team_b_id, sb)):
            if best_week is None or sc > best_week[0]:
                best_week = (sc, m, tid)
            if worst_week is None or sc < worst_week[0]:
                worst_week = (sc, m, tid)
        margin = abs(sa - sb)
        combined = sa + sb
        if biggest_blowout is None or margin > biggest_blowout[0]:
            biggest_blowout = (margin, m)
        if margin > 0 and (closest is None or margin < closest[0]):
            closest = (margin, m)
        if highest_combined is None or combined > highest_combined[0]:
            highest_combined = (combined, m)

        # points in loss / win
        if sa > sb:
            # a wins
            if fewest_in_win is None or sa < fewest_in_win[0]:
                fewest_in_win = (sa, m, m.team_a_id)
            if most_in_loss is None or sb > most_in_loss[0]:
                most_in_loss = (sb, m, m.team_b_id)
        elif sb > sa:
            if fewest_in_win is None or sb < fewest_in_win[0]:
                fewest_in_win = (sb, m, m.team_b_id)
            if most_in_loss is None or sa > most_in_loss[0]:
                most_in_loss = (sa, m, m.team_a_id)

    def _ctx_matchup(m: LvMatchup, team_id: Optional[int] = None) -> dict:
        s = season_by_id[m.season_id]
        ta = team_by_id.get(m.team_a_id) if m.team_a_id else None
        tb = team_by_id.get(m.team_b_id) if m.team_b_id else None
        return {
            "season": s.season,
            "week": m.week,
            "team_a_score": m.team_a_score,
            "team_b_score": m.team_b_score,
            "team_id": team_id,
            "team_a_id": m.team_a_id,
            "team_b_id": m.team_b_id,
            "manager_a_id": ta.manager_id if ta else None,
            "manager_b_id": tb.manager_id if tb else None,
            "team_a_name": ta.team_name if ta else None,
            "team_b_name": tb.team_name if tb else None,
        }

    records: list[LvRecord] = []

    if best_week:
        sc, m, tid = best_week
        t = team_by_id[tid]
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="highest_single_week_score",
                value=sc,
                manager_id=t.manager_id,
                team_id=tid,
                context=_ctx_matchup(m, tid),
            )
        )
    if worst_week:
        sc, m, tid = worst_week
        t = team_by_id[tid]
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="lowest_single_week_score",
                value=sc,
                manager_id=t.manager_id,
                team_id=tid,
                context=_ctx_matchup(m, tid),
            )
        )
    if biggest_blowout:
        margin, m = biggest_blowout
        winner = m.winner_team_id
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="biggest_blowout",
                value=margin,
                manager_id=(
                    team_by_id[winner].manager_id if winner in team_by_id else None
                ),
                team_id=winner,
                context=_ctx_matchup(m, winner),
            )
        )
    if closest:
        margin, m = closest
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="closest_game",
                value=margin,
                context=_ctx_matchup(m),
            )
        )
    if most_in_loss:
        sc, m, tid = most_in_loss
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="most_points_in_loss",
                value=sc,
                manager_id=team_by_id[tid].manager_id,
                team_id=tid,
                context=_ctx_matchup(m, tid),
            )
        )
    if fewest_in_win:
        sc, m, tid = fewest_in_win
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="fewest_points_in_win",
                value=sc,
                manager_id=team_by_id[tid].manager_id,
                team_id=tid,
                context=_ctx_matchup(m, tid),
            )
        )
    if highest_combined:
        combined, m = highest_combined
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="highest_combined_score",
                value=combined,
                context=_ctx_matchup(m),
            )
        )

    # Highest scoring season (PF and PPG)
    if teams:
        best_pf = max(teams, key=lambda t: t.points_for or 0)
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="highest_scoring_season_pf",
                value=best_pf.points_for or 0,
                season=season_by_id[best_pf.season_id].season,
                manager_id=best_pf.manager_id,
                team_id=best_pf.id,
            )
        )

        def _ppg(t: LvTeam) -> float:
            g = (t.wins or 0) + (t.losses or 0) + (t.ties or 0)
            return (t.points_for or 0) / g if g else 0.0

        best_ppg = max(teams, key=_ppg)
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="highest_scoring_season_ppg",
                value=round(_ppg(best_ppg), 3),
                season=season_by_id[best_ppg.season_id].season,
                manager_id=best_ppg.manager_id,
                team_id=best_ppg.id,
            )
        )

        best_rec = max(teams, key=lambda t: ((t.wins or 0), t.points_for or 0))
        worst_rec = min(teams, key=lambda t: ((t.wins or 0), t.points_for or 0))
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="best_regular_season_record",
                value=float(best_rec.wins or 0),
                season=season_by_id[best_rec.season_id].season,
                manager_id=best_rec.manager_id,
                team_id=best_rec.id,
                context={
                    "wins": best_rec.wins,
                    "losses": best_rec.losses,
                    "ties": best_rec.ties,
                },
            )
        )
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="worst_regular_season_record",
                value=float(worst_rec.wins or 0),
                season=season_by_id[worst_rec.season_id].season,
                manager_id=worst_rec.manager_id,
                team_id=worst_rec.id,
                context={
                    "wins": worst_rec.wins,
                    "losses": worst_rec.losses,
                    "ties": worst_rec.ties,
                },
            )
        )

        # All-play / luck leaders (if computed)
        with_ap = [t for t in teams if t.all_play_wins is not None]
        if with_ap:
            best_ap = max(
                with_ap,
                key=lambda t: (t.all_play_wins or 0)
                / max(1, (t.all_play_wins or 0) + (t.all_play_losses or 0)),
            )
            luckiest = max(with_ap, key=lambda t: t.luck_differential or 0)
            unluckiest = min(with_ap, key=lambda t: t.luck_differential or 0)
            records.append(
                _add(
                    db,
                    lineage_id=lineage_id,
                    record_key="best_all_play_season",
                    value=float(best_ap.all_play_wins or 0),
                    season=season_by_id[best_ap.season_id].season,
                    manager_id=best_ap.manager_id,
                    team_id=best_ap.id,
                    context={
                        "all_play_wins": best_ap.all_play_wins,
                        "all_play_losses": best_ap.all_play_losses,
                    },
                )
            )
            records.append(
                _add(
                    db,
                    lineage_id=lineage_id,
                    record_key="luckiest_season",
                    value=float(luckiest.luck_differential or 0),
                    season=season_by_id[luckiest.season_id].season,
                    manager_id=luckiest.manager_id,
                    team_id=luckiest.id,
                )
            )
            records.append(
                _add(
                    db,
                    lineage_id=lineage_id,
                    record_key="unluckiest_season",
                    value=float(unluckiest.luck_differential or 0),
                    season=season_by_id[unluckiest.season_id].season,
                    manager_id=unluckiest.manager_id,
                    team_id=unluckiest.id,
                )
            )

    # Streaks (can span seasons chronologically per manager)
    streak_records = _compute_streaks(matchups, team_by_id, season_by_id)
    for key, value, manager_id, ctx in streak_records:
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key=key,
                value=value,
                manager_id=manager_id,
                context=ctx,
            )
        )

    # Titles / career
    managers = db.query(LvManager).filter_by(lineage_id=lineage_id).all()
    titles: dict[int, int] = defaultdict(int)
    for s in seasons:
        if s.champion_manager_id:
            titles[s.champion_manager_id] += 1
    if titles:
        champ_id, n = max(titles.items(), key=lambda x: x[1])
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="titles",
                value=float(n),
                manager_id=champ_id,
                context={"by_manager": {str(k): v for k, v in titles.items()}},
            )
        )
        # Also store per-manager title counts as career records
        for mid, n in titles.items():
            records.append(
                _add(
                    db,
                    lineage_id=lineage_id,
                    record_key="career_titles",
                    value=float(n),
                    scope="career",
                    manager_id=mid,
                )
            )

    career_wl: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    for t in teams:
        career_wl[t.manager_id][0] += t.wins or 0
        career_wl[t.manager_id][1] += t.losses or 0
        career_wl[t.manager_id][2] += t.ties or 0
    for mid, (w, l, ti) in career_wl.items():
        records.append(
            _add(
                db,
                lineage_id=lineage_id,
                record_key="career_wins",
                value=float(w),
                scope="career",
                manager_id=mid,
                context={"wins": w, "losses": l, "ties": ti},
            )
        )

    _ = managers
    db.commit()
    return (
        db.query(LvRecord)
        .filter_by(lineage_id=lineage_id)
        .order_by(LvRecord.record_key)
        .all()
    )


def _compute_streaks(matchups, team_by_id, season_by_id):
    """Return list of (key, value, manager_id, context) for longest W/L streaks."""
    # Chronological results per manager
    by_mgr: dict[int, list[bool]] = defaultdict(list)  # True = win
    for m in matchups:
        if m.winner_team_id is None or m.team_a_score is None or m.team_b_score is None:
            continue
        if m.team_a_score == m.team_b_score:
            continue
        for tid in (m.team_a_id, m.team_b_id):
            if not tid or tid not in team_by_id:
                continue
            mid = team_by_id[tid].manager_id
            by_mgr[mid].append(tid == m.winner_team_id)

    def longest(seq: list[bool], want: bool) -> int:
        best = cur = 0
        for x in seq:
            if x is want:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    out = []
    best_w = (0, None)
    best_l = (0, None)
    for mid, seq in by_mgr.items():
        w = longest(seq, True)
        l = longest(seq, False)
        if w > best_w[0]:
            best_w = (w, mid)
        if l > best_l[0]:
            best_l = (l, mid)
    if best_w[1] is not None:
        out.append(("longest_win_streak", float(best_w[0]), best_w[1], {}))
    if best_l[1] is not None:
        out.append(("longest_losing_streak", float(best_l[0]), best_l[1], {}))
    return out
