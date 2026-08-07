/**
 * League Vault “intrigue” — pure helpers for rivalry gossip, season stories,
 * luck callouts, draft regret/glory, droughts/streaks, throwbacks, and epithets.
 */

import {
  draftOverallPick,
  formatDraftPlayer,
  isDraftPending,
  managerById,
  type VaultManager,
  type VaultSeason,
  type VaultSnapshot,
} from './vault';

export type RivalryKind = 'blood_feud' | 'lopsided' | 'dead_even';

export type RivalryCard = {
  kind: RivalryKind;
  title: string;
  tease: string;
  recordLabel: string;
  managerA: VaultManager;
  managerB: VaultManager;
  games: number;
};

export type SeasonBeat = {
  key: string;
  label: string;
  detail: string;
};

export type LuckCallout = {
  kind: 'lucky' | 'unlucky';
  manager: VaultManager;
  season: number | null;
  value: number;
  tease: string;
};

export type DraftIntrigue = {
  kind: 'regret' | 'glory' | 'note';
  title: string;
  detail: string;
  manager?: VaultManager;
};

export type TitleStreak = {
  manager: VaultManager;
  seasons: number[];
  length: number;
  label: string;
};

export type TitleDrought = {
  manager: VaultManager;
  seasonsSince: number;
  lastTitleSeason: number | null;
  label: string;
};

export type ThrowbackMoment = {
  season: number;
  week: number;
  teamA: string;
  teamB: string;
  scoreLabel: string;
  tease: string;
  isPlayoff: boolean;
};

export type ShareSeasonCardModel = {
  season: number;
  leagueName: string;
  championName: string;
  championAsterisk?: boolean;
  championMarker?: string;
  championNote?: string | null;
  championLink?: string | null;
  championLinkLabel?: string | null;
  runnerUpName: string;
  lastPlaceName: string;
  lastPlaceLabel: string;
  recordLine: string;
  href: string;
};

function h2hGames(rec: { wins: number; losses: number; ties: number }): number {
  return rec.wins + rec.losses + rec.ties;
}

function h2hLabel(rec: { wins: number; losses: number; ties: number }): string {
  return `${rec.wins}–${rec.losses}${rec.ties ? `–${rec.ties}` : ''}`;
}

