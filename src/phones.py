"""Croatian phone-number classification and normalization.

Two outputs from any input string:

* `classify(s)` -> "mobile" | "landline" | "unknown"
* `to_e164(s)`  -> "+385XXXXXXXX" or None

We do not import phonenumbers — for our scope (Croatian numbers, ad-hoc
formatting from Firecrawl extracts) a tiny prefix-based parser is enough.

Mobile prefixes per HAKOM allocation: 091, 092, 093, 095, 097, 098, 099.
Everything else with a valid Croatian length is treated as landline.
Numbers that don't pass length sanity are "unknown".
"""
from __future__ import annotations

from typing import Literal

PhoneKind = Literal["mobile", "landline", "unknown"]

_MOBILE_PREFIXES = {"91", "92", "93", "95", "97", "98", "99"}


def _digits_only(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def _national_digits(s: str) -> str | None:
    """Return the 'national' portion (no country code, no leading 0).

    None if the input doesn't look like a Croatian number.
    """
    if not s:
        return None
    d = _digits_only(s)
    # 00385... or 0...0 weirdness — strip the 00 international prefix.
    if d.startswith("00385"):
        d = d[5:]
    elif d.startswith("385"):
        d = d[3:]
    # Now expect national format: optional leading 0 then area/mobile code.
    if d.startswith("0"):
        d = d[1:]
    # Croatian national numbers: Zagreb area is 8 digits (1XXXXXXX),
    # all other areas + mobiles are 9 digits.
    if len(d) not in (8, 9):
        return None
    return d


def classify(s: str | None) -> PhoneKind:
    if not s:
        return "unknown"
    national = _national_digits(s)
    if not national:
        return "unknown"
    return "mobile" if national[:2] in _MOBILE_PREFIXES else "landline"


def to_e164(s: str | None) -> str | None:
    national = _national_digits(s) if s else None
    if not national:
        return None
    return "+385" + national
