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
      <polygon fill="#0e1e3d" fillOpacity="0.08" points={points} transform="translate(3 5)" />
      <polygon fill="#fffdf4" points={points} stroke="#0e1e3d" strokeLinejoin="round" strokeWidth="3" />
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

/**
 * The haloes, warm light and hills deliberately reach past the 560 x 520 artwork's
 * sides and bottom (the SVG renders with overflow visible); the hero card clips
 * them at its edges. Nothing rises above the artwork's top edge, because on narrow
 * screens the hero copy sits right above it, and the hills fade out on the left so
 * they never sit behind the copy on wide screens.
 */
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
        <radialGradient id="hero-warm-light">
          <stop offset="0%" stopColor="#fff1bd" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#fff1bd" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="hero-hill-far" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#5888e8" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#5888e8" stopOpacity="0.03" />
        </linearGradient>
        <linearGradient id="hero-hill-near" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#5888e8" stopOpacity="0.13" />
          <stop offset="100%" stopColor="#5888e8" stopOpacity="0.04" />
        </linearGradient>
        <linearGradient id="hero-hills-fade-gradient" gradientUnits="userSpaceOnUse" x1="-70" x2="80" y1="0" y2="0">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="1" />
        </linearGradient>
        <mask height="1600" id="hero-hills-fade" maskUnits="userSpaceOnUse" width="2000" x="-600" y="-400">
          <rect fill="url(#hero-hills-fade-gradient)" height="1600" width="2000" x="-600" y="-400" />
        </mask>
      </defs>

      {/* Atmosphere: soft haloes behind Hannah and the signpost, warm light from the sun's side */}
      <circle cx="300" cy="262" fill="#5888e8" fillOpacity="0.05" r="262" />
      <circle cx="300" cy="262" fill="#5888e8" fillOpacity="0.06" r="190" />
      <circle cx="540" cy="200" fill="url(#hero-warm-light)" r="200" />

      {/* Sun */}
      <g className="sun-in">
        <circle cx="470" cy="76" r="78" fill="url(#hero-sun-glow)" />
        <circle cx="470" cy="76" r="24" fill="#ffd401" />
        <g stroke="#ffd401" strokeLinecap="round" strokeWidth="5">
          <path d="M470 28v-12M470 124v12M422 76h-12M518 76h12M436 42l-9-9M504 110l9 9M504 42l9-9M436 110l-9 9" />
        </g>
      </g>

      {/* Rolling hills, layered for depth, running off the card's right and bottom edges */}
      <g mask="url(#hero-hills-fade)">
        <ellipse cx="530" cy="472" fill="url(#hero-hill-far)" rx="340" ry="94" />
        <ellipse cx="250" cy="502" fill="url(#hero-hill-near)" rx="390" ry="98" />
        <ellipse cx="20" cy="566" fill="url(#hero-hill-near)" rx="360" ry="112" />
        <path
          d="M-20 482C100 498 220 494 340 474"
          fill="none"
          stroke="#3d6bc4"
          strokeLinecap="round"
          strokeOpacity="0.3"
          strokeWidth="2.5"
        />
      </g>

      {/* The ground Hannah stands on */}
      <ellipse cx="240" cy="404" fill="#5888e8" fillOpacity="0.08" rx="140" ry="18" />
      <ellipse cx="240" cy="408" fill="none" rx="112" ry="12" stroke="#5888e8" strokeOpacity="0.35" strokeWidth="2" />

      {/* Pathway with a soft glow, drawn once on entry */}
      <path
        className="path-draw"
        d="M20 360C130 330 160 230 300 205S400 150 445 125"
        fill="none"
        pathLength="1"
        stroke="#5888e8"
        strokeLinecap="round"
        strokeOpacity="0.14"
        strokeWidth="12"
      />
      <path
        className="path-draw"
        d="M20 360C130 330 160 230 300 205S400 150 445 125"
        fill="none"
        pathLength="1"
        stroke="#5888e8"
        strokeLinecap="round"
        strokeWidth="3.5"
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