/** Top rivalry gossip cards for the home page. */
export function buildRivalryCards(snap: VaultSnapshot, limit = 3): RivalryCard[] {
  type Pair = {
    a: VaultManager;
    b: VaultManager;
    wins: number;
    losses: number;
    ties: number;
    games: number;
    diff: number;
  };
  const pairs: Pair[] = [];
  const seen = new Set<string>();

  for (const a of snap.managers) {
    const row = snap.h2h[String(a.id)];
    if (!row) continue;
    for (const b of snap.managers) {
      if (a.id >= b.id) continue;
      const rec = row[String(b.id)];
      if (!rec) continue;
      const games = h2hGames(rec);
      if (games < 3) continue;
      const key = `${a.id}:${b.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      pairs.push({
        a,
        b,
        wins: rec.wins,
        losses: rec.losses,
        ties: rec.ties,
        games,
        diff: Math.abs(rec.wins - rec.losses),
      });
    }
  }

  if (pairs.length === 0) return [];

  const blood = [...pairs]
    .filter((p) => p.diff <= 1 && p.games >= 4)
    .sort((x, y) => y.games - x.games || x.diff - y.diff)[0];

  const lopsided = [...pairs]
    .filter((p) => p.diff >= 3)
    .sort((x, y) => y.diff - x.diff || y.games - x.games)[0];

  const even = [...pairs]
    .filter((p) => p.diff === 0)
    .sort((x, y) => y.games - x.games)[0];

  const cards: RivalryCard[] = [];
  const used = new Set<string>();

  const push = (kind: RivalryKind, pair: Pair | undefined, title: string, tease: string) => {
    if (!pair || cards.length >= limit) return;
    const id = `${pair.a.id}-${pair.b.id}`;
    if (used.has(id)) return;
    used.add(id);
    const leader = pair.wins >= pair.losses ? pair.a : pair.b;
    const trailer = pair.wins >= pair.losses ? pair.b : pair.a;
    const fromLeader = snap.h2h[String(leader.id)]?.[String(trailer.id)];
    cards.push({
      kind,
      title,
      tease,
      recordLabel: fromLeader ? h2hLabel(fromLeader) : h2hLabel(pair),
      managerA: leader,
      managerB: trailer,
      games: pair.games,
    });
  };

  push(
    'blood_feud',
    blood,
    'Blood feud',
    blood
      ? `${blood.games} meetings and still basically tied — this one never cools off.`
      : '',
  );
  push(
    'lopsided',
    lopsided,
    'Most lopsided',
    lopsided
      ? `A ${lopsided.diff}-win gap. Someone brought a knife to a dynasty fight.`
      : '',
  );
  push(
    'dead_even',
    even,
    'Dead even',
    even ? `${even.games} games, dead square. Coin-flip rivals.` : '',
  );

  // Fill remaining slots with most-played rivalries
  if (cards.length < limit) {
    const leftovers = [...pairs]
      .sort((x, y) => y.games - x.games)
      .filter((p) => !used.has(`${p.a.id}-${p.b.id}`));
    for (const pair of leftovers) {
      push(
        'blood_feud',
        pair,
        'Heavyweight series',
        `${pair.games} meetings in the archive.`,
      );
      if (cards.length >= limit) break;
    }
  }

  return cards;
}

function teamName(season: VaultSeason, id: number | null | undefined): string {
  if (id == null) return '—';
  return season.teams.find((t) => t.id === id)?.team_name ?? '—';
}

/** Narrative beats for a finished (or in-progress) season. */
export function buildSeasonBeats(
  snap: VaultSnapshot,
  season: VaultSeason,
  limit = 5,
): SeasonBeat[] {
  const beats: SeasonBeat[] = [];
  const scored = season.matchups.filter(
    (m) => m.team_a_score != null && m.team_b_score != null,
  );

  if (scored.length) {
    const closest = [...scored].sort(
      (a, b) => (a.margin ?? 999) - (b.margin ?? 999),
    )[0];
    if (closest?.margin != null) {
      beats.push({
        key: 'closest',
        label: 'Closest game',
        detail: `${teamName(season, closest.team_a_id)} vs ${teamName(season, closest.team_b_id)} · Wk ${closest.week} · margin ${closest.margin.toFixed(2)}`,
      });
    }

    const combined = [...scored].sort((a, b) => {
      const ca = (a.team_a_score ?? 0) + (a.team_b_score ?? 0);
      const cb = (b.team_a_score ?? 0) + (b.team_b_score ?? 0);
      return cb - ca;
    })[0];
    if (combined) {
      const total = (combined.team_a_score ?? 0) + (combined.team_b_score ?? 0);
      beats.push({
        key: 'combined',
        label: 'Highest combined',
        detail: `${teamName(season, combined.team_a_id)} vs ${teamName(season, combined.team_b_id)} · Wk ${combined.week} · ${total.toFixed(1)} pts`,
      });
    }

    const blowout = [...scored].sort(
      (a, b) => (b.margin ?? -1) - (a.margin ?? -1),
    )[0];
    if (blowout?.margin != null && blowout.margin >= 20) {
      beats.push({
        key: 'blowout',
        label: 'Biggest blowout',
        detail: `${teamName(season, blowout.team_a_id)} vs ${teamName(season, blowout.team_b_id)} · Wk ${blowout.week} · +${blowout.margin.toFixed(1)}`,
      });
    }
  }

  const withLuck = season.teams.filter((t) => t.luck_differential != null);
  if (withLuck.length) {
    const luckiest = [...withLuck].sort(
      (a, b) => (b.luck_differential ?? 0) - (a.luck_differential ?? 0),
    )[0];
    const mgr = managerById(snap, luckiest.manager_id);
    if (mgr && (luckiest.luck_differential ?? 0) > 0.5) {
      const champNote =
        season.champion?.id === mgr.id ? ' — and they still won the title' : '';
      beats.push({
        key: 'luck',
        label: 'Luckiest manager',
        detail: `${mgr.display_name} · luck ${(luckiest.luck_differential ?? 0).toFixed(2)}${champNote}`,
      });
    }
  }

  const withAllPlay = season.teams.filter((t) => t.all_play_wins != null);
  if (withAllPlay.length && season.champion) {
    const bestAllPlay = [...withAllPlay].sort(
      (a, b) => (b.all_play_wins ?? 0) - (a.all_play_wins ?? 0),
    )[0];
    if (bestAllPlay.manager_id !== season.champion.id) {
      const mgr = managerById(snap, bestAllPlay.manager_id);
      const playoffCut = season.playoff_teams ?? Math.ceil(season.teams.length / 2);
      const missed =
        bestAllPlay.final_rank != null && bestAllPlay.final_rank > playoffCut;
      if (mgr) {
        beats.push({
          key: 'almost',
          label: missed ? 'Best team, missed it' : 'Best all-play, no ring',
          detail: `${mgr.display_name} led all-play (${bestAllPlay.all_play_wins}-${bestAllPlay.all_play_losses}) but ${
            missed ? 'missed the dance' : `finished #${bestAllPlay.final_rank ?? '—'}`
          }.`,
        });
      }
    }
  }

  return beats.slice(0, limit);
}

/** League-wide luck / karma callouts from season teams + records. */
export function buildLuckCallouts(snap: VaultSnapshot, limit = 2): LuckCallout[] {
  const out: LuckCallout[] = [];

  type Cand = {
    managerId: number;
    season: number;
    value: number;
  };
  const cands: Cand[] = [];
  for (const season of snap.seasons) {
    for (const team of season.teams) {
      if (team.luck_differential == null) continue;
      cands.push({
        managerId: team.manager_id,
        season: season.season,
        value: team.luck_differential,
      });
    }
  }
  if (cands.length === 0) {
    for (const key of ['luckiest_season', 'unluckiest_season'] as const) {
      const rec = snap.records.find((r) => r.record_key === key);
      if (!rec?.manager_id) continue;
      const mgr = managerById(snap, rec.manager_id);
      if (!mgr) continue;
      out.push({
        kind: key === 'luckiest_season' ? 'lucky' : 'unlucky',
        manager: mgr,
        season: rec.season,
        value: rec.value,
        tease:
          key === 'luckiest_season'
            ? 'Record book: luckiest season on file.'
            : 'Record book: unluckiest season on file.',
      });
    }
    return out.slice(0, limit);
  }

  const lucky = [...cands].sort((a, b) => b.value - a.value)[0];
  const unlucky = [...cands].sort((a, b) => a.value - b.value)[0];
  const luckyMgr = managerById(snap, lucky.managerId);
  const unluckyMgr = managerById(snap, unlucky.managerId);
  if (luckyMgr && lucky.value > 0) {
    out.push({
      kind: 'lucky',
      manager: luckyMgr,
      season: lucky.season,
      value: lucky.value,
      tease: `Won ${lucky.value.toFixed(2)} more games than all-play expected in ${lucky.season}. Pure vibes.`,
    });
  }
  if (unluckyMgr && unlucky.value < 0) {
    out.push({
      kind: 'unlucky',
      manager: unluckyMgr,
      season: unlucky.season,
      value: unlucky.value,
      tease: `${unlucky.value.toFixed(2)} vs all-play in ${unlucky.season}. The schedule was personal.`,
    });
  }
  return out.slice(0, limit);
}

/** Draft regret / glory from pick order vs final standings. */
export function buildDraftIntrigue(
  snap: VaultSnapshot,
  season: VaultSeason,
): DraftIntrigue[] {
  const draft = season.drafts[0];
  if (!draft || isDraftPending(draft) || draft.picks.length === 0) return [];

  const teamById = new Map(season.teams.map((t) => [t.id, t]));
  const round1 = draft.picks
    .filter((p) => p.round === 1)
    .map((p) => ({
      pick: p,
      overall: draftOverallPick(p),
      team: p.team_id != null ? teamById.get(p.team_id) : undefined,
    }))
    .filter((x) => x.team)
    .sort((a, b) => a.overall - b.overall);

  if (round1.length === 0) return [];

  const out: DraftIntrigue[] = [];
  const first = round1[0];
  const last = round1[round1.length - 1];
  const firstMgr = first.team ? managerById(snap, first.team.manager_id) : undefined;
  const lastMgr = last.team ? managerById(snap, last.team.manager_id) : undefined;
  const teamCount = season.teams.length || round1.length;

  if (firstMgr && first.team?.final_rank != null) {
    const rank = first.team.final_rank;
    const player = formatDraftPlayer(first.pick);
    if (rank >= Math.ceil(teamCount * 0.6)) {
      out.push({
        kind: 'regret',
        title: 'First-overall regret',
        detail: `${firstMgr.display_name} took ${player} at 1.01 and finished #${rank}.`,
        manager: firstMgr,
      });
    } else if (season.champion?.id === firstMgr.id) {
      out.push({
        kind: 'glory',
        title: 'First overall, first place',
        detail: `${firstMgr.display_name} opened with ${player} and brought home the title.`,
        manager: firstMgr,
      });
    } else {
      out.push({
        kind: 'note',
        title: 'The 1.01',
        detail: `${firstMgr.display_name} · ${player} · finished #${rank}.`,
        manager: firstMgr,
      });
    }
  }

  if (
    lastMgr &&
    season.champion?.id === lastMgr.id &&
    lastMgr.id !== firstMgr?.id
  ) {
    out.push({
      kind: 'glory',
      title: 'From the back of round 1',
      detail: `${lastMgr.display_name} picked ${last.overall}th in round 1 and still won the league.`,
      manager: lastMgr,
    });
  } else if (
    lastMgr &&
    last.team?.final_rank === 1 &&
    lastMgr.id !== firstMgr?.id
  ) {
    out.push({
      kind: 'glory',
      title: 'Last pick, first place',
      detail: `${lastMgr.display_name} turned draft slot ${last.overall} into a title.`,
      manager: lastMgr,
    });
  }

  if (season.champion) {
    const champPick = round1.find(
      (r) => r.team?.manager_id === season.champion?.id,
    );
    if (champPick && !out.some((x) => x.kind === 'glory' && x.manager?.id === season.champion?.id)) {
      out.push({
        kind: 'note',
        title: 'Champion’s first pick',
        detail: `${season.champion.display_name} · overall ${champPick.overall} · ${formatDraftPlayer(champPick.pick)}`,
        manager: season.champion,
      });
    }
  }

  return out.slice(0, 3);
}

