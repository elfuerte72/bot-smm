export default function Spinner({ label = "loading" }: { label?: string }) {
  return <span className="spinner" aria-label={label} role="status" />;
}
