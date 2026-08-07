'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { ShareSeasonCardModel } from '../../lib/vault-intrigue';

export function ShareSeasonCard({ card }: { card: ShareSeasonCardModel }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(t);
  }, [copied]);

  const onCopy = async () => {
    try {
      const url = new URL(card.href, window.location.origin).toString();
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <aside className="vault-share-card" aria-label={`${card.season} season share card`}>
      <div className="vault-share-card-face">
        <p className="vault-intrigue-kicker">{card.leagueName}</p>
        <p className="vault-share-year">{card.season}</p>
        <p className="vault-share-champ vault-display">{card.championName}</p>
        <p className="vault-muted vault-share-record">{card.recordLine}</p>
        <dl className="vault-share-meta">
          <div>
            <dt>Runner-up</dt>
            <dd>{card.runnerUpName}</dd>
          </div>
          <div>
            <dt>{card.lastPlaceLabel}</dt>
            <dd>{card.lastPlaceName}</dd>
          </div>
        </dl>
      </div>
      <div className="vault-share-actions">
        <Link href={card.href} className="vault-intrigue-link">
          View season
        </Link>
        <button type="button" className="vault-share-copy" onClick={onCopy}>
          {copied ? 'Link copied' : 'Copy link'}
        </button>
      </div>
    </aside>
  );
}
