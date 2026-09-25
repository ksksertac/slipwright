// Which language the UI speaks. It rides the topbar once you are inside, and sits under
// the card on the way in -- sign-in, sign-up and the letters' pages are where the choice
// matters most, because until it is made all we have is the browser's guess about the
// person standing at the door.
import { FlagGB, FlagTR } from "./flags";
import { useLang, useT } from "../i18n";

const LANGS = [
  { code: "tr", name: "Türkçe", Flag: FlagTR },
  { code: "en", name: "English", Flag: FlagGB },
] as const;

/** Two letters, for the topbar, where the row of controls around them says what they are. */
export function LangPicker() {
  const tx = useT();
  const { lang, setLang } = useLang();
  return (
    <div className="segmented" role="group" aria-label={tx("Language")}>
      {LANGS.map(({ code, name }) => (
        <button
          key={code}
          type="button"
          className={lang === code ? "on" : ""}
          title={name}
          aria-pressed={lang === code}
          onClick={() => setLang(code)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

/** The same choice on the pages before sign-in, where nothing else on screen explains it.
 *
 * Two bare letters under a login card have nothing to be read against, so here each one
 * carries its flag and its own name for it -- "Türkçe", not "Turkish". Somebody who
 * cannot read the page yet can still find their way out of it.
 */
export function AuthLangPicker() {
  const tx = useT();
  const { lang, setLang } = useLang();
  return (
    <div className="login-lang">
      <div className="segmented lang-flags" role="group" aria-label={tx("Language")}>
        {LANGS.map(({ code, name, Flag }) => (
          <button
            key={code}
            type="button"
            className={lang === code ? "on" : ""}
            lang={code}
            aria-pressed={lang === code}
            onClick={() => setLang(code)}
          >
            <Flag />
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}
