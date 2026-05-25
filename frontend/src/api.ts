import { tg } from "./telegram";

export class ApiError extends Error {
  constructor(public status: number, public body: string) {
    super(`API ${status}: ${body}`);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const initData = tg?.initData ?? "";
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
      "X-Telegram-Init-Data": initData,
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  return (await res.json()) as T;
}
