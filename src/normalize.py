from __future__ import annotations

import re
import unicodedata

_PREFIX_RE = re.compile(
    r"^(hnk|gnk|nk|rnk|mnk|hašk|šnk|nogometni\s+klub|građanski\s+nogometni\s+klub)\s+",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# Croatian Đ/đ don't decompose under NFKD (they're standalone letters, not
# base+combining), so we map them explicitly before the general pass.
_CROATIAN_MAP = str.maketrans({"đ": "d", "Đ": "D"})


def strip_diacritics(s: str) -> str:
    s = s.translate(_CROATIAN_MAP)
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def slugify(name: str, city: str | None = None) -> str:
    base = strip_diacritics(name).lower().strip()
    base = _PREFIX_RE.sub("", base)
    if city:
        city_norm = strip_diacritics(city).lower().strip()
        if city_norm and not base.endswith(city_norm):
            base = f"{base}-{city_norm}"
    base = _NON_ALNUM.sub("-", base).strip("-")
    return base


def short_name(canonical: str) -> str:
    stripped = _PREFIX_RE.sub("", canonical).strip()
    return stripped.split()[0] if stripped else canonical
