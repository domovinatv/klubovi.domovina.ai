const TIER_LABELS: Record<number, string> = {
  1: "HNL",
  2: "1. NL",
  3: "3. HNL / 2. NL",
  4: "3. NL",
  5: "1. ŽNL",
  6: "2. ŽNL",
  7: "3. ŽNL",
  8: "Amaterska",
};

export function TierBadge({
  tier,
  size = "sm",
  withLabel = true,
}: {
  tier?: number;
  size?: "xs" | "sm" | "md";
  withLabel?: boolean;
}) {
  if (!tier) return null;
  const dot = {
    xs: "h-2 w-2",
    sm: "h-2.5 w-2.5",
    md: "h-3 w-3",
  }[size];
  const text = size === "md" ? "text-sm" : "text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${text} font-medium text-navy-700`}
    >
      <span
        className={`${dot} rounded-full ring-2 ring-white shadow-sm`}
        style={{ background: `var(--tier-${tier}, #94A3B8)` }}
        aria-hidden="true"
      />
      <span className="tabular-nums">T{tier}</span>
      {withLabel && (
        <span className="text-muted font-normal">{TIER_LABELS[tier]}</span>
      )}
    </span>
  );
}
