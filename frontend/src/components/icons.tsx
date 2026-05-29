import type { SVGProps } from "react";

// Лёгкий набор stroke-иконок (currentColor, 24x24). Без сторонних зависимостей —
// чтобы не раздувать бандл Mini App. Все принимают size и обычные svg-props.

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base({ size = 22, ...props }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    ...props,
  };
}

export function IconHome(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" />
      <path d="M9.5 21v-6h5v6" />
    </svg>
  );
}

export function IconPosts(p: IconProps) {
  return (
    <svg {...base(p)}>
      <rect x="3.5" y="4" width="17" height="16" rx="2.5" />
      <path d="M7.5 9h9M7.5 13h9M7.5 17h5" />
    </svg>
  );
}

export function IconChart(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M4 19V5" />
      <path d="M4 19h16" />
      <path d="m7.5 14 3.5-3.5 2.5 2.5L20 7" />
    </svg>
  );
}

export function IconHeart(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M12 20s-7-4.6-7-9.5A3.5 3.5 0 0 1 12 8a3.5 3.5 0 0 1 7 2.5C19 15.4 12 20 12 20Z" />
    </svg>
  );
}

export function IconSearch(p: IconProps) {
  return (
    <svg {...base({ size: 18, ...p })}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.2-3.2" />
    </svg>
  );
}

export function IconChevronRight(p: IconProps) {
  return (
    <svg {...base({ size: 16, ...p })}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function IconArrowUp(p: IconProps) {
  return (
    <svg {...base({ size: 14, ...p })}>
      <path d="M12 19V5" />
      <path d="m6 11 6-6 6 6" />
    </svg>
  );
}

export function IconArrowDown(p: IconProps) {
  return (
    <svg {...base({ size: 14, ...p })}>
      <path d="M12 5v14" />
      <path d="m6 13 6 6 6-6" />
    </svg>
  );
}

export function IconLink(p: IconProps) {
  return (
    <svg {...base({ size: 18, ...p })}>
      <path d="M9 15 15 9" />
      <path d="M11 6.5 12.6 5a4 4 0 0 1 5.7 5.7L16.5 12" />
      <path d="M13 17.5 11.4 19a4 4 0 0 1-5.7-5.7L7.5 12" />
    </svg>
  );
}

export function IconClock(p: IconProps) {
  return (
    <svg {...base({ size: 16, ...p })}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 1.8" />
    </svg>
  );
}

export function IconUsers(p: IconProps) {
  return (
    <svg {...base(p)}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
      <path d="M16 5.5a3 3 0 0 1 0 5.8" />
      <path d="M17.5 13.5A5.2 5.2 0 0 1 21 18.5" />
    </svg>
  );
}

export function IconSparkles(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M12 4.5 13.4 9 18 10.4 13.4 11.8 12 16.3 10.6 11.8 6 10.4 10.6 9 12 4.5Z" />
      <path d="M18.5 4v3M20 5.5h-3M6 16v3M7.5 17.5h-3" />
    </svg>
  );
}

export function IconCheck(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="m5 12.5 4.5 4.5L19 7" />
    </svg>
  );
}

export function IconInbox(p: IconProps) {
  return (
    <svg {...base({ size: 26, ...p })}>
      <path d="M3.5 13.5 6 6.5A2 2 0 0 1 7.9 5h8.2A2 2 0 0 1 18 6.5l2.5 7" />
      <path d="M3.5 13.5V18a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-4.5" />
      <path d="M3.5 13.5h4.2l1.3 2.5h6l1.3-2.5h4.2" />
    </svg>
  );
}

export function IconBack(p: IconProps) {
  return (
    <svg {...base({ size: 18, ...p })}>
      <path d="m14 6-6 6 6 6" />
    </svg>
  );
}
