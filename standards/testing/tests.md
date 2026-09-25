---
domain: testing
tags: [pytest, unit, integration, e2e, fixtures, coverage, flaky, test-cases, review]
applies_to: [python, pytest, typescript, vitest, playwright, any]
---

# Test

## Test piramidi ve neyi test etmeli

Testlerin çoğu, davranışı herkese açık arayüz üzerinden sınayan birim testleridir;
entegrasyon testleri her seferinde tek bir gerçek sınırı (veritabanı, HTTP katmanı, bir
kuyruk) kapsar, gerisi sahtedir; birkaç uçtan uca test ana kullanıcı yolculuklarını
yürür. Özel yardımcıları doğrudan test etme, log metnine göre doğrulama yapma ve çatıyı
test etme.

## Adlandırma ve yapı

Test dosyaları kaynak ağacını yansıtır (`tests/test_<modul>.py`, `Foo.test.ts`). Adlar
davranışı ve koşulu söyler: `test_odenmemis_faturada_iade_reddedilir`. Hazırla–uygula–
doğrula, aralarında boş satırla; test başına tek davranış; doğrulama mesajı ne olması
gerektiğini açıklar. Ortak kurulum modül düzeyindeki global'lerde değil, fixture'larda
yaşar.

## Fixture'lar ve sahteler

Dış servisler için mock yerine süreç içi sahteleri yeğle (sahte bir Jira, çağrıları
kaydeden sahte bir posta göndericisi); yalnızca kendi sahip olduğun sınırda mock'la. Her
sahte, gerçeğiyle aynı sözleşmeyi uygular (durum kodları, hata biçimleri). Testler ağa,
gerçek saate ya da geçici dizin dışındaki gerçek dosya sistemine asla dokunmaz.

## Test vakalarını önermek

Kod yazılmadan önce test vakası istendiğinde, bunları `name` + neyi kontrol ettiği olarak
listele: mutlu yol, her doğrulama kuralı, kodun beyan ettiği her hata yolu, boş/sıfır
durumu, sınırlar (limitler, sayfalama uçları), tasarımın söz verdiği yerlerde eşzamanlılık
ya da idempotency, ve izinler. Davranış başına tek vaka; "her şeyi test et" vakaları yok;
fazın uygulamadığı davranışlar için vaka yok.

## Belirlilik ve hız

Uyku yok, zamana bağlı doğrulama yok (saati enjekte et), testler arası sıra bağımlılığı
yok, paylaşılan değişken durum yok. Bir birim testi milisaniyelerle ölçülür; bir saniyeden
yavaş olan her şeyi işaretle ve varsayılan koşunun dışında tut. Kararsız testleri
göründükleri gün düzelt; asla yeniden denemeyle sarmalama.

## Kapsam ve kapılar

Yeni kod, eklediği her dal için testiyle gelir; build kapısı bir alt kümeyi değil, tüm
takımı koşar. Kapsam bir hedef değil, bir işarettir: sayıyı büyütmek için doğrulamasız
test yazma. Düşen bir test, nedeni düzeltilerek ya da test yanlışsa aynı değişiklik içinde
ve nedeni özette yazılarak değiştirilerek onarılır.

## Bir değişikliği standartlara karşı incelemek

Bir diff'i incelerken ihlalin kırdığı bölümü, dosyayı, satırı ve somut düzeltmeyi yaz.
Sınıflandır: güvenlik, veri kaybı, kırılan sözleşmeler ya da yeni davranışın eksik
testleri için `blocking`; adlandırma, yapı ve biçim için `advisory`. Diff temizse "ihlal
yok" de — rapor edecek bir şey olsun diye bulgu uydurma.
