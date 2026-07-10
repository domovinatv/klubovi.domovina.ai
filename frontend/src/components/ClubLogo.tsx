import { useState } from "react";
import { Shield } from "lucide-react";
import type { Club } from "@/lib/types";
import { logoUrl, logoSrcSet } from "@/lib/data";

/**
 * Club crest inside a fixed square *footprint* (keeps list rows aligned) but
 * with no visible box: non-square crests keep their aspect ratio and simply
 * take less width/height — never cropped, never letterboxed in a grey frame.
 * The grey rounded square only appears for the missing-crest fallback.
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
  const [failed, setFailed] = useState(false);
  const url = logoUrl(club);
  const px = `${size}px`;
  return (
    <div
      className={`flex-shrink-0 grid place-items-center ${className}`}
      style={{ width: px, height: px }}
      aria-hidden="true"
    >
      {url && !failed ? (
        <img
          src={url}
          srcSet={logoSrcSet(club)}
          sizes={px}
          alt=""
          loading="lazy"
          decoding="async"
          className="max-w-full max-h-full w-auto h-auto object-contain"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="w-full h-full rounded-sm bg-surface grid place-items-center text-muted/60">
          <Shield size={size * 0.5} strokeWidth={1.5} />
        </span>
      )}
    </div>
  );
}
