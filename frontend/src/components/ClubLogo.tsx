import type { Club } from "@/lib/types";
import { logoUrl, logoSrcSet } from "@/lib/data";

/**
 * Club crest inside a fixed square *footprint* (keeps list rows aligned) but
 * with no visible box: non-square crests keep their aspect ratio and simply
 * take less width/height — never cropped, never letterboxed in a grey frame.
 * The grey rounded square only appears for the ⚽ fallback.
 */
export function ClubLogo({
  club,
  size = 48,
  className = "",
}: {
  club: Pick<Club, "logo" | "slug" | "canonical_name" | "logo_sizes">;
  size?: number;
  className?: string;
}) {
  const url = logoUrl(club);
  const px = `${size}px`;
  return (
    <div
      className={`flex-shrink-0 grid place-items-center ${className}`}
      style={{ width: px, height: px }}
      aria-hidden="true"
    >
      {url ? (
        <img
          src={url}
          srcSet={logoSrcSet(club)}
          sizes={px}
          alt=""
          loading="lazy"
          decoding="async"
          className="max-w-full max-h-full w-auto h-auto object-contain"
          onError={(e) => {
            const t = e.currentTarget;
            t.style.display = "none";
            t.parentElement!.classList.add("rounded-sm", "bg-surface");
            t.parentElement!.textContent = "⚽";
          }}
        />
      ) : (
        <span
          className="w-full h-full rounded-sm bg-surface grid place-items-center"
          style={{ fontSize: size * 0.55 }}
        >
          ⚽
        </span>
      )}
    </div>
  );
}
