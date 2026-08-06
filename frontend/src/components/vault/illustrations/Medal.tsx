type MedalProps = {
  className?: string;
  rank?: 1 | 2 | 3;
};

const RANK_FILL: Record<1 | 2 | 3, string> = {
  1: '#c6a035',
  2: '#a8a9ad',
  3: '#cd7f32',
};

const RANK_STROKE: Record<1 | 2 | 3, string> = {
  1: '#a88628',
  2: '#8a8b8f',
  3: '#a86628',
};

export function Medal({ className, rank = 1 }: MedalProps) {
  const fill = RANK_FILL[rank];
  const stroke = RANK_STROKE[rank];

  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 80 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Ribbon */}
      <path d="M28 4 40 28 52 4 48 32 32 32Z" fill="#147a5f" stroke="#0c1210" strokeWidth="1.5" strokeLinejoin="round" />

      {/* Medal circle */}
      <circle cx="40" cy="58" r="22" fill={fill} stroke="#0c1210" strokeWidth="2" />
      <circle cx="40" cy="58" r="16" fill="none" stroke={stroke} strokeWidth="1.5" />
      <text
        x="40"
        y="64"
        textAnchor="middle"
        fill="#0c1210"
        fontSize="16"
        fontWeight="700"
        fontFamily="system-ui, sans-serif"
      >
        {rank}
      </text>
    </svg>
  );
}
