/**
 * Environment disclaimer. One constant so a future production configuration
 * can swap the copy in a single place. It deliberately has no environment
 * detection: while this is the demonstration deployment, it is always shown.
 */
export const ENVIRONMENT_NOTICE = "Temporary demonstration environment. All data is synthetic.";

export function DemoNotice({ className }: { className?: string }) {
  return (
    <p className={`text-sm text-hero-muted ${className ?? ""}`} role="note">
      {ENVIRONMENT_NOTICE}
    </p>
  );
}
