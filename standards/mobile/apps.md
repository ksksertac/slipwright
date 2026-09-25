---
domain: mobile
tags: [flutter, react-native, ios, android, navigation, offline, sync, permissions, releases]
applies_to: [flutter, react-native, swift, kotlin, any]
---

# Mobil uygulamalar

## Proje yapısı

Katman değil, özellik öncelikli klasörler
(`features/invoices/{screens,widgets,state,api}`). Ortak arayüz parçaları, tema ve ağ
katmanı `core/` altında yaşar. Dosya başına tek ekran; ekran widget'ları birleştirir ve iş
mantığı taşımaz — o mantık özelliğin durum katmanındadır (bloc/provider/store), ki cihaz
olmadan birim testi yazılabilsin.

## Gezinme

Her ekranın bir rota adı ve tipli parametreleri olur; derin bağlantılar aynı rotalara
düşer. Geri davranışı platformu izler: Android'de donanım geri tuşu yığından çıkarır,
iOS'ta gezinme çubuğu kullanılır. Çift dokunuşta aynı ekranı iki kez açma — gezinme
çağrılarını koru. Döndürmede ve arka plana alınmada kaydırma konumunu ve form girdisini
sakla.

## Ağ ve çevrimdışı

Tüm API erişimi tek bir istemciden geçer: temel URL build yapılandırmasından gelir, yetki
başlığı orada eklenir, zaman aşımları (bağlanma 5 sn, okuma 15 sn) oradadır ve HTTP
hatalarını tipli hatalara çeviren tek bir yer vardır. Okumalar önce önbellekten yapılır ve
bayatlık göstergesi taşır; ağ koptuğunda yaşaması gereken yazmalar idempotency anahtarıyla
yerelde kuyruğa alınır ve bağlantı dönünce sırayla yeniden oynatılır. Bağlantı durumunu
kullanıcıya göster; asla sessizce başarısız olma.

## Durum ve veri

API şemasından üretilen değişmez modeller; sınırda ayrıştır, ham JSON'u ortalıkta
dolaştırma. Yerel kalıcılık (SQLite / güvenli depolama) bir repository arayüzünün
arkasındadır. Sırlar ve token'lar platformun güvenli deposuna (Keychain /
EncryptedSharedPreferences) yazılır, düz tercihlere ya da dosyalara asla.

## İzinler ve gizlilik

Bir izni tam ihtiyaç duyulduğu anda, kullanıcının kabul edeceği tek cümlelik bir
gerekçeyle iste; "reddedildi" ve "bir daha sorma" durumlarını ayarlara giden bir yolla
karşıla. En az veriyi topla, mağaza listelerinde beyan et ve kişisel veriyi asla loglama.
Analitik olayları `<ekran>_<eylem>` biçiminde adlandırılır ve kod gibi incelenir.

## Platform alışkanlıkları

Kontrollerde, boşluklarda ve tipografide Android'de Material'ı, iOS'ta Human Interface
Guidelines'ı izle — tasarım sistemi açıkça aksini söylemedikçe. Sistem yazı tipi
ölçeklemesine, karanlık moda, güvenli alanlara ve sağdan sola düzenlere saygı göster.
Dokunma hedefleri en az 44×44 pt olur. Desteklenen en küçük ekranda test et.

## Build'ler ve sürümler

Debug/staging/üretim çeşitleri yalnızca yapılandırmada ayrışır (temel URL, anahtarlar,
özellik bayrakları), kod yollarında asla. Sürüm ve build numarasını CI artırır. Çökme
raporlaması debug dışındaki her build'de açıktır ve sembol yüklemesi yapılır. Bir sürüm
kontrol listesi (ekran görüntüleri, izin metinleri, değişiklik günlüğü) deponun parçasıdır.
