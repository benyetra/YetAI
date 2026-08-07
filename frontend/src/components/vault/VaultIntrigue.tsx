/**
 * Presentational intrigue surfaces for League Vault (server components).
 */

import Link from 'next/link';
import { vaultNameFitClass, vaultPath } from '../../lib/vault';
import type {
  DraftIntrigue,
  LuckCallout,
  ManagerEpithet,
  RivalryCard,
  SeasonBeat,
  ThrowbackMoment,
  TitleDrought,
  TitleStreak,
} from '../../lib/vault-intrigue';

export function RivalryCards({
  slug,
  cards,
}: {
  slug: string;
  cards: RivalryCard[];
}) {
  if (cards.length === 0) return null;
  return (
    <section className="vault-section vault-intrigue-rivalries" aria-labelledby="rivalry-heading">
      <div className="vault-section-heading">
        <h2 id="rivalry-heading">Rivalry desk</h2>
        <p className="vault-muted">The series the group chat already knows by heart.</p>
      </div>
      <div className="vault-intrigue-grid">
        {cards.map((card) => (
          <article
            key={`${card.kind}-${card.managerA.id}-${card.managerB.id}`}
            className="vault-intrigue-card"
          >
            <p className="vault-intrigue-kicker">{card.title}</p>
            <p className="vault-intrigue-headline">
              <Link
                href={vaultPath(slug, `/managers/${card.managerA.slug}`)}
                className={vaultNameFitClass(card.managerA.display_name)}
                title={card.managerA.display_name}
              >
                {card.managerA.display_name}
              </Link>
              <span className="vault-intrigue-record">{card.recordLabel}</span>
              <Link
                href={vaultPath(slug, `/managers/${card.managerB.slug}`)}
                className={vaultNameFitClass(card.managerB.display_name)}
                title={card.managerB.display_name}
              >
                {card.managerB.display_name}
              </Link>
            </p>
            <p className="vault-muted">{card.tease}</p>
            <Link href={vaultPath(slug, '/h2h')} className="vault-intrigue-link">
              Open H2H matrix
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}

export function ThrowbackBanner({
  slug,
  moment,
}: {
  slug: string;
  moment: ThrowbackMoment | null;
}) {
  if (!moment) return null;
  return (
    <section className="vault-section vault-throwback" aria-labelledby="throwback-heading">
      <div className="vault-throwback-inner">
        <div>
          <p className="vault-intrigue-kicker" id="throwback-heading">
            On this week
          </p>
          <h2 className="vault-throwback-title">{moment.tease}</h2>
          <p className="vault-throwback-matchup">
            <span className={vaultNameFitClass(moment.teamA)} title={moment.teamA}>
              {moment.teamA}
            </span>
            <span className="vault-throwback-score">{moment.scoreLabel}</span>
            <span className={vaultNameFitClass(moment.teamB)} title={moment.teamB}>
              {moment.teamB}
            </span>
          </p>
          <p className="vault-muted">
            {moment.season} · Week {moment.week}
            {moment.isPlayoff ? ' · Playoffs' : ''}
          </p>
        </div>
        <Link
          href={vaultPath(slug, `/seasons/${moment.season}`)}
          className="vault-intrigue-link"
        >
          Relive the season
        </Link>
      </div>
    </section>
  );
}

export function KarmaStrip({
  slug,
  callouts,
}: {
  slug: string;
  callouts: LuckCallout[];
}) {
  if (callouts.length === 0) return null;
  return (
    <section className="vault-section vault-karma" aria-labelledby="karma-heading">
      <div className="vault-section-heading">
        <h2 id="karma-heading">Luck &amp; karma</h2>
        <p className="vault-muted">All-play doesn’t lie — the schedule sometimes does.</p>
      </div>
      <div className="vault-intrigue-grid vault-intrigue-grid-2">
        {callouts.map((c) => (
          <article
            key={`${c.kind}-${c.manager.id}-${c.season}`}
            className={`vault-intrigue-card is-${c.kind}`}
          >
            <p className="vault-intrigue-kicker">
              {c.kind === 'lucky' ? 'Won on vibes' : 'Schedule victim'}
            </p>
            <p className="vault-intrigue-headline">
              <Link
                href={vaultPath(slug, `/managers/${c.manager.slug}`)}
                className={vaultNameFitClass(c.manager.display_name)}
                title={c.manager.display_name}
              >
                {c.manager.display_name}
              </Link>
              <span className="vault-intrigue-record vault-num">
                {c.value > 0 ? '+' : ''}
                {c.value.toFixed(2)}
              </span>
            </p>
            <p className="vault-muted">{c.tease}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function DroughtStreakStrip({
  slug,
  streaks,
  droughts,
}: {
  slug: string;
  streaks: TitleStreak[];
  droughts: TitleDrought[];
}) {
  if (streaks.length === 0 && droughts.length === 0) return null;
  return (
    <section className="vault-section vault-droughts" aria-labelledby="streak-heading">
      <div className="vault-section-heading">
        <h2 id="streak-heading">Crowns &amp; droughts</h2>
        <p className="vault-muted">Dynasty heat checks and the longest waits for a ring.</p>
      </div>
      <div className="vault-intrigue-grid vault-intrigue-grid-2">
        {streaks.slice(0, 2).map((s) => (
          <article
            key={`streak-${s.manager.id}-${s.seasons[0]}`}
            className="vault-intrigue-card is-streak"
          >
            <p className="vault-intrigue-kicker">{s.label}</p>
            <p className="vault-intrigue-headline">
              <Link
                href={vaultPath(slug, `/managers/${s.manager.slug}`)}
                className={vaultNameFitClass(s.manager.display_name)}
              >
                {s.manager.display_name}
              </Link>
            </p>
            <p className="vault-muted">{s.seasons.join(' · ')}</p>
          </article>
        ))}
        {droughts.slice(0, 2).map((d) => (
          <article key={`drought-${d.manager.id}`} className="vault-intrigue-card is-drought">
            <p className="vault-intrigue-kicker">Title drought</p>
            <p className="vault-intrigue-headline">
              <Link
                href={vaultPath(slug, `/managers/${d.manager.slug}`)}
                className={vaultNameFitClass(d.manager.display_name)}
              >
                {d.manager.display_name}
              </Link>
              <span className="vault-intrigue-record vault-num">{d.seasonsSince}</span>
            </p>
            <p className="vault-muted">{d.label}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function SeasonStoryBeats({ beats }: { beats: SeasonBeat[] }) {
  if (beats.length === 0) return null;
  return (
    <section className="vault-section vault-season-story" aria-labelledby="story-heading">
      <div className="vault-section-heading">
        <h2 id="story-heading">Season story</h2>
        <p className="vault-muted">The beats worth arguing about.</p>
      </div>
      <ol className="vault-story-beats">
        {beats.map((b) => (
          <li key={b.key}>
            <span className="vault-story-label">{b.label}</span>
            <span className="vault-story-detail">{b.detail}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function DraftIntriguePanel({ items }: { items: DraftIntrigue[] }) {
  if (items.length === 0) return null;
  return (
    <div className="vault-draft-intrigue" aria-label="Draft regret and glory">
      {items.map((item) => (
        <article
          key={`${item.kind}-${item.title}`}
          className={`vault-intrigue-card is-${item.kind}`}
        >
          <p className="vault-intrigue-kicker">
            {item.kind === 'regret' ? 'Regret' : item.kind === 'glory' ? 'Glory' : 'Draft note'}
          </p>
          <p className="vault-intrigue-headline">{item.title}</p>
          <p className="vault-muted">{item.detail}</p>
        </article>
      ))}
    </div>
  );
}

export function ManagerEpithetLine({
  epithet,
  luck,
}: {
  epithet: ManagerEpithet | null;
  luck?: LuckCallout | null;
}) {
  if (!epithet && !luck) return null;
  return (
    <div className="vault-epithet-block">
      {epithet ? (
        <p className="vault-epithet" title={epithet.reason}>
          “{epithet.epithet}”
        </p>
      ) : null}
      {luck ? (
        <p className={`vault-luck-chip is-${luck.kind}`}>
          {luck.kind === 'lucky' ? 'Karma darling' : 'Karma culprit'}
          {luck.season != null ? ` · ${luck.season}` : ''}
          {' · '}
          <span className="vault-num">
            {luck.value > 0 ? '+' : ''}
            {luck.value.toFixed(2)}
          </span>
        </p>
      ) : null}
    </div>
  );
}
