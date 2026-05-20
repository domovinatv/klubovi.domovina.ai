export function Footer() {
  return (
    <footer className="mt-16 border-t border-border bg-surface/50">
      <div className="container-page py-10 grid gap-8 sm:grid-cols-3 text-sm">
        <div>
          <div className="brand-mark text-lg">
            DOMOVINA<span className="ai">.ai</span>
          </div>
          <p className="mt-2 text-muted leading-relaxed">
            Otvoreni katalog hrvatskih nogometnih klubova — od HNL-a do 3. ŽNL.
            Podaci se osvježavaju iz javnih izvora.
          </p>
        </div>
        <div>
          <div className="field-label">Izvori</div>
          <ul className="space-y-1.5 text-muted">
            <li>SofaScore (tier 1–4)</li>
            <li>hrnogomet.hr (tier 5–8)</li>
            <li>HNS Semafor</li>
            <li>Registar udruga RH</li>
          </ul>
        </div>
        <div>
          <div className="field-label">DOMOVINA mreža</div>
          <ul className="space-y-1.5">
            <li>
              <a href="https://domovina.ai" target="_blank" rel="noopener">
                domovina.ai
              </a>
            </li>
            <li>
              <a href="https://donate.domovina.ai" target="_blank" rel="noopener">
                donate.domovina.ai
              </a>
            </li>
            <li>
              <a
                href="https://github.com/domovinatv"
                target="_blank"
                rel="noopener"
              >
                github.com/domovinatv
              </a>
            </li>
          </ul>
        </div>
      </div>
      <div className="border-t border-border">
        <div className="container-page py-4 text-xs text-muted flex items-center justify-between gap-4 flex-wrap">
          <span>
            © {new Date().getFullYear()} DOMOVINA · Otvoreni podaci · CC-BY
          </span>
          <span>Statički PWA · Cloudflare Pages</span>
        </div>
      </div>
    </footer>
  );
}
