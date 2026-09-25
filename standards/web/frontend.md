---
domain: web
tags: [react, components, state, styling, accessibility, forms, api-client, performance]
applies_to: [react, typescript, vite, nextjs, vue, any]
---

# Web ön yüzü

## Bileşenler ve dosyalar

Dosya başına tek bileşen, dosyayla aynı adda, adıyla dışa aktarılır. Sayfalar özellik
bileşenlerini birleştirir; özellik bileşenleri ortak `components/` klasöründeki arayüz
parçalarını birleştirir — bir parçanın işaretlemesini asla sayfanın içine kopyalama.
Prop'lar açıkça tiplenir; `any` kullanma. Bileşenleri ~250 satırın altında tut; boyuta
göre değil, sorumluluğa göre böl.

## Durum

Sunucu verisi sorgu katmanında yaşar (TanStack Query ya da projenin dengi) ve canlı
güncellemeler tam olarak değişeni geçersiz kılabilsin diye anahtarlanır; kullanıcı
düzenlemedikçe sunucu verisini düzenlemek için yerel duruma asla kopyalama (düzenlerken
`dirty` bilgisini tut ve o ana dek sunucu değerini izle). Yerel arayüz durumu bileşende
kalır. Global depolar yalnızca kesişen konular içindir (oturum, tema). Effect'lerle
prop'lardan türetilen durum olmaz — render sırasında türet.

## API erişimi

Tüm çağrılar API'nin OpenAPI şemasından üretilen tipli istemciden geçer; bileşenlerde ham
`fetch` olmaz. Üç durumu da açıkça karşıla: yükleniyor (tüm sayfayı kaplayan bir dönme
değil, iskelet), hata (sunucunun mesajını taşıyan satır içi uyarı), boş (bundan sonra ne
yapılacağını söyleyen bir cümle). Mutasyonlar düğmede bekleme durumunu gösterir ve
başarıda ya da hatada bir bildirim düşer.

## Stil ve tema

Renkler, boşluklar, köşe yarıçapları ve yazı tipleri `styles.css` içindeki tasarım
token'larından gelir; bir bileşene asla hex değeri gömme. Açık ve karanlık temayı
token'lar üzerinden destekle. Düzenler 360 px genişlikte, 16 px kenar boşluğuyla ve yatay
kaydırma olmadan çalışmalıdır. Tek seferlik ölçüler dışında satır içi stil yerine CSS
sınıflarını yeğle.

## Erişilebilirlik

Etkileşimli her öğe bir `button` ya da `a`'dır (`onClick`'li bir `div` değil), görünür bir
odak halkası ve erişilebilir bir adı vardır; yalnızca ikonlu düğmeler `aria-label` taşır.
Formlarda `label`, girdiye `id` ile bağlanır. Renk tek başına anlam taşımaz — yanına metin
ya da ikon koy. Modaller odağı içeride tutar ve Escape ile kapanır. Bir sayfayı bitti
saymadan önce yalnızca klavyeyle test et.

## Formlar

Gönderimde doğrula ve alan hatalarını alanın yanında göster; beklerken gönder düğmesini
kilitle, bir tıklamayı asla sessizce yutma. İstek düştüğünde kullanıcının yazdığını
koru. Parola ve token alanları `type="password"` olur, sırlar için `autocomplete="off"`
kullanılır ve saklanan bir sır asla girdiye geri yazılmaz.

## Başarım

Rotaya göre kod böl; ağır görünümleri (editörler, grafikler) tembel yükle. Büyük
listeleri her tuş vuruşunda yeniden çizme — aramaları geciktir, listeleri kararlı
kimliklerle anahtarla, pahalı türetmeleri belleğe al. Görsellerde genişlik/yükseklik
bulunur. İyileştirmeden önce tarayıcının profilleyicisiyle ölç; tahmine dayalı
memoization ekleme.
