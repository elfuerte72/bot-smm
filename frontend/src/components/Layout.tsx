import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/", label: "Посты", end: true },
  { to: "/channel", label: "Канал" },
  { to: "/reactions", label: "Реакции" },
];

export default function Layout() {
  return (
    <div className="app">
      <nav className="nav" aria-label="Главная навигация">
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) =>
              isActive ? "nav__link nav__link--active" : "nav__link"
            }
          >
            {l.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
