type IllustrationProps = {
  className?: string;
};

export function TrophyCup({ className }: IllustrationProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 120 140"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M38 28h44v8c0 18-6 32-22 36-16-4-22-18-22-36v-8Z"
        fill="#c6a035"
        stroke="#0c1210"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M38 28H28c-2 0-4 2-4 6 0 10 6 18 14 22M82 28h10c2 0 4 2 4 6 0 10-6 18-14 22"
        stroke="#0c1210"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M48 72h24v6c0 4-4 8-12 8s-12-4-12-8v-6Z"
        fill="#c6a035"
        stroke="#0c1210"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <rect
        x="34"
        y="86"
        width="52"
        height="10"
        rx="1"
        fill="#c6a035"
        stroke="#0c1210"
        strokeWidth="2"
      />
      <rect
        x="28"
        y="98"
        width="64"
        height="12"
        rx="2"
        fill="#a88628"
        stroke="#0c1210"
        strokeWidth="2"
      />
      <path
        d="M60 20v10"
        stroke="#0c1210"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <ellipse cx="60" cy="18" rx="6" ry="3" fill="#e8d48b" stroke="#0c1210" strokeWidth="1.5" />
    </svg>
  );
}
