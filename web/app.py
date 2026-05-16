"""FastAPI + HTMX catalog of Croatian football clubs.

Run with:
    uv run uvicorn web.app:app --reload --port 8000

Reads the same SQLite DB the ingest scripts populate. HTMX-driven so the list /
filter sidebar / search box update without full page reloads, but every URL
remains a real GET so deep-linking works and crawlers see content.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
LOGO_DIR = PROJECT_ROOT / "data" / "logos"
LOGO_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))

app = FastAPI(title="Hrvatski nogometni klubovi", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.mount("/logos", StaticFiles(directory=str(LOGO_DIR)), name="logos")

PAGE_SIZE = 30

CONTACT_FIELDS = (
    "address", "email", "phone", "website",
    "fb_url", "ig_url", "x_url", "president",
)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _conn() -> sqlite3.Connection:
    return connect()


def _global_stats(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN city IS NOT NULL THEN 1 ELSE 0 END) AS with_city,
          SUM(CASE WHEN county IS NOT NULL THEN 1 ELSE 0 END) AS with_county,
          SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) AS with_email,
          SUM(CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END) AS with_phone,
          SUM(CASE WHEN phone_kind = 'mobile' THEN 1 ELSE 0 END) AS with_mobile,
          SUM(CASE WHEN phone_kind = 'landline' THEN 1 ELSE 0 END) AS with_landline,
          SUM(CASE WHEN website IS NOT NULL THEN 1 ELSE 0 END) AS with_website,
          SUM(CASE WHEN fb_url IS NOT NULL THEN 1 ELSE 0 END) AS with_fb
        FROM clubs
        """
    ).fetchone()
    return dict(row)


