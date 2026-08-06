import type { IllustrationProps } from './types';

/** Open ledger for the record book. */
export function RecordBook({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 100 84"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M50 12c-10-6-22-8-34-8v60c12 0 24 2 34 8 10-6 22-8 34-8V4c-12 0-24 2-34 8Z"
        fill="#0f3d2e"
        stroke="#0c1210"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M50 12v60" stroke="#c6a035" strokeWidth="2" strokeLinecap="round" />
      <path
        d="M22 24h20M22 34h18M22 44h16M62 24h20M62 34h18M62 44h16"
        stroke="#eef3ef"
        strokeWidth="2"
        strokeLinecap="round"
        strokeOpacity="0.85"
      />
      <circle cx="72" cy="56" r="8" fill="#c6a035" stroke="#0c1210" strokeWidth="1.5" />
      <path d="M69 56h6M72 53v6" stroke="#0c1210" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