/** Consecutive title streaks (length >= 2). */
export function buildTitleStreaks(snap: VaultSnapshot): TitleStreak[] {
  const finished = snap.dynasty_timeline.filter((c) => c.champion);
  const streaks: TitleStreak[] = [];
  let i = 0;
  while (i < finished.length) {
    const start = finished[i];
    if (!start.champion) {
      i += 1;
      continue;
    }
    let j = i + 1;
    while (
      j < finished.length &&
      finished[j].champion?.id === start.champion.id
    ) {
      j += 1;
    }
    const length = j - i;
    if (length >= 2 && start.champion) {
      const seasons = finished.slice(i, j).map((c) => c.season);
      streaks.push({
        manager: start.champion,
        seasons,
        length,
        label:
          length >= 3
            ? `${length}-peat`
            : 'Back-to-back',
      });
    }
    i = j;
  }
  return streaks.sort((a, b) => b.length - a.length);
}

/** Active droughts: seasons since last title (managers with history). */
export function buildTitleDroughts(snap: VaultSnapshot, limit = 4): TitleDrought[] {
  const latest = snap.latest_season ?? snap.seasons.at(-1)?.season;
  if (latest == null) return [];

  const lastTitle = new Map<number, number>();
  for (const cell of snap.dynasty_timeline) {
    if (cell.champion) lastTitle.set(cell.champion.id, cell.season);
  }

  const droughts: TitleDrought[] = [];
  for (const m of snap.managers) {
    if (!m.is_active && (m.last_season ?? 0) < latest - 1) continue;
    const last = lastTitle.get(m.id) ?? null;
    const seasonsSince = last == null
      ? (m.first_season != null ? latest - m.first_season + 1 : 0)
      : latest - last;
    if (seasonsSince < 2) continue;
    // Skip brand-new managers with no title yet under 3 seasons
    const careerSeasons =
      m.first_season != null && m.last_season != null
        ? m.last_season - m.first_season + 1
        : 0;
    if (last == null && careerSeasons < 3) continue;
    droughts.push({
      manager: m,
      seasonsSince,
      lastTitleSeason: last,
      label:
        last == null
          ? `${seasonsSince}-season title drought`
          : `${seasonsSince} seasons since ${last}`,
    });
  }

  return droughts
    .sort((a, b) => b.seasonsSince - a.seasonsSince)
    .slice(0, limit);
}

