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

import csv
import io

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.db import connect  # noqa: E402
from src.normalize import strip_diacritics  # noqa: E402

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
          SUM(CASE WHEN phone_kind = 'mobile' THEN 1 ELSE 0 END) AS can_sms,
          SUM(CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END) AS can_call,
          SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) AS can_email,
          SUM(CASE WHEN address IS NOT NULL THEN 1 ELSE 0 END) AS can_mail,
          SUM(CASE WHEN
            website IS NOT NULL OR fb_url IS NOT NULL OR ig_url IS NOT NULL
            THEN 1 ELSE 0 END) AS can_web,
          SUM(CASE WHEN
            phone_kind = 'mobile' AND phone IS NOT NULL
            AND email IS NOT NULL AND address IS NOT NULL
            AND (website IS NOT NULL OR fb_url IS NOT NULL OR ig_url IS NOT NULL)
            THEN 1 ELSE 0 END) AS full_contact,
          SUM(CASE WHEN
            phone IS NULL AND email IS NULL AND address IS NULL
            AND website IS NULL AND fb_url IS NULL AND ig_url IS NULL
            THEN 1 ELSE 0 END) AS unreachable
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


_ACTION_SCORE_SQL = (
    "((CASE WHEN c.phone_kind = 'mobile' THEN 1 ELSE 0 END) + "
    " (CASE WHEN c.phone IS NOT NULL THEN 1 ELSE 0 END) + "
    " (CASE WHEN c.email IS NOT NULL THEN 1 ELSE 0 END) + "
    " (CASE WHEN c.address IS NOT NULL THEN 1 ELSE 0 END) + "
    " (CASE WHEN c.website IS NOT NULL OR c.fb_url IS NOT NULL "
    "       OR c.ig_url IS NOT NULL THEN 1 ELSE 0 END))"
)


def _enrich_clubs(conn, rows: list[dict]) -> list[dict]:
    """Decorate plain club rows with logo + tier badges + reachability flags."""
    for r in rows:
        r["logo_url"] = _logo_url(conn, r["id"], r["slug"])
        r["tiers"] = _club_tiers(conn, r["id"])
        r["can_sms"] = r.get("phone_kind") == "mobile"
        r["can_call"] = bool(r.get("phone"))
        r["can_email"] = bool(r.get("email"))
        r["can_mail"] = bool(r.get("address"))
        r["can_web"] = bool(r.get("website") or r.get("fb_url") or r.get("ig_url"))
        r["action_score"] = sum([
            r["can_sms"], r["can_call"], r["can_email"],
            r["can_mail"], r["can_web"],
        ])
        r["is_full"] = r["action_score"] == 5
    return rows


