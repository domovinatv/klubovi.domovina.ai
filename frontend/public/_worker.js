/**
 * Cloudflare Pages Advanced Mode worker — klubovi.domovina.ai
 *
 * Odgovornosti:
 *  1. SPA fallback — sve neasset rute vraćaju index.html
 *  2. OG/social tagovi — za /klub/<slug> obogati index.html s meta tagovima
 *     iz clubs.json prije nego što crawler dobije odgovor
 *  3. Cache-Control — patchamo u workeru jer _headers nije aktivan dok worker
 *     handla request (CF Pages Advanced Mode contract)
 *
 * NAPOMENA: bez _redirects fajla — ako se vrati SPA fallback unutra, ASSETS.fetch
 * vraća index.html za bilo koji nepostojeći /klub/* prije nego worker stigne
 * injekciju OG-a (vidi domovina.ai feedback).
 */

const SITE = "https://klubovi.domovina.ai";

let CLUBS_PROMISE = null;

async function loadClubs(env) {
  if (CLUBS_PROMISE) return CLUBS_PROMISE;
  CLUBS_PROMISE = env.ASSETS.fetch(new Request(`${SITE}/data/clubs.json`))
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  return CLUBS_PROMISE;
}

function applyCacheHeaders(res, path) {
  const headers = new Headers(res.headers);
  if (/^\/assets\//.test(path)) {
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
  } else if (/^\/logos\//.test(path)) {
    headers.set("Cache-Control", "public, max-age=2592000, immutable");
  } else if (/^\/data\//.test(path)) {
    headers.set("Cache-Control", "public, max-age=3600, must-revalidate");
  } else if (/^\/icons\//.test(path) || path === "/og-image.png") {
    headers.set("Cache-Control", "public, max-age=86400");
  } else if (/\.(js|css|svg|woff2?|png|jpg|webp)$/.test(path)) {
    headers.set("Cache-Control", "public, max-age=3600");
  }
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  headers.set("Permissions-Policy", "interest-cohort=()");
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (ch) =>
    ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[ch],
  );
}

const TIER_LABELS = {
  1: "HNL",
  2: "1. NL",
  3: "3. HNL / 2. NL",
  4: "3. NL",
  5: "1. ŽNL",
  6: "2. ŽNL",
  7: "3. ŽNL",
  8: "Amaterska liga",
};

function buildOgFor(club, url) {
  const title = `${club.canonical_name} · DOMOVINA Klubovi`;
  const parts = [];
  if (club.top_tier) parts.push(`${TIER_LABELS[club.top_tier] || "Tier " + club.top_tier}`);
  if (club.city) parts.push(club.city);
  if (club.county) parts.push(club.county.replace(" županija", ""));
  if (club.founded_year) parts.push(`osnovan ${club.founded_year}`);
  const desc =
    parts.length > 0
      ? `${parts.join(" · ")}. Kontakti i podaci na klubovi.domovina.ai.`
      : `Podaci o klubu ${club.canonical_name} na klubovi.domovina.ai.`;
  const image = club.logo
    ? `${SITE}/logos/${club.logo}`
    : `${SITE}/og-image.png`;
  return { title, desc, image, canonical: url };
}

class OgRewriter {
  constructor(og) {
    this.og = og;
    this.seen = new Set();
  }
  element(el) {
    const name = el.tagName.toLowerCase();
    if (name === "title") {
      el.setInnerContent(this.og.title);
      return;
    }
    if (name !== "meta" && name !== "link") return;
    const property = el.getAttribute("property") || "";
    const metaName = el.getAttribute("name") || "";
    const rel = el.getAttribute("rel") || "";
    const map = {
      "og:title": this.og.title,
      "og:description": this.og.desc,
      "og:image": this.og.image,
      "og:url": this.og.canonical,
      "twitter:title": this.og.title,
      "twitter:description": this.og.desc,
      "twitter:image": this.og.image,
    };
    if (property && map[property] != null) {
      el.setAttribute("content", map[property]);
      this.seen.add(property);
    }
    if (metaName === "description") {
      el.setAttribute("content", this.og.desc);
    }
    if (metaName === "twitter:card") {
      el.setAttribute("content", "summary_large_image");
    }
    if (rel === "canonical") {
      el.setAttribute("href", this.og.canonical);
    }
  }
}

class HeadInjector {
  constructor(rewriter, extras) {
    this.r = rewriter;
    this.extras = extras;
  }
  element(el) {
    if (el.tagName.toLowerCase() !== "head") return;
    // Append any og:* properties that the source index.html did not have so
    // crawlers see a complete set.
    for (const [prop, val] of Object.entries(this.extras)) {
      if (this.r.seen.has(prop)) continue;
      const v = escapeHtml(val);
      el.append(
        `<meta property="${prop}" content="${v}" />`,
        { html: true },
      );
    }
  }
}

async function serveSpaWithOg(env, request, club) {
  const url = new URL(request.url);
  const indexRes = await env.ASSETS.fetch(new Request(`${SITE}/index.html`));
  if (!indexRes.ok) return indexRes;

  const og = buildOgFor(club, `${SITE}${url.pathname}`);
  const rewriter = new OgRewriter(og);

  const transformed = new HTMLRewriter()
    .on("title", rewriter)
    .on("meta", rewriter)
    .on("link", rewriter)
    .on("head", new HeadInjector(rewriter, {
      "og:title": og.title,
      "og:description": og.desc,
      "og:image": og.image,
      "og:url": og.canonical,
      "og:type": "website",
      "og:locale": "hr_HR",
    }))
    .transform(indexRes);

  const out = new Response(transformed.body, transformed);
  out.headers.set("Content-Type", "text/html; charset=utf-8");
  out.headers.set("Cache-Control", "public, max-age=300, must-revalidate");
  out.headers.set("X-Content-Type-Options", "nosniff");
  out.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Static assets — pass through to ASSETS with cache patching.
    if (/\.\w{1,8}$/.test(path)) {
      const res = await env.ASSETS.fetch(request);
      return applyCacheHeaders(res, path);
    }

    // OG injection for /klub/<slug>
    const m = path.match(/^\/klub\/([^/]+)\/?$/);
    if (m) {
      const slug = decodeURIComponent(m[1]);
      const clubs = await loadClubs(env);
      const club = clubs.find((c) => c.slug === slug);
      if (club) {
        return serveSpaWithOg(env, request, club);
      }
    }

    // SPA fallback — serve index.html for everything else
    const indexRes = await env.ASSETS.fetch(new Request(`${SITE}/index.html`));
    const headers = new Headers(indexRes.headers);
    headers.set("Cache-Control", "public, max-age=300, must-revalidate");
    headers.set("Content-Type", "text/html; charset=utf-8");
    headers.set("X-Content-Type-Options", "nosniff");
    return new Response(indexRes.body, {
      status: indexRes.status === 404 ? 200 : indexRes.status,
      headers,
    });
  },
};
