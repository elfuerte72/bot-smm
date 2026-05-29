import { hapticSelection } from "../telegram";

interface Option<T extends string> {
  value: T;
  label: string;
}

export default function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: Array<Option<T>>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((opt) => (
        <button
          key={opt.value}
          role="tab"
          aria-selected={value === opt.value}
          onClick={() => {
            if (opt.value !== value) {
              hapticSelection();
              onChange(opt.value);
            }
          }}
          className={
            value === opt.value ? "segmented__item segmented__item--active" : "segmented__item"
          }
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
