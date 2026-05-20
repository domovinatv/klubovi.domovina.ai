import { useWideLayout } from "@/lib/layout";

export function WidthToggle() {
  const [wide, toggle] = useWideLayout();
  return (
    <button
      type="button"
      onClick={toggle}
      title={wide ? "Suzi (zadana širina)" : "Razvuci preko cijelog ekrana"}
      aria-label={wide ? "Suzi sadržaj" : "Razvuci sadržaj preko cijelog ekrana"}
      aria-pressed={wide}
      className="hidden xl:inline-flex items-center justify-center w-9 h-9 rounded-sm border border-border text-muted hover:text-navy hover:border-navy hover:bg-surface transition-colors"
    >
      {wide ? <NarrowIcon /> : <WideIcon />}
    </button>
  );
}

function WideIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12h18" />
      <path d="M3 12l4-4" />
      <path d="M3 12l4 4" />
      <path d="M21 12l-4-4" />
      <path d="M21 12l-4 4" />
    </svg>
  );
}

function NarrowIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 12h10" />
      <path d="M7 12l4-4" />
      <path d="M7 12l4 4" />
      <path d="M17 12l-4-4" />
      <path d="M17 12l-4 4" />
    </svg>
  );
}
