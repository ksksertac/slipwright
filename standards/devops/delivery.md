---
domain: devops
tags: [ci, github-actions, docker, deployment, pull-requests, secrets, infrastructure, monitoring]
applies_to: [github, docker, compose, kubernetes, terraform, any]
---

# Teslimat ve altyapı

## Pull request'ler

İş dalı başına tek PR; başlık emir kipinde ve 70 karakterin altında; gövde neyin
değiştiğini, nedenini, nasıl test edildiğini ve inceleyicinin önce nereye bakması
gerektiğini söyler. İzleyicideki kaydı bağla. Dalı taban dalın üzerine rebase'li tut;
tabanı özellik dalına tekrar tekrar merge etme. Altyapıyı değiştiren bir PR, plan
çıktısını (`terraform plan`, migration SQL'i) açıklamasında taşır.

## Sürekli entegrasyon

CI her push'ta çalışır: lint, tip kontrolü, birim testleri, `docker compose` servisleriyle
entegrasyon testleri ve her çıktının build'i. Hat depoda tanımlıdır, sabitlenmiş
action/imaj sürümleri kullanır, bağımlılıkları lock dosyasının özetine göre önbellekler ve
en ucuz kontrolde erken düşer. Kırmızı CI merge'ü engeller; açık kaydı olan bilinen bir
flake değilse kırmızı bir koşuyu düzeltmeden yeniden çalıştırma.

## Konteynerler

Çok aşamalı Dockerfile'lar; çalışma imajında yalnızca koşan şey bulunur (derleyici yok,
geliştirme bağımlılığı yok, build aşamasının kaynağı yok). Temel imajları etiketle
sabitle ve ayda bir tazele. İş yükü elverdiğince root olmayan bir kullanıcıyla çalıştır.
Her imajın bir `HEALTHCHECK`'i olur ve yapılandırmayı yalnızca ortam değişkenleriyle alır.
Sırları katmanlara ya da build argümanlarına asla gömme.

## Dağıtım

Dağıtımlar bildirimseldir (compose, Helm, Terraform) ve idempotent'tir; değişiklik yokken
yeniden koşmak hiçbir şeyi değiştirmez. Sağlık kontrolleriyle ve gerekmeden önce
denenmiş bir geri alma yoluyla yay. Veritabanı migration'ları yeni sürüm trafik almadan
önce koşar ve hâlâ çalışan sürümle geriye dönük uyumludur. Riskli davranışı özellik
bayrakları kapatır ki geri almak yeniden dağıtım değil, bayrak çevirmek olsun.

## Sırlar ve erişim

Sırlar platformun sır yöneticisinde durur ve sürece açılışta ortam değişkeni olarak
ulaşır; depoda, CI loglarında ya da imajlarda asla bulunmaz. Her ayrılışta ve her sızıntı
şüphesinde döndür. CI token'ları en aza kısıtlanır (contents: write, pull-requests: write)
ve süresi dolar. Üretim erişimi role bağlıdır, denetlenir ve asla paylaşılmaz.

## İzleme ve nöbet

Her servis bir panoyla (trafik, hata, gecikme, doyum) ve nedenlere değil kullanıcının
hissettiği belirtilere (hata oranı, p95 gecikme, kuyruk gecikmesi) kurulmuş uyarılarla
gelir. Uyarıların bir runbook bağlantısı olur. Log saklama ve kişisel veri kuralları
yazılıdır. Bir olaydan sonra, eylemleri olan kısa ve suçlamasız bir yazı depoya girer.

## Kırmızı CI'yı düzeltmek

Bir iş dalında CI düştüğünde önce düşen adımın logunu oku; nedeni en küçük değişiklikle
düzelt; adımı devre dışı bırakma, kontrolü gevşetme ya da gerçek bir hatayı örtmek için
zaman aşımını büyütme. Hata ilgisiz bir kararsızlıksa, bir insan karar verebilsin diye
özette log alıntısıyla birlikte bunu söyle.
