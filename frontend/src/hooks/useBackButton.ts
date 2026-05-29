import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { hapticImpact, tg } from "../telegram";

// Показывает нативную Telegram BackButton на время жизни экрана и навешивает
// колбэк. По умолчанию — navigate(-1). Вне Telegram это no-op (tg === null),
// поэтому экраны отдельно рендерят свою текстовую ссылку «назад».
export function useBackButton(onBack?: () => void): void {
  const navigate = useNavigate();
  useEffect(() => {
    const wa = tg;
    if (!wa) return;
    const handler = () => {
      hapticImpact("light");
      if (onBack) onBack();
      else navigate(-1);
    };
    wa.BackButton.onClick(handler);
    wa.BackButton.show();
    return () => {
      wa.BackButton.offClick(handler);
      wa.BackButton.hide();
    };
    // onBack намеренно не в deps: экраны передают стабильный колбэк или ничего.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
