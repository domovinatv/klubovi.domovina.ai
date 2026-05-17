"""Scrape phone/email/website from Facebook Page About sections via Firecrawl.

Direct unauthenticated HTTP to facebook.com hits a login wall — even
mbasic.facebook.com redirects after one request. The `facebookexternalhit/1.1`
UA returns og: meta tags but those carry only title + like-count + cover image
(no phone/email). Firecrawl's stealth scrape passes the wall and returns the
full About markdown including the "Contact info" section.

For each fb_url:
  1. Normalise to canonical page URL (strip /mentions, /photos, etc.)
  2. Append /about_contact_and_basic_info — that single path renders the
     Contact info + Basic info blocks
  3. Scrape via Firecrawl (cached on the underlying _post call)
  4. Parse `## Contact info` and `## Websites and social links` sections
     for phone, email, and a club-owned website

Output is a flat dict — None for any field the page does not expose.

Cost: 1 Firecrawl credit per scrape. Pages we have already cached re-use
the cache for free.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit

from src.firecrawl import FirecrawlClient

logger = logging.getLogger(__name__)

# Strip these path suffixes so the about-URL composes cleanly.
_STRIP_SUFFIXES = (
    "/mentions/", "/mentions",
    "/photos/", "/photos",
    "/videos/", "/videos",
    "/reviews/", "/reviews",
    "/posts/", "/posts",
    "/about/", "/about",
    "/about_contact_and_basic_info/", "/about_contact_and_basic_info",
)

PHONE_RE = re.compile(
    r"(\+?\s?385[\s\-/]?\d[\s\-/\d]{6,12}\d"      # +385 / 385 international
    r"|0\d{1,2}[\s\-/]?\d{3,4}[\s\-/]?\d{3,4})"   # local 0XX...
)
EMAIL_RE = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I)
URL_RE = re.compile(r"https?://[^\s)\]]+", re.I)

# Domain suffixes we IGNORE as "website" — FB-internal CDN, social profiles
# (already in their own columns), media hosts. Matched via endswith on the
# `host_no_www` so any subdomain (e.g. scontent-lax3-2.xx.fbcdn.net) is caught.
_NON_WEBSITE_HOST_SUFFIXES = (
    "facebook.com", "fb.com", "fbcdn.net",
    "instagram.com", "cdninstagram.com",
    "twitter.com", "x.com", "t.co",
    "youtube.com", "youtu.be",
    "tiktok.com", "ttwstatic.com",
    "wa.me", "whatsapp.com",
)


def canonical_about_url(fb_url: str) -> str | None:
    """Return the …/about_contact_and_basic_info URL for a given fb page URL.

    None if fb_url is not a recognisable Facebook page URL.
    """
    if not fb_url:
        return None
    s = urlsplit(fb_url)
    if "facebook.com" not in s.netloc.lower() and "fb.com" not in s.netloc.lower():
        return None
    path = s.path.rstrip("/")
    for suf in _STRIP_SUFFIXES:
        if path.endswith(suf):
            path = path[: -len(suf)] or "/"
            break
    if not path or path == "/":
        return None
    return f"https://www.facebook.com{path}/about_contact_and_basic_info"


def _normalise_phone(s: str) -> str:
    """Trim whitespace, internal slashes, runs of spaces, into a single token."""
    return re.sub(r"\s+", " ", s.replace("/", " ").strip())


def _is_club_website(url: str) -> bool:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    if not host:
        return False
    host_no_www = host.removeprefix("www.")
    for suf in _NON_WEBSITE_HOST_SUFFIXES:
        if host_no_www == suf or host_no_www.endswith("." + suf):
            return False
    return True


def parse_about_markdown(md: str) -> dict[str, Any]:
    """Parse the markdown Firecrawl returns for /about_contact_and_basic_info.

    Returns flat dict with keys: phone, email, website, hint (a short string
    indicating which markdown section produced each value, or None).
    """
    out: dict[str, Any] = {"phone": None, "email": None, "website": None}
    if not md:
        return out

    # Section-aware: prefer values inside the "Contact info" block, fall back
    # to the whole document if nothing landed there.
    contact_block = ""
    m = re.search(r"##\s*Contact info(.*?)(?=\n##\s|\Z)", md, re.S)
    if m:
        contact_block = m.group(1)
    websites_block = ""
    m = re.search(r"##\s*Websites?\s*(?:and social[^\n]*)?(.*?)(?=\n##\s|\Z)", md, re.S)
    if m:
        websites_block = m.group(1)

    # PHONE — first hit in contact block, else first hit in whole doc.
    for source in (contact_block, md):
        for raw in PHONE_RE.findall(source):
            p = _normalise_phone(raw)
            # Filter obvious noise: long FB internal numeric IDs end up as
            # 10+ digits with no spaces and no leading + — the regex already
            # filters most of those, but double-check.
            digits = re.sub(r"\D", "", p)
            if len(digits) < 8 or len(digits) > 13:
                continue
            out["phone"] = p
            break
        if out["phone"]:
            break

    # EMAIL — same precedence.
    for source in (contact_block, md):
        for e in EMAIL_RE.findall(source):
            e = e.strip(".,;)")
            # Drop FB system addresses if any leaked in.
            if e.endswith(("@facebook.com", "@fb.com", "@instagram.com")):
                continue
            out["email"] = e.lower()
            break
        if out["email"]:
            break

    # WEBSITE — prefer the Websites section, then Contact info, then whole doc.
    for source in (websites_block, contact_block, md):
        for u in URL_RE.findall(source):
            u = u.rstrip(".,;)\"'")
            if _is_club_website(u):
                out["website"] = u
                break
        if out["website"]:
            break

    return out


def scrape_about(client: FirecrawlClient, fb_url: str) -> dict[str, Any] | None:
    """Fetch + parse one Facebook page's contact-and-basic-info.

    Returns None when the URL isn't a recognisable page URL.
    Raises InsufficientCreditsError from the underlying client if every
    configured key is exhausted.
    """
    about = canonical_about_url(fb_url)
    if about is None:
        return None
    payload = {
        "url": about,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }
    data = client._post("scrape", payload)  # noqa: SLF001  - reuses cache
    md = (data.get("data") or {}).get("markdown") or ""
    parsed = parse_about_markdown(md)
    parsed["about_url"] = about
    return parsed
