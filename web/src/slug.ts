/** Turkish (and the rest of Latin-1) folded to ascii, so a name typed here stays typeable
 *  anywhere: a repository name and a branch name both travel through git, URLs and other
 *  people's shells. Mirrors `_FOLD` in slipwright/schemas/job.py. */
const FOLD: Record<string, string> = {
  ı: "i", İ: "i", ğ: "g", Ğ: "g", ü: "u", Ü: "u",
  ş: "s", Ş: "s", ö: "o", Ö: "o", ç: "c", Ç: "c",
  â: "a", î: "i", û: "u", é: "e", è: "e", ñ: "n",
};

/** `text` as a name git and GitHub both accept: ascii, lower case, hyphen-joined.
 *  Empty when nothing usable is left, which the caller has to handle. */
export function slugify(text: string, limit = 40): string {
  let out = "";
  for (const ch of text) {
    const c = (FOLD[ch] ?? ch).toLowerCase();
    if (/[a-z0-9]/.test(c)) out += c;
    else if (out && !out.endsWith("-")) out += "-";
  }
  return out.slice(0, limit).replace(/^-+|-+$/g, "");
}
