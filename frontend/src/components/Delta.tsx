import { IconArrowDown, IconArrowUp } from "./icons";

// Индикатор изменения значения за период. value === null → данных мало (—).
export default function Delta({ value, suffix }: { value: number | null; suffix?: string }) {
  if (value === null) {
    return <span className="delta delta--flat">— {suffix}</span>;
  }
  if (value === 0) {
    return <span className="delta delta--flat">0 {suffix}</span>;
  }
  const up = value > 0;
  return (
    <span className={up ? "delta delta--up" : "delta delta--down"}>
      {up ? <IconArrowUp /> : <IconArrowDown />}
      {up ? "+" : "−"}
      {Math.abs(value).toLocaleString("ru-RU")}
      {suffix ? ` ${suffix}` : ""}
    </span>
  );
}
