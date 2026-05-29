// Минимальные типы для window.Telegram.WebApp.
// Полный объект описан в https://core.telegram.org/bots/webapps —
// здесь объявлено только то, что реально используем.

export interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
  header_bg_color?: string;
  accent_text_color?: string;
  section_bg_color?: string;
  section_header_text_color?: string;
  subtitle_text_color?: string;
  destructive_text_color?: string;
}

export interface HapticFeedback {
  impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
  notificationOccurred: (type: "error" | "success" | "warning") => void;
  selectionChanged: () => void;
}

export interface BackButton {
  isVisible: boolean;
  show: () => void;
  hide: () => void;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
}

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: {
      id: number;
      username?: string;
      first_name?: string;
      last_name?: string;
    };
  };
  version: string;
  platform: string;
  themeParams: TelegramThemeParams;
  colorScheme: "light" | "dark";
  isExpanded: boolean;
  viewportStableHeight: number;
  ready: () => void;
  expand: () => void;
  close: () => void;
  setHeaderColor: (color: string) => void;
  setBackgroundColor: (color: string) => void;
  onEvent: (event: string, cb: () => void) => void;
  offEvent: (event: string, cb: () => void) => void;
  HapticFeedback: HapticFeedback;
  BackButton: BackButton;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export const tg: TelegramWebApp | null = window.Telegram?.WebApp ?? null;

// Сравнение версий WebApp ("7.0" >= "6.1"): не все методы есть в старых клиентах,
// вызывать их там — исключение. Гейтим setHeaderColor/setBackgroundColor.
function versionAtLeast(target: string): boolean {
  const cur = (tg?.version ?? "0").split(".").map((n) => parseInt(n, 10) || 0);
  const want = target.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(cur.length, want.length); i += 1) {
    const a = cur[i] ?? 0;
    const b = want[i] ?? 0;
    if (a !== b) return a > b;
  }
  return true;
}

export function tgReady(): void {
  if (!tg) return;
  tg.ready();
  tg.expand();
  if (versionAtLeast("6.1")) {
    try {
      // Хедер и фон под цвет темы — Mini App выглядит цельно, без «шва».
      tg.setHeaderColor(tg.themeParams.bg_color ?? "#17212b");
      tg.setBackgroundColor(tg.themeParams.bg_color ?? "#17212b");
    } catch {
      // старый клиент: метода нет — игнорируем
    }
  }
}

// ── Haptics ────────────────────────────────────────────────────────────────
// Все хелперы no-op вне Telegram (dev в браузере) и обёрнуты в try/catch:
// HapticFeedback может бросать на десктоп-клиентах без вибромотора.
export function hapticSelection(): void {
  try {
    tg?.HapticFeedback.selectionChanged();
  } catch {
    /* нет поддержки */
  }
}

export function hapticImpact(style: "light" | "medium" | "heavy" = "light"): void {
  try {
    tg?.HapticFeedback.impactOccurred(style);
  } catch {
    /* нет поддержки */
  }
}

export function hapticNotify(type: "error" | "success" | "warning"): void {
  try {
    tg?.HapticFeedback.notificationOccurred(type);
  } catch {
    /* нет поддержки */
  }
}
