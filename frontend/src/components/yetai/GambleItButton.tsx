'use client';

import React from 'react';
import { Zap } from 'lucide-react';
import { gamblyUrlForLegs, isGamblyEnabled } from '@/lib/gambly';

/**
 * Opens Gambly with the given legs pre-submitted; Gambly replies with a one-click
 * betslip deep-linked to the user's sportsbook. Renders nothing when there are no
 * legs or `NEXT_PUBLIC_GAMBLY_ENABLED` is off.
 */
export default function GambleItButton({
  legs,
  parlay,
  label = 'Gamble It',
  className = 'btn btn-sm btn-gambly',
  block,
  iconOnly,
  style,
}: {
  legs: Array<string | null | undefined>;
  parlay?: boolean;
  label?: string;
  className?: string;
  block?: boolean;
  iconOnly?: boolean;
  style?: React.CSSProperties;
}) {
  if (!isGamblyEnabled()) return null;
  const href = gamblyUrlForLegs(legs.filter((l): l is string => !!l), { parlay });
  if (!href) return null;

  const title = 'Build a one-click betslip on Gambly';
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`${className}${block ? ' btn-block' : ''}`}
      style={{ justifyContent: 'center', ...style }}
      title={title}
      aria-label={iconOnly ? title : undefined}
      onClick={(e) => e.stopPropagation()}
    >
      <Zap size={13} aria-hidden />
      {iconOnly ? null : <span>{label}</span>}
    </a>
  );
}
