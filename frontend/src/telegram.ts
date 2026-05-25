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
  themeParams: TelegramThemeParams;
  colorScheme: "light" | "dark";
  isExpanded: boolean;
  ready: () => void;
  expand: () => void;
  close: () => void;
  HapticFeedback: {
    impactOccurred: (style: "light" | "medium" | "heavy") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
  };
  BackButton: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export const tg: TelegramWebApp | null = window.Telegram?.WebApp ?? null;

export function tgReady(): void {
  tg?.ready();
  tg?.expand();
}
