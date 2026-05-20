import { NavLink, Link } from "react-router-dom";

const navItem = ({ isActive }: { isActive: boolean }) =>
  [
    "px-3 py-1.5 rounded-sm text-sm font-medium transition-colors",
    isActive
      ? "text-navy bg-surface"
      : "text-muted hover:text-navy hover:bg-surface/60",
  ].join(" ");

export function Header() {
  return (
    <header className="sticky top-0 z-30 bg-white/85 backdrop-blur-md border-b border-border">
      <div className="container-page flex items-center justify-between gap-4 py-3">
        <Link to="/" className="flex items-baseline gap-2 group">
          <span className="brand-mark">
            DOMOVINA<span className="ai">.ai</span>
          </span>
          <span className="hidden sm:inline text-muted text-sm font-medium tracking-wide">
            / Klubovi
          </span>
        </Link>

        <nav className="flex items-center gap-1 sm:gap-2 text-sm" aria-label="Glavna navigacija">
          <NavLink to="/" end className={navItem}>
            Klubovi
          </NavLink>
          <NavLink to="/karta" className={navItem}>
            Karta
          </NavLink>
          <NavLink to="/statistika" className={navItem}>
            Statistika
          </NavLink>
          <NavLink to="/o-projektu" className={navItem}>
            O projektu
          </NavLink>
        </nav>
      </div>
    </header>
  );
}
