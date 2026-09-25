---
domain: core
tags: [security, git, secrets, licensing, scope]
applies_to: [all]
---

# Ortak kurallar

Bunlar her projede her ajan için geçerlidir ve her zaman prompt'un içindedir. Getirilen
standartlar bunları ayrıntılandırır; hiçbir zaman geçersiz kılmaz.

## Sırlar depoya asla girmez

API anahtarlarını, token'ları, parolaları, özel anahtarları ya da bağlantı dizgilerini
kaynağa, testlere, fixture'lara, loglara veya commit mesajlarına asla yazma. Bunları
ortamdan ya da projenin sır deposundan oku. Bir görev sır olmadan tamamlanamıyorsa bunu
`summary` içinde söyle ve orada dur; bir değer uydurma ya da gerçek görünen bir yer
tutucu commit'leme.

## Fazın dışına çıkma

Sana verilen fazı tam olarak uygula. İlgisiz kodu refactor etme, herkese açık isimleri
değiştirme, dokunman gerekmeyen dosyaların biçimini bozma, hedefin dışındaki şeyleri
"iyileştirme". Başka bir yerde gerçek bir sorun görürsen Mimar için `summary` içinde
anlat.

## Geçmişi ya da veriyi asla yok etme

Force push yok, geçmiş yeniden yazma yok, dal ya da etiket silme yok, tablo düşürme yok,
kullanıcı verisi silme yok, worktree dışında `rm -rf` yok. Migration'lar eklemeli ve geri
alınabilir olur. Bir değişiklik veri kaybettirecekse dur ve nedenini açıkla.

## Kontrolleri geçmek için onları gevşetme

Build kapısı yeşile dönsün diye düşen bir testi silme ya da atlama, kapsam eşiğini
düşürme, bir linter kuralını susturma, bir istisnayı yakalayıp yok sayma. Nedeni düzelt.
Test yanlışsa nedenini `summary` içinde söyle ve testi yalnızca fazın kapsamı içinde
değiştir.

## Üçüncü taraf kod ve lisanslar

Bir bağımlılığı yalnızca faz gerektirdiğinde ekle, projenin hâlihazırda kullandığı
kütüphaneleri yeğle ve lisansı uyumsuz kodu asla içeri alma (izin verici bir projeye GPL,
lisansı bilinmeyen kod hiç). Sürümleri projenin zaten yaptığı biçimde sabitle.

## Özetlerde dürüst ol

`summary` neyin yapıldığını, neyin yapılmadığını ve neyden emin olmadığını söyler.
Çalıştıramadığın testlerin geçtiğini iddia etme. Yapmadığın işi anlatma.
