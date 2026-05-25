import { ApiError } from "../api";
import { tg } from "../telegram";

interface Props {
  error: unknown;
}

export default function ErrorView({ error }: Props) {
  let text = String(error);
  if (error instanceof ApiError) {
    text = `HTTP ${error.status}: ${error.body || "ошибка"}`;
    if (error.status === 401 || error.status === 403) {
      tg?.close();
    }
  }
  return (
    <div className="error" role="alert">
      {text}
    </div>
  );
}
