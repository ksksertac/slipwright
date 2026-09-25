---
domain: backend
tags: [api, http, rest, errors, validation, pagination, versioning]
applies_to: [python, fastapi, node, go, java, any]
---

# Servisler ve API'ler

## API tasarımı

Kaynaklar çoğul isimlerdir (`/invoices`, `/invoices/{id}`); CRUD olmayan eylemler kaynağın
altında alt kaynak ya da fiil olur (`/invoices/{id}/refund`). Niyeti HTTP fiiliyle söyle:
GET okur ve idempotent'tir, PUT değiştirir, PATCH bir kısmını günceller, DELETE siler,
POST oluşturur ya da tetikler. Oluşturmada 201 ile yeni temsili, silmede gövdesiz 204,
bilinmeyen kimlikte 404, durum çakışmasında (mevcut durumunda değişemeyen kaynak) 409
dön. Gövdesinde hata taşıyan 200 asla dönme.

## İstek doğrulama

Her isteği sınırda, çatının şema katmanıyla doğrula (pydantic, zod, bean validation …),
asla handler içinde elle değil. Bilinmeyen alanları reddet. 422 (ya da çatının doğrulama
durumu) ile makinece okunabilir bir alan hatası listesi dön. Veri gerektiren iş kuralları
(tekillik, bakiye kontrolü) servis katmanında yaşar ve serbest metin yerine kararlı bir
hata koduyla 409 ya da 400'e eşlenir.

## Hata yanıtları

Her hata gövdesi aynı biçimdedir: `{"error": {"code": "invoice_not_found", "message":
"insanca okunur", "details": {...}}}`. Kodlar, istemcilerin üzerine dallanabileceği
kararlı snake_case tanımlayıcılardır; mesajlar değişebilir. Yığın izlerini, SQL'i ya da iç
yolları asla dışarı sızdırma. İstisnanın tamamını sunucu tarafında bir korelasyon
kimliğiyle logla ve o kimliği yanıtta dön ki destek onu bulabilsin.

## Sayfalama ve süzme

Liste uç noktaları varsayılan olarak sayfalar (sayfa boyu 50, en çok 200); birkaç bini
geçebilecek her şey için imleç (cursor) sayfalaması kullanılır, offset sayfalaması
yalnızca küçük ve yönetici listeleri için kabul edilir. Süzgeçler alan adını taşıyan
sorgu parametreleridir (`?status=open&customer_id=…`); sıralama `?sort=-created_at`
biçimindedir. Yanıtlar `next_cursor` (ya da `null`) taşır ki istemciler tahmin yürütmesin.

## Sürümleme ve uyumluluk

Alan eklemek serbesttir; bir alanı kaldırmak, yeniden adlandırmak, tipini ya da var olan
bir durumun anlamını değiştirmek sürüm artırmadan yapılmaz. Yola sürüm (`/v2/`) yalnızca
kırıcı bir değişiklik kaçınılmazsa eklenir ve her istemci taşınana dek eski sürüm
çalışmaya devam eder. Kullanımdan kaldırmalar, silinmeden önce yanıtta (`Deprecation`
başlığı) ve değişiklik günlüğünde duyurulur.

## Idempotency ve yeniden denemeler

Para hareketi, mesaj ya da dış yan etki yaratan her POST bir `Idempotency-Key` başlığı
kabul eder ve aynı anahtar tekrar geldiğinde ilk sonucu döner. Başka servislere giden
çağrılar zaman aşımı kullanır (bağlanma 2 sn, okuma 10 sn — belgelenmiş bir istisna
yoksa) ve üstel backoff ile jitter'lı, sınırlı sayıda yeniden dener; yalnızca idempotent
işlemler ve yalnızca geçici hatalarda (zaman aşımı, 502/503/504, bağlantı kopması).