/** Note for a dynasty timeline cell (streak / current drought context). */
export function dynastyCellNote(
  snap: VaultSnapshot,
  season: number,
  championId: number | null | undefined,
): string {
  if (championId == null) return 'In progress';
  const streaks = buildTitleStreaks(snap);
  const hit = streaks.find((s) => s.seasons.includes(season));
  if (hit) {
    const idx = hit.seasons.indexOf(season);
    if (idx === hit.seasons.length - 1) return hit.label;
    if (idx === 0 && hit.length === 2) return 'Title #1 of 2';
    return `Year ${idx + 1} of ${hit.length}`;
  }
  const latestChamp = [...snap.dynasty_timeline]
    .reverse()
    .find((c) => c.champion)?.season;
  if (season === latestChamp) return 'Current crown';
  return 'Champion';
}

/**
 * Rotating throwback: seed by calendar day so the home page changes daily,
 * preferring notable margins from the matching fantasy week number.
 */
export function buildThrowbackMoment(
  snap: VaultSnapshot,
  asOf: Date = new Date(),
): ThrowbackMoment | null {
  const dayOfYear = Math.floor(
    (Date.UTC(asOf.getFullYear(), asOf.getMonth(), asOf.getDate()) -
      Date.UTC(asOf.getFullYear(), 0, 0)) /
      86400000,
  );
  const targetWeek = (dayOfYear % 17) + 1;

  type Cand = {
    season: number;
    week: number;
    teamA: string;
    teamB: string;
    scoreA: number;
    scoreB: number;
    margin: number;
    combined: number;
    isPlayoff: boolean;
  };
  const cands: Cand[] = [];
  for (const season of snap.seasons) {
    for (const m of season.matchups) {
      if (m.team_a_score == null || m.team_b_score == null) continue;
      if (m.week !== targetWeek && Math.abs(m.week - targetWeek) > 1) continue;
      cands.push({
        season: season.season,
        week: m.week,
        teamA: teamName(season, m.team_a_id),
        teamB: teamName(season, m.team_b_id),
        scoreA: m.team_a_score,
        scoreB: m.team_b_score,
        margin: m.margin ?? Math.abs(m.team_a_score - m.team_b_score),
        combined: m.team_a_score + m.team_b_score,
        isPlayoff: Boolean(m.is_playoff),
      });
    }
  }

  // Fallback: any notable historical matchup
  if (cands.length === 0) {
    for (const season of snap.seasons) {
      for (const m of season.matchups) {
        if (m.team_a_score == null || m.team_b_score == null) continue;
        cands.push({
          season: season.season,
          week: m.week,
          teamA: teamName(season, m.team_a_id),
          teamB: teamName(season, m.team_b_id),
          scoreA: m.team_a_score,
          scoreB: m.team_b_score,
          margin: m.margin ?? Math.abs(m.team_a_score - m.team_b_score),
          combined: m.team_a_score + m.team_b_score,
          isPlayoff: Boolean(m.is_playoff),
        });
      }
    }
  }
  if (cands.length === 0) return null;

  const notable = [...cands].sort((a, b) => {
    // Prefer nail-biters, then shootouts
    const score = (c: Cand) =>
      (c.margin <= 3 ? 1000 - c.margin * 10 : 0) + c.combined * 0.01;
    return score(b) - score(a);
  });
  const pick = notable[dayOfYear % notable.length];
  const nailBiter = pick.margin <= 5;
  return {
    season: pick.season,
    week: pick.week,
    teamA: pick.teamA,
    teamB: pick.teamB,
    scoreLabel: `${pick.scoreA.toFixed(1)} – ${pick.scoreB.toFixed(1)}`,
    tease: nailBiter
      ? `This week in ${pick.season}: a ${pick.margin.toFixed(2)}-pt thriller.`
      : `This week in ${pick.season}: ${pick.combined.toFixed(0)} combined points.`,
    isPlayoff: pick.isPlayoff,
  };
}

