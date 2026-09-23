// Turkish. Keys are the English source strings; anything missing shows the English.
export const TR: Record<string, string> = {
  "phase {n}": "faz {n}",
  "Proposed these cases; it writes the tests for the ones you approve":
    "Bu senaryoları önerdi; onayladıklarını test olarak yazacak",
  "Plans the deployment, then takes the finished branch to where the code lives":
    "Dağıtımı planlar, sonra biten dalı kodun yaşadığı yere götürür",
  "Deploys to {target} and takes the finished branch to where the code lives":
    "{target} üzerine dağıtır ve biten dalı kodun yaşadığı yere götürür",
  Repository: "Depo",
  "An existing one": "Var olan bir depo",
  "Open a new one": "Yeni depo aç",
  "Name of the new repository": "Yeni deponun adı",
  Private: "Özel",
  "my-service": "servisim",
  "It is opened on {label} when you create the project, with a first commit in it, and the agents work there from the start.":
    "Projeyi oluşturduğunda {label} üzerinde açılır, içine ilk commit atılır ve ajanlar baştan orada çalışır.",
  "No source is connected yet:": "Henüz bağlı kaynak yok:",
  "connect one": "birini bağla",
  "to work on a hosted repository.": "— barındırılan bir depoda çalışmak için.",
  "Push finished work to (optional)": "Biten işi nereye push'lasın (isteğe bağlı)",
  "What the agents will do": "Ajanlar ne yapacak",
  "{tasks} task(s) in {phases} phase(s) — reword anything before it starts.":
    "{phases} fazda {tasks} görev — başlamadan önce istediğini düzelt.",
  "Everything is fine — start": "Her şey tamam — geliştirmeye başla",
  "Save the wording": "Yazımı kaydet",
  "Have it written again…": "Yeniden yazdır…",
  "What should change?": "Ne değişsin?",
  "{n} item(s)": "{n} madde",
  "Working it out…": "Çıkarılıyor…",
  "Plan it": "Planla",
  "The Product Owner and the Architect answer first; nothing is built yet.":
    "Önce Ürün Sahibi ve Mimar cevap verir; henüz hiçbir şey yazılmaz.",
  "Turned the request into epics, stories and tasks": "İsteği epic, story ve tasklara böldü",
  "Decided how it is built, tested and run":
    "Nasıl kurulacağına, test edileceğine ve çalıştırılacağına karar verdi",
  "Proposes the test cases, then writes the tests you approve":
    "Test senaryolarını önerir, onayladıklarını yazar",
  "Takes the finished branch to where the code lives": "Biten dalı kodun yaşadığı yere götürür",
  "Propose the test cases for the approved backlog":
    "Onaylanan backlog için test senaryolarını öner",
  "Write the tests that cover the approved cases": "Onaylanan senaryoları kapsayan testleri yaz",
  "Push the branch and open a pull request": "Dalı push'la ve pull request aç",
  "Watch the checks and fix what they report": "Kontrolleri izle, bildirdiklerini düzelt",
  "What to build, and how it will be built and tested": "Ne yapılacak, nasıl kurulup test edilecek",
  "One phase per task, each behind the build gate":
    "Her task için bir faz, her biri build kapısından geçer",
  "The cases you approve, then the tests that cover them":
    "Onayladığın senaryolar, sonra onları kapsayan testler",
  "The branch, the pull request and its checks": "Dal, pull request ve kontrolleri",
  Sources: "Kaynaklar",
  "Where the code lives: clone, push and open pull requests.":
    "Kodun yaşadığı yer: klonla, push'la ve pull request aç.",
  "Connect the services your repositories live on. A token is stored encrypted and never shown again; a token from the server's environment is used when none is stored. A project keeps the service it was created from, and new projects start on the one marked":
    "Depolarının bulunduğu servisleri bağla. Token şifreli saklanır ve bir daha gösterilmez; kayıtlı token yoksa sunucunun ortam değişkenindeki kullanılır. Bir proje hangi servisle açıldıysa onunla kalır; yeni projeler aşağıda",
  "add a token to use it": "kullanmak için token ekle",
  "no default {owner}": "varsayılan {owner} yok",
  "token set": "token ayarlı",
  "not connected": "bağlı değil",
  "paste a token": "bir token yapıştır",
  "Create one at": "Buradan oluştur:",
  "New projects look here first when listing repositories.":
    "Yeni projede depolar önce burada aranır.",
  "What a pull request is opened against, and what a finished branch merges into.":
    "Pull request'in açılacağı ve biten dalın birleşeceği dal.",
  "API URL (optional)": "API adresi (isteğe bağlı)",
  "Leave empty for {url}; set for a self-hosted server.":
    "{url} için boş bırak; kendi sunucunu kullanıyorsan doldur.",
  "Workspace or repository access token": "Workspace ya da depo erişim token'ı",
  Workspace: "Workspace",
  "The last {n} days": "Son {n} gün",
  steps: "adım",
  "Where the developments stand": "Gelişimler nerede",
  "Who did the work": "İşi kim yaptı",
  "the numbers": "sayılar",
  Agent: "Ajan",
  "{day}.{month}": "{day}.{month}",
  "build {id}": "sürüm {id}",
  "New version — reload": "Yeni sürüm var — yenile",
  "{running} running · {waiting} waiting for approval · {done} done · {failed} failed · last activity {when}":
    "{running} çalışıyor · {waiting} onay bekliyor · {done} tamam · {failed} başarısız · son hareket {when}",
  "What came out of it": "Ne çıktı ortaya",
  "on its branch": "kendi dalında",
  "merged into {branch}": "{branch} dalına alındı",
  "{files} file(s), +{added} −{removed}, in {commits} commit(s) on":
    "{files} dosya, +{added} −{removed}, {commits} commit —",
  in: "·",
  "and {n} more": "ve {n} dosya daha",
  "Take it into your working copy:": "Kendi çalışma kopyana almak için:",
  "Open the development": "Gelişimi aç",
  "What DevOps wrote about it": "DevOps'un yazdıkları",
  "the branch is no longer in the checkout": "dal artık çalışma kopyasında değil",
  "Runs by itself at startup and every hour: missing epics, stories and sub-tasks are created, stories join the sprint (one is started when none is running), statuses catch up. Nothing to set — this is how a half-mirrored plan repairs itself.":
    "Açılışta ve her saat kendiliğinden çalışır: eksik epic, story ve alt görevler açılır, story'ler sprint'e girer (açık sprint yoksa yenisi başlatılır), durumlar güncellenir. Ayarlanacak bir şey yok — yarım kalmış bir aynalama böyle kendini toparlar.",
  "Once this is set up an approved plan appears in Jira by itself: the Product Owner creates the epics, stories and sub-tasks, the specialists move them as they work, and pull request links and failures are commented. Five tabs, left to right.":
    "Bu kurulum bittiğinde onayladığın plan Jira'ya kendiliğinden düşer: Ürün Sahibi epic, story ve alt görevleri açar, uzmanlar çalıştıkça onları ilerletir, pull request bağlantıları ve hatalar yorum olarak eklenir. Beş sekme, soldan sağa.",
  Connection: "Bağlantı",
  "Agent account": "Ajan hesabı",
  "Issue types": "Konu tipleri",
  "The round": "Tur",
  "The connection": "Bağlantı",
  "The Jira site and the account Slipwright signs in with. Nothing works without it.":
    "Jira siteniz ve Slipwright'ın giriş yapacağı hesap. Bu olmadan hiçbiri çalışmaz.",
  connected: "bağlı",
  "not connected yet": "henüz bağlı değil",
  "Who the agents write as": "Ajanlar kimin adına yazsın",
  "Optional: a second Jira account for the bot, so comments and transitions carry its name instead of yours.":
    "İsteğe bağlı: bot için ayrı bir Jira hesabı — yorumlar ve durum değişiklikleri senin adınla değil onun adıyla görünür.",
  "its own account": "kendi hesabı",
  "your account": "senin hesabın",
  "What your Jira site calls an epic, a story, a task and a bug. The defaults fit most sites.":
    "Jira sitende epic, story, task ve bug'ın hangi adla geçtiği. Varsayılanlar çoğu siteye uyar.",
  defaults: "varsayılan",
  "Which project goes where": "Hangi proje nereye gidiyor",
  "Each Slipwright project mirrors into one Jira project, and each task status becomes a transition there.":
    "Her Slipwright projesi bir Jira projesine aynalanır; her task durumu orada bir geçişe karşılık gelir.",
  "per project": "proje bazında",
  "Create one in Atlassian under Account settings → Security → API tokens.":
    "Atlassian'da Hesap ayarları → Güvenlik → API token'ları altından oluştur.",
  "agents act as": "ajanlar şu hesapla davranıyor:",
  "Projects this account can see:": "Bu hesabın gördüğü projeler:",
  none: "yok",
  "Tasks default to": "Tasklar varsayılan olarak",
  "Open the Connection tab first: Jira is not connected yet.":
    "Önce Bağlantı sekmesini aç: Jira henüz bağlı değil.",
  "No agent account is set: agents would act through the human connection ({email}).":
    "Ajan hesabı ayarlı değil: ajanlar senin bağlantınla ({email}) davranır.",
  "The name of the transition in your workflow, not the status: leave one empty to skip it.":
    "İş akışındaki geçişin adı (durumun adı değil); boş bırakırsan o geçiş atlanır.",
  "Agent account saved": "Ajan hesabı kaydedildi",
  "Jira mapping saved": "Jira eşleştirmesi kaydedildi",
  "last run {when}": "son tur {when}",
  "not run yet": "henüz çalışmadı",
  in_progress: "devam ediyor",
  epic: "epic",
  story: "story",
  task: "task",
  bug: "bug",
  "{n} waiting": "{n} bekliyor",
  "{n} running": "{n} çalışıyor",
  "local checkout": "yerel çalışma kopyası",
  "{n} development(s)": "{n} gelişim",
  "{n} failed": "{n} başarısız",
  "active {when}": "son hareket {when}",
  "No project matches “{query}”.": "“{query}” ile eşleşen proje yok.",
  "{n} (vendor default)": "{n} (sağlayıcı varsayılanı)",
  "not set": "ayarlı değil",
  "so they nest under stories;": "olur, böylece story altına yerleşir;",
  "is for older sites.": "ise eski siteler içindir.",
  your: "senin",
  folder: "klasörün",
  "A folder that is not a git repository yet becomes one on create, with everything in it committed.":
    "Henüz git deposu olmayan bir klasör, oluştururken depoya dönüştürülür ve içindeki her şey commit'lenir.",
  server: "sunucunun",
  "and enter": "yaz, sonra şunu gir:",
  "Loading…": "Yükleniyor…",
  "Not found.": "Bulunamadı.",
  passed: "geçti",
  error: "hata",
  domain: "alan",
  backend: "backend",
  web: "web",
  mobile: "mobil",
  infra: "altyapı",
  docs: "doküman",
  general: "genel",
  "Approved plans are mirrored as epics, stories and sub-tasks here; task statuses map to the transition names below.":
    "Onaylanan planlar burada epic, story ve alt görev olarak aynalanır; task durumları aşağıdaki geçiş adlarıyla eşleşir.",
  "GitHub repository (owner/name)": "GitHub deposu (sahip/ad)",
  "Retry continues from the step that failed": "Yeniden dene, hata alınan adımdan devam eder",
  "everything built so far stays.": "o ana kadar üretilen her şey kalır.",
  "QA proposes these test cases. Add, remove or rewrite them; the tests written next cover exactly this list.":
    "QA bu test senaryolarını öneriyor. Ekle, çıkar ya da yeniden yaz; sonra yazılacak testler tam olarak bu listeyi kapsar.",
  "No login exists yet. Create the first (admin) user on the server:":
    "Henüz bir giriş yok. İlk (yönetici) kullanıcıyı sunucuda oluştur:",
  "Pick a folder under {root}…": "{root} altından bir klasör seç…",
  "Repository (owner/name)": "Depo (sahip/ad)",
  development: "gelişim",
  "With Jira connected, every approved plan is mirrored as epics, stories and sub-tasks in the project's Jira project, issues move as tasks complete, and PR links and failures are commented. This is the connection used by the engine; the account the agents themselves act as, and which Jira project each Slipwright project mirrors into, are set below.":
    "Jira bağlıyken onaylanan her plan, projenin Jira projesine epic, story ve alt görev olarak aynalanır; tasklar bittikçe issue'lar ilerler, PR bağlantıları ve hatalar yorum olarak düşülür. Bu, motorun kullandığı bağlantıdır; ajanların hangi hesapla davrandığı ve hangi Slipwright projesinin hangi Jira projesine aynalandığı aşağıda ayarlanır.",
  "so they nest under stories; use": "böylece story altına yerleşirler; eski sitelerde",
  "Last round {when}: {jobs} development(s) checked, {updated} updated, {errors} with Jira errors.":
    "Son tur {when}: {jobs} gelişim denetlendi, {updated} güncellendi, {errors} tanesinde Jira hatası.",
  "Copy it now; it will not be shown again:": "Şimdi kopyala; bir daha gösterilmeyecek:",
  "Enter an API key for each provider you want to use. Keys are stored encrypted and never shown again; a key from the server's environment is used when none is stored. Every agent runs on the provider marked":
    "Kullanmak istediğin her sağlayıcı için bir API anahtarı gir. Anahtarlar şifreli saklanır ve bir daha gösterilmez; kayıtlı anahtar yoksa sunucunun ortam değişkenindeki kullanılır. Her ajan aşağıda",
  "below, on that provider's": "işaretli sağlayıcıda, o sağlayıcının",
  default: "varsayılan",
  "— unless a role is pinned to a provider and model of its own under":
    "ile çalışır — bir rol kendi sağlayıcı ve modeline sabitlenmemişse:",
  "(from {env})": "({env} ortamından)",
  "set, ends with {hint}": "kayıtlı, sonu {hint}",
  "or set": "ya da sunucuda",
  "Leave empty for {url}; set for proxies.":
    "{url} için boş bırak; vekil sunucu kullanacaksan doldur.",
  "Connected. {n} model(s) available:": "Bağlandı. {n} model kullanılabilir:",
  "Copy to clipboard": "Panoya kopyala",
  Copy: "Kopyala",
  Copied: "Kopyalandı",
  // -- navigation, shell -------------------------------------------------------------------
  Dashboard: "Panel",
  Projects: "Projeler",
  Agents: "Ajanlar",
  Settings: "Ayarlar",
  Models: "Modeller",
  Users: "Kullanıcılar",
  "Log out": "Çıkış yap",
  Theme: "Tema",
  Light: "Açık",
  Dark: "Koyu",
  System: "Sistem",
  admin: "yönetici",
  member: "üye",

  // -- generic actions -----------------------------------------------------------------------
  Approve: "Onayla",
  "Reject…": "Reddet…",
  "Send rejection": "Reddi gönder",
  Cancel: "Vazgeç",
  Close: "Kapat",
  Clear: "Temizle",
  Save: "Kaydet",
  "Saving…": "Kaydediliyor…",
  Saved: "Kaydedildi.",
  "Saved.": "Kaydedildi.",
  Delete: "Sil",
  Remove: "Kaldır",
  Edit: "Düzenle",
  Open: "Aç",
  Search: "Ara",
  "Search…": "Ara…",
  Send: "Gönder",
  Set: "Ayarla",
  Retry: "Yeniden dene",
  "Retrying…": "Yeniden deneniyor…",
  "Retry with a note…": "Notla yeniden dene…",
  "Send & retry": "Gönder ve yeniden dene",
  "Undo…": "Geri al…",
  "Create project": "Proje oluştur",
  "Creating…": "Oluşturuluyor…",
  "Cloning…": "Klonlanıyor…",
  "Run now": "Şimdi çalıştır",
  "Running…": "Çalışıyor…",
  "Test connection": "Bağlantıyı sına",
  "Testing…": "Sınanıyor…",
  "Use as default": "Varsayılan yap",
  "Remove key": "Anahtarı kaldır",
  "Select all": "Tümünü seç",
  "Select all waiting": "Bekleyenlerin tümünü seç",
  "Approve selected": "Seçilenleri onayla",
  "Reject selected…": "Seçilenleri reddet…",
  "Bulk approvals": "Toplu onay",
  "{n} selected": "{n} seçili",
  "feedback for every selected gate": "seçili her kapı için geri bildirim",
  "what should change?": "ne değişmeli?",
  "what the agent should know this time": "ajan bu sefer neyi bilmeli",
  "what the supervisor missed": "denetçinin gözden kaçırdığı şey",
  "continue from the step that failed; what was built stays":
    "düştüğü adımdan devam eder; yapılanlar kalır",
  "no detail": "ayrıntı yok",
  more: "devamı",
  less: "kısalt",
  "the record as JSON": "kaydın JSON hâli",
  "what happened": "ne oldu",
  "open development →": "geliştirmeyi aç →",
  "open ↗": "aç ↗",
  "… still running": "… hâlâ çalışıyor",
  "unsaved changes": "kaydedilmemiş değişiklik",
  "unsaved changes — save before approving": "kaydedilmemiş değişiklik — onaylamadan önce kaydet",

  // -- states, statuses, kinds --------------------------------------------------------------
  created: "oluşturuldu",
  "writing backlog": "backlog yazılıyor",
  "needs backlog approval": "backlog onayı bekliyor",
  designing: "mimari kurgulanıyor",
  "needs architecture approval": "mimari onayı bekliyor",
  developing: "geliştiriliyor",
  "build gate": "build kapısı",
  "standards review": "standart incelemesi",
  "needs review decision": "inceleme kararı bekliyor",
  qa: "QA",
  "needs test approval": "test onayı bekliyor",
  devops: "DevOps",
  "needs your decision": "kararını bekliyor",
  done: "tamam",
  failed: "başarısız",
  pending: "bekliyor",
  running: "çalışıyor",
  waiting: "seni bekliyor",
  todo: "yapılacak",
  "in progress": "sürüyor",
  "needs {pending}": "{pending} bekliyor",
  backlog: "backlog",
  architecture: "mimari",
  review: "inceleme",
  decision: "karar",
  "test cases": "test vakaları",
  "written tests": "yazılan testler",
  started: "başladı",
  agent: "ajan",
  you: "sen",
  steering: "yönlendirme",
  jira: "jira",
  standards: "standartlar",
  crash: "çökme",
  other: "diğer",
  gate: "kapı",
  diff: "diff",

  // -- roles ------------------------------------------------------------------------------------
  "Product Owner": "Ürün Sahibi",
  Architect: "Mimar",
  Backend: "Backend",
  "Web UI": "Web Arayüzü",
  "Mobile UI": "Mobil Arayüz",
  QA: "QA",
  DevOps: "DevOps",
  Supervisor: "Denetçi",
  "all domains": "tüm alanlar",

  // -- dashboard ----------------------------------------------------------------------------------
  "What the agents are doing right now, and what waits for you.":
    "Ajanların şu an ne yaptığı ve senden ne beklendiği.",
  "Waiting for you": "Seni bekleyen",
  "Tasks done": "Biten görevler",
  Outcomes: "Sonuçlar",
  Running: "Çalışan",
  "Pending approvals": "Onay bekleyenler",
  "Recent activity": "Son etkinlik",
  "Approved by the supervisor": "Denetçinin onayladıkları",
  "Nothing waits for you.": "Seni bekleyen bir şey yok.",
  "No activity yet.": "Henüz etkinlik yok.",
  "Add a project": "Proje ekle",
  "Add your first project": "İlk projeni ekle",
  "Start a development": "Bir geliştirme başlat",
  "A project is a repository the agents work on. Connect GitHub under Settings, or point at a local checkout.":
    "Proje, ajanların üzerinde çalıştığı bir depodur. Ayarlar'dan GitHub'ı bağla ya da yerel bir klasörü göster.",
  "{n} development(s) in total": "toplam {n} geliştirme",
  "agents working now": "şu an çalışan ajanlar",
  "approvals pending": "onay bekliyor",
  "nothing pending": "bekleyen yok",
  "needs {pending} approval": "{pending} onayı bekliyor",

  // -- projects ----------------------------------------------------------------------------------
  "New project": "Yeni proje",
  "Repositories the agents work on.": "Ajanların üzerinde çalıştığı depolar.",
  "A project is a repository Slipwright works on: add one from a local checkout or a GitHub repository, then start a development by describing what you want.":
    "Proje, Slipwright'ın üzerinde çalıştığı bir depodur: yerel bir klasörden ya da GitHub deposundan ekle, sonra ne istediğini yazarak bir geliştirme başlat.",
  "No projects yet": "Henüz proje yok",
  "No projects yet.": "Henüz proje yok.",
  "Add the first project": "İlk projeyi ekle",
  "No description": "Açıklama yok",
  "A repository for the agents to work on.": "Ajanların üzerinde çalışacağı bir depo.",
  Name: "Ad",
  Description: "Açıklama",
  "What this project is, for the people who will read the board":
    "Bu proje nedir — panoyu okuyacak kişiler için",
  Source: "Kaynak",
  "GitHub repository": "GitHub deposu",
  "Local checkout": "Yerel klasör",
  "Path on the server": "Sunucudaki yol",
  Checkout: "Klasör",
  "Type a path instead": "Bunun yerine yol yaz",
  "Pick from the list": "Listeden seç",
  "Pick a repository…": "Bir depo seç…",
  "GitHub repository (optional)": "GitHub deposu (isteğe bağlı)",
  "Run the tests again": "Testleri tekrar çalıştır",
  "Run DevOps again": "DevOps'u tekrar çalıştır",
  "Runs the test command over this development's worktree.":
    "Bu geliştirmenin çalışma kopyasında test komutunu çalıştırır.",
  "Writes the pull request again, pushes the branch and opens it.":
    "Pull request metnini yeniden yazar, dalı push'lar ve PR'ı açar.",
  "Where finished work is pushed: each development pushes its branch and opens a pull request there. Leave it empty and the branch stays in the checkout for you to merge by hand.":
    "Biten iş buraya push'lanır: her geliştirme kendi dalını push'lar ve orada bir pull request açar. Boş bırakırsan dal klasörde kalır, merge'ü elle yaparsın.",
  "No GitHub token is configured, so nothing can be pushed.":
    "GitHub token'ı tanımlı değil, bu yüzden hiçbir şey push'lanamaz.",
  "No GitHub token is configured, so private repositories cannot be cloned.":
    "GitHub token'ı tanımlı değil, bu yüzden özel depolar klonlanamaz.",
  "Jira project (optional)": "Jira projesi (isteğe bağlı)",
  "Not linked": "Bağlı değil",
  "Connect Jira": "Jira'yı bağla",
  "Connect GitHub": "GitHub'ı bağla",
  "to mirror epics, stories and tasks.": "epic, story ve taskları aynalamak için.",
  "to pick from your repositories.": "depolarından seçmek için.",
  "What should the agents build first? (optional)": "Ajanlar önce ne yapsın? (isteğe bağlı)",
  "e.g. Add a /health endpoint that reports the database status, with tests":
    "örn. Veritabanı durumunu dönen bir /health endpoint'i ekle, testleriyle",
  "e.g. Add a /health endpoint that reports the database status":
    "örn. Veritabanı durumunu dönen bir /health endpoint'i ekle",
  "Every request becomes a": "Her istek bir",
  ": the Product Owner turns it into epics, stories and tasks for you to approve, the Architect plans it, the specialists build it. You can add more later from the project's":
    " olur: Ürün Sahibi onu onaylaman için epic, story ve tasklara böler, Mimar planlar, uzmanlar yapar. Sonradan projenin",
  "tab.": "sekmesinden yenilerini ekleyebilirsin.",
  "The path as the": "Yol,",
  "sees it. In Docker only the mounted folder is visible: put the checkout under":
    "gördüğü haliyle. Docker'da yalnızca bağlanan klasör görünür: klasörü",
  "These are the folders under": "Bunlar şu klasörün altındakiler:",
  "e.g. DEM": "örn. DEM",
  "Edit project": "Projeyi düzenle",
  "Delete project": "Projeyi sil",
  "and its finished developments? The repository on disk is not touched. Projects with a running development cannot be deleted.":
    "ve biten geliştirmeleri silinsin mi? Diskteki depoya dokunulmaz. Çalışan geliştirmesi olan proje silinemez.",
  "Jira project key": "Jira proje anahtarı",
  Language: "Dil",
  "Language the agents write in": "Ajanların yazdığı dil",
  Turkish: "Türkçe",
  English: "İngilizce",
  "Backlog titles and descriptions (and so Jira), plan summaries, test cases and every summary are written in this language; code stays in English.":
    "Backlog başlıkları ve açıklamaları (dolayısıyla Jira), plan özetleri, test vakaları ve tüm özetler bu dilde yazılır; kod İngilizce kalır.",
  "Jira sprint for mirrored stories": "Aynalanan story'ler için Jira sprint'i",
  "running sprint, else start a new one for the development":
    "aktif sprint; yoksa geliştirme için yeni bir sprint başlat",
  "running sprint only, else leave them in the backlog":
    "yalnızca aktif sprint; yoksa backlog'da kalsın",
  "never — stories stay in the backlog": "hiç — story'ler backlog'da kalır",
  "Standards review after each phase": "Her fazdan sonra standart incelemesi",
  "off — never review": "kapalı — inceleme yok",
  "advisory — record findings, never block": "öneri — bulguları kaydet, hiç durdurma",
  "blocking — the specialist fixes, then you decide":
    "engelleyici — uzman düzeltir, sonra sen karar verirsin",
  "QA checks every phase's diff against the standards its specialist was given. In blocking mode a blocking finding sends the phase back (two rounds) before it waits for you.":
    "QA her fazın diff'ini uzmanına verilen standartlarla karşılaştırır. Engelleyici modda engelleyici bir bulgu fazı (iki tur) geri gönderir, sonra seni bekler.",
  "Supervisor at the gates": "Kapılarda denetçi",
  "manual — no supervisor, you decide every gate":
    "manuel — denetçi yok, her kapıya sen karar verirsin",
  "assisted — a recommendation next to each gate, you decide":
    "yardımcı — her kapının yanında öneri, karar senin",
  "auto — confident low-risk approvals are made for you":
    "otomatik — emin ve düşük riskli onaylar senin yerine verilir",
  "Confidence needed": "Gereken güven",
  "Automatic approvals per development": "Geliştirme başına otomatik onay",
  "let it approve the written tests too (the gate before the pull request)":
    "yazılan testleri de onaylasın (pull request'ten önceki kapı)",
  "Rejections are never automatic; every automatic approval is recorded on the job and can be undone from the dashboard while the next step runs.":
    "Ret asla otomatik değildir; her otomatik onay işe kaydedilir ve sonraki adım çalışırken panelden geri alınabilir.",
  "Budget per development (blank = unlimited)": "Geliştirme başına bütçe (boş = sınırsız)",
  Tokens: "Token",
  "Wall clock (seconds)": "Süre (saniye)",
  "Model calls": "Model çağrıları",
  "Exceeding a limit fails the development with the reason in its history — never silently.":
    "Bir sınır aşılırsa geliştirme, sebebi geçmişine yazılarak durur — asla sessizce değil.",
  "The checkout path (": "Klasör yolu (",
  ") cannot be changed here; models and permissions per role live under Agents.":
    ") buradan değiştirilemez; rol başına model ve izinler Ajanlar altında.",

  // -- project tabs ----------------------------------------------------------------------------------
  Pipeline: "Akış",
  Overview: "Genel bakış",
  Board: "Pano",
  Developments: "Geliştirmeler",
  Tests: "Testler",
  Activity: "Etkinlik",
  "New development": "Yeni geliştirme",
  "Describe what you want. The Product Owner turns it into epics, stories and tasks, the Architect designs how to build and test it, and you approve each step.":
    "Ne istediğini yaz. Ürün Sahibi bunu epic, story ve tasklara böler, Mimar nasıl yapılıp test edileceğini kurgular, her adımı sen onaylarsın.",
  "Start development": "Geliştirmeyi başlat",
  "Starting…": "Başlatılıyor…",
  "No developments yet. Describe one above to start.":
    "Henüz geliştirme yok. Başlamak için yukarıya bir tane yaz.",
  "No development is running.": "Çalışan geliştirme yok.",
  Progress: "İlerleme",
  "{running} running · {pending} waiting for approval · {done} done · {failed} failed · last activity {ago}":
    "{running} çalışıyor · {pending} onay bekliyor · {done} tamam · {failed} başarısız · son etkinlik {ago}",
  "Standards review: {n} review(s)": "Standart incelemesi: {n} inceleme",
  "{n} blocking": "{n} engelleyici",
  "{n} advisory finding(s)": "{n} öneri bulgusu",
  "Epics → stories → tasks": "Epic → story → task",
  "The board fills in once a development's plan is approved: each epic, story and task appears here and moves as the work is done.":
    "Pano bir geliştirmenin planı onaylanınca dolar: her epic, story ve task burada görünür ve iş ilerledikçe hareket eder.",
  "Every build gate the engine runs is recorded here, and you can run the project's test command yourself at any time.":
    "Motorun çalıştırdığı her build kapısı burada kayıtlıdır; projenin test komutunu istediğin zaman kendin de çalıştırabilirsin.",
  "Run tests": "Testleri çalıştır",
  "No test runs yet": "Henüz test çalıştırması yok",
  "main checkout": "ana klasör",
  "on the main checkout": "ana klasörde",
  "any job": "herhangi bir iş",
  "any status": "herhangi bir durum",
  Command: "Komut",
  Duration: "Süre",
  Started: "Başlangıç",
  Status: "Durum",
  Job: "İş",
  "Nothing has happened yet.": "Henüz bir şey olmadı.",
  "Last activity": "Son etkinlik",
  State: "Durum",
  Request: "İstek",
  Created: "Oluşturulma",
  "Delete development": "Geliştirmeyi sil",
  "? Its worktree, branch, history and test runs are removed. A pull request already opened stays on GitHub.":
    " silinsin mi? Worktree'si, dalı, geçmişi ve test çalıştırmaları kaldırılır. Açılmış bir pull request GitHub'da kalır.",

  // -- pipeline -----------------------------------------------------------------------------------------
  "Every development shows up here as a lane of steps: what the agents did, what runs now, and what waits for you.":
    "Her geliştirme burada bir adım şeridi olarak görünür: ajanların yaptıkları, şu an çalışan ve seni bekleyen.",
  "No development yet": "Henüz geliştirme yok",
  "Start one": "Bir tane başlat",
  "{n} development(s) waiting for your approval": "{n} geliştirme onayını bekliyor",
  "Select all recommended ({n})": "Önerilenlerin tümünü seç ({n})",
  "the gates the supervisor recommends approving": "denetçinin onaylanmasını önerdiği kapılar",
  "started {ago}": "{ago} başladı",

  // -- dashboard charts ---------------------------------------------------------------------
  "Activity, last 14 days": "Etkinlik — son 14 gün",
  "What each agent did": "Hangi ajan ne yaptı",
  events: "olay",
  finished: "biten",
  runs: "çalışma",
  "in total": "toplam",
  "waiting for you": "seni bekliyor",
  "table view": "tablo görünümü",
  Day: "Gün",
  "{done} of {total} steps": "{total} adımın {done} tanesi",
  "What was asked": "İstenen",
  "The plan": "Plan",
  "show more": "devamını göster",
  "show less": "kısalt",
  Planning: "Planlama",
  Building: "Geliştirme",
  Testing: "Test",
  Delivery: "Teslim",
  "recommends approve": "onay öneriyor",
  "recommends reject": "ret öneriyor",
  "approved by supervisor": "denetçi onayladı",
  Backlog: "Backlog",
  "Backlog approval": "Backlog onayı",
  Architecture: "Mimari",
  "Architecture approval": "Mimari onayı",
  Develop: "Geliştirme",
  "QA: test cases": "QA: test vakaları",
  "Test cases approval": "Test vakaları onayı",
  "QA: write tests": "QA: testleri yaz",
  "Written tests approval": "Yazılan testlerin onayı",
  Done: "Tamam",
  "Your decision": "Senin kararın",
  "Review approval: phase {n}": "İnceleme onayı: faz {n}",
  "Nothing recorded for this step yet.": "Bu adım için henüz kayıt yok.",
  "Waiting for your approval of the": "Onayını bekleyen:",
  "Rename epics, stories and tasks or add and remove tasks; the Architect designs one phase per task from what you approve.":
    "Epic, story ve taskları yeniden adlandır ya da task ekle/çıkar; Mimar onayladığın her task için bir faz kurgular.",
  Phases: "Fazlar",
  Profile: "Profil",
  "Save & approve": "Kaydet ve onayla",
  "QA proposed these cases; edit the list, then approve it.":
    "QA bu vakaları önerdi; listeyi düzenle, sonra onayla.",

  // -- job page ------------------------------------------------------------------------------------------
  "Waiting for your approval of the {pending}": "Onayını bekleyen: {pending}",
  "Failed:": "Başarısız:",
  detail: "ayrıntı",
  "Retry continues from the step that failed (": "Yeniden deneme düştüğü adımdan devam eder (",
  "); everything built so far stays.": "); şimdiye kadar yapılanlar kalır.",
  "The Product Owner turned the request into epics, stories and tasks. Once approved they are mirrored to Jira and the Architect designs one phase per task.":
    "Ürün Sahibi isteği epic, story ve tasklara böldü. Onaylanınca Jira'ya aynalanır ve Mimar her task için bir faz kurgular.",
  Decisions: "Kararlar",
  "The Architect proposes how the project is built, tested and run. Edit anything before approving; the roles come from the project's seed profile and stay a human decision.":
    "Mimar projenin nasıl kurulup test edilip çalıştırılacağını öneriyor. Onaylamadan önce dilediğini düzenle; roller projenin çekirdek profilinden gelir ve insan kararı olarak kalır.",
  "Save changes": "Değişiklikleri kaydet",
  "Approving continues with": "Onaylarsan şununla devam eder:",
  "as it was; rejecting continues too, with your feedback delivered to the agent that runs next. Nothing more is spent until you decide.":
    "; reddedersen de devam eder, geri bildirimin sıradaki ajana iletilir. Karar verene kadar başka harcama yapılmaz.",
  "Phase {n} passed the build but still breaks {b} blocking standard(s) after {r} fix round(s). Approving keeps the phase as built and continues; rejecting sends it back to the specialist with your feedback.":
    "Faz {n} build'i geçti ama {r} düzeltme turundan sonra hâlâ {b} engelleyici standardı ihlal ediyor. Onaylarsan faz olduğu gibi kalır ve devam edilir; reddedersen geri bildiriminle uzmana geri gider.",
  "No findings.": "Bulgu yok.",
  Severity: "Önem",
  Section: "Bölüm",
  Where: "Nerede",
  Finding: "Bulgu",
  blocking: "engelleyici",
  advisory: "öneri",
  "fix: ": "düzeltme: ",
  "Add case": "Vaka ekle",
  "Save list": "Listeyi kaydet",
  "QA wrote tests for the approved cases and they passed the build gate. Approving hands the branch to DevOps.":
    "QA onaylanan vakalar için testleri yazdı ve build kapısını geçtiler. Onaylarsan dal DevOps'a geçer.",
  "Phase {n}: {goal}": "Faz {n}: {goal}",
  "in review": "incelemede",
  "Model calls (title)": "Model çağrıları",
  "{calls} call(s) · {attempts} attempt(s) · {tokens} tokens":
    "{calls} çağrı · {attempts} deneme · {tokens} token",
  When: "Ne zaman",
  Role: "Rol",
  Step: "Adım",
  Prompt: "İstem",
  "Tokens in / out": "Token giriş / çıkış",
  Attempts: "Deneme",
  Result: "Sonuç",
  "Test cases": "Test vakaları",
  "What it checks": "Neyi kontrol eder",
  "what it checks": "neyi kontrol eder",
  Steering: "Yönlendirme",
  "Messages reach the next role that runs; each is delivered exactly once.":
    "Mesajlar sıradaki role ulaşır; her biri tam olarak bir kez iletilir.",
  "message for the next role": "sıradaki role mesaj",
  "read by": "okuyan:",
  History: "Geçmiş",
  "Approved profile": "Onaylanan profil",
  "created {time}": "oluşturulma {time}",

  // -- agents ---------------------------------------------------------------------------------------------
  "Each card shows the provider and model the agent runs on right now; open one for its setup, standards and activity.":
    "Her kart ajanın şu an çalıştığı sağlayıcı ve modeli gösterir; kurulumu, standartları ve etkinliği için birini aç.",
  "{n} invocation(s)": "{n} çağrı",
  "used {ago}": "{ago} kullanıldı",
  "never used": "hiç kullanılmadı",
  Model: "Model",
  Thinking: "Düşünme",
  Standards: "Standartlar",
  Setup: "Kurulum",
  "This agent has not run yet.": "Bu ajan henüz çalışmadı.",
  "Thinking depth and permissions are read from the project's seed profile — never from engine code. Pick a project; projects without their own profile start from the engine default and get one when you save.":
    "Düşünme derinliği ve izinler projenin çekirdek profilinden okunur — asla motor kodundan değil. Bir proje seç; kendi profili olmayan projeler motor varsayılanından başlar ve kaydedince kendi profilini alır.",
  "Project profile": "Proje profili",
  "assigned — every project": "atanmış — her projede",
  "follows the default provider (Settings → Models)":
    "varsayılan sağlayıcıyı izler (Ayarlar → Modeller)",
  "Pick the provider and model this agent works with. It runs there on every project, whatever the project profile says; if the provider cannot be reached the job fails with the reason.":
    "Bu ajanın çalışacağı sağlayıcıyı ve modeli seç. Proje profili ne derse desin her projede orada çalışır; sağlayıcıya ulaşılamazsa iş nedeniyle birlikte başarısız olur.",
  "pick a model…": "bir model seç…",
  "the provider's default model": "sağlayıcının varsayılan modeli",
  "add a key under Settings → Models first": "önce Ayarlar → Modeller altında bir anahtar ekle",
  "model id": "model kimliği",
  "no API key for {provider}": "{provider} için API anahtarı yok",
  "Connected to {provider}: {n} model(s).": "{provider} bağlantısı kuruldu: {n} model.",
  "{model} is available.": "{model} kullanılabilir.",
  "{model} is not in the vendor's list — it may still fail at run time.":
    "{model} sağlayıcının listesinde yok — çalışma anında yine de başarısız olabilir.",
  "Clear assignment": "Atamayı kaldır",
  "{agent} now runs on {model}": "{agent} artık {model} ile çalışıyor",
  "{agent} follows the default provider again": "{agent} yeniden varsayılan sağlayıcıyı izliyor",
  assigned: "atanmış",
  "Create one": "Bir tane oluştur",
  "first.": "önce.",
  Project: "Proje",
  "project profile": "proje profili",
  "engine default (saved into the project on save)":
    "motor varsayılanı (kaydedince projeye yazılır)",
  Provider: "Sağlayıcı",
  "default ({provider})": "varsayılan ({provider})",
  "Thinking depth": "Düşünme derinliği",
  Permissions: "İzinler",
  Roles: "Roller",
  Routing: "Yönlendirme",
  "Build command": "Build komutu",
  "Test command": "Test komutu",
  "Package manager": "Paket yöneticisi",
  "Default port": "Varsayılan port",

  // -- standards tab --------------------------------------------------------------------------------------
  Scope: "Kapsam",
  "every project": "her proje",
  "only {name}": "yalnızca {name}",
  "Add rule": "Kural ekle",
  Rules: "Kurallar",
  Title: "Başlık",
  "At each step the {role} agent reads the rules below that best match its task (up to {k}), plus the shared rules. Write them in any language — the model reads it.":
    "{role} ajanı her adımda aşağıdaki listeden görevine en çok uyan kuralları (en fazla {k}) ve ortak kuralları okur. İstediğin dilde yaz — modeli anlar.",
  "At each step the {role} agent reads the rules below that best match its task, plus the shared rules. Write them in any language — the model reads it.":
    "{role} ajanı her adımda aşağıdaki listeden görevine en çok uyan kuralları ve ortak kuralları okur. İstediğin dilde yaz — modeli anlar.",
  "Rules in this scope apply to that project only and win over the shared list.":
    "Bu kapsamdaki kurallar yalnızca o projeye uygulanır ve genel listeye göre önceliklidir.",
  "No rules yet. Add the first one.": "Henüz kural yok. İlkini ekle.",
  "No project-specific rules yet — a rule added here applies to that project only.":
    "Bu projeye özel kural henüz yok — buraya eklenen kural yalnızca o projeye uygulanır.",
  "Shared rules — every agent": "Ortak kurallar — her ajan",
  "Read in full by every agent on every project; a rule above never overrides them.":
    "Her projede her ajan tamamını okur; yukarıdaki bir kural bunları asla geçersiz kılamaz.",
  "Shared rules are edited under the every-project scope.":
    "Ortak kurallar “her proje” kapsamında düzenlenir.",
  "No shared rules.": "Ortak kural yok.",
  "Which rules would this agent get?": "Bu ajana hangi kurallar gider?",
  "Write a task the way you would give it, and see the list it would be handed.":
    "Vereceğin gibi bir görev yaz, ajana gidecek listeyi gör.",
  "How matching works — index settings": "Eşleşme nasıl çalışır — dizin ayarları",
  "Embeddings, how many rules a step gets and the token budget.":
    "Gömmeler, bir adımın kaç kural alacağı ve token bütçesi.",
  "Nothing is sent to the agent from here — this only shows which rules a task of that shape would pull in.":
    "Buradan ajana bir şey gönderilmez — yalnızca bu şekildeki bir görevin hangi kuralları çekeceğini gösterir.",
  "Looking through the rules…": "Kurallara bakılıyor…",
  "The top {k} go into the prompt, together with the shared rules.":
    "İlk {k} tanesi ortak kurallarla birlikte isteme girer.",
  "goes to the agent": "ajana gider",
  "not this time": "bu görevde gitmez",
  "keyword {kw} · meaning {sem}": "anahtar kelime {kw} · anlam {sem}",
  "this project": "bu proje",
  "read the rule": "kuralı oku",
  "Rule title — e.g. Every story has an acceptance criterion":
    "Kural başlığı — örn. Her story'nin bir kabul kriteri olur",
  "What the agent must do or watch out for, and why. Markdown is fine; keep it under 400 words.":
    "Ajanın ne yapması ya da nelere dikkat etmesi gerektiği ve nedeni. Markdown kullanabilirsin; 400 kelimeyi geçme.",
  "Rule added": "Kural eklendi",
  "Rule saved": "Kural kaydedildi",
  "Rule deleted": "Kural silindi",
  "Delete rule": "Kuralı sil",
  "Delete “{heading}”? It stops reaching the agent as soon as the index refreshes.":
    "“{heading}” silinsin mi? Dizin yenilenir yenilenmez ajana ulaşmaz olur.",
  "Try a search": "Arama dene",
  "Type a task the way a phase goal reads and see which rules the agent would be given, ranked.":
    "Bir faz hedefi gibi bir görev yaz ve ajana hangi kuralların verileceğini sıralı gör.",
  "e.g. add a Kafka consumer that retries failed messages":
    "örn. başarısız mesajları yeniden deneyen bir Kafka consumer ekle",
  "Nothing matched; the agent would get the domain's opening rules instead.":
    "Eşleşen yok; ajan bunun yerine alanın ilk kurallarını alır.",
  Index: "Dizin",
  "Reindex now": "Şimdi yeniden dizinle",
  "Reindexing…": "Yeniden dizinleniyor…",
  Embedder: "Gömme modeli",
  "Embedding model": "Gömme modeli",
  "Local model": "Yerel model",
  "Sections per role (top k)": "Rol başına bölüm (top k)",
  "Token budget per prompt": "İstem başına token bütçesi",
  "Save settings": "Ayarları kaydet",
  "none — keyword search only": "yok — yalnızca anahtar kelime araması",
  "openai — text embeddings (needs an OpenAI key)":
    "openai — metin gömmeleri (OpenAI anahtarı gerekir)",
  "local — sentence-transformers on this machine": "yerel — bu makinede sentence-transformers",
  "hashing — offline stand-in": "hashing — çevrimdışı yedek",
  "task title": "task başlığı",
  "Add task": "Task ekle",
  "Remove task": "Taskı kaldır",
  "Move up": "Yukarı taşı",
  "Move down": "Aşağı taşı",
  "what this phase builds": "bu faz ne yapar",
  "files, comma separated": "dosyalar, virgülle",

  // -- settings: models ---------------------------------------------------------------------------------------
  "API keys for Anthropic, OpenAI and DeepSeek.":
    "Anthropic, OpenAI ve DeepSeek için API anahtarları.",
  "API key": "API anahtarı",
  "paste a key": "bir anahtar yapıştır",
  "Get one at": "Buradan al:",
  "; or set": "; ya da sunucuda",
  "on the server.": "ayarla.",
  "Base URL (optional)": "Temel URL (isteğe bağlı)",
  "Leave empty for": "Varsayılan için boş bırak:",
  "; set for proxies.": "; vekil sunucular için ayarla.",
  "Default model": "Varsayılan model",
  "— not set: roles use the model in their profile —":
    "— ayarlı değil: roller profillerindeki modeli kullanır —",
  "add a key to list the models": "modelleri listelemek için anahtar ekle",
  "What every agent without a pinned provider runs on right now.":
    "Sağlayıcısı sabitlenmemiş her ajanın şu an çalıştığı model.",
  "Used by every agent without a pinned provider once this provider is the default.":
    "Bu sağlayıcı varsayılan olunca sağlayıcısı sabitlenmemiş her ajan bunu kullanır.",
  "Max output tokens per call": "Çağrı başına en fazla çıktı token'ı",
  "How long one answer may be. Raise it if the vendor's newer models allow more; an agent that still hits the limit is asked for smaller parts automatically.":
    "Bir cevap en fazla ne kadar uzun olabilir. Sağlayıcının yeni modelleri izin veriyorsa yükselt; sınıra yine takılan ajandan otomatik olarak daha küçük parçalar istenir.",
  "no key": "anahtar yok",
  "key set": "anahtar ayarlı",
  "no default model": "varsayılan model seçilmedi",
  "add a key to use it": "kullanmak için anahtar ekle",
  "default model": "varsayılan model",
  "Connected.": "Bağlandı.",
  "model(s) available:": "model kullanılabilir:",

  // -- settings: github / jira / users -------------------------------------------------------------------------
  "Clone, push and open pull requests.": "Klonla, push'la ve pull request aç.",
  "Used to clone private repositories, push job branches and open pull requests. Stored encrypted and never shown again.":
    "Özel depoları klonlamak, iş dallarını push'lamak ve pull request açmak için kullanılır. Şifreli saklanır, bir daha gösterilmez.",
  "Personal access token": "Kişisel erişim token'ı",
  "Not connected": "Bağlı değil",
  "Checking…": "Kontrol ediliyor…",
  "Token rejected": "Token reddedildi",
  Connected: "Bağlı",
  Connect: "Bağlan",
  "Change token": "Token'ı değiştir",
  Disconnect: "Bağlantıyı kes",
  Token: "Token",
  "{n} API calls left": "{n} API çağrısı kaldı",
  "Defaults for new projects": "Yeni projeler için varsayılanlar",
  "Owner / organisation": "Sahip / kuruluş",
  "Base branch": "Temel dal",
  "Connected as": "Bağlı hesap:",
  "Only admins can change these settings.": "Bu ayarları yalnızca yöneticiler değiştirebilir.",
  "Mirror epics, stories and tasks into your tracker.":
    "Epic, story ve taskları takip aracına aynala.",
  "Site URL": "Site URL'si",
  "Account e-mail": "Hesap e-postası",
  "API token": "API token'ı",
  "Issue type names": "Konu tipi adları",
  "As they are called in your Jira site. Tasks default to":
    "Jira sitende adlandırıldıkları gibi. Tasklar varsayılan olarak",
  "on older sites.": "eski sitelerde.",
  "Agents in Jira": "Jira'da ajanlar",
  "Jira account for the agents": "Ajanlar için Jira hesabı",
  "Comments, transitions and bug issues the agents create appear under this account, so Jira history shows the bot and not the person who configured the connection.":
    "Ajanların yazdığı yorumlar, geçişler ve bug'lar bu hesap altında görünür; böylece Jira geçmişinde bağlantıyı kuran kişi değil bot görünür.",
  "Agent e-mail": "Ajan e-postası",
  "Agent API token": "Ajan API token'ı",
  "Remove agent token": "Ajan token'ını kaldır",
  "Agents act as": "Ajanlar şu hesapla çalışır:",
  "The connection works but no agent account is configured.":
    "Bağlantı çalışıyor ama ajan hesabı ayarlı değil.",
  "Jira is not connected yet:": "Jira henüz bağlı değil:",
  "set up the connection": "bağlantıyı kur",
  "Project → Jira project": "Proje → Jira projesi",
  "Task status → Jira transition": "Task durumu → Jira geçişi",
  "The Product Owner's round": "Ürün Sahibi'nin turu",
  "At startup and every hour, every development of a Jira-linked project is checked: missing epics, stories and sub-tasks are created, stories join the sprint (one is started when none is running), statuses catch up.":
    "Açılışta ve her saat, Jira'ya bağlı projelerin her geliştirmesi kontrol edilir: eksik epic, story ve alt görevler açılır, story'ler sprint'e girer (aktif sprint yoksa biri başlatılır), durumlar eşitlenir.",
  "No round has run yet.": "Henüz tur çalışmadı.",
  "Logins and API tokens.": "Girişler ve API token'ları.",
  "Add user": "Kullanıcı ekle",
  Username: "Kullanıcı adı",
  Password: "Şifre",
  "new password": "yeni şifre",
  "Reset password": "Şifreyi sıfırla",
  "Password changed.": "Şifre değişti.",
  "Delete user": "Kullanıcıyı sil",
  "Ends every session and revokes every token of the user.":
    "Kullanıcının bütün oturumlarını bitirir ve bütün token'larını iptal eder.",
  "API tokens": "API token'ları",
  "Issue token": "Token oluştur",
  "Remove token": "Token'ı kaldır",
  "Admins only.": "Yalnızca yöneticiler.",
  "For the CLI:": "CLI için:",
  "Multi-agent delivery, with you at every gate.": "Çok ajanlı teslimat, her kapıda sen varsın.",
  "Sign in": "Giriş yap",
  "Signing in…": "Giriş yapılıyor…",

  // -- misc --------------------------------------------------------------------------------------------------------
  "supervisor unavailable": "denetçi kullanılamıyor",
  "supervisor recommends {decision} · {confidence} · risk {risk}":
    "denetçi {decision} öneriyor · {confidence} · risk {risk}",
  approve: "onay",
  reject: "ret",
  low: "düşük",
  medium: "orta",
  high: "yüksek",
  "suggested feedback: ": "önerilen geri bildirim: ",
  "not approved automatically: ": "otomatik onaylanmadı: ",
  "standards review findings": "standart incelemesi bulguları",
  "{n} advisory": "{n} öneri",
  // -- stepper -----------------------------------------------------------------------------------------------
  "backlog approval": "backlog onayı",
  "architecture approval": "mimari onayı",
  develop: "geliştirme",
  "review decision": "inceleme kararı",
  "test approval": "test onayı",

  // -- an agent's page: scopes, the "what it does" tab, the setup --------------------------------------------
  "What it does": "Ne yapar",
  "Agent setup saved": "Ajan kurulumu kaydedildi",
  off: "kapalı",
  max: "en yüksek",
  product: "ürün",
  testing: "test",
  "When it works": "Ne zaman çalışır",
  "What it reads": "Ne okur",
  "What it hands back": "Ne teslim eder",
  "What it leaves to others": "Neyi başkasına bırakır",
  "How it is set up right now": "Şu anki kurulumu",
  "plus the shared rules": "artı ortak kurallar",
  "Thinking depth and permissions come from the project you pick under Setup; the model is the one this agent is pinned to, on every project.":
    "Düşünme derinliği ve izinler Kurulum sekmesinde seçtiğin projeden gelir; model ise bu ajanın her projede bağlı olduğu modeldir.",

  // the one-liner under an agent's name (the engine's SCOPE table)
  "Turns a request into epics, stories and tasks — the backlog that goes to Jira.":
    "Bir isteği epic, story ve tasklara çevirir — Jira'ya giden backlog.",
  "From backlog and repository: build/test/run profile, decisions, phases.":
    "Backlog ve depodan: build/test/çalıştırma profili, kararlar, fazlar.",
  "Services, APIs, data models, migrations, background jobs.":
    "Servisler, API'ler, veri modelleri, migration'lar, arka plan işleri.",
  "Web front-end: pages, components, state, styling, accessibility.":
    "Web ön yüzü: sayfalar, bileşenler, durum, stil, erişilebilirlik.",
  "Mobile apps: screens, navigation, platform APIs, offline state.":
    "Mobil uygulamalar: ekranlar, gezinme, platform API'leri, çevrimdışı durum.",
  "Proposes test cases; writes unit, integration and end-to-end tests.":
    "Test vakalarını önerir; birim, entegrasyon ve uçtan uca testleri yazar.",
  "Infrastructure phases, pull requests, CI, deployment.":
    "Altyapı fazları, pull request'ler, CI, dağıtım.",
  "Reads what waits at a gate and recommends approve or reject.":
    "Kapıda bekleyeni okur, onay ya da ret önerir.",

  // product owner
  "The Product Owner turns the request into a backlog: epics, stories and tasks. It reads the repository lightly — the tree, the manifests, the README — so the backlog fits the product that already exists, but it decides nothing about technology or files. A task is one piece of work a single specialist can finish and a tester can verify.":
    "Ürün Sahibi isteği bir backlog'a çevirir: epic'ler, story'ler ve tasklar. Depoya hafifçe bakar — dosya ağacı, manifestler, README — ki backlog var olan ürüne otursun; ama teknoloji ya da dosyalar hakkında hiçbir karar vermez. Bir task, tek bir uzmanın bitirebileceği ve bir testçinin doğrulayabileceği tek bir iş parçasıdır.",
  "First, as soon as a development starts. Its backlog waits at the first gate for you; once approved it is mirrored into Jira and the Architect takes over.":
    "En başta, gelişim başlar başlamaz. Yazdığı backlog ilk kapıda seni bekler; onaylanınca Jira'ya aynalanır ve sıra Mimar'a geçer.",
  "Your request, in your words": "Senin isteğin, kendi cümlelerinle",
  "The repository at a glance: tree, manifests, README":
    "Depoya kuşbakışı: dosya ağacı, manifestler, README",
  "Your feedback, when you rejected the previous backlog":
    "Önceki backlog'u reddettiysen geri bildirimin",
  "The product standards and the core rules": "Ürün standartları ve ortak kurallar",
  "Epics, stories and tasks, ordered so that what others depend on comes first":
    "Epic, story ve tasklar — başkalarının dayandığı iş önce gelecek şekilde sıralı",
  "A one- or two-sentence description per task saying what done looks like":
    'Her task için bir-iki cümlelik, "bitti" halinin neye benzediğini söyleyen açıklama',
  "The Jira issues, once you approve the backlog": "Backlog'u onaylayınca Jira kayıtları",
  "Choosing technology, libraries or files — that is the Architect's decision":
    "Teknoloji, kütüphane ya da dosya seçmek — o Mimar'ın kararı",
  "Writing a task that needs two specialists: it splits it in two and says which comes first":
    "İki uzman isteyen bir task yazmak: ikiye böler ve hangisinin önce geldiğini söyler",

  // architect
  "The Architect reads the approved backlog together with the repository and decides how the work will be done: the project profile (the exact commands that build, test and run it), the decisions worth writing down, and the ordered phases — one phase per backlog task, each tagged with the domain whose specialist implements it.":
    "Mimar onaylanan backlog'u depoyla birlikte okur ve işin nasıl yapılacağına karar verir: proje profili (projeyi build eden, test eden ve çalıştıran tam komutlar), yazmaya değer kararlar ve sıralı fazlar — her backlog task'ı için bir faz, her biri hangi uzmanın uygulayacağını söyleyen alan etiketiyle.",
  "After you approve the backlog. Its plan waits at the architecture gate; once approved the specialists start on phase one.":
    "Backlog'u onayladıktan sonra. Planı mimari kapısında bekler; onaylanınca uzmanlar birinci fazdan başlar.",
  "The approved backlog": "Onaylanan backlog",
  "The repository: manifests, lockfiles, CI configuration, README":
    "Depo: manifestler, lock dosyaları, CI yapılandırması, README",
  "The seed profile, whose model routing it must keep as given":
    "Çekirdek profil — model yönlendirmesini verildiği gibi korumak zorundadır",
  "Your feedback, when you rejected the previous plan": "Önceki planı reddettiysen geri bildirimin",
  "The architecture standards and the core rules": "Mimari standartları ve ortak kurallar",
  "The build, test and run commands — preferring the ones CI already runs":
    "Build, test ve çalıştırma komutları — tercihen CI'ın zaten çalıştırdıkları",
  "Architecture decisions: one sentence each, saying the choice and the reason":
    "Mimari kararlar: her biri tek cümle, seçimi ve nedenini söyler",
  "Ordered phases with the files each one will touch, backend contracts before the front-ends that use them":
    "Her birinin dokunacağı dosyalarla birlikte sıralı fazlar; backend sözleşmeleri onları kullanan arayüzlerden önce",
  "Choosing models — routing always comes from the project's seed profile":
    "Model seçmek — yönlendirme her zaman projenin çekirdek profilinden gelir",
  "Inventing a command the repository does not support: it says what is missing instead":
    "Deponun desteklemediği bir komut uydurmak: bunun yerine neyin eksik olduğunu söyler",
  "Guessing past an ambiguity that would change the design — it stops and asks at the gate":
    "Tasarımı değiştirecek bir belirsizliği tahminle geçmek — durur ve kapıda sorar",

  // the specialists
  "The Backend specialist implements one phase at a time: services, HTTP and RPC APIs, data models and migrations, background jobs and integrations. It returns the complete contents of every file it creates or changes, and the change goes through the build gate before the next phase begins. Phases with no specialist domain of their own — general work and documentation — also come here.":
    "Backend uzmanı her seferinde tek bir fazı uygular: servisler, HTTP ve RPC API'leri, veri modelleri ve migration'lar, arka plan işleri ve entegrasyonlar. Oluşturduğu ya da değiştirdiği her dosyanın tam içeriğini döner; değişiklik bir sonraki faz başlamadan build kapısından geçer. Kendi uzmanı olmayan fazlar — genel işler ve dokümantasyon — da buraya gelir.",
  "During development, on every phase the Architect tagged backend (and on general and docs phases).":
    "Geliştirme sırasında, Mimar'ın backend etiketlediği her fazda (ve genel ile doküman fazlarında).",
  "The phase it was given, and only that phase": "Kendisine verilen faz, yalnızca o faz",
  "The files the phase names, and the project's build and test commands":
    "Fazın adını verdiği dosyalar ve projenin build ile test komutları",
  "The build output, when its previous attempt failed the gate":
    "Önceki denemesi kapıdan geçemediyse build çıktısı",
  "The backend standards and the core rules": "Backend standartları ve ortak kurallar",
  "The complete new contents of each file it touches": "Dokunduğu her dosyanın tam yeni içeriği",
  "A summary saying what was done, what was not, and what it was unsure about":
    "Neyin yapıldığını, neyin yapılmadığını ve neyden emin olmadığını söyleyen bir özet",
  "The Jira transition and the work log on the task it implemented":
    "Uyguladığı task üzerinde Jira durum geçişi ve iş kaydı",
  "Touching front-end code: it finishes the backend part and describes the missing piece for the Architect":
    "Arayüz koduna dokunmak: backend kısmını bitirir, eksik parçayı Mimar için anlatır",
  "Refactoring beyond the phase, or weakening a check to make the build gate green":
    "Fazın dışına taşan refactor ya da build kapısı yeşil olsun diye bir kontrolü gevşetmek",

  "The Web UI specialist implements web front-end phases: pages, components, client state, styling, accessibility and front-end tests. It works against the contract the plan describes and keeps every call to the server in one client module.":
    "Web Arayüzü uzmanı web ön yüz fazlarını uygular: sayfalar, bileşenler, istemci durumu, stil, erişilebilirlik ve ön yüz testleri. Planın tarif ettiği sözleşmeye göre çalışır ve sunucuya giden her çağrıyı tek bir istemci modülünde tutar.",
  "During development, on every phase the Architect tagged web.":
    "Geliştirme sırasında, Mimar'ın web etiketlediği her fazda.",
  "The files the phase names, the design tokens and the existing components":
    "Fazın adını verdiği dosyalar, tasarım token'ları ve mevcut bileşenler",
  "The contract the backend phase defined, from the architecture decisions":
    "Backend fazının tanımladığı sözleşme — mimari kararlardan",
  "The web standards and the core rules": "Web standartları ve ortak kurallar",
  "A summary naming any endpoint it needed that does not exist yet":
    "İhtiyaç duyduğu ama henüz var olmayan uç noktaları adıyla söyleyen bir özet",
  "Adding or changing a server endpoint — it says exactly which one is missing so the Architect can add a backend phase":
    "Sunucu uç noktası eklemek ya da değiştirmek — Mimar backend fazı ekleyebilsin diye hangisinin eksik olduğunu tam olarak söyler",
  "Hard-coding a colour, or shipping a control that the keyboard cannot reach":
    "Renk kodunu koda gömmek ya da klavyeyle erişilemeyen bir kontrol bırakmak",

  "The Mobile UI specialist implements mobile phases: screens, navigation, platform APIs, offline and sync state, and mobile tests. It prefers the platform's conventions over web patterns.":
    "Mobil Arayüz uzmanı mobil fazları uygular: ekranlar, gezinme, platform API'leri, çevrimdışı ve senkron durumu, mobil testler. Web alışkanlıkları yerine platformun kendi kurallarını yeğler.",
  "During development, on every phase the Architect tagged mobile.":
    "Geliştirme sırasında, Mimar'ın mobil etiketlediği her fazda.",
  "The app's structure: features, shared core, the API client":
    "Uygulamanın yapısı: özellikler, ortak çekirdek, API istemcisi",
  "The backend contracts it has to rely on": "Dayanmak zorunda olduğu backend sözleşmeleri",
  "The mobile standards and the core rules": "Mobil standartları ve ortak kurallar",
  "A summary naming the backend contracts it relied on and the ones that are missing":
    "Dayandığı ve eksik olan backend sözleşmelerini adıyla söyleyen bir özet",
  "Changing server code": "Sunucu kodunu değiştirmek",
  "Putting business logic in a screen, or a token anywhere but the platform's secure store":
    "İş mantığını ekrana koymak ya da bir token'ı platformun güvenli deposu dışında bir yere yazmak",

  // qa
  "QA does three jobs. After every phase it reviews the specialist's diff against the standards that specialist was told to follow, and reports each breach with the file, the line and a concrete fix. When the branch is complete it proposes the test cases that would prove the change works — for you to add to, remove from and approve. Then it writes automated tests for exactly the approved list.":
    "QA üç iş yapar. Her fazdan sonra uzmanın diff'ini, o uzmana verilen standartlara karşı inceler ve her ihlali dosyası, satırı ve somut düzeltmesiyle bildirir. Dal tamamlandığında değişikliğin çalıştığını kanıtlayacak test vakalarını önerir — ekleyip çıkarman ve onaylaman için. Sonra yalnızca onaylanan liste için otomatik testleri yazar.",
  "After each phase for the standards review, and once the whole branch is built for the test cases and the tests.":
    "Standart incelemesi için her fazdan sonra; test vakaları ve testler için dalın tamamı kurulduğunda.",
  "The phase diff, together with the standards sections that phase was given":
    "Faz diff'i ve o faza verilen standart bölümleri",
  "The branch diff, the plan and the backlog it implements":
    "Dal diff'i, plan ve uyguladığı backlog",
  "The project's existing test layout, frameworks and runners":
    "Projenin mevcut test düzeni, çatıları ve koşucuları",
  "The approved list of test cases — no more, no fewer":
    "Onaylanan test vakası listesi — ne fazlası ne eksiği",
  "Standards violations, each marked blocking or advisory, with a fix":
    "Standart ihlalleri — her biri engelleyici ya da tavsiye olarak işaretli, düzeltmesiyle",
  "At most fifteen proposed test cases, each in a sentence or two":
    "En fazla on beş test vakası önerisi, her biri bir-iki cümle",
  "The test files themselves, complete, in the project's own layout":
    "Test dosyalarının kendisi — eksiksiz, projenin kendi düzeninde",
  "A Jira bug for each defect it finds, closed once the fix passes":
    "Bulduğu her kusur için bir Jira bug'ı; düzeltme geçtiğinde kapatılır",
  "Inventing a rule that is not in the standards, or a finding to have something to report":
    "Standartlarda olmayan bir kural uydurmak ya da rapor edecek bir şey olsun diye bulgu üretmek",
  "Writing a test for a case you did not approve": "Onaylamadığın bir vaka için test yazmak",

  // devops
  "DevOps does the infrastructure phases — Dockerfiles, compose files, CI workflows, deployment and environment configuration — and, at the end of a development, writes the pull request: a title and a body that say what changed, why, and how it was tested, from the approved plan and the job history.":
    "DevOps altyapı fazlarını yapar — Dockerfile'lar, compose dosyaları, CI akışları, dağıtım ve ortam yapılandırması — ve gelişimin sonunda pull request'i yazar: onaylanan plandan ve iş geçmişinden, neyin neden değiştiğini ve nasıl test edildiğini söyleyen bir başlık ve gövde.",
  "During development on infra phases, and at the end of every development for the pull request.":
    "Geliştirme sırasında altyapı fazlarında, ve her gelişimin sonunda pull request için.",
  "The phase it was given, for infrastructure work": "Altyapı işi için kendisine verilen faz",
  "The factual draft assembled from the plan and the job history":
    "Plandan ve iş geçmişinden derlenen olgusal taslak",
  "The branch diff: everything that actually changed": "Dal diff'i: gerçekte ne değiştiyse",
  "The devops standards and the core rules": "DevOps standartları ve ortak kurallar",
  "Packaging and pipeline files, with configuration through environment variables":
    "Paketleme ve pipeline dosyaları; yapılandırma ortam değişkenleriyle",
  "A pull request title under seventy characters and a Markdown body listing the phases":
    "Yetmiş karakterin altında bir pull request başlığı ve fazları sıralayan Markdown gövde",
  "A note on what a person still has to do by hand — create a secret, open a port":
    "Bir insanın elle yapması gerekenlerin notu — bir secret oluşturmak, bir port açmak",
  "The outcome commented on the Jira stories": "Sonucun Jira story'lerine yorum olarak düşülmesi",
  "Inventing anything that is not in the draft or the diff":
    "Taslakta ya da diff'te olmayan bir şey uydurmak",
  "Committing a secret, or changing application code beyond what packaging needs":
    "Bir secret'ı commit'lemek ya da paketlemenin gerektirdiğinden fazlasına uygulama kodunda dokunmak",

  // supervisor
  "The Supervisor reads exactly what you would read at a gate — the proposal and the history behind it — and recommends approve or reject, with its confidence, the risk it sees and short concrete reasons. When a phase fails the build gate there is nothing to approve: it decides whether the specialist tries again, the plan is redone, or a human is needed.":
    "Denetçi bir kapıda senin okuyacağın şeyi okur — öneriyi ve arkasındaki geçmişi — ve onay ya da ret önerir; güveniyle, gördüğü riskle ve kısa somut gerekçelerle. Bir faz build kapısından geçemediğinde onaylanacak bir şey yoktur: uzmanın yeniden mi deneyeceğine, planın mı yenileneceğine, yoksa bir insana mı sorulacağına karar verir.",
  "At every human gate, and whenever a phase fails the build gate.":
    "Her insan kapısında, ve bir faz build kapısından her düştüğünde.",
  "The material at the gate: a backlog, an architecture, a standards review, test cases or the written tests":
    "Kapıdaki malzeme: bir backlog, bir mimari, bir standart incelemesi, test vakaları ya da yazılan testler",
  "The job history so far, and the original request": "Şimdiye kadarki iş geçmişi ve asıl istek",
  "The build output, when a phase failed the gate": "Bir faz kapıdan geçemediyse build çıktısı",
  "The standards of every domain and the core rules": "Her alanın standartları ve ortak kurallar",
  "Approve or reject, with a confidence between 0 and 1":
    "Onay ya da ret — 0 ile 1 arasında bir güvenle",
  "A risk reading: low, medium or high, and at most five reasons":
    "Risk okuması: düşük, orta ya da yüksek; en fazla beş gerekçe",
  "Feedback the agent can act on, when it rejects":
    "Reddettiğinde ajanın üzerine iş yapabileceği geri bildirim",
  "After a failed build: fix, replan or ask a human":
    "Build düştüğünde: düzelt, yeniden planla ya da insana sor",
  "Inventing objections — it prefers approving with medium risk noted":
    "İtiraz uydurmak — riski orta diye not edip onaylamayı yeğler",
  "Deciding in your place: the recommendation is yours to take or leave, unless you turned auto-approval on":
    "Senin yerine karar vermek: otomatik onayı açmadıysan öneri senin alıp bırakacağın bir şeydir",
};
