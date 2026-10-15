/**
 * Hero artwork. Hannah is JJ's final static artwork
 * (public/branding/hannah-hero-static.webp, 480 x 600, transparent), shown at
 * its native aspect ratio and deliberately without animation. Sun, pathway,
 * hills and signpost are plain SVG. Decorative, so hidden from assistive
 * technology.
 */

const MASCOT_WIDTH = 480;
const MASCOT_HEIGHT = 600;
const MASCOT_SCALE = 0.6;
// In the 480 x 600 artwork, Hannah's boots end at y = 593 and her cape at x = 427.
const MASCOT_FEET_Y = 593;
const MASCOT_RIGHT_X = 427;

/**
 * Hannah standing on the ground (y = 402) in the 560 x 520 artwork space, her
 * cape ending at x = 328, clear of the signpost's leftmost tip (x = 340).
 */
function MascotSlot() {
  const width = MASCOT_WIDTH * MASCOT_SCALE;
  const height = MASCOT_HEIGHT * MASCOT_SCALE;
  return (
    <image
      height={height}
      href="/branding/hannah-hero-static.webp"
      preserveAspectRatio="xMidYMax meet"
      width={width}
      x={328 - MASCOT_RIGHT_X * MASCOT_SCALE}
      y={402 - MASCOT_FEET_Y * MASCOT_SCALE}
    />
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
        <circle cx="470" cy="76" r="78" fill="url(#hero-sun-glow)" />
        <circle cx="470" cy="76" r="24" fill="#ffd401" />
        <g stroke="#ffd401" strokeLinecap="round" strokeWidth="5">
          <path d="M470 28v-12M470 124v12M422 76h-12M518 76h12M436 42l-9-9M504 110l9 9M504 42l9-9M436 110l-9 9" />
        </g>
      </g>

      {/* Clouds and hills */}
      <ellipse cx="116" cy="410" fill="#5888e8" fillOpacity="0.14" rx="86" ry="46" />
      <ellipse cx="86" cy="430" fill="#5888e8" fillOpacity="0.12" rx="70" ry="38" />
      <ellipse cx="300" cy="468" fill="url(#hero-hill)" rx="255" ry="56" />
      <ellipse cx="250" cy="486" fill="url(#hero-hill)" rx="210" ry="40" />

      {/* Pathway, drawn once on entry */}
      <path
        className="path-draw"
        d="M20 360C130 330 160 230 300 205S400 150 445 125"
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
      <MascotSlot />
    </svg>
  );
}
