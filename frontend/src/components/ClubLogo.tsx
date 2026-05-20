import type { Club } from "@/lib/types";
import { logoUrl } from "@/lib/data";

export function ClubLogo({
  club,
  size = 48,
  className = "",
}: {
  club: Pick<Club, "logo" | "slug" | "canonical_name">;
  size?: number;
  className?: string;
}) {
  const url = logoUrl(club);
  const px = `${size}px`;
  return (
    <div
      className={`flex-shrink-0 rounded-sm bg-surface grid place-items-center overflow-hidden ${className}`}
      style={{ width: px, height: px }}
      aria-hidden="true"
    >
      {url ? (
        <img
          src={url}
          alt=""
          loading="lazy"
          decoding="async"
          className="w-full h-full object-contain"
          onError={(e) => {
            const t = e.currentTarget;
            t.style.display = "none";
            t.parentElement!.textContent = "⚽";
          }}
        />
      ) : (
        <span style={{ fontSize: size * 0.55 }}>⚽</span>
      )}
    </div>
  );
}
