/**
 * TEMPORARY wordmark. The original HeroOS logo files will come from JJ; swap
 * the contents of this one component and every header and footer follows.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ""}`}>
      <svg aria-hidden="true" className="size-9" viewBox="0 0 40 40">
        <circle cx="15" cy="20" r="13" fill="#3d6bc4" />
        <circle cx="26" cy="20" r="13" fill="#ffd401" fillOpacity="0.95" />
        <path d="M26 7.2a13 13 0 0 1 0 25.600A13 13 0 0 1 26 7.2Z" fill="#0e1e3d" fillOpacity="0.18" />
      </svg>
      <span className="text-2xl font-extrabold tracking-tight text-hero-navy">
        Hero<span className="text-hero-blue">OS</span>
      </span>
    </span>
  );
}
