import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Spinner from "./components/Spinner";

const Posts = lazy(() => import("./pages/Posts"));
const PostDetail = lazy(() => import("./pages/PostDetail"));
const Channel = lazy(() => import("./pages/Channel"));
const Reactions = lazy(() => import("./pages/Reactions"));

function PageFallback() {
  return (
    <div style={{ textAlign: "center", padding: 20 }}>
      <Spinner />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route
            index
            element={
              <Suspense fallback={<PageFallback />}>
                <Posts />
              </Suspense>
            }
          />
          <Route
            path="/posts/:id"
            element={
              <Suspense fallback={<PageFallback />}>
                <PostDetail />
              </Suspense>
            }
          />
          <Route
            path="/channel"
            element={
              <Suspense fallback={<PageFallback />}>
                <Channel />
              </Suspense>
            }
          />
          <Route
            path="/reactions"
            element={
              <Suspense fallback={<PageFallback />}>
                <Reactions />
              </Suspense>
            }
          />
          <Route
            path="*"
            element={
              <div className="card">
                <h2>404</h2>
                <p className="muted">Страница не найдена.</p>
              </div>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
