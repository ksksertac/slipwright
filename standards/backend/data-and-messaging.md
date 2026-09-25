---
domain: backend
tags: [database, migrations, transactions, kafka, events, retry, dead-letter, logging, observability]
applies_to: [python, fastapi, sqlalchemy, postgres, kafka, any]
---

# Veri, mesajlaşma ve gözlemlenebilirlik

## Migration'lar

Her şema değişikliği, ona ihtiyaç duyan kodla birlikte commit'lenen bir migration
dosyasıdır ve canlı sistemde koşabilecek biçimde yazılır: kolonları nullable ya da
varsayılanlı ekle, veriyi ayrı bir adımda doldur, kısıtları sonra sıkılaştır. Bir kolonu
yerinde asla yeniden adlandırma — yenisini ekle, veriyi taşı, eskisini sonraki bir sürümde
düşür. Migration'ların bir geri alma adımı olur ya da neden geri alınamadığı yazılır.
Bunları CI'da hem boş veritabanına hem de veri dolu bir kopyaya karşı çalıştır.

## İşlemler ve tutarlılık

Bir istek, bir transaction; olabildiğince geç açılır ve olabildiğince erken kapanır. Bir
transaction'ı ağ çağrısı boyunca açık tutma. Para ya da stok üzerinde oku-değiştir-yaz
için `SELECT … FOR UPDATE` (ya da iyimser sürüm kolonları) kullan. Tekillikte doğrunun
kaynağı veritabanındaki unique kısıtlardır; uygulama kontrolleri yalnızca daha güzel hata
vermek içindir.

## Kafka tüketicileri ve yeniden denemeler

Tüketiciler idempotent olur: aynı mesajın iki kez işlenmesi zararsız olmalıdır (sonuçla
birlikte saklanan olay kimliğiyle tekilleştir). Offset'leri ancak yan etki kalıcı
olduktan sonra commit et. Geçici bir hatada süreç içinde üstel `backoff` ile yeniden dene
(taban 1 sn, çarpan 2, en çok 5 deneme, jitter); kalıcı bir hatada (bozuk gövde, iş
kuralı) yeniden deneme — hatayı ve özgün başlıkları `<topic>.dlq` konusuna yaz, commit et
ve uyarı üret. Partition'ı süresiz bloklama ve bir mesajı sessizce asla düşürme. Zehirli
mesajlar tüketici grubunu durdurmamalıdır.

## Olay sözleşmeleri

Olaylar sürümlü JSON'dur; her zarfta `event_id`, `event_type`, `occurred_at`, `producer`
ve `schema_version` bulunur. Üreticiler alan kaldırmaz ya da tipini değiştirmez;
tüketiciler bilmedikleri alanları yok sayar. Konu adları küçük harfle
`<alan>.<varlık>.<olay>` biçimindedir (`billing.invoice.paid`). Gövdeler kimlikleri ve
değişen olguları taşır, başka servislerin bütün nesnelerini değil.

## Loglama

Yapılandırılmış loglar (üretimde JSON): `level`, `message`, `correlation_id`, `service`
ve isteğe ilişkin kimlikler (`user_id`, `invoice_id`). Durum değişiklikleri ve dış
çağrılar için INFO, ele alınan sapmalar için WARNING, yalnızca bir insan gerektiğinde
ERROR. Sırları, token'ları, tam kart numaralarını ya da kimlik dışındaki kişisel veriyi
asla loglama. Olay başına tek satır — üretimde çok satırlı dökümler olmaz.

## Metrikler ve izleme

İstek sayısı, gecikme histogramı ve uç nokta başına hata oranını, ayrıca tüketici başına
kuyruk gecikmesini projenin zaten kullandığı biçimde (Prometheus, OpenTelemetry) yayınla.
İz/korelasyon kimliğini HTTP ve mesaj başlıkları boyunca taşı. Veritabanını ve broker'ı
kısa zaman aşımlarıyla yoklayan, her bağımlılığı ayrı ayrı raporlayan bir sağlık uç
noktası ekle.

## Yapılandırma

Yapılandırma ortamdan gelir (twelve-factor), açılışta tipli bir ayar nesnesine
doğrulanarak okunur; eksik ya da bozuk değerde hemen dur. Sırlar için varsayılan olmaz,
geri kalan her şey için makul varsayılanlar olur ve her ayar README'deki tabloda yazılır.
