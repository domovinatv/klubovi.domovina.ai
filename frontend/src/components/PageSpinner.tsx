export function PageSpinner() {
  return (
    <div className="container-page py-24 flex items-center justify-center">
      <div
        className="h-8 w-8 rounded-full border-2 border-navy/15 border-t-navy animate-spin"
        aria-label="Učitavanje"
      />
    </div>
  );
}
