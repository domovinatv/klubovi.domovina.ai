import { Info } from "lucide-react";
export default function About() {
  return (
    <article className="container-page py-10 max-w-3xl">
      <div className="pill mb-3 inline-flex items-center gap-1.5"><Info size={13} /> O projektu</div>
      <h1 className="text-3xl sm:text-4xl font-extrabold text-navy">
        Što je DOMOVINA Klubovi
      </h1>
      <p className="lead mt-4 text-lg text-muted leading-relaxed">
        Otvoreni javni katalog svih hrvatskih nogometnih klubova — od
        SuperSport HNL-a do 3. ŽNL. Cilj je sve podatke koje različiti izvori
        čuvaju u zatvorenim ili rascjepkanim sustavima učiniti dostupnim,
        pretraživim i izvozim.
      </p>

      <section className="mt-10 prose prose-slate max-w-none">
        <h2 className="text-xl font-bold text-navy">Izvori podataka</h2>
        <ul className="space-y-2 text-navy-700">
          <li>
            <strong>SofaScore</strong> — tier 1–4, vrhovne lige (stadion, godina, koord.)
          </li>
          <li>
            <strong>hrnogomet.hr</strong> — tier 5–8, županijske lige
          </li>
          <li>
            <strong>HNS Semafor</strong> — službene ID-jevi klubova i mreža
          </li>
          <li>
            <strong>Registar udruga RH</strong> — predsjednik, OIB, adresa
            (~97% klubova)
          </li>
          <li>
            <strong>Nominatim + Google Places</strong> — geokodirane koordinate
          </li>
          <li>
            <strong>Facebook Page About</strong> — kontakti za amaterske klubove
          </li>
        </ul>

        <h2 className="text-xl font-bold text-navy mt-8">Licenca</h2>
        <p className="text-navy-700">
          Podaci su prikupljeni iz javnih izvora i dijele se pod CC-BY
          licencom. Pripisivanje "DOMOVINA Klubovi" obavezno kod ponovne objave.
        </p>

        <h2 className="text-xl font-bold text-navy mt-8">Tehnologija</h2>
        <p className="text-navy-700">
          Statički React PWA hostan na Cloudflare Pages. Sve podatke fetcha
          klijent iz pre-generiranih JSON datoteka — bez backenda, bez
          praćenja, bez kolačića.
        </p>

        <h2 className="text-xl font-bold text-navy mt-8">Doprinos</h2>
        <p className="text-navy-700">
          Pogreška u podacima? Nedostaje klub? Otvori issue na{" "}
          <a href="https://github.com/domovinatv" target="_blank" rel="noopener">
            github.com/domovinatv
          </a>{" "}
          ili javi se na{" "}
          <a href="mailto:hello@domovina.ai">hello@domovina.ai</a>.
        </p>
      </section>
    </article>
  );
}