export type ManagerEpithet = {
  epithet: string;
  reason: string;
};

/** Witty one-liner under a manager name — rule-based, not mean by default. */
export function managerEpithet(
  snap: VaultSnapshot,
  managerId: number,
): ManagerEpithet | null {
  const manager = managerById(snap, managerId);
  if (!manager) return null;
  const career = snap.manager_careers[String(managerId)];
  const titles = career?.titles ?? 0;
  const seasonsPlayed = snap.seasons.filter((s) =>
    s.teams.some((t) => t.manager_id === managerId),
  ).length;

  const luckVals = snap.seasons.flatMap((s) =>
    s.teams
      .filter((t) => t.manager_id === managerId && t.luck_differential != null)
      .map((t) => t.luck_differential as number),
  );
  const avgLuck =
    luckVals.length > 0
      ? luckVals.reduce((a, b) => a + b, 0) / luckVals.length
      : null;

  const lastPlaces = snap.seasons.filter((s) => s.last_place?.id === managerId).length;
  const pf = career?.points_for ?? 0;
  const wins = career?.wins ?? 0;
  const games = wins + (career?.losses ?? 0) + (career?.ties ?? 0);
  const winPct = games > 0 ? wins / games : 0;

  // Priority order — first match wins
  if (titles >= 3) {
    return { epithet: 'Dynasty Architect', reason: `${titles} titles in the archive` };
  }
  const streaks = buildTitleStreaks(snap).filter((s) => s.manager.id === managerId);
  if (streaks.some((s) => s.length >= 2)) {
    return { epithet: 'Repeat Offender', reason: 'Stacked titles back-to-back' };
  }
  if (titles >= 1 && avgLuck != null && avgLuck >= 0.8) {
    return { epithet: 'Vibes Champion', reason: 'Titles with friendly luck differentials' };
  }
  if (titles >= 1 && seasonsPlayed >= 3 && winPct >= 0.58) {
    return { epithet: 'Playoff Assassin', reason: 'Wins when it counts' };
  }
  if (titles === 0 && seasonsPlayed >= 2 && pf > 0) {
    const pfLeaders = [...snap.managers].sort(
      (a, b) =>
        (snap.manager_careers[String(b.id)]?.points_for ?? 0) -
        (snap.manager_careers[String(a.id)]?.points_for ?? 0),
    );
    if (pfLeaders[0]?.id === managerId) {
      return { epithet: 'PF Merchant', reason: 'Leads the vault in points for — still hunting a ring' };
    }
    if (seasonsPlayed >= 3) {
      return { epithet: 'The Nearly Man', reason: `${seasonsPlayed} seasons, zero titles` };
    }
  }
  if (avgLuck != null && avgLuck <= -0.9 && seasonsPlayed >= 2) {
    return { epithet: 'Schedule Victim', reason: 'Career luck well below all-play' };
  }
  if (lastPlaces >= 2) {
    return {
      epithet: `${snap.last_place_label} Specialist`,
      reason: `${lastPlaces} trips to the cellar`,
    };
  }
  if (titles === 1) {
    return { epithet: 'One-Time Wonder', reason: 'A single crown in the case' };
  }
  if (seasonsPlayed >= 2 && winPct >= 0.55) {
    return { epithet: 'Perennial Contender', reason: 'Keeps showing up in the win column' };
  }
  return null;
}

