/**
 * Closing artwork: the end of the opening scene's journey. The same soft hills
 * and blue pathway lead to a low, setting sun, and Hannah walks toward it, seen
 * from behind and smaller, farther away than in the hero. No signpost. Static
 * and decorative, so hidden from assistive technology.
 *
 * Hannah is a separate image so she can be replaced without touching the scene.
 * public/branding/hannah-rear-provisional.svg is a PROVISIONAL stand-in drawn to
 * fit the composition, not approved artwork: replace CLOSING_MASCOT with JJ's
 * final rear-view Hannah (any size; `feetY` is where her soles are in the file).
 *
 * The 800 x 360 scene keeps its story in the bottom-right corner, so the
 * container can crop it (preserveAspectRatio "xMaxYMax slice") to a wide strip
 * on phones or a narrow column beside the CTA text.
 */

const CLOSING_MASCOT = {
  href: "/branding/hannah-rear-provisional.svg",
  width: 120,
  height: 200,
  feetY: 190,
};
const MASCOT_HEIGHT = 76;
/** Where Hannah stands: on the pathway, a little short of the sun. */
const MASCOT_FEET = { x: 612, y: 268 };

function WalkingMascotSlot() {
  const scale = MASCOT_HEIGHT / CLOSING_MASCOT.height;
  const width = CLOSING_MASCOT.width * scale;
  return (
    <image
      height={MASCOT_HEIGHT}
      href={CLOSING_MASCOT.href}
      preserveAspectRatio="xMidYMax meet"
      width={width}
      x={MASCOT_FEET.x - width / 2}
      y={MASCOT_FEET.y - CLOSING_MASCOT.feetY * scale}
    />
  );
}

export function ClosingIllustration({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      focusable="false"
      preserveAspectRatio="xMaxYMax slice"
      viewBox="0 0 800 360"
    >
      <defs>
        <radialGradient id="closing-sun-glow">
          <stop offset="0%" stopColor="#ffd401" stopOpacity="0.5" />
          <stop offset="55%" stopColor="#ffd401" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#ffd401" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="closing-hill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#5888e8" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#5888e8" stopOpacity="0" />
        </linearGradient>
        {/* Everything above the far hill: the sun is drawn only there, so it sets behind the hill. */}
        <clipPath id="closing-sky">
          <path d="M0 0H800V262C750 248 712 256 650 256C560 256 470 236 380 262C300 284 200 290 120 318L0 340Z" />
        </clipPath>
      </defs>

      {/* Low sun with its halo */}
      <circle cx="700" cy="252" fill="#5888e8" fillOpacity="0.07" r="168" />
      <circle cx="700" cy="252" fill="#5888e8" fillOpacity="0.07" r="112" />
      <circle cx="700" cy="252" fill="url(#closing-sun-glow)" r="84" />
      <circle clipPath="url(#closing-sky)" cx="700" cy="258" fill="#ffd401" r="26" />

      {/* Hills */}
      <path
        d="M120 318C200 290 300 284 380 262C470 236 560 256 650 256C712 256 750 248 800 262V360H0V340Z"
        fill="#5888e8"
        fillOpacity="0.1"
      />
      <path d="M0 330C140 300 280 296 420 300C560 304 690 292 800 282V360H0Z" fill="url(#closing-hill)" />
      <ellipse cx="420" cy="346" fill="#3d6bc4" fillOpacity="0.06" rx="400" ry="22" />

      {/* Pathway, leading to the sun */}
      <path
        d="M16 334C110 318 170 350 260 330C350 310 420 312 500 296C560 284 600 272 640 264C664 259 680 257 690 256"
        fill="none"
        stroke="#5888e8"
        strokeLinecap="round"
        strokeWidth="3"
      />
      <path
        d="M14 350C110 340 160 362 262 348"
        fill="none"
        stroke="#3d6bc4"
        strokeLinecap="round"
        strokeOpacity="0.5"
        strokeWidth="2.5"
      />

      {/* Grass tufts */}
      <g fill="none" stroke="#3d6bc4" strokeLinecap="round" strokeWidth="3">
        <path d="M470 312c-4-12-2-22 5-29M479 314c2-10 7-18 14-22" />
        <path d="M752 288c-3-12 0-21 6-28M762 290c3-9 8-16 15-19" />
      </g>

      {/* Hannah's shadow stays with the scene; Hannah is the replaceable slot. */}
      <ellipse cx={MASCOT_FEET.x + 3} cy={MASCOT_FEET.y} fill="#0e1e3d" fillOpacity="0.1" rx="16" ry="3" />
      <WalkingMascotSlot />
    </svg>
  );
}
