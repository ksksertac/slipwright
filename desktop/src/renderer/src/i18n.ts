// Every word the app shows, in one place. The keys are the English text, as in the web
// app's `useT()` (web/src/i18n/tr.ts): a string missing from a table shows its English
// source rather than nothing, and adding English is adding nothing at all. `{name}`
// placeholders are filled by `t(key, {name})`.

export type Lang = "tr" | "en";

const tr: Record<string, string> = {
  // the left side
  Now: "Şimdi",
  Agents: "Ajanlar",
  Work: "İş",
  History: "Geçmiş",
  Connections: "Bağlantılar",
  "Slipwright team": "Slipwright ekibi",
  Models: "Modeller",
  Source: "Kaynak",
  App: "Uygulama",
  Settings: "Ayarlar",
  "Pause taking work": "İş almayı duraklat",
  "Resume taking work": "İş almaya devam et",
  Connected: "Bağlı",
  "Not connected": "Bağlı değil",
  Connecting: "Bağlanıyor",
  "No connection": "Bağlantı yok",
  Paused: "Duraklatıldı",
  "On battery": "Pilde",
  "Phase {n}": "Faz {n}",
  Build: "Build",

  // agents
  Backend: "Backend",
  Web: "Web",
  Mobile: "Mobile",
  DevOps: "DevOps",
  writing: "yazıyor",
  "fetching code": "kodu çekiyor",
  starting: "başlıyor",
  building: "build ediyor",
  idle: "boşta",
  "off on this machine": "bu makinede kapalı",
  "no model": "model yok",
  "This machine does not take {agent} phases": "Bu makine {agent} fazı almıyor",
  "Waiting for a phase": "Faz bekliyor",
  "Choose a model for this agent under Models": "Bu ajan için Modeller'den bir model seç",
  "Can build {what}": "{what} build edebilir",
  "{agent} agent": "{agent} ajanı",
  "Takes {agent} phases on this machine. Its model and whether it is on are set here.":
    "Bu makinede {agent} fazlarını alır. Modeli ve açık/kapalı durumu buradan.",
  "On this machine": "Bu makinede",
  Model: "Model",
  "Model name (empty: default)": "Model adı (boş: varsayılan)",
  "Writes the domains": "Yazdığı alanlar",
  "{n} tasks running": "{n} iş sürüyor",
  "1 task running": "1 iş sürüyor",
  "Phase {n}/{m}": "Faz {n}/{m}",
  "{min} min": "{min} dk",
  "<1 min": "<1 dk",
  "The agents on this machine and the work they hold. The development's page on Slipwright shows the same.":
    "Bu makinedeki ajanlar ve aldıkları işler. Ana ekrandaki geliştirme kutusu da aynısını gösterir.",
  "Live log": "Canlı kayıt",
  "Nothing yet": "Henüz bir şey yok",

  // not paired
  "This machine is not lent to a Slipwright team yet": "Bu makine henüz bir Slipwright ekibine bağlı değil",
  "Once it is, its agents write phases with your own Claude Code, Codex or API key, and it builds iOS and Android when it can.":
    "Bağlandığında ajanları fazları senin Claude Code, Codex ya da API anahtarınla yazar; yapabiliyorsa iOS ve Android build eder.",
  "In Slipwright, open Settings → Machines → Connect a machine": "Slipwright'ta Ayarlar → Makineler → Makine bağla'yı aç",
  "Copy the code (SW-…); it works for 15 minutes, once": "Kodu (SW-…) kopyala; 15 dakika geçerli ve tek kullanımlık",
  "Paste it on the Slipwright team page": "Slipwright ekibi sayfasına yapıştır",
  "Connect to a team": "Ekibe bağlan",

  // history
  "The phases and builds this machine handled.": "Bu makinenin yazdığı fazlar ve yaptığı build'ler.",
  Phase: "Faz",
  Project: "Proje",
  Agent: "Ajan",
  Duration: "Süre",
  Outcome: "Sonuç",
  answered: "yazıldı",
  built: "build tamam",
  "build-failed": "build kırık",
  "taken-back": "geri alındı",
  failed: "hata",
  timeout: "zaman aşımı",
  rejected: "plan/anahtar reddetti",
  "Nothing handled yet": "Henüz iş alınmadı",

  // team
  "Which Slipwright this machine is connected to, and as what.": "Bu makine hangi Slipwright'a bağlı ve kimin adına çalışıyor.",
  "Connected: {where}": "Bağlı: {where}",
  Relay: "Relay",
  LAN: "LAN",
  Connection: "Bağlantı",
  "end-to-end encrypted": "uçtan uca şifreli",
  "on this network": "bu ağda",
  "Machine key": "Makine anahtarı",
  "in the system keychain": "sistemin anahtar zincirinde",
  "only for this run (no keychain)": "yalnızca bu oturum (anahtar zinciri yok)",
  "Machine name": "Makine adı",
  "Connect to another team": "Başka bir ekibe bağla",
  "Paste the code from Slipwright's Settings → Machines → Connect a machine. A code works for 15 minutes, once.":
    "Slipwright'ta Ayarlar → Makineler → Makine bağla'dan aldığın kodu yapıştır. Kod 15 dakika geçerli ve tek kullanımlık.",
  "Connection code": "Bağlantı kodu",
  Connect: "Bağlan",
  "Connecting…": "Bağlanıyor…",
  "Leave this team": "Bu ekipten ayrıl",
  "This machine forgets the pairing. Remove it on Slipwright's Machines page too.":
    "Bu makine bağlantıyı unutur. Slipwright'taki Makineler sayfasından da kaldırabilirsin.",
  "Last error": "Son hata",

  // models
  "The agents write with this machine's own subscription or key. Keys never leave this machine.":
    "Ajanlar kodu bu makinenin kendi aboneliği veya anahtarıyla yazar. Anahtarlar bu makineden çıkmaz.",
  "Claude Code": "Claude Code",
  Codex: "Codex",
  "Anthropic API": "Anthropic API",
  "OpenAI API": "OpenAI API",
  Subscription: "Abonelik",
  "ChatGPT plan": "ChatGPT planı",
  "claude CLI found": "claude CLI bulundu",
  "codex CLI found": "codex CLI bulundu",
  "not installed": "kurulu değil",
  "signed in": "oturum açık",
  "sign-in not known": "oturum bilinmiyor",
  ready: "hazır",
  "not found": "bulunamadı",
  "No key": "Anahtar yok",
  "Add key": "Anahtar ekle",
  Change: "Değiştir",
  Remove: "Kaldır",
  Save: "Kaydet",
  Cancel: "Vazgeç",
  "Look again": "Tekrar bak",
  "Which agent uses which model": "Hangi ajan hangi modeli kullansın",
  "Install with": "Kurulum",
  "Platforms this machine builds": "Bu makinenin build edebildiği platformlar",
  "Xcode not found": "Xcode bulunamadı",
  "Xcode is installed but was never opened": "Xcode kurulu ama hiç açılmamış",
  "Android SDK found but no JDK": "Android SDK var ama JDK yok",
  "Android SDK not found": "Android SDK bulunamadı",
  "iOS builds need a Mac": "iOS build için Mac gerekir",

  // source
  "The agents read the project's code from here. Read access is enough: only Slipwright writes to the branch.":
    "Ajanlar projenin kodunu buradan çeker. Okuma izni yeterli: branch'e yalnızca Slipwright yazar.",
  "GitHub token": "GitHub token",
  "Bitbucket (optional)": "Bitbucket (isteğe bağlı)",
  "Bitbucket username": "Bitbucket kullanıcı adı",
  "App password": "App password",
  "Save and test": "Kaydet ve dene",
  "Testing…": "Deneniyor…",
  "Without a token the agents answer from the prompt alone.": "Token yoksa ajanlar yalnızca istemdeki bilgiyle yazar.",
  "Leave empty to keep the saved one": "Boş bırakırsan kayıtlı olan kalır",

  // jira
  'When a phase is taken, its issue moves to "In Progress" under your name. Optional.':
    'İş alındığında görev senin adınla "Devam ediyor"a taşınır. İsteğe bağlı.',
  Site: "Site",
  "E-mail": "E-posta",
  "API token": "API token",
  "Connected as {name}": "Bağlantı tamam · {name}",

  // settings
  "How this machine works.": "Bu makinenin nasıl çalışacağı.",
  "Run build and test commands on this machine": "Bu makinede build ve test komutları çalışsın",
  "The commands the agents wrote run in a folder of their own, with a restricted environment.":
    "Ajanların yazdığı komutlar ayrı bir klasörde, kısıtlı ortamla çalışır.",
  "Start when the computer starts": "Bilgisayar açılınca başlasın",
  "Runs in the background with a tray icon.": "Tepsi ikonuyla arka planda çalışır.",
  "Do not take work on battery": "Pil ile çalışırken iş alma",
  "A laptop that is not plugged in takes no new phase.": "Laptop prize takılı değilken yeni faz almaz.",
  "Notify when a task is done": "İş bitince bildirim göster",
  "At most this many tasks at once": "Aynı anda en fazla kaç iş",
  "Work folder": "Çalışma klasörü",
  Theme: "Tema",
  System: "Sistem",
  Light: "Açık",
  Dark: "Koyu",
};

const tables: Record<Lang, Record<string, string>> = { tr, en: {} };

let lang: Lang = "tr";

export function setLang(next: Lang): void {
  lang = next;
}

export function t(key: string, vars: Record<string, string | number> = {}): string {
  const text = tables[lang][key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? `{${name}}`));
}
