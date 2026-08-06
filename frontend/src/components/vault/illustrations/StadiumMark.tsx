type IllustrationProps = {
  className?: string;
};

export function StadiumMark({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 64 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Stadium arch */}
      <path
        d="M8 40V28c0-12 10-20 24-20s24 8 24 20v12"
        stroke="#0f3d2e"
        strokeWidth="2.5"
        strokeLinecap="round"
      />

      {/* Floodlight poles */}
      <path d="M16 40V20M48 40V20" stroke="#0c1210" strokeWidth="2" strokeLinecap="round" />

      {/* Light fixtures */}
      <rect x="10" y="14" width="12" height="6" rx="1" fill="#c6a035" stroke="#0c1210" strokeWidth="1.5" />
      <rect x="42" y="14" width="12" height="6" rx="1" fill="#c6a035" stroke="#0c1210" strokeWidth="1.5" />

      {/* Light beams */}
      <path
        d="M16 20 28 40M48 20 36 40"
        stroke="#c6a035"
        strokeWidth="1"
        strokeOpacity="0.35"
        strokeLinecap="round"
      />

      {/* Ground line */}
      <path d="M4 40h56" stroke="#0c1210" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
