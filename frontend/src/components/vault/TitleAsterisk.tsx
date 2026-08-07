import type { ReactNode } from 'react';
import type { VaultSeason, VaultSnapshot } from '../../lib/vault';

type TitleNote = {
  season: number;
  marker: string;
  note: string;
  link?: string | null;
  link_label?: string | null;
};

/** Marker shown next to an annotated championship name. */
export function titleMarker(
  season: Pick<VaultSeason, 'champion_asterisk' | 'champion_marker'> | null | undefined,
): string {
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
  season?: Pick<
    VaultSeason,
    'champion_asterisk' | 'champion_marker' | 'champion_note'
  > | null;
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

function notesFromSnapshot(snap: VaultSnapshot): TitleNote[] {
  const notes = snap.title_footnotes?.filter((n) => n.note) ?? [];
  if (notes.length > 0) {
    return notes.map((n) => ({
      season: n.season,
      marker: n.marker || '*',
      note: n.note,
      link: n.link,
      link_label: n.link_label,
    }));
  }
  return snap.seasons
    .filter((s) => s.champion_asterisk && s.champion_note)
    .map((s) => ({
      season: s.season,
      marker: s.champion_marker || '*',
      note: s.champion_note as string,
      link: s.champion_link,
      link_label: s.champion_link_label,
    }));
}

export function TitleFootnotes({ snap }: { snap: VaultSnapshot }) {
  const notes = notesFromSnapshot(snap);
  if (notes.length === 0) return null;
  return <FootnoteList notes={notes} />;
}

function FootnoteList({ notes }: { notes: TitleNote[] }) {
  return (
    <aside className="vault-title-footnotes" aria-label="Title footnotes">
      {notes.map((n) => (
        <p key={n.season} className="vault-muted">
          <sup className="vault-title-asterisk">{n.marker}</sup>
          {n.season}: {n.note}
          {n.link ? (
            <>
              {' '}
              <a
                className="vault-title-footnote-link"
                href={n.link}
                target="_blank"
                rel="noopener noreferrer"
              >
                {n.link_label || 'Watch'}
              </a>
            </>
          ) : null}
        </p>
      ))}
    </aside>
  );
}
