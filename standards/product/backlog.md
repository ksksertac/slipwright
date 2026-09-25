---
domain: product
tags: [backlog, epics, stories, tasks, acceptance, scope, jira]
applies_to: [all]
---

# Ürün backlog'u

## Backlog'u yazmadan önce ürünü okumak

Manifestten (`pyproject.toml`, `package.json`, `go.mod`, `pom.xml`, …), lock dosyasından,
CI yapılandırmasından ve README'den başla; bunlar dosya ağacından çok daha fazlasını
söyler. Paket yöneticisini alışkanlıkla değil, var olan lock dosyasından belirle
(`uv.lock`, `package-lock.json`, `pnpm-lock.yaml`). Monorepo'ları (birden çok manifest)
not et ve isteğin ilgilendirdiği paketi adıyla söyle.

## Bir task neyi söylemeli

Bir task, testçi kimseye sormadan doğrulayabildiğinde bitmiştir: kullanıcının gördüğü
davranışı, girdileri ve beklenen sonucu, ayrıca geçerli olan kuralı ya da sınırı yaz.
Teknik seçimi gizleyen tasklar ("Redis kullan") yanlıştır — ihtiyacı söyle ("yanıtlar 200
ms'nin altında") ve seçimi Mimar'a bırak. Bir task, bir uzman: bir task hem backend
değişikliği hem ekran gerektiriyorsa iki task yaz ve hangisinin önce geldiğini söyle.

## Epic, story ve tasklar

Epic, isteği yapanın tanıyacağı bir sonuçtur; story, onun içindeki kullanıcıya görünen tek
bir yetenektir; task ise tek bir fazdır. Başlıklar kısa ve somuttur ("Webhook teslimini
backoff ile yeniden dene", "Webhook iyileştirmeleri" değil). Açıklamalar, bir testçinin
vakalara çevirebileceği bir-iki cümleyle "bitti" halinin neye benzediğini söyler.

## Ne zaman durup sormalı

İstek, tasarımı değiştirecek biçimde belirsizse (iki makul okuma farklı fazlara
götürüyorsa), deponun sahip olmadığı bir bağımlılık ya da servis gerekiyorsa, ya da bir
ortak kuralla çelişiyorsa tahmin yürütme: belirsizliği `summary` içinde anlat ki insan
kapıda karar versin.
