/**
 * Closing artwork: the end of the opening scene's journey. The same soft hills
 * and blue pathway lead to a low, setting sun, and Hannah walks toward it, seen
 * from behind and farther away than in the hero. No signpost. Decorative, so
 * hidden from assistive technology; only scene accents move (clouds, glow, a
 * light along the path), never Hannah, and not at all with reduced motion.
 *
 * Hannah is JJ's approved back-view artwork (public/branding/hannah-walking-back.webp:
 * an exact, proportional 512 x 768 lossless WebP of the approved 1024 x 1536 PNG),
 * a separate image so she can be swapped without touching the scene. `feetX` and
 * `feetY` are where her planted boot meets the ground in that file.
 *
 * The 800 x 360 scene keeps its story in the bottom-right corner, so the
 * container can crop it (preserveAspectRatio "xMaxYMax slice") to a wide strip
 * on phones or a narrow column beside the CTA text.
 */

const CLOSING_MASCOT = {
  href: "/branding/hannah-walking-back.webp",
  width: 512,
  height: 768,
  feetX: 305,
  feetY: 735,
};
const MASCOT_HEIGHT = 141;
/** Where Hannah's planted boot meets the pathway, a little short of the sun. */
const MASCOT_FEET = { x: 630, y: 283 };

function WalkingMascotSlot() {
  const scale = MASCOT_HEIGHT / CLOSING_MASCOT.height;
  return (
    <image
      height={MASCOT_HEIGHT}
      href={CLOSING_MASCOT.href}
      preserveAspectRatio="xMidYMax meet"
      width={CLOSING_MASCOT.width * scale}
      x={MASCOT_FEET.x - CLOSING_MASCOT.feetX * scale}
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
          <stop offset="0%" stopColor="#ffd401" stopOpacity="0.55" />
          <stop offset="55%" stopColor="#ffd401" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#ffd401" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="closing-horizon-glow">
          <stop offset="0%" stopColor="#ffc95a" stopOpacity="0.6" />
          <stop offset="60%" stopColor="#ffd98a" stopOpacity="0.22" />
          <stop offset="100%" stopColor="#ffd98a" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="closing-cloud">
          <stop offset="0%" stopColor="#ffcf8a" stopOpacity="0.8" />
          <stop offset="100%" stopColor="#ffcf8a" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="closing-hill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#5888e8" stopOpacity="0.24" />
          <stop offset="100%" stopColor="#5888e8" stopOpacity="0.08" />
        </linearGradient>
        <linearGradient id="closing-hill-near" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#5888e8" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#5888e8" stopOpacity="0.12" />
        </linearGradient>
        {/* Everything above the far hill: the sun is drawn only there, so it sets behind the hill. */}
        <clipPath id="closing-sky">
          <path d="M0 0H800V262C750 248 712 256 650 256C560 256 470 236 380 262C300 284 200 290 120 318L0 340Z" />
        </clipPath>
      </defs>

      {/* Airy sky: soft haloes around the low sun and a golden glow along the horizon */}
      <circle cx="724" cy="254" fill="#5888e8" fillOpacity="0.07" r="236" />
      <circle cx="724" cy="254" fill="#5888e8" fillOpacity="0.07" r="156" />
      <ellipse cx="700" cy="258" fill="url(#closing-horizon-glow)" rx="410" ry="108" />
      <circle className="scene-glow" cx="724" cy="252" fill="url(#closing-sun-glow)" r="124" />

      {/* Soft clouds near the horizon */}
      <g className="scene-drift" fill="url(#closing-cloud)">
        <ellipse cx="548" cy="216" rx="74" ry="8" />
        <ellipse cx="590" cy="206" rx="42" ry="5" />
        <ellipse cx="782" cy="226" rx="60" ry="7" />
        <ellipse cx="452" cy="234" rx="34" ry="4" />
      </g>

      {/* Setting sun */}
      <circle clipPath="url(#closing-sky)" cx="724" cy="266" fill="#ffd401" r="48" />

      {/* Rolling hills, far to near */}
      <path
        d="M120 318C200 290 300 284 380 262C470 236 560 256 650 256C712 256 750 248 800 262V360H0V340Z"
        fill="#5888e8"
        fillOpacity="0.15"
      />
      <path d="M430 360C500 318 600 296 700 298C752 299 782 292 800 288V360Z" fill="url(#closing-hill)" />
      <path d="M0 326C140 300 280 300 420 310C560 320 690 318 800 312V360H0Z" fill="url(#closing-hill-near)" />

      {/* Winding pathway to the sun, with a soft glow */}
      <g fill="none" stroke="#5888e8" strokeLinecap="round" strokeLinejoin="round">
        <path
          d="M-10 352C90 336 170 352 270 336C370 320 450 314 530 302C590 293 650 281 690 270C706 265 716 260 724 257"
          strokeOpacity="0.16"
          strokeWidth="12"
        />
        <path
          d="M-10 352C90 336 170 352 270 336C370 320 450 314 530 302C590 293 650 281 690 270C706 265 716 260 724 257"
          strokeWidth="4"
        />
      </g>
      {/* A soft light travelling along the path into the sunset (ambient; off for reduced motion) */}
      <path
        className="scene-path-light"
        d="M-10 352C90 336 170 352 270 336C370 320 450 314 530 302C590 293 650 281 690 270C706 265 716 260 724 257"
        fill="none"
        pathLength="1"
        stroke="#ffffff"
        strokeLinecap="round"
        strokeWidth="3"
      />
      <path
        d="M14 356C110 346 160 366 262 352"
        fill="none"
        stroke="#3d6bc4"
        strokeLinecap="round"
        strokeOpacity="0.4"
        strokeWidth="2.5"
      />

      {/* Grass tufts */}
      <g fill="none" stroke="#3d6bc4" strokeLinecap="round" strokeWidth="3">
        <path d="M454 326c-4-12-2-22 5-29M463 328c2-10 7-18 14-22" />
        <path d="M760 312c-3-12 0-21 6-28M770 314c3-9 8-16 15-19" />
      </g>

      {/* Hannah's shadow stays with the scene; Hannah is the replaceable slot. */}
      <ellipse cx={MASCOT_FEET.x - 4} cy={MASCOT_FEET.y + 1} fill="#0e1e3d" fillOpacity="0.12" rx="30" ry="4.5" />
      <WalkingMascotSlot />
    </svg>
  );
}
