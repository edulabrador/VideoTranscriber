import { useClipboard } from "../hooks/useClipboard";
import { Icon } from "./Icon";

export function CopyButton({ text }: { text: string }) {
  const { copy, copied } = useClipboard();

  return (
    <button
      type="button"
      onClick={() => copy(text)}
      className="secondary-button"
    >
      <Icon name={copied ? "check" : "copy"} size={14} />
      {copied ? "¡Copiado!" : "Copiar texto"}
    </button>
  );
}
