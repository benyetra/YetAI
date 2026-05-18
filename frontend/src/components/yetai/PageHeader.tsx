'use client';

import React from 'react';

export default function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'end', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
      <div>
        <h1 className="type-page-title">{title}</h1>
        {subtitle ? <p style={{ color: 'var(--text-3)', fontSize: 13, marginTop: 4 }}>{subtitle}</p> : null}
      </div>
      {actions ? <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>{actions}</div> : null}
    </div>
  );
}
