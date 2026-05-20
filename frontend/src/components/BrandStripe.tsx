export function BrandStripe({ className = "" }: { className?: string }) {
  return (
    <div className={`flex h-[6px] w-full ${className}`} aria-hidden="true">
      <span className="flex-1 bg-flag-red" />
      <span className="flex-1 bg-flag-white" />
      <span className="flex-1 bg-flag-navy" />
    </div>
  );
}
