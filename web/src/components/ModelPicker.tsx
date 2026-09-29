import { useProviderModels } from "../api/hooks";
import { useT } from "../i18n";

/**
 * Which model a provider runs on: a text field whose suggestions are the models that
 * provider's key can actually use.
 *
 * It used to be a `<select>` in two of the three places it appears, which was pleasant
 * while a vendor offered a dozen models and became unusable the day OpenRouter was added
 * — four hundred of them, behind one key, in a dropdown with no way to type. A `<datalist>`
 * is the same list with the browser's own filtering on top, and it keeps the one thing
 * the select could not do at all: typing in a model the vendor has not listed yet, which
 * is how a model released this morning gets used this morning.
 */
export function ModelPicker({
  provider,
  value,
  disabled,
  onChange,
  id,
  placeholder,
  title,
}: {
  /** The provider whose models to suggest; null asks for none. */
  provider: string | null;
  value: string;
  disabled?: boolean;
  onChange: (model: string) => void;
  id?: string;
  placeholder?: string;
  title?: string;
}) {
  const tx = useT();
  // "" reaches here from a profile row whose provider is not set yet; it is "no provider"
  const name = provider || null;
  const models = useProviderModels(name);
  const listed = models.data?.models ?? [];
  const listId = name ? `models-${name}` : undefined;
  return (
    <>
      <input
        id={id}
        type="text"
        className="mono"
        list={listed.length > 0 ? listId : undefined}
        value={value}
        disabled={disabled}
        title={title}
        placeholder={placeholder ?? tx("model id")}
        onChange={(e) => onChange(e.target.value)}
      />
      {listed.length > 0 && (
        <datalist id={listId}>
          {listed.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      )}
    </>
  );
}