export function buildShareSeasonCard(
  snap: VaultSnapshot,
  season: VaultSeason,
  slug: string,
): ShareSeasonCardModel | null {
  if (!season.champion) return null;
  const champTeam = season.teams.find((t) => t.manager_id === season.champion?.id);
  const recordLine = champTeam
    ? `${champTeam.wins}-${champTeam.losses}${champTeam.ties ? `-${champTeam.ties}` : ''} · ${(champTeam.points_for ?? 0).toFixed(0)} PF`
    : `${season.season} champion`;
  return {
    season: season.season,
    leagueName: snap.display_name,
    championName: season.champion.display_name,
    championAsterisk: Boolean(season.champion_asterisk),
    championMarker: season.champion_marker || '*',
    championNote: season.champion_note || null,
    championLink: season.champion_link || null,
    championLinkLabel: season.champion_link_label || null,
    runnerUpName: season.runner_up?.display_name ?? '—',
    lastPlaceName: season.last_place?.display_name ?? '—',
    lastPlaceLabel: snap.last_place_label,
    recordLine,
    href: `/vault/${slug}/seasons/${season.season}`,
  };
}

/** Career luck badge for manager profile. */
export function managerLuckBadge(
  snap: VaultSnapshot,
  managerId: number,
): LuckCallout | null {
  const callouts = buildLuckCallouts(snap, 10);
  return callouts.find((c) => c.manager.id === managerId) ?? null;
}
