type IllustrationProps = {
  className?: string;
};

export function Podium({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 200 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* 2nd place — left */}
      <rect
        x="12"
        y="52"
        width="48"
        height="56"
        fill="#eef3ef"
        stroke="#0c1210"
        strokeWidth="2"
      />
      <text
        x="36"
        y="78"
        textAnchor="middle"
        fill="#5c6b63"
        fontSize="18"
        fontWeight="700"
        fontFamily="system-ui, sans-serif"
      >
        2
      </text>

      {/* 1st place — center, tallest */}
      <rect
        x="68"
        y="24"
        width="64"
        height="84"
        fill="#eef3ef"
        stroke="#c6a035"
        strokeWidth="3"
      />
      <rect x="68" y="24" width="64" height="6" fill="#c6a035" />
      <text
        x="100"
        y="62"
        textAnchor="middle"
        fill="#c6a035"
        fontSize="22"
        fontWeight="700"
        fontFamily="system-ui, sans-serif"
      >
        1
      </text>

      {/* 3rd place — right */}
      <rect
        x="140"
        y="68"
        width="48"
        height="40"
        fill="#eef3ef"
        stroke="#0c1210"
        strokeWidth="2"
      />
      <text
        x="164"
        y="94"
        textAnchor="middle"
        fill="#5c6b63"
        fontSize="16"
        fontWeight="700"
        fontFamily="system-ui, sans-serif"
      >
        3
      </text>

      {/* Base platform */}
      <rect
        x="8"
        y="108"
        width="184"
        height="8"
        rx="1"
        fill="#0f3d2e"
        stroke="#0c1210"
        strokeWidth="1.5"
      />
    </svg>
  );
}
