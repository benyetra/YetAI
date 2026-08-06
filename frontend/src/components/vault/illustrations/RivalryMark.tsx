import type { IllustrationProps } from './types';

/** Crossed rivalry arrows for head-to-head. */
export function RivalryMark({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 96 96"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle cx="48" cy="48" r="36" fill="#0f3d2e" stroke="#0c1210" strokeWidth="2" />
      <path
        d="M28 68 68 28"
        stroke="#c6a035"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M28 28 68 68"
        stroke="#eef3ef"
        strokeWidth="3"
        strokeLinecap="round"
        strokeOpacity="0.9"
      />
      <path
        d="M60 24h12v12M24 60v12h12M36 24H24v12M72 60v12H60"
        stroke="#c6a035"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
