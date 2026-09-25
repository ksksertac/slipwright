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
  "Where the developments stand": "Geliştirmeler nerede",
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
  "Open the development": "Geliştirmeyi aç",
  "What DevOps wrote about it": "DevOps'un yazdıkları",
  "the branch is no longer in the checkout": "dal artık çalışma kopyasında değil",
  "Runs by itself at startup and every hour: missing epics, stories and sub-tasks are created, stories join the sprint (one is started when none is running), statuses catch up. Nothing to set — this is how a half-mirrored plan repairs itself.":
    "Açılışta ve her saat kendiliğinden çalışır: eksik epic, story ve alt görevler açılır, story'ler sprint'e girer (açık sprint yoksa yenisi başlatılır), durumlar güncellenir. Ayarlanacak bir şey yok — yarım kalmış bir aynalama böyle kendini toparlar.",
  "Once this is set up an approved plan appears in Jira by itself: the Product Owner creates the epics, stories and sub-tasks, the specialists move them as they work, and pull request links and failures are commented. Five tabs, left to right.":
    "Bu kurulum bittiğinde onayladığın plan Jira'ya kendiliğinden düşer: Ürün Sahibi epic, story ve alt görevleri açar, uzmanlar çalıştıkça onları ilerletir, pull request bağlantıları ve hatalar yorum olarak eklenir. Beş sekme, soldan sağa.",
  Connection: "Bağlantı",
  "Agent account": "Ajan hesabı",
  "Issue types": "Konu tipleri",
  "Automatic sync": "Otomatik eşitleme",
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
  "last run {when}": "son eşitleme {when}",
  "not run yet": "henüz çalışmadı",
  in_progress: "devam ediyor",
  epic: "epic",
  story: "story",
  task: "task",
  bug: "bug",
  "{n} waiting": "{n} bekliyor",
  "{n} running": "{n} çalışıyor",
  "local checkout": "yerel çalışma kopyası",
  "{n} development(s)": "{n} geliştirme",
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
  development: "geliştirme",
  "With Jira connected, every approved plan is mirrored as epics, stories and sub-tasks in the project's Jira project, issues move as tasks complete, and PR links and failures are commented. This is the connection used by the engine; the account the agents themselves act as, and which Jira project each Slipwright project mirrors into, are set below.":
    "Jira bağlıyken onaylanan her plan, projenin Jira projesine epic, story ve alt görev olarak aynalanır; tasklar bittikçe issue'lar ilerler, PR bağlantıları ve hatalar yorum olarak düşülür. Bu, motorun kullandığı bağlantıdır; ajanların hangi hesapla davrandığı ve hangi Slipwright projesinin hangi Jira projesine aynalandığı aşağıda ayarlanır.",
  "so they nest under stories; use": "böylece story altına yerleşirler; eski sitelerde",
  "Last sync {when}: {jobs} development(s) checked, {updated} updated, {errors} with Jira errors.":
    "Son eşitleme {when}: {jobs} geliştirme denetlendi, {updated} güncellendi, {errors} tanesinde Jira hatası.",
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
  "Try a different way…": "Farklı yol ile dene…",
  "Try a different way": "Farklı yol ile dene",
  "Say what should be tried instead. It goes to the Product Owner together with what failed: the backlog is written again and can gain tasks it was missing, the Architect plans the phases again, and you approve both as usual. The branch and everything built on it stay.":
    "Bunun yerine ne denensin, yaz. Yazdığın, hatayla birlikte Ürün Sahibi'ne gider: backlog yeniden yazılır ve eksik kalan tasklar eklenebilir, Mimar fazları yeniden kurgular, ikisini de her zamanki gibi sen onaylarsın. Dal ve üzerinde üretilmiş her şey durur.",
  "What failed": "Ne patladı",
  "e.g. split the API phase in two and let the routing package be exported in its own phase":
    "ör. API fazını ikiye böl, yönlendirme paketinin dışa aktarımı kendi fazında olsun",
  "Plan it again": "Yeniden planla",
  "Planning…": "Planlanıyor…",
  "Nothing is thrown away; the phases are simply walked again from the first.":
    "Hiçbir şey atılmıyor; fazlar baştan tekrar yürünüyor.",
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
  "Working on it": "üzerinde çalışıyor",
  "last sign of life {ago}": "en son {ago} kıpırdadı",
  "phase {at} of {of}": "{of} fazın {at}. fazı",
  "the model was asked again {n} times": "modele {n} kez yeniden soruldu",

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
  po: "Ürün Sahibi",
  Architect: "Yazılım Mimarı",
  architect: "Yazılım Mimarı",
  web_ui: "Web Arayüzü",
  mobile_ui: "Mobil Arayüz",
  supervisor: "Denetçi",
  "Backend Developer": "Backend Geliştirici",
  "Web Developer": "Web Geliştirici",
  "Mobile Developer": "Mobil Geliştirici",
  Designer: "Tasarımcı",
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
  "The project": "Proje",
  "The checkout": "Çalışma kopyası",
  "What is already written stays as it was; this is for what comes next.":
    "Yazılmış olanlar olduğu gibi kalır; bu, bundan sonrası için.",
  "Where the agents work. It is set when the project is created and does not move: the developments already in it are worktrees of this checkout.":
    "Ajanların çalıştığı yer. Proje açılırken belirlenir ve yerinden oynamaz: içindeki geliştirmeler bu kopyanın worktree'leri.",
  "Epics, stories and tasks are mirrored into it from the next development onwards; what is already on the board stays where it is.":
    "Epic, story ve tasklar bir sonraki geliştirmeden itibaren buraya aynalanır; panoda duranlar yerinde kalır.",

  "Where the work happens": "İş nerede yapılacak",
  Tracking: "Takip",
  "The first development": "İlk geliştirme",
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

  // -- paging ----------------------------------------------------------------------------------------
  Previous: "Önceki",
  Next: "Sonraki",
  Continue: "Devam",
  Back: "Geri",
  "Something above is still missing.": "Yukarıda eksik bir şey kaldı.",

  "{from}-{to} of {total}": "{total} kayıttan {from}-{to}",

  // -- project tabs ----------------------------------------------------------------------------------
  Pipeline: "Akışlar",
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
  "main branch": "ana dal (main)",
  "on the main branch": "ana dalda (main)",
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
  Details: "Detay",
  Flow: "Akış",
  // the supervisor's decision at a failed build gate, with its reasons under it
  "The supervisor stopped and left the decision to you": "Süpervizör durdu, kararı sana bıraktı",
  "The supervisor asked the Architect to plan it again":
    "Süpervizör, Mimar'dan yeniden planlamasını istedi",
  "The supervisor sent it back to the same specialist": "Süpervizör işi aynı uzmana geri gönderdi",

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
  // -- teams: the people an account puts on its agents (T12) --
  "Who holds it": "Takım üyeleri",
  "Add someone to the team": "Takıma birini ekle",
  "nobody holds it yet": "henüz kimse tutmuyor",
  "Which agents": "Hangi ajanlar",
  "Pick at least one agent": "En az bir ajan seç",
  "They approve at the gates of the agents you pick, edit what those agents propose and see this team's projects - nothing else.":
    "Seçtiğin ajanların kapılarında onay verir, o ajanların önerdiğini düzenler ve bu ekibin projelerini görür — başka hiçbir şey yapamaz.",

  "Whoever is on this agent approves at its gates, edits what it proposes and sees this team's projects — and nothing else. Work that arrives here is mailed to them.":
    "Bu ajanda olan kişi, ajanın kapılarında onay verir, önerdiğini düzenler ve ekibin projelerini görür — başka hiçbir şey yapamaz. Buraya iş düştüğünde kendisine e-posta gider.",
  "Nobody but you holds this agent.": "Bu ajanı senden başka tutan yok.",
  "Put somebody on this agent": "Bu ajana birini ata",
  "Work email": "İş e-postası",
  "Name (optional)": "Ad (isteğe bağlı)",
  "They get a letter with a link: they accept it by choosing a password, or decline. The address becomes part of this team and cannot open an account of its own afterwards.":
    "Kişiye bağlantılı bir posta gider: şifre belirleyip kabul eder ya da reddeder. Adres artık bu ekibe aittir; sonrasında kendi başına hesap açamaz.",
  "Send the invitation": "Daveti gönder",
  "No longer on this agent": "Artık bu ajanda değil",
  Person: "Kişi",
  Since: "Tarih",
  "Step off this agent": "Bu ajandan ayrıl",
  "Take the agent back": "Ajanı geri al",
  "Leave…": "Ayrıl…",
  "Remove…": "Çıkar…",
  invited: "davet edildi",
  active: "çalışıyor",
  declined: "reddetti",
  left: "ayrıldı",
  removed: "çıkarıldı",
  "{n} person/people": "{n} kişi",
  yours: "sende",
  "You have been invited": "Ekibe davet edildin",
  "{inviter} would like you on the {agents} agent.":
    "{inviter} seni {agents} ajanına atamak istiyor.",
  "You will approve at that agent's gates, edit the work it proposes and see the team's projects. Nothing else on the account is yours to change.":
    "O ajanın kapılarında onay verir, önerdiği işi düzenler ve ekibin projelerini görürsün. Hesabın geri kalanı senin değiştirebileceğin bir şey değil.",
  "Choose a password": "Bir şifre belirle",
  "Accept and start": "Kabul et ve başla",
  "Joining…": "Katılınıyor…",
  "Decline this invitation": "Daveti reddet",
  Declined: "Reddedildi",
  "Nothing has been shared with you.": "Seninle hiçbir şey paylaşılmadı.",
  "We have told them. If you change your mind, ask them to invite you again.":
    "Karşı tarafa iletildi. Fikrini değiştirirsen seni yeniden davet etmesini isteyebilirsin.",
  Invitation: "Davet",
  "This link is no longer valid.": "Bu bağlantı artık geçerli değil.",
  "You have been taken off this team's agents, so you are signed out.":
    "Bu ekibin ajanlarından çıkarıldın, bu yüzden oturumun kapandı.",
  "Accept your invitation first: the link is in the letter we sent you.":
    "Önce davetini kabul et: bağlantı sana gönderdiğimiz postada.",
  "Waiting for the {agent} agent.": "{agent} ajanını bekliyor.",
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
  "All projects": "Tüm Projeler",
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
  "Shared rules are edited under the All projects scope.":
    "Ortak kurallar “Tüm Projeler” kapsamında düzenlenir.",
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
  "The Product Owner's automatic sync": "Ürün Sahibi'nin otomatik eşitlemesi",
  "At startup and every hour, every development of a Jira-linked project is checked: missing epics, stories and sub-tasks are created, stories join the sprint (one is started when none is running), statuses catch up.":
    "Açılışta ve her saat, Jira'ya bağlı projelerin her geliştirmesi kontrol edilir: eksik epic, story ve alt görevler açılır, story'ler sprint'e girer (aktif sprint yoksa biri başlatılır), durumlar eşitlenir.",
  "No sync has run yet.": "Henüz eşitleme yapılmadı.",
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
    "En başta, geliştirme başlar başlamaz. Yazdığı backlog ilk kapıda seni bekler; onaylanınca Jira'ya aynalanır ve sıra Mimar'a geçer.",
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
    "DevOps altyapı fazlarını yapar — Dockerfile'lar, compose dosyaları, CI akışları, dağıtım ve ortam yapılandırması — ve geliştirmenin sonunda pull request'i yazar: onaylanan plandan ve iş geçmişinden, neyin neden değiştiğini ve nasıl test edildiğini söyleyen bir başlık ve gövde.",
  "During development on infra phases, and at the end of every development for the pull request.":
    "Geliştirme sırasında altyapı fazlarında, ve her geliştirmenin sonunda pull request için.",
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

  // -- the tests tab: what ran, when, what it was for and how it ended --------------------------
  Today: "Bugün",
  Yesterday: "Dün",
  "under a second": "bir saniyeden az",
  "build gate · phase {n}": "build kapısı · faz {n}",
  "by hand · on the development's branch": "elle · geliştirmenin dalında",
  "by hand · on the main branch": "elle · ana dalda (main)",
  "in the development: {request}": "geliştirmede: {request}",
  "any development": "herhangi bir geliştirme",
  "The project's test command, run on the branch you pick. Every build gate the engine ran is in the same list — open a row to see what it was for and how it ended.":
    "Projenin test komutu, seçtiğin dalda çalışır. Motorun geçtiği her build kapısı da aynı listede — bir satırı aç, neden çalıştığını ve nasıl bittiğini gör.",
  "Nothing matches these filters": "Bu süzgeçlere uyan yok",
  "Clear the status or the development filter to see the runs again.":
    "Koşuları yeniden görmek için durum ya da geliştirme süzgecini temizle.",
  "{n} run(s)": "{n} çalıştırma",
  "{n} passed": "{n} geçti",
  "What was tested": "Ne test edildi",
  Development: "Geliştirme",
  "Why this ran": "Neden çalıştı",
  "What it ran": "Ne çalıştırdı",
  "What was expected": "Ne bekleniyordu",
  "What happened": "Ne oldu",
  "The specialist finished phase {n} of this development. Before the next phase starts, the engine builds the branch and runs the whole test suite: this is that check.":
    "Uzman bu geliştirmenin {n}. fazını bitirdi. Bir sonraki faz başlamadan önce motor dalı kurar ve test takımının tamamını koşar: bu, o kontrol.",
  "The engine built the branch and ran the whole test suite before letting the development move on.":
    "Motor, geliştirmenin devam etmesine izin vermeden önce dalı kurdu ve test takımının tamamını koştu.",
  "You started this run yourself, on the development's own branch.":
    "Bu koşuyu, geliştirmenin kendi dalında sen başlattın.",
  "You started this run yourself, on the project's main branch.":
    "Bu koşuyu, projenin ana dalında (main) sen başlattın.",
  "All {n} commands end in exit code 0 — the build, the linters and the type checks first, then the whole test suite, with no test skipped or weakened.":
    "{n} komutun hepsi 0 çıkış koduyla bitmeli — önce build, linter'lar ve tip kontrolleri, sonra test takımının tamamı; hiçbir test atlanmadan ya da gevşetilmeden.",
  "The command ends in exit code 0 — the whole test suite green, with no test skipped or weakened.":
    "Komut 0 çıkış koduyla bitmeli — test takımının tamamı yeşil; hiçbir test atlanmadan ya da gevşetilmeden.",
  "Still running.": "Hâlâ çalışıyor.",
  "Every command ended in exit code 0: nothing to fix here.":
    "Her komut 0 çıkış koduyla bitti: burada düzeltilecek bir şey yok.",
  "The run could not be carried out at all.": "Koşu hiç yapılamadı.",
  "A command ended in exit code {code}; the first failure is highlighted below.":
    "Bir komut {code} çıkış koduyla bitti; ilk hata aşağıda işaretli.",
  "Took {duration}.": "{duration} sürdü.",
  Output: "Çıktı",
  "scrolled to the first failure": "ilk hataya kaydırıldı",

  // -- the activity feed: the engine's own notes, read back in Turkish (i18n/notes.ts) ----------
  "Development started": "Geliştirme başladı",
  "{1}, by {2}; continues with {3}": "{1} — onaylayan: {2}; {3} ile devam ediyor",
  "{1}; continues with {2}": "{1}; {2} ile devam ediyor",
  "{1}, by {2}": "{1} — onaylayan: {2}",
  Approved: "Onaylandı",
  "{1} test cases approved": "{1} test senaryosu onaylandı",
  "Phase {1} approved despite the review": "{1}. faz, incelemeye rağmen onaylandı",
  "Sent back: {1}": "Geri gönderildi: {1}",
  "Taken back: {1}": "Geri alındı: {1}",
  "Tests re-run by hand": "Testler elle yeniden çalıştırıldı",
  "DevOps step re-run by hand": "DevOps adımı elle yeniden çalıştırıldı",
  "Retried, continuing from {1}": "Yeniden denendi, {1} adımından devam ediliyor",
  "Retried, continuing from {1} ({2})": "Yeniden denendi, {1} adımından devam ediliyor ({2})",
  "Tests re-run by hand: passed": "Testler elle yeniden çalıştırıldı: geçti",
  "Backlog ready: {1} epics, {2} stories, {3} tasks":
    "Backlog hazır: {1} epic, {2} story, {3} task",
  "Plan ready: {1} phases, {2} decisions": "Plan hazır: {1} faz, {2} karar",
  "Phase {1}/{2}, build fix {3}: {4} ({5} files)":
    "{1}/{2}. faz, {3}. build düzeltmesi: {4} ({5} dosya)",
  "Phase {1}/{2}, review fix {3}: {4} ({5} files)":
    "{1}/{2}. faz, {3}. inceleme düzeltmesi: {4} ({5} dosya)",
  "Phase {1}/{2}, part {3}: {4} ({5} files so far)":
    "{1}/{2}. faz, {3}. parça: {4} (şimdiye kadar {5} dosya)",
  "Phase {1}/{2} built in {5} parts: {3} ({4} files)":
    "{1}/{2}. faz {5} parçada yapıldı: {3} ({4} dosya)",
  "Phase {1}/{2} built: {3} ({4} files)": "{1}/{2}. faz yapıldı: {3} ({4} dosya)",
  "Build gate passed — phase {1}/{2}": "Build kapısı geçildi — {1}/{2}. faz",
  "Build gate — phase {1}": "Build kapısı — {1}. faz",
  "Build gate failed — phase {1} (attempt {2}/{3})":
    "Build kapısı geçilemedi — {1}. faz ({2}/{3}. deneme)",
  "Build gate failed {1} times on phase {2} — giving up":
    "Build kapısı {2}. fazda {1} kez geçilemedi — vazgeçildi",
  "The test was wrong, not the code — phase {1}, corrected ({2} files): {3}":
    "Hatalı olan kod değil testti — {1}. faz, düzeltildi ({2} dosya): {3}",
  "The code is wrong, not the test — phase {1}: {2}": "Hatalı olan test değil kod — {1}. faz: {2}",
  "Test fix refused — it changed {2}, which is not a test":
    "Test düzeltmesi kabul edilmedi — test dosyası olmayan {2} değiştirilmiş",
  "Called the test wrong but sent no correction": "Test hatalı dendi ama düzeltmesi gelmedi",
  "Test fix not written ({2})": "Test düzeltmesi yazılamadı ({2})",
  "{1}; Supervisor: re-plan ({2})": "{1}; Süpervizör: yeniden planla ({2})",
  "{1}; Supervisor: asks you ({2})": "{1}; Süpervizör: sana soruyor ({2})",
  "{1}; Supervisor: the same specialist fixes it ({2})":
    "{1}; Süpervizör: aynı uzman düzeltsin ({2})",
  "Supervisor recommends {1} (confidence {2}, risk {3})":
    "Süpervizörün önerisi: {1} (güven {2}, risk {3})",
  "{1}; waits for you: {2}": "{1}; seni bekliyor: {2}",
  "Supervisor failed ({1}) — the gate waits for you":
    "Süpervizör çalışmadı ({1}) — kapı seni bekliyor",
  "Supervisor: {1} ({2})": "Süpervizör: {1} ({2})",
  "Supervisor (confidence {1}): {2}": "Süpervizör (güven {1}): {2}",
  "Review of phase {1}/{2}: {3}": "{1}/{2}. fazın incelemesi: {3}",
  "nothing to fix": "düzeltilecek bir şey yok",
  "{1} findings, {2} blocking, {3} advisory": "{1} bulgu, {2} engelleyici, {3} tavsiye",
  "{1} — fix round {2}/{3}": "{1} — {2}/{3}. düzeltme turu",
  "{1}, after {2} fix rounds — needs your decision":
    "{1}, {2} düzeltme turundan sonra — kararını bekliyor",
  "{1} test cases proposed": "{1} test senaryosu önerildi",
  "No test cases came back — asking again": "Cevapta test senaryosu yoktu — yeniden soruluyor",
  "Tests written and passing ({1} files): {2}": "Testler yazıldı ve geçiyor ({1} dosya): {2}",
  "Jira, second try: {1}": "Jira, ikinci deneme: {1}",
  "Jira: {1}": "Jira: {1}",
  "Jira: {1} updates": "Jira: {1} güncelleme",
  "Jira could not be reached — will retry": "Jira'ya ulaşılamadı — yeniden denenecek",
  "{1} written": "{1} yazıldı",
  "{1} refused": "{1} reddedildi",
  "{1} queued": "{1} kuyrukta",
  "{1} unchanged": "{1} değişmedi",
  "Standards read for phase {1}: {2} sections": "{1}. faz için standartlar okundu: {2} bölüm",
  "Standards read: {1} sections": "Standartlar okundu: {1} bölüm",
  "{1} messages from you went to {2}": "Senden gelen {1} mesajı {2} okudu",
  "Attempt {1} failed ({2}) — trying again in {3}s, {4} of {5} retries used":
    "{1}. deneme başarısız ({2}) — {3} sn sonra yeniden; {5} denemenin {4} tanesi kullanıldı",
  "Attempt {1} hit the answer limit — asking for a smaller part ({3}/{4})":
    "{1}. deneme cevap sınırına takıldı — daha küçük bir parça isteniyor ({3}/{4})",
  "{1} gave up after {3} attempts: {2}": "{1} {3} denemeden sonra vazgeçti: {2}",
  "{1} failed: {2}": "{1} başarısız oldu: {2}",
  "{1} crashed: {2}": "{1} çöktü: {2}",
  "Went in circles: {1}": "Döngüye girildi: {1}",
  "DevOps could not finish: {1}": "DevOps tamamlayamadı: {1}",
  "CI was still running after {1}s": "CI {1} sn sonra hâlâ sürüyordu",
  "CI still red after {1} fix attempts": "CI {1} düzeltme denemesinden sonra hâlâ kırmızı",
  "Pull request {1} ({2})": "Pull request {1} ({2})",
  "Nothing was pushed: the checkout {1} has no remote. The branch {2} is ready there — merge it with `git merge {2}`, or give the project a GitHub repository so the next development pushes and opens a pull request.":
    "Hiçbir şey gönderilmedi: {1} çalışma kopyasının uzak deposu yok. {2} dalı orada hazır — `git merge {2}` ile birleştir ya da projeye bir GitHub deposu tanımla; sonraki geliştirme kendiliğinden gönderip pull request açsın.",
  // why a role's turn ended badly (InvokeErrorKind)
  "timed out": "zaman aşımı",
  "provider error": "sağlayıcı hatası",
  "provider unavailable": "sağlayıcıya ulaşılamadı",
  "the provider refused the account": "sağlayıcı hesabı reddetti",
  "refused by the model": "model reddetti",
  "unusable answer": "kullanılamaz cevap",
  "budget spent": "bütçe bitti",
  "went in circles": "döngüye girdi",
  "answer cut off": "cevap kesildi",
  // -- the step panel: what each step produced, item by item ----------------------------
  "Epics, stories and tasks": "Epic, story ve task'lar",
  "Every epic opens onto its stories, and every story onto its tasks.":
    "Her epic story'lerine, her story de task'larına açılır.",
  "The Product Owner has not written the backlog yet.": "Ürün sahibi backlog'u henüz yazmadı.",
  Jira: "Jira",
  "Where the backlog ended up: one issue per epic, story and task.":
    "Backlog nereye gitti: her epic, story ve task için bir iş kaydı.",
  "What was mirrored to Jira, and what is still waiting.": "Jira'ya ne yansıdı, ne hâlâ bekliyor.",
  "Nothing was sent to Jira for this step.": "Bu adım için Jira'ya bir şey gönderilmedi.",
  "Mirrored to Jira": "Jira'ya yansıtıldı",
  Sprint: "Sprint",
  "the last Jira sync failed": "son Jira eşitlemesi başarısız oldu",
  "not in Jira": "Jira'da yok",
  "What the Architect settled on, and why the plan looks the way it does.":
    "Mimarın neye karar verdiği ve planın neden böyle olduğu.",
  "The Architect recorded no separate decisions.": "Mimar ayrıca bir karar kaydetmedi.",
  "How it is built, tested and run": "Nasıl kurulur, test edilir ve çalıştırılır",
  "No build facts were proposed.": "Kurulum bilgisi önerilmedi.",
  Build: "Kurulum",
  Run: "Çalıştırma",
  "One phase per backlog task, in the order they are built.":
    "Her backlog task'ı için bir faz, yapılacakları sırayla.",
  "No phases were planned.": "Hiç faz planlanmadı.",
  "What this phase was asked to do": "Bu fazdan ne istendi",
  Files: "Dosyalar",
  "Planned by the Architect, then what the diff actually touched.":
    "Mimarın planladıkları, sonra diff'in gerçekten dokunduğu dosyalar.",
  "No files were named for this phase.": "Bu faz için dosya belirtilmedi.",
  planned: "planlanan",
  changed: "değişen",
  phase: "faz",
  files: "dosya",
  "The phase's own run and every build gate it went through.":
    "Fazın kendi koşusu ve geçtiği her build kapısı.",
  "Nothing recorded yet.": "Henüz bir kayıt yok.",
  "Standards review": "Standart incelemesi",
  "What QA found when it read this phase's diff against the standards.":
    "QA, bu fazın diff'ini standartlara göre okuduğunda ne buldu.",
  "No standards review was recorded for this phase.":
    "Bu faz için standart incelemesi kaydedilmedi.",
  "The scenarios QA proposed; the tests are written against exactly these.":
    "QA'in önerdiği senaryolar; testler tam olarak bunlara göre yazılır.",
  "QA proposed no test cases.": "QA hiç test senaryosu önermedi.",
  "Test files written": "Yazılan test dosyaları",
  "QA wrote no new test files: the approved cases were already covered.":
    "QA yeni test dosyası yazmadı: onaylanan senaryolar zaten kapsanıyordu.",
  "The run": "Koşu",
  "What the build and test commands said.": "Kurulum ve test komutları ne dedi.",
  "Where the work ended up: the branch, the pull request and its checks.":
    "İş nerede bitti: dal, pull request ve kontrolleri.",
  Branch: "Dal",
  "Pull request": "Pull request",
  pushed: "gönderildi",
  "not pushed": "gönderilmedi",
  "CI fix rounds": "CI düzeltme turu",
  "What this development produced": "Bu geliştirme ne üretti",
  "The decision": "Karar",
  "Nobody has decided yet.": "Henüz kimse karar vermedi.",
  "The supervisor's advice": "Süpervizörün önerisi",
  recommends: "öneri",
  confidence: "güven",
  risk: "risk",
  "The agent's record, as it was written": "Ajanın kaydı, yazıldığı hâliyle",
  approved: "onaylandı",
  "by you": "senin tarafından",
  "by the supervisor": "süpervizör tarafından",
  "not started": "başlamadı",
  "not touched": "dokunulmadı",
  // -- a development's own page --------------------------------------------------------
  Port: "Port",
  "What came out": "Ne çıktı ortaya",
  "{n} step(s)": "{n} adım",
  "{n} attempt(s)": "{n} deneme",
  "{n} gate failure(s)": "{n} kapı hatası",
  "Nothing has run in this phase yet.": "Bu fazda henüz bir şey çalışmadı.",
  "Nothing is built yet: the plan has to be approved first.":
    "Henüz bir şey yapılmadı: önce planın onaylanması gerekiyor.",
  "QA has not proposed any test cases for this development.":
    "QA bu geliştirme için test senaryosu önermedi.",
  "No model call has been recorded yet.": "Henüz bir model çağrısı kaydedilmedi.",
  "Propose the test cases again": "Test senaryolarını yeniden öner",
  "Asks QA for the list of scenarios again, from the top.":
    "QA'e senaryo listesini en baştan yeniden sorar.",
  // -- about the project: the analysis, the intake, the brief (T11.1-T11.3) -------------
  "About the project": "Proje hakkında",
  "What the agents know about this project": "Ajanların bu proje hakkında bildikleri",
  "The Architect reads the checkout and writes down what this project is. Every agent is handed this list at every step, so strike out anything wrong and correct anything half-right before you approve it.":
    "Mimar depoyu okur ve bu projenin ne olduğunu maddeler hâlinde yazar. Bu liste her adımda her ajana verilir; onaylamadan önce yanlış olanı sil, yarım doğru olanı düzelt.",
  "The repository is empty, so the Product Owner asks you about the product. Your answers become the first development and the list below, which every agent is handed at every step.":
    "Depo boş, o yüzden Ürün Sahibi ürünü sana sorar. Cevapların hem ilk geliştirmeye hem de aşağıdaki listeye dönüşür; o liste her adımda her ajana verilir.",
  "Nothing has been written down yet.": "Henüz hiçbir şey yazılmadı.",
  "Analyse the repository": "Depoyu analiz et",
  "Analyse again": "Yeniden analiz et",
  "Reading the repository…": "Depo okunuyor…",
  "Project brief": "Proje künyesi",
  "Add a line": "Madde ekle",
  "No lines yet.": "Henüz madde yok.",
  "Approved — every agent reads this.": "Onaylandı — bunu her ajan okuyor.",
  "Not approved yet: the agents are told nothing until you approve it.":
    "Henüz onaylanmadı: sen onaylayana kadar ajanlara hiçbir şey söylenmiyor.",
  "Save draft": "Taslağı kaydet",
  "Approve and continue": "Onayla ve devam et",
  "Saved — the agents read this from now on": "Kaydedildi — ajanlar bundan sonra bunu okuyor",
  Detail: "Ayrıntı",
  // the brief's categories
  stack: "teknoloji",
  modules: "modüller",
  conventions: "kurallar",
  deployment: "dağıtım",
  risks: "riskler",
  // the intake
  "A few questions": "Birkaç soru",
  "round {n} of {max}": "{max} turdan {n}. tur",
  "Send the answers": "Cevapları gönder",
  "The Product Owner is reading your answers…": "Ürün Sahibi cevaplarını okuyor…",
  "Tell the agents what you are building and they will start from there.":
    "Ajanlara ne yaptığını anlat, oradan başlasınlar.",
  "What you answered before": "Daha önce ne cevapladın",
  // -- the stack and the deployment (T11.5, T11.6) --------------------------------------
  "What it is written in": "Neyle yazılıyor",
  "Add a part": "Parça ekle",
  Framework: "Framework",
  "The stack was changed": "Teknoloji seçimi değişti",
  "needs deployment approval": "dağıtım onayı bekliyor",
  "DevOps: deployment plan": "DevOps: dağıtım planı",
  "Deployment approval": "Dağıtım onayı",
  "Files it will write": "Yazacağı dosyalar",
  "What you have to supply": "Senin sağlaman gerekenler",
  "Add a file": "Dosya ekle",
  "The deployment plan was changed": "Dağıtım planı değişti",
  "Every file lives under deployment/ — DevOps opens pull requests, it does not edit the product.":
    "Her dosya deployment/ altında durur — DevOps pull request açar, ürünü düzenlemez.",
  Target: "Hedef",
  aws: "AWS",
  azure: "Azure",
  Path: "Yol",
  "Nothing to deploy for this development.": "Bu geliştirme için dağıtılacak bir şey yok.",
  "That is a project name, not its key. The key is short and uppercase, like SCRUM.":
    "Bu projenin adı, anahtarı değil. Anahtar kısa ve büyük harflidir, SCRUM gibi.",
  "The Jira project list could not be loaded, so type the key yourself.":
    "Jira proje listesi yüklenemedi, anahtarı kendin yaz.",
  "Which Jira project? (optional)": "Hangi Jira projesi? (isteğe bağlı)",
  "Jira is connected ({site}).": "Jira bağlı ({site}).",
  "Pick the project its epics, stories and tasks are written into.":
    "Epic, story ve task'larının yazılacağı projeyi seç.",
  "An existing Jira project": "Var olan bir Jira projesi",
  "Open a new Jira project": "Yeni Jira projesi aç",
  "A Scrum project with this key is opened on Jira when you create the project, named after it, led by the connected account.":
    "Projeyi oluşturduğunda Jira'da bu anahtarla bir Scrum projesi açılır, adı projenin adı olur ve bağlı hesap yönetici olur.",
  "A Jira key is 2 to 10 characters, starts with a letter, like SCRUM.":
    "Jira anahtarı 2-10 karakterdir ve harfle başlar, SCRUM gibi.",
  // -- the architecture gate's own tabs and the build setup under them -------------------
  Preferences: "Tercihler",
  "Run command (must contain {port})": "Çalıştırma komutu ({port} içermeli)",
  // -- the Designer ---------------------------------------------------------------------
  Design: "Tasarım",
  "Design approval": "Tasarım onayı",
  design: "tasarım",
  "The screens": "Ekranlar",
  "all {n} approved": "{n} ekranın hepsi onaylı",
  "{done} of {total} approved": "{total} ekranın {done} tanesi onaylı",
  "The web and mobile phases start when every screen has a yes; the backend ones do not wait.":
    "Web ve mobil fazları her ekran onaylanınca başlar; arka uç fazları beklemez.",
  "Open the screen": "Ekranı aç",
  "Not this — draw it again…": "Bunu beğenmedim — yeniden çiz…",
  "what should be different?": "ne değişsin? (zorunlu)",
  "Send it back": "Geri gönder",
  "Is this the screen?": "Bu ekran böyle mi olsun?",
  Surface: "Yüzey",
  Web: "Web",
  Mobile: "Mobil",
  "You asked for:": "Senin istediğin:",
  "no mock": "görsel yok",
  Screens: "Ekranlar",
  "What the Web and Mobile specialists build from.":
    "Web ve Mobil uzmanlarının üzerine inşa ettiği şey.",
  "The Designer has not written the screens yet.": "Tasarımcı ekranları henüz yazmadı.",
  Principles: "İlkeler",
  "What holds across every screen.": "Her ekranda geçerli olanlar.",
  "No principle was recorded beyond the screens themselves.":
    "Ekranların kendisi dışında bir ilke kaydedilmedi.",
  Layout: "Yerleşim",
  components: "bileşenler",
  states: "durumlar",
  interactions: "etkileşimler",
  Notes: "Notlar",
  "Designs the screens the two UI specialists build: purpose, layout, states, interactions.":
    "İki arayüz uzmanının inşa edeceği ekranları tasarlar: amaç, yerleşim, durumlar, etkileşimler.",
  "designing the screens": "ekranları tasarlıyor",
  // -- the cost tab ---------------------------------------------------------------------
  Costs: "Maliyet",
  Spent: "Harcanan",
  Expected: "Beklenen",
  Difference: "Fark",
  expected: "beklenen",
  "By agent": "Ajana göre",
  "By phase": "Faza göre",
  "By model": "Modele göre",
  Calls: "Çağrı",
  "Based on": "Neye dayanıyor",
  "no history": "geçmiş yok",
  "{n} call(s)": "{n} çağrı",
  "calls with no stored price": "kayıtlı fiyatı olmayan çağrılar",
  "No model prices yet": "Henüz model fiyatı yok",
  "Nothing can be costed until the price table has been fetched. It runs once a day, and you can fetch it now from Settings.":
    "Fiyat tablosu çekilmeden hiçbir şey hesaplanamaz. Günde bir kez çalışır, Ayarlar'dan hemen de çekebilirsin.",
  "No development has run yet.": "Henüz bir geliştirme çalışmadı.",
  "{n} call(s) ran on a model with no stored price and are not in these totals.":
    "{n} çağrı, kayıtlı fiyatı olmayan bir modelde koştu ve bu toplamlara dâhil değil.",

  // -- accounts: signing up, confirming an address, getting back in -----------------------------
  "Create an account": "Hesap aç",
  "Create account": "Hesabı aç",
  "You bring your own model keys; Slipwright runs the agents.":
    "Model anahtarların sende kalır; ajanları Slipwright çalıştırır.",
  Email: "E-posta",
  "Your name": "Adın",
  optional: "isteğe bağlı",
  "At least 8 characters.": "En az 8 karakter.",
  "Already have an account?": "Hesabın var mı?",
  "Confirm your email": "E-postanı doğrula",
  "Confirming…": "Doğrulanıyor…",
  "We sent a link to {email}. Open it to finish setting up your account.":
    "{email} adresine bir bağlantı gönderdik. Hesabını tamamlamak için aç.",
  "Open the link we sent you to finish setting up your account.":
    "Hesabını tamamlamak için gönderdiğimiz bağlantıyı aç.",
  "Send the link again": "Bağlantıyı yeniden gönder",
  "Sending…": "Gönderiliyor…",
  "Sent. Check your inbox.": "Gönderildi. Gelen kutuna bak.",
  "Back to sign in": "Girişe dön",
  "Forgot your password?": "Şifreni mi unuttun?",
  "We will mail you a link to set a new one.":
    "Yeni bir şifre belirlemen için sana bağlantı yollayacağız.",
  "Send the link": "Bağlantıyı gönder",
  "Check your inbox": "Gelen kutuna bak",
  "If that address has an account, a link is on its way.":
    "O adrese ait bir hesap varsa bağlantı yola çıktı.",
  "Set a new password": "Yeni şifre belirle",
  "New password": "Yeni şifre",
  "Signing in everywhere else will need the new password.":
    "Diğer her yerde artık yeni şifreyle gireceksin.",
  "Save and sign in": "Kaydet ve gir",
  "This link is no longer valid": "Bu bağlantı artık geçerli değil",
  "Ask for a new one": "Yenisini iste",
  "Confirm {email} before starting any work.": "İş başlatmadan önce {email} adresini doğrula.",
  "Confirm now": "Şimdi doğrula",
  "needs design approval": "tasarım onayı bekliyor",
  // -- the Designer's About card --------------------------------------------------------
  "The Designer decides what each screen is before anyone builds one: what a person comes there to do, what sits where, which states it has and what every control does. It draws each screen as a self-contained HTML mock so you approve a picture rather than a paragraph. The Web and Mobile specialists then build the same screen from the same decision, which is what keeps the two halves of a product looking like one product.":
    "Tasarımcı, kimse bir ekran yazmadan önce o ekranın ne olduğuna karar verir: kişi oraya ne yapmaya gelir, ne nerede durur, hangi durumları vardır ve her kontrol ne yapar. Her ekranı kendi içinde kapalı bir HTML maket olarak çizer, böylece bir paragrafı değil bir resmi onaylarsın. Web ve Mobil uzmanları sonra aynı ekranı aynı karardan inşa eder; ürünün iki yarısını tek bir ürün gibi gösteren de budur.",
  "After you approve the plan, and only when that plan has a web or mobile phase in it. The backend phases are built while its screens wait for you; the first UI phase stops until they are approved.":
    "Planı onayladıktan sonra, ve yalnız o planda bir web ya da mobil faz varsa. Backend fazları, ekranlar seni beklerken yapılır; ilk arayüz fazı onaylanana kadar durur.",
  "The approved backlog and the plan's phases": "Onaylanmış backlog ve planın fazları",
  "The design standards and the core rules": "Tasarım standartları ve çekirdek kurallar",
  "Its previous screens, and your reason when you sent one back":
    "Önceki ekranları ve birini geri gönderdiğindeki gerekçen",
  "One entry per screen: purpose, layout, components, states and interactions":
    "Ekran başına bir kayıt: amaç, yerleşim, bileşenler, durumlar ve etkileşimler",
  "An HTML mock of each screen, drawn in its ordinary state":
    "Her ekranın olağan hâliyle çizilmiş HTML maketi",
  "The few principles that hold across every screen": "Her ekranda geçerli olan birkaç ilke",
  "Writing code or files — it has no permission to, and the specialists build from what it wrote":
    "Kod ya da dosya yazmak — buna izni yok, uzmanlar onun yazdığından inşa eder",
  "Inventing a screen the backlog does not ask for: it says so in the notes instead":
    "Backlog'un istemediği bir ekranı uydurmak: bunun yerine notlarında söyler",
  "Choosing colours, fonts or a component library — that follows the stack the Architect chose":
    "Renk, yazı tipi ya da bileşen kütüphanesi seçmek — o, Mimar'ın seçtiği yığını izler",

  // -- support and email settings --------------------------------------------------------
  Support: "Destek",
  "Write to us and we answer by email.": "Bize yaz, e-posta ile dönelim.",
  "Tell us what you need. It reaches us as an email, and we reply to the address below — so a question written here does not need chasing anywhere else.":
    "Neye ihtiyacın olduğunu yaz. Talebin bize e-posta olarak ulaşır ve aşağıdaki adrese yanıt veririz — yani buraya yazdığın soruyu başka bir yerden takip etmen gerekmez.",
  "What is it about?": "Konu nedir?",
  "A question": "Bir sorum var",
  "Something is broken": "Bir şey bozuk",
  Billing: "Faturalandırma",
  "A request": "Bir talebim var",
  "Something else": "Başka bir şey",
  "Reply to": "Yanıt adresi",
  "your address": "adresin",
  "Empty means {email}, the address on your account.":
    "Boş bırakırsan hesabındaki adres kullanılır: {email}",
  "Your account has no address, so please give one here.":
    "Hesabında adres yok; lütfen buraya bir adres yaz.",
  Subject: "Konu",
  "One line: what happened": "Tek satır: ne oldu",
  "Your message": "Mesajın",
  "What you were doing, what you expected, and what happened instead. A project name or a job link helps.":
    "Ne yapıyordun, ne bekliyordun ve onun yerine ne oldu. Bir proje adı ya da iş bağlantısı işimizi kolaylaştırır.",
  "What you have asked before": "Daha önce sorduklarım",
  "Nothing yet.": "Henüz bir şey yok.",
  "Anything you send will be listed here with its state.":
    "Gönderdiğin her talep, durumuyla birlikte burada listelenir.",
  About: "Konusu",
  Sent: "Gönderildi",
  answered: "yanıtlandı",
  open: "açık",
  "Sent. We reply to {email}.": "Gönderildi. {email} adresine yanıt vereceğiz.",
  "Saved. This installation has no mail server configured yet, so an administrator reads it in the app rather than by email.":
    "Kaydedildi. Bu kurulumda henüz posta sunucusu tanımlı değil; talebini bir yönetici e-posta yerine uygulama üzerinden okuyacak.",
  "Saved, but the email could not be sent — an administrator can still read it here. Nothing you wrote was lost.":
    "Kaydedildi ama e-posta gönderilemedi — bir yönetici yine de burada okuyabilir. Yazdıklarının hiçbiri kaybolmadı.",

  "The sender every letter goes out from, and where support requests land.":
    "Tüm postaların çıktığı gönderici ve destek taleplerinin düştüğü adres.",
  Sending: "Gönderim",
  "letters go out over SMTP": "postalar SMTP ile gidiyor",
  "no mail server: letters wait in the outbox":
    "posta sunucusu yok: postalar giden kutusunda bekliyor",
  "Until a mail server is set here, verification links, password resets and support requests are written to the outbox instead of being sent. Nothing is lost either way.":
    "Burada bir posta sunucusu tanımlanana kadar doğrulama bağlantıları, şifre sıfırlamaları ve destek talepleri gönderilmek yerine giden kutusuna yazılır. Her iki durumda da hiçbir şey kaybolmaz.",
  Transport: "Taşıma",
  "SMTP server": "SMTP sunucusu",
  "Outbox only (send nothing)": "Yalnızca giden kutusu (hiçbir şey gönderme)",
  Security: "Güvenlik",
  "STARTTLS (usually port 587)": "STARTTLS (genelde port 587)",
  "SSL/TLS (usually port 465)": "SSL/TLS (genelde port 465)",
  "None (port 25)": "Yok (port 25)",
  Server: "Sunucu",
  "Leave empty for a server that needs no login.": "Giriş istemeyen bir sunucu için boş bırak.",
  "paste a password": "bir şifre yapıştır",
  "Stored encrypted and never shown again. Empty keeps the stored one.":
    "Şifrelenerek saklanır ve bir daha gösterilmez. Boş bırakırsan kayıtlı olan korunur.",
  "Sender address": "Gönderici adresi",
  "Sender name": "Gönderici adı",
  "Address of this installation": "Bu kurulumun adresi",
  "What the links in the letters point at — verification and password resets.":
    "Postalardaki bağlantıların işaret ettiği adres — doğrulama ve şifre sıfırlama.",
  "Forget the password": "Şifreyi unut",
  "Send a test message to": "Deneme mesajını şu adrese gönder",
  "Send a test message": "Deneme mesajı gönder",
  "Sent to {email}. If it arrives, the settings are right.":
    "{email} adresine gönderildi. Ulaştıysa ayarlar doğru.",
  "Written to the outbox for {email}: no mail server is configured yet.":
    "{email} için giden kutusuna yazıldı: henüz tanımlı bir posta sunucusu yok.",
  "Support requests": "Destek talepleri",
  "What people write on the support page is emailed here. Several addresses may be given, separated by commas. Left empty, it goes to every administrator who has confirmed an address.":
    "Destek sayfasına yazılanlar bu adrese e-posta olarak gider. Virgülle ayırarak birden çok adres yazabilirsin. Boş bırakırsan adresini doğrulamış tüm yöneticilere gider.",
  "Support address": "Destek adresi",
  "support@example.com": "destek@ornek.com",
  "As things stand a request reaches:": "Şu anki ayarlarla bir talep şuraya ulaşıyor:",
  "A request would reach nobody: no support address is set and no administrator has a confirmed address. Requests are still kept, under Requests.":
    "Bir talep şu an kimseye ulaşmaz: destek adresi tanımlı değil ve hiçbir yöneticinin doğrulanmış adresi yok. Talepler yine de saklanır; Talepler sekmesinden görebilirsin.",
  "What people have written": "Gelen talepler",
  "Requests written on the support page are kept here as well as emailed.":
    "Destek sayfasına yazılan talepler e-postayla gönderilmenin yanı sıra burada da saklanır.",
  "The email did not go out:": "E-posta gönderilemedi:",
  "Mark answered": "Yanıtlandı olarak işaretle",
  Reopen: "Yeniden aç",
  emailed: "e-postalandı",
  "in the outbox": "giden kutusunda",
  "not sent": "gönderilemedi",
  "The outbox": "Giden kutusu",
  "Letters written but never sent — verification links included.":
    "Yazılmış ama hiç gönderilmemiş postalar — doğrulama bağlantıları dâhil.",
  "Empty.": "Boş.",

  // -- email settings, as tabs ------------------------------------------------------------
  Requests: "Talepler",
  "How letters leave": "Postalar nasıl çıkıyor",
  "The mail server every letter goes out from: verification links, password resets and support requests alike.":
    "Her postanın çıktığı posta sunucusu: doğrulama bağlantıları, şifre sıfırlamaları ve destek talepleri dâhil.",
  "nothing is sent yet": "henüz hiçbir şey gönderilmiyor",
  "Where support requests land": "Destek talepleri nereye düşüyor",
  "The inbox that receives what people write on the support page. Left empty, it falls back to the administrators.":
    "Destek sayfasına yazılanların düştüğü kutu. Boş bırakılırsa yöneticilere geri düşer.",
  "someone gets them": "ulaşacak biri var",
  "nobody gets them": "ulaşacak kimse yok",
  "Every request, kept here whatever the mail server did, so an unanswered question is never only an email.":
    "Posta sunucusu ne yaparsa yapsın her talep burada saklanır; yanıtlanmamış bir soru hiçbir zaman yalnızca bir e-postadan ibaret kalmaz.",
  "nothing waiting": "bekleyen yok",
  "Letters written but never sent, verification links included. An installation with no mail server keeps them here.":
    "Yazılmış ama hiç gönderilmemiş postalar — doğrulama bağlantıları dâhil. Posta sunucusu olmayan bir kurulum bunları burada tutar.",
  empty: "boş",
  "Nothing is waiting: every letter has gone out.": "Bekleyen yok: bütün postalar çıkmış.",
  "Several addresses may be given, separated by commas.":
    "Virgülle ayırarak birden çok adres yazabilirsin.",

  // -- the result tab before there is a result ---------------------------------------------
  "Nothing has come out yet.": "Henüz ortaya bir şey çıkmadı.",
  "This development is still running — it is {state}. What it produced, and how to take it into your working copy, appears here once it finishes.":
    "Bu geliştirme hâlâ sürüyor — şu an {state}. Ne ürettiği ve onu kendi çalışma kopyana nasıl alacağın, iş bittiğinde burada görünecek.",

  // -- the tests tab filter bar ------------------------------------------------------------
  "Clear the filters": "Filtreleri temizle",
  "{shown} of {total} run(s)": "{total} çalıştırmanın {shown} tanesi",
  "All {n} run(s) are still here — the filters above are hiding them.":
    "{n} çalıştırmanın hepsi hâlâ burada — yukarıdaki filtreler onları gizliyor.",

  // -- getting started: the checklist a new account sees -----------------------------------------
  "Getting set up": "Kuruluma başlayalım",
  "Hide this": "Bunu gizle",
  "Slipwright runs the agents; the model keys stay yours. Two things to connect and you are ready.":
    "Ajanları Slipwright çalıştırır; model anahtarları sende kalır. İki şeyi bağlayınca hazırsın.",
  "Add a model key": "Model anahtarı ekle",
  "Your own key, from any provider. Nothing runs without one.":
    "Kendi anahtarın, hangi sağlayıcıdan istersen. Bu olmadan hiçbir şey koşmaz.",
  "Connect GitHub or Bitbucket": "GitHub ya da Bitbucket bağla",
  "So a finished development can be pushed and opened as a pull request.":
    "Biten geliştirme gönderilip pull request olarak açılabilsin diye.",
  "Optional. The backlog is mirrored there when you do.":
    "İsteğe bağlı. Bağlarsan backlog oraya aynalanır.",
  "Start your first project": "İlk projeni aç",
  "Pick a repository, or let Slipwright open a new one.":
    "Bir depo seç ya da Slipwright senin için yeni bir tane açsın.",
  "Example: a Notes app": "Örnek: Notlar uygulaması",
  "this is the example project: it is there to read, not to run":
    "bu örnek proje: okumak için var, çalıştırmak için değil",
};
