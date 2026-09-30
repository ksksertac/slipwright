import { useProviderModels } from "../api/hooks";
import { useT } from "../i18n";

/**
 * Which model a provider runs on, in the three places a model is chosen.
 *
 * Two shapes, because the vendors are not the same shape. A `<select>` was pleasant while
 * a vendor offered a dozen models and became unusable the day OpenRouter was added — four
 * hundred of them, behind one key, in a dropdown with no way to type. So it became a text
 * field with the models as `<datalist>` suggestions, which is the same list with the
 * browser's own filtering on top.
 *
 * That swap then broke the opposite case. A ChatGPT plan offers exactly one model, called
 * `default`, and Chrome draws no arrow on a datalist input: the one choice there was sat
 * behind a box that looked empty and gave no sign a list existed at all. Somebody signing
 * in and finding nothing to pick is not a small annoyance -- it reads as "this did not
 * work".
 *
 * So the list decides. Short enough to read, and it is a dropdown you can see; longer than
 * that, and typing is the only way through, so it is the text field. The threshold is
 * about what a dropdown can show without becoming a scroll, not a measured number.
 */
const SHORT = 25;

export function ModelPicker({
  provider,
  value,
  disabled,
  onChange,
  id,
  placeholder,
  emptyLabel,
  title,
}: {
  /** The provider whose models to offer; null asks for none. */
  provider: string | null;
  value: string;
  disabled?: boolean;
  onChange: (model: string) => void;
  id?: string;
  placeholder?: string;
  /** What the "nothing chosen" row of the dropdown says. */
  emptyLabel?: string;
  title?: string;
}) {
  const tx = useT();
  // "" reaches here from a profile row whose provider is not set yet; it is "no provider"
  const name = provider || null;
  const models = useProviderModels(name);
  const listed = models.data?.models ?? [];
  const listId = name ? `models-${name}` : undefined;

  if (listed.length > 0 && listed.length <= SHORT) {
    return (
      <select
        id={id}
        className="mono"
        value={value}
        disabled={disabled}
        title={title}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{emptyLabel ?? tx("— not set —")}</option>
        {/* a model that was chosen before the vendor stopped listing it still shows, or
            saving this form would silently change which model the agent runs on */}
        {value && !listed.includes(value) && <option value={value}>{value}</option>}
        {listed.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    );
  }

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
