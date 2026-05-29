import type { ComponentType } from "react";
import { NavLink } from "react-router-dom";
import { hapticSelection } from "../telegram";
import { IconChart, IconHeart, IconHome, IconPosts } from "./icons";

interface Tab {
  to: string;
  label: string;
  Icon: ComponentType<{ size?: number }>;
  end?: boolean;
}

const TABS: Tab[] = [
  { to: "/", label: "Главная", Icon: IconHome, end: true },
  { to: "/posts", label: "Посты", Icon: IconPosts },
  { to: "/channel", label: "Канал", Icon: IconChart },
  { to: "/reactions", label: "Реакции", Icon: IconHeart },
];

export default function BottomNav() {
  return (
    <nav className="tabbar" aria-label="Основная навигация">
      {TABS.map(({ to, label, Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={hapticSelection}
          className={({ isActive }) =>
            isActive ? "tabbar__item tabbar__item--active" : "tabbar__item"
          }
        >
          <span className="tabbar__icon">
            <Icon size={23} />
          </span>
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
