import { useClipboard } from "../hooks/useClipboard";

export function CopyButton({ text }: { text: string }) {
  const { copy, copied } = useClipboard();

  return (
    <button
      type="button"
      onClick={() => copy(text)}
      className="rounded-xl border border-stone-200 bg-white px-4 py-2 text-sm font-semibold text-stone-600 shadow-sm transition hover:border-brand-300 hover:text-brand-600 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-300 dark:hover:border-brand-700 dark:hover:text-brand-400"
    >
      {copied ? "¡Copiado!" : "Copiar texto"}
    </button>
  );
}
