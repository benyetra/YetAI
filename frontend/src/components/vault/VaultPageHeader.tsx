import type { ReactNode } from 'react';
import { VaultHelp } from './VaultHelp';

type Props = {
  kicker?: ReactNode;
  title: string;
  blurb?: ReactNode;
  help?: string;
  illustration: ReactNode;
};

/** Illustrated destination header shared by vault section pages. */
export function VaultPageHeader({ kicker, title, blurb, help, illustration }: Props) {
  return (
    <section className="vault-section vault-page-header">
      <div className="vault-page-header-illust" aria-hidden="true">
        {illustration}
      </div>
      <div className="vault-page-header-copy">
        {kicker ? <p className="vault-hero-kicker">{kicker}</p> : null}
        <div className="vault-page-header-title-row">
          <h1 className="vault-display">{title}</h1>
          {help ? <VaultHelp text={help} label={`About ${title}`} /> : null}
        </div>
        {blurb ? <p className="vault-muted">{blurb}</p> : null}
      </div>
    </section>
  );
}
