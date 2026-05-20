import { createBrowserRouter } from "react-router-dom";
import { lazy, Suspense } from "react";
import { RootLayout } from "./components/RootLayout";
import { PageSpinner } from "./components/PageSpinner";

const Home = lazy(() => import("./routes/Home"));
const Map = lazy(() => import("./routes/Map"));
const Club = lazy(() => import("./routes/Club"));
const County = lazy(() => import("./routes/County"));
const League = lazy(() => import("./routes/League"));
const Stats = lazy(() => import("./routes/Stats"));
const About = lazy(() => import("./routes/About"));
const NotFound = lazy(() => import("./routes/NotFound"));

const lazyRoute = (Cmp: React.LazyExoticComponent<() => JSX.Element>) => (
  <Suspense fallback={<PageSpinner />}>
    <Cmp />
  </Suspense>
);

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    errorElement: <RootLayout error />,
    children: [
      { index: true, element: lazyRoute(Home) },
      { path: "karta", element: lazyRoute(Map) },
      { path: "klub/:slug", element: lazyRoute(Club) },
      { path: "zupanija/:name", element: lazyRoute(County) },
      { path: "liga/:id", element: lazyRoute(League) },
      { path: "statistika", element: lazyRoute(Stats) },
      { path: "o-projektu", element: lazyRoute(About) },
      { path: "*", element: lazyRoute(NotFound) },
    ],
  },
]);
