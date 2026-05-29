import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Spinner from "./components/Spinner";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Posts = lazy(() => import("./pages/Posts"));
const PostDetail = lazy(() => import("./pages/PostDetail"));
const Channel = lazy(() => import("./pages/Channel"));
const Reactions = lazy(() => import("./pages/Reactions"));

function PageFallback() {
  return (
    <div className="center-pad">
      <Spinner />
    </div>
  );
}

function lazyRoute(node: ReactNode) {
  return <Suspense fallback={<PageFallback />}>{node}</Suspense>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={lazyRoute(<Dashboard />)} />
          <Route path="/posts" element={lazyRoute(<Posts />)} />
          <Route path="/posts/:id" element={lazyRoute(<PostDetail />)} />
          <Route path="/channel" element={lazyRoute(<Channel />)} />
          <Route path="/reactions" element={lazyRoute(<Reactions />)} />
          <Route
            path="*"
            element={
              <div className="page">
                <div className="empty">
                  <div className="empty__title">404</div>
                  <div className="text-sm">Страница не найдена.</div>
                </div>
              </div>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