def _counties(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT county AS name, COUNT(*) AS n
        FROM clubs
        WHERE county IS NOT NULL
        GROUP BY county
        ORDER BY n DESC, county
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _tier_counts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.tier AS tier, COUNT(DISTINCT cs.club_id) AS n
        FROM leagues l
        JOIN club_seasons cs ON cs.league_id = l.id
        GROUP BY l.tier
        ORDER BY l.tier
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _hrnogomet_id(conn, club_id: int) -> str | None:
    row = conn.execute(
        "SELECT alias FROM club_aliases WHERE club_id = ? AND source = 'hrnogomet-id'",
        (club_id,),
    ).fetchone()
    return row["alias"] if row else None


def _logo_url(conn, club_id: int, slug: str) -> str | None:
    """Return a logo URL if a local file exists, otherwise None.

    Logos are fetched by scripts/07_fetch_logos.py into data/logos/{slug}.png
    and served via the /logos static mount.
    """
    if (LOGO_DIR / f"{slug}.png").exists():
        return f"/logos/{slug}.png"
    return None


def _filtered_clubs(
    conn: sqlite3.Connection,
    *,
    q: str | None,
    county: str | None,
    tier: int | None,
    has_mobile: bool,
    has_landline: bool,
    has_email: bool,
    page: int,
) -> tuple[list[dict], int]:
    where: list[str] = []
    params: list = []
    join = ""
    if tier:
        join = (
            " JOIN club_seasons cs ON cs.club_id = c.id "
            " JOIN leagues l ON l.id = cs.league_id "
        )
        where.append("l.tier = ?")
        params.append(tier)
    if county:
        where.append("c.county = ?")
        params.append(county)
    if q:
        where.append(
            "(c.canonical_name LIKE ? OR c.short_name LIKE ? OR c.city LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])
    if has_mobile:
        where.append("c.phone_kind = 'mobile'")
    if has_landline:
        where.append("c.phone_kind = 'landline'")
    if has_email:
        where.append("c.email IS NOT NULL")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    count_sql = f"SELECT COUNT(DISTINCT c.id) AS n FROM clubs c {join} {where_sql}"
    total = conn.execute(count_sql, params).fetchone()["n"]

    offset = max(0, (page - 1) * PAGE_SIZE)
    list_sql = (
        f"SELECT DISTINCT c.* FROM clubs c {join} {where_sql} "
        " ORDER BY c.canonical_name "
        f" LIMIT {PAGE_SIZE} OFFSET {offset}"
    )
    rows = [dict(r) for r in conn.execute(list_sql, params).fetchall()]
    # Tack on logo URL + tier badge for each.
    for r in rows:
        r["logo_url"] = _logo_url(conn, r["id"], r["slug"])
        r["tiers"] = _club_tiers(conn, r["id"])
        r["contact_count"] = sum(1 for f in CONTACT_FIELDS if r.get(f))
    return rows, total


def _club_tiers(conn, club_id: int) -> list[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT l.tier
        FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
        WHERE cs.club_id = ?
        ORDER BY l.tier
        """,
        (club_id,),
    ).fetchall()
    return [r["tier"] for r in rows]


def _club_leagues(conn, club_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.name AS league_name, l.tier, cs.season, cs.source
        FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
        WHERE cs.club_id = ?
        ORDER BY l.tier, l.name
        """,
        (club_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _aliases(conn, club_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT alias, source FROM club_aliases WHERE club_id = ? "
        "AND source NOT LIKE '%-id'",  # exclude opaque numeric IDs
        (club_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- Routes ----------

def _truthy(v: str | None) -> bool:
    # Form/links serialize unchecked boxes as empty string; FastAPI's bool
    # type rejects "" with 422, so accept strings and convert ourselves.
    return v not in (None, "", "0", "false", "False")


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str | None = Query(None),
    county: str | None = Query(None),
    tier: str | None = Query(None),
    has_mobile: str | None = Query(None),
    has_landline: str | None = Query(None),
    has_email: str | None = Query(None),
    page: int = Query(1, ge=1),
):
    # The <select> sends `tier=""` for "Sve razine"; treat as no filter.
    tier_int = int(tier) if tier and tier.isdigit() else None
    has_mobile_b = _truthy(has_mobile)
    has_landline_b = _truthy(has_landline)
    has_email_b = _truthy(has_email)
    with _conn() as conn:
        clubs, total = _filtered_clubs(
            conn, q=q, county=county, tier=tier_int,
            has_mobile=has_mobile_b, has_landline=has_landline_b,
            has_email=has_email_b, page=page,
        )
        ctx = {
            "request": request,
            "clubs": clubs,
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "q": q or "",
            "county": county or "",
            "tier": tier_int,
            "has_mobile": has_mobile_b,
            "has_landline": has_landline_b,
            "has_email": has_email_b,
            "counties": _counties(conn),
            "tier_counts": _tier_counts(conn),
            "stats": _global_stats(conn),
        }
    # HTMX requests want just the partial that re-renders the list region.
    if _is_htmx(request):
        return TEMPLATES.TemplateResponse(request, "partials/club_list.html", ctx)
    return TEMPLATES.TemplateResponse(request, "index.html", ctx)


@app.get("/clubs/{slug}", response_class=HTMLResponse)
def club_detail(slug: str, request: Request):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM clubs WHERE slug = ?", (slug,)).fetchone()
        if not row:
            return HTMLResponse("Not found", status_code=404)
        club = dict(row)
        club["logo_url"] = _logo_url(conn, club["id"], club["slug"])
        club["leagues"] = _club_leagues(conn, club["id"])
        club["aliases"] = _aliases(conn, club["id"])
        runs = conn.execute(
            "SELECT ran_at, fields_filled, source_urls FROM backfill_runs "
            "WHERE club_id = ? ORDER BY ran_at DESC LIMIT 5",
            (club["id"],),
        ).fetchall()
        club["backfill_runs"] = [dict(r) for r in runs]
    return TEMPLATES.TemplateResponse(
        request, "club.html", {"club": club, "contact_fields": CONTACT_FIELDS},
    )


@app.get("/api/stats")
def api_stats() -> JSONResponse:
    with _conn() as conn:
        return JSONResponse({
            "global": _global_stats(conn),
            "counties": _counties(conn),
            "tiers": _tier_counts(conn),
        })
