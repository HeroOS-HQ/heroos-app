/**
 * Hero artwork. TEMPORARY: sun, pathway, hills and signpost are plain SVG, and
 * the mascot slot holds a neutral "H" badge, not a character. When JJ's
 * original mascot arrives, replace <MascotSlot /> (or this whole component);
 * the hero layout around it does not change. Decorative, so hidden from
 * assistive technology.
 */

/** Badge standing on the path: about 120 x 170, origin at bottom centre. */
function MascotSlot() {
  return (
    <g className="float-slow">
      <path
        d="M-60 -150Q-60 -170 -40 -170H40Q60 -170 60 -150V-70C60 -30 30 -8 0 0C-30 -8 -60 -30 -60 -70Z"
        fill="#0e1e3d"
      />
      <path
        d="M-46 -150Q-46 -158 -38 -158H38Q46 -158 46 -150V-72C46 -42 24 -22 0 -14C-24 -22 -46 -42 -46 -72Z"
        fill="none"
        stroke="#5888e8"
        strokeOpacity="0.55"
        strokeWidth="2"
      />
      <text
        fill="#ffd401"
        fontFamily="inherit"
        fontSize="84"
        fontWeight="800"
        textAnchor="middle"
        x="0"
        y="-62"
      >
        H
      </text>
    </g>
  );
}

function SignBoard({ label, y, flip = false }: { label: string; y: number; flip?: boolean }) {
  const points = flip
    ? `-20,${y + 20} 0,${y} 150,${y} 150,${y + 40} 0,${y + 40}`
    : `0,${y} 150,${y} 170,${y + 20} 150,${y + 40} 0,${y + 40}`;
  return (
    <g>
      <polygon fill="#ffffff" points={points} stroke="#0e1e3d" strokeLinejoin="round" strokeWidth="3" />
      <text
        fill="#0e1e3d"
        fontFamily="inherit"
        fontSize="12"
        fontWeight="800"
        letterSpacing="0.3"
        textAnchor="middle"
        x={flip ? 76 : 76}
        y={y + 25}
      >
        {label}
      </text>
    </g>
  );
}

export function HeroIllustration({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      focusable="false"
      viewBox="0 0 560 520"
    >
      <defs>
        <radialGradient id="hero-sun-glow">
          <stop offset="0%" stopColor="#ffd401" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#ffd401" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="hero-hill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#5888e8" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#5888e8" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Sun */}
      <g className="sun-in">
        <circle cx="130" cy="82" r="78" fill="url(#hero-sun-glow)" />
        <circle cx="130" cy="82" r="24" fill="#ffd401" />
        <g stroke="#ffd401" strokeLinecap="round" strokeWidth="5">
          <path d="M130 34v-12M130 130v12M82 82H70M178 82h12M96 48l-9-9M164 116l9 9M164 48l9-9M96 116l-9 9" />
        </g>
      </g>

      {/* Clouds and hills */}
      <ellipse cx="110" cy="392" fill="#5888e8" fillOpacity="0.14" rx="86" ry="46" />
      <ellipse cx="76" cy="414" fill="#5888e8" fillOpacity="0.12" rx="70" ry="38" />
      <ellipse cx="300" cy="468" fill="url(#hero-hill)" rx="255" ry="56" />
      <ellipse cx="250" cy="486" fill="url(#hero-hill)" rx="210" ry="40" />

      {/* Pathway, drawn once on entry */}
      <path
        className="path-draw"
        d="M20 330C130 300 150 190 290 170S470 110 548 60"
        fill="none"
        pathLength="1"
        stroke="#5888e8"
        strokeLinecap="round"
        strokeWidth="3"
      />
      <path
        className="path-draw"
        d="M30 452c80 22 160 20 240 8"
        fill="none"
        pathLength="1"
        stroke="#3d6bc4"
        strokeLinecap="round"
        strokeOpacity="0.5"
        strokeWidth="2.5"
      />

      {/* Signpost */}
      <g transform="translate(350 180)">
        <rect fill="#0e1e3d" height="250" rx="4" width="10" x="70" y="0" />
        <g transform="translate(0 20)">
          <SignBoard label="PEOPLE" y={0} />
        </g>
        <g transform="translate(10 0)">
          <SignBoard flip label="GUIDANCE" y={64} />
        </g>
        <g transform="translate(0 20)">
          <SignBoard label="BETTER OUTCOMES" y={100} />
        </g>
      </g>

      {/* Grass tufts */}
      <g fill="none" stroke="#3d6bc4" strokeLinecap="round" strokeWidth="3">
        <path d="M316 440c-4-14-2-26 6-34M326 442c2-12 8-22 16-26" />
        <path d="M498 430c-2-16 2-28 10-38M510 432c4-12 10-20 20-24" />
      </g>

      {/* Mascot slot */}
      <g transform="translate(200 372)">
        <ellipse cx="0" cy="8" fill="#0e1e3d" fillOpacity="0.12" rx="58" ry="9" />
        <MascotSlot />
      </g>
    </svg>
  );
}
