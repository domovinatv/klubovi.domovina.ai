import { Outlet, isRouteErrorResponse, useRouteError } from "react-router-dom";
import { BrandStripe } from "./BrandStripe";
import { Header } from "./Header";
import { Footer } from "./Footer";

function ErrorBlock() {
  const err = useRouteError();
  const status =
    isRouteErrorResponse(err) && err.status ? err.status : "Greška";
  const msg =
    isRouteErrorResponse(err) && err.statusText
      ? err.statusText
      : (err as Error)?.message || "Dogodila se neočekivana greška.";
  return (
    <main className="container-page py-24 text-center">
      <h1 className="text-4xl font-extrabold text-navy">{status}</h1>
      <p className="mt-3 text-muted">{msg}</p>
      <a href="/" className="btn-primary mt-6 inline-flex">
        ← Natrag na početnu
      </a>
    </main>
  );
}

export function RootLayout({ error = false }: { error?: boolean }) {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <BrandStripe />
      <Header />
      <div className="flex-1">{error ? <ErrorBlock /> : <Outlet />}</div>
      <Footer />
      <BrandStripe />
    </div>
  );
}
