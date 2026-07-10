import { Shield } from "lucide-react";
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="container-page py-24 text-center">
      <div className="mb-4 grid place-items-center text-muted/50"><Shield size={56} strokeWidth={1.5} /></div>
      <h1 className="text-3xl font-extrabold text-navy">404 — stranica ne postoji</h1>
      <p className="text-muted mt-2">Lopta je otišla u korner.</p>
      <Link to="/" className="btn-primary mt-6 inline-flex">
        ← Natrag na početnu
      </Link>
    </div>
  );
}
