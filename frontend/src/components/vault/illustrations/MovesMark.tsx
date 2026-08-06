import type { IllustrationProps } from './types';

/** Swap arrows for waivers, trades, and roster moves. */
export function MovesMark({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 96 80"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect
        x="8"
        y="10"
        width="80"
        height="60"
        rx="8"
        fill="#0f3d2e"
        stroke="#0c1210"
        strokeWidth="2"
      />
      <path
        d="M28 34h28m0 0-8-8m8 8-8 8"
        stroke="#c6a035"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M68 50H40m0 0 8-8m-8 8 8 8"
        stroke="#eef3ef"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="22" cy="28" r="3" fill="#c6a035" />
      <circle cx="74" cy="56" r="3" fill="#eef3ef" />
    </svg>
  );
}
