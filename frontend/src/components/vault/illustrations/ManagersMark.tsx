import type { IllustrationProps } from './types';

/** Crest-style mark for the managers roster. */
export function ManagersMark({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 96 96"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M48 8 84 22v22c0 22-14 38-36 44C26 82 12 66 12 44V22L48 8Z"
        fill="#0f3d2e"
        stroke="#0c1210"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="48" cy="38" r="12" fill="#eef3ef" stroke="#c6a035" strokeWidth="2" />
      <path
        d="M28 68c4-12 14-18 20-18s16 6 20 18"
        stroke="#eef3ef"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path d="M48 18v6M40 22h16" stroke="#c6a035" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