def _county_stats(conn, name: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN phone_kind = 'mobile' THEN 1 ELSE 0 END) AS can_sms,
          SUM(CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END) AS can_call,
          SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) AS can_email,
          SUM(CASE WHEN address IS NOT NULL THEN 1 ELSE 0 END) AS can_mail,
          SUM(CASE WHEN
            website IS NOT NULL OR fb_url IS NOT NULL OR ig_url IS NOT NULL
            THEN 1 ELSE 0 END) AS can_web,
          SUM(CASE WHEN
            phone_kind = 'mobile' AND phone IS NOT NULL
            AND email IS NOT NULL AND address IS NOT NULL
            AND (website IS NOT NULL OR fb_url IS NOT NULL OR ig_url IS NOT NULL)
            THEN 1 ELSE 0 END) AS full_contact,
          SUM(CASE WHEN
            phone IS NULL AND email IS NULL AND address IS NULL
            AND website IS NULL AND fb_url IS NULL AND ig_url IS NULL
            THEN 1 ELSE 0 END) AS unreachable
        FROM clubs WHERE county = ?
        """,
        (name,),
    ).fetchone()
    return dict(row)


def _filtered_clubs(
    conn: sqlite3.Connection,
    *,
    q: str | None,
    county: str | None,
    tier: int | None,
    has_mobile: bool,
    has_landline: bool,
    has_email: bool,
    only_full: bool = False,
    page: int | None = 1,
    per_page: int = PAGE_SIZE,
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
        # Route search through clubs_fts (FTS5). Each word becomes a prefix
        # match so "hajd" hits "hajduk". Normalize the query the same way
        # we normalized the index so "djakovo" / "Đakovo" / "dakovo" collide.
        tokens = [w for w in strip_diacritics(q).lower().split() if w]
        if tokens:
            fts_query = " ".join(f'"{w}"*' for w in tokens)
            where.append(
                "c.slug IN (SELECT slug FROM clubs_fts WHERE clubs_fts MATCH ?)"
            )
            params.append(fts_query)
        else:
            where.append("1 = 0")  # empty query post-norm → no results
    if has_mobile:
        where.append("c.phone_kind = 'mobile'")
    if has_landline:
        where.append("c.phone_kind = 'landline'")
    if has_email:
        where.append("c.email IS NOT NULL")
    if only_full:
        where.append(f"{_ACTION_SCORE_SQL} = 5")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    count_sql = f"SELECT COUNT(DISTINCT c.id) AS n FROM clubs c {join} {where_sql}"
    total = conn.execute(count_sql, params).fetchone()["n"]

    # page=None means "all rows" (used by /export.csv).
    if page is None:
        limit_sql = ""
    else:
        offset = max(0, (page - 1) * per_page)
        limit_sql = f" LIMIT {per_page} OFFSET {offset}"
    list_sql = (
        f"SELECT DISTINCT c.* FROM clubs c {join} {where_sql} "
        " ORDER BY c.canonical_name "
        f" {limit_sql}"
    )
    rows = _enrich_clubs(conn, [dict(r) for r in conn.execute(list_sql, params).fetchall()])
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
        SELECT l.id AS league_id, l.name AS league_name, l.tier,
               cs.season, cs.source
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
    only_full: str | None = Query(None),
    page: int = Query(1, ge=1),
):
    # The <select> sends `tier=""` for "Sve razine"; treat as no filter.
    tier_int = int(tier) if tier and tier.isdigit() else None
    has_mobile_b = _truthy(has_mobile)
    has_landline_b = _truthy(has_landline)
    has_email_b = _truthy(has_email)
    only_full_b = _truthy(only_full)
    with _conn() as conn:
        clubs, total = _filtered_clubs(
            conn, q=q, county=county, tier=tier_int,
            has_mobile=has_mobile_b, has_landline=has_landline_b,
            has_email=has_email_b, only_full=only_full_b, page=page,
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
            "only_full": only_full_b,
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


@app.get("/export.csv")
def export_csv(
    q: str | None = Query(None),
    county: str | None = Query(None),
    tier: str | None = Query(None),
    has_mobile: str | None = Query(None),
    has_landline: str | None = Query(None),
    has_email: str | None = Query(None),
    only_full: str | None = Query(None),
):
    """Stream the currently-filtered set as a CSV with SMS-friendly columns."""
    tier_int = int(tier) if tier and tier.isdigit() else None
    with _conn() as conn:
        clubs, _ = _filtered_clubs(
            conn, q=q, county=county, tier=tier_int,
            has_mobile=_truthy(has_mobile),
            has_landline=_truthy(has_landline),
            has_email=_truthy(has_email),
            only_full=_truthy(only_full),
            page=None,  # all rows
        )

    columns = [
        "slug", "canonical_name", "short_name", "city", "county",
        "phone", "phone_kind", "phone_e164", "email", "website",
        "fb_url", "ig_url", "x_url", "address", "president",
        "stadium_name", "founded_year",
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for c in clubs:
        w.writerow([c.get(col) or "" for col in columns])
    body = buf.getvalue()
    filename_parts = ["klubovi"]
    if county:
        filename_parts.append(county.split()[0].lower())
    if tier_int:
        filename_parts.append(f"tier{tier_int}")
    if _truthy(only_full):
        filename_parts.append("punkontakt")
    fname = "-".join(filename_parts) + ".csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/counties/{name}", response_class=HTMLResponse)
def county_detail(name: str, request: Request):
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM clubs WHERE county = ?", (name,)
        ).fetchone()
        if not row["n"]:
            return HTMLResponse("Nepoznata županija", status_code=404)

        rows = conn.execute(
            "SELECT * FROM clubs WHERE county = ? ORDER BY canonical_name",
            (name,),
        ).fetchall()
        clubs = _enrich_clubs(conn, [dict(r) for r in rows])

        tier_breakdown = conn.execute(
            """
            SELECT l.tier, COUNT(DISTINCT cs.club_id) AS n
            FROM leagues l
            JOIN club_seasons cs ON cs.league_id = l.id
            JOIN clubs c ON c.id = cs.club_id
            WHERE c.county = ?
            GROUP BY l.tier
            ORDER BY l.tier
            """,
            (name,),
        ).fetchall()

    return TEMPLATES.TemplateResponse(
        request, "county.html",
        {
            "county_name": name,
            "clubs": clubs,
            "stats": _county_stats(conn, name),
            "tier_breakdown": [dict(r) for r in tier_breakdown],
        },
    )


@app.get("/leagues/{league_id}", response_class=HTMLResponse)
def league_detail(league_id: int, request: Request):
    with _conn() as conn:
        league = conn.execute(
            "SELECT * FROM leagues WHERE id = ?", (league_id,)
        ).fetchone()
        if not league:
            return HTMLResponse("Nepoznata liga", status_code=404)

        rows = conn.execute(
            """
            SELECT DISTINCT c.*, cs.season
            FROM clubs c
            JOIN club_seasons cs ON cs.club_id = c.id
            WHERE cs.league_id = ?
            ORDER BY c.canonical_name
            """,
            (league_id,),
        ).fetchall()
        clubs = _enrich_clubs(conn, [dict(r) for r in rows])

    return TEMPLATES.TemplateResponse(
        request, "league.html",
        {"league": dict(league), "clubs": clubs},
    )


@app.get("/map", response_class=HTMLResponse)
def map_view(request: Request):
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.slug, c.canonical_name, c.city, c.county,
                   c.lat, c.lng, c.phone, c.email,
                   (SELECT MIN(l.tier)
                      FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
                      WHERE cs.club_id = c.id) AS tier
            FROM clubs c
            WHERE c.lat IS NOT NULL AND c.lng IS NOT NULL
            """
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM clubs").fetchone()[0]
    clubs = [dict(r) for r in rows]
    import json as _json
    return TEMPLATES.TemplateResponse(
        request, "map.html",
        {
            "clubs_json": _json.dumps(clubs, ensure_ascii=False),
            "geo_count": len(clubs),
            "total": total,
        },
    )


@app.get("/api/stats")
def api_stats() -> JSONResponse:
    with _conn() as conn:
        return JSONResponse({
            "global": _global_stats(conn),
            "counties": _counties(conn),
            "tiers": _tier_counts(conn),
        })
