---
domain: architecture
tags: [profile, build, test, run, phases, decisions, contracts, repository]
applies_to: [all]
---

# Mimari ve planlama

## Bir depoyu okumak

Manifestten (`pyproject.toml`, `package.json`, `go.mod`, `pom.xml`, …), lock dosyasından,
CI yapılandırmasından ve README'den başla; bunlar dosya ağacından çok daha fazlasını
söyler. Paket yöneticisini alışkanlıkla değil, var olan lock dosyasından belirle
(`uv.lock`, `package-lock.json`, `pnpm-lock.yaml`). Monorepo'ları (birden çok manifest)
not et ve isteğin ilgilendirdiği paketi adıyla söyle.

## Build, test ve çalıştırma komutlarını seçmek

CI'ın zaten çalıştırdığı komutları yeğle; onların çalıştığı bilinir. Build komutu
projenin kullandığı linter'ları ve tip kontrollerini içermelidir; test komutu tüm takımı
etkileşimsiz ve sessiz çıktıyla koşar. Çalıştırma komutu servisi düz `{port}` yer
tutucusu üzerinde başlatır ve arka plana düşmez. Deponun desteklemediği bir komutu asla
uydurma — bunun yerine neyin eksik olduğunu söyle.

## Fazları yazmak

Fazlar küçük, sıralı ve tek başına doğrulanabilir olur: her biri build kapısını kendi
başına geçebilir ve tam olarak bir backlog task'ını uygular. Backend sözleşmeleri, onları
tüketen arayüzlerden önce gelir. Faz başına tek alan (backend, web, mobil, altyapı,
doküman). Her fazın dokunacağı dosyaları adıyla yaz — uzmanın bağlamı böyle seçilir. Bir
task tek alanda tek faz olamıyorsa, alanları karıştırmak yerine bunu `summary` içinde
söyle ki backlog bölünsün.

## Yazmaya değer kararlar

Bir inceleyicinin "neden böyle?" diye soracağı her yerde karar yaz: yeni bir bileşen ya
da bağımlılık, bir veri modeli değişikliği ve migration'ı, backend ile bir arayüz
arasındaki sözleşme (uç nokta, gövde, hata kodları), verilen bir ödünleşim (gecikme
yerine tutarlılık, …), sonraki fazları kısıtlayan her şey. Her biri tek cümle: seçimi ve
nedenini söyler. Yalnızca isteği tekrarlayan kararları yazma.

## Alanlar arası sözleşmeler

Backend ve arayüz fazları bir sözleşmeyi paylaştığında, sözleşmeyi backend fazı açıkça
tanımlar (yollar, metotlar, istek ve yanıt biçimleri, hata kodları, sayfalama) ve arayüz
fazı tam olarak onu tüketir. Sözleşmeyi kararların içine koy ki iki uzman da aynı metni
görsün. Neredeyse aynısı olan yeni bir uç nokta eklemek yerine var olanı genişletmeyi
yeğle.

## Ne zaman durup sormalı

Backlog, tasarımı değiştirecek biçimde belirsizse (iki makul okuma farklı fazlara
götürüyorsa), deponun sahip olmadığı bir bağımlılık ya da servis gerekiyorsa, ya da bir
ortak kuralla çelişiyorsa tahmin yürütme: belirsizliği `summary` içinde anlat ki insan
kapıda karar versin.
