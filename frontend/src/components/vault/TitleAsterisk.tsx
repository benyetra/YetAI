import type { ReactNode } from 'react';
import type { VaultSeason, VaultSnapshot } from '../../lib/vault';

/** Marker shown next to an annotated championship name. */
export function titleMarker(season: Pick<VaultSeason, 'champion_asterisk' | 'champion_marker'> | null | undefined): string {
  if (!season?.champion_asterisk) return '';
  return season.champion_marker || '*';
}

export function ChampionNameWithAsterisk({
  name,
  season,
  className,
  children,
}: {
  name: string;
  season?: Pick<VaultSeason, 'champion_asterisk' | 'champion_marker' | 'champion_note'> | null;
  className?: string;
  children?: ReactNode;
}) {
  const marker = titleMarker(season);
  const note = season?.champion_note || undefined;
  return (
    <span className={className} title={note || name}>
      {children ?? name}
      {marker ? (
        <sup className="vault-title-asterisk" aria-label={note || 'Title annotated'}>
          {marker}
        </sup>
      ) : null}
    </span>
  );
}

export function TitleFootnotes({ snap }: { snap: VaultSnapshot }) {
  const notes = snap.title_footnotes?.filter((n) => n.note) ?? [];
  if (notes.length === 0) {
    // Fall back to season-embedded notes if footnotes array missing
    const fromSeasons = snap.seasons
      .filter((s) => s.champion_asterisk && s.champion_note)
      .map((s) => ({
        season: s.season,
        marker: s.champion_marker || '*',
        note: s.champion_note as string,
      }));
    if (fromSeasons.length === 0) return null;
    return <FootnoteList notes={fromSeasons} />;
  }
  return <FootnoteList notes={notes} />;
}

function FootnoteList({
  notes,
}: {
  notes: Array<{ season: number; marker: string; note: string }>;
}) {
  return (
    <aside className="vault-title-footnotes" aria-label="Title footnotes">
      {notes.map((n) => (
        <p key={n.season} className="vault-muted">
          <sup className="vault-title-asterisk">{n.marker}</sup>
          {n.season}: {n.note}
        </p>
      ))}
    </aside>
  );
}
