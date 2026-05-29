import { ApiError } from "../api";
import { tg } from "../telegram";

interface Props {
  error: unknown;
  onRetry?: () => void;
}

export default function ErrorView({ error, onRetry }: Props) {
  let title = "Что-то пошло не так";
  let detail = String(error);
  if (error instanceof ApiError) {
    detail = `HTTP ${error.status}${error.body ? `: ${error.body}` : ""}`;
    if (error.status === 401 || error.status === 403) {
      title = "Нет доступа";
      // Авторизация не прошла (чужой initData / истёк) — закрываем Mini App.
      tg?.close();
    } else if (error.status === 404) {
      title = "Не найдено";
    } else if (error.status >= 500) {
      title = "Ошибка сервера";
    }
  }
  return (
    <div className="error" role="alert">
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{title}</div>
      <div className="text-sm muted" style={{ wordBreak: "break-word" }}>
        {detail}
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="pager__btn"
          style={{ marginTop: 12, background: "var(--bg)" }}
        >
          Повторить
        </button>
      )}
    </div>
  );
}
