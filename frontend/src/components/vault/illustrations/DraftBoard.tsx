import type { IllustrationProps } from './types';

/** Draft board / pick card mark. */
export function DraftBoard({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 88 96"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect
        x="10"
        y="8"
        width="68"
        height="80"
        rx="6"
        fill="#0f3d2e"
        stroke="#0c1210"
        strokeWidth="2"
      />
      <rect
        x="18"
        y="18"
        width="52"
        height="14"
        rx="2"
        fill="#c6a035"
        stroke="#0c1210"
        strokeWidth="1.5"
      />
      <text
        x="44"
        y="29"
        textAnchor="middle"
        fill="#0c1210"
        fontSize="10"
        fontWeight="700"
        fontFamily="system-ui, sans-serif"
      >
        1.01
      </text>
      {[0, 1, 2, 3].map((i) => (
        <g key={i}>
          <rect
            x="18"
            y={40 + i * 10}
            width="10"
            height="6"
            rx="1"
            fill="#c6a035"
            fillOpacity={i === 0 ? 1 : 0.55}
          />
          <path
            d={`M34 ${43 + i * 10}h28`}
            stroke="#eef3ef"
            strokeWidth="2"
            strokeLinecap="round"
            strokeOpacity={i === 0 ? 0.95 : 0.45}
          />
        </g>
      ))}
    </svg>
  );
}
