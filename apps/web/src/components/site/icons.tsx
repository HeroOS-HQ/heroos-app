import type { ReactNode } from "react";

/** Small outline icons (24px grid). Decorative: always hidden from assistive tech. */
function Icon({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className ?? "size-6"}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.75"
      viewBox="0 0 24 24"
    >
      {children}
    </svg>
  );
}

type IconProps = { className?: string };

export function ChatIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <path d="M21 11.5a8.4 8.4 0 0 1-8.9 8.4 9 9 0 0 1-3.2-.6L3.5 21l1.6-4.6A8.3 8.3 0 0 1 3.6 11.5 8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4Z" />
    </Icon>
  );
}

export function DocumentIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </Icon>
  );
}

export function PeopleIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5" />
      <path d="M16 4.9a3.2 3.2 0 0 1 0 6.2M18 14.9c1.8.7 3 2.4 3 5.1" />
    </Icon>
  );
}

export function ChecklistIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <rect height="18" rx="3" width="18" x="3" y="3" />
      <path d="m8 12.2 2.8 2.8L16 9.5" />
    </Icon>
  );
}

export function ShieldIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <path d="M12 3 5 5.8v5.7c0 4.3 2.9 7.9 7 9.5 4.1-1.6 7-5.2 7-9.5V5.8L12 3Z" />
      <path d="m9 12 2.2 2.2L15.2 10" />
    </Icon>
  );
}

export function BuildingIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <path d="M5 21V4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v17M15 9h3a1 1 0 0 1 1 1v11M3 21h18" />
      <path d="M9 7h2M9 11h2M9 15h2" />
    </Icon>
  );
}

export function CaseIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <rect height="13" rx="2.5" width="18" x="3" y="7" />
      <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3 12.5h18" />
    </Icon>
  );
}

export function ArrowRightIcon({ className }: IconProps) {
  return (
    <Icon className={className ?? "size-4"}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Icon>
  );
}

export function MenuIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Icon>
  );
}

export function CloseIcon({ className }: IconProps) {
  return (
    <Icon className={className}>
      <path d="m6 6 12 12M18 6 6 18" />
    </Icon>
  );
}
