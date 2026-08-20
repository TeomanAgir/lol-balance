# Skorun nasıl hesaplanıyor?

> Bu rehber oyuncular içindir; teknik tanım değildir. Bağlayıcı spesifikasyon
> repo'daki `docs/rating_contract.md` dosyasındadır (aktif engine:
> `openskill-pl-blend30-s2-v1`).

Leaderboard'daki o tek sayı rastgele değil: her custom maçtan sonra aynı
kurallarla, herkes için aynı şekilde yeniden hesaplanıyor. İşte adım adım tüm mutfak.

## Büyük resim

**Skor = %30 kazanmak + %70 nasıl oynadığın − belirsizlik payı**

```
 %30 W/L  |  %70 Performans (KDA · hasar · gold · CS · vizyon)
```

Bu ikisinin harmanından bir "efektif güç" çıkar; sistem senden ne kadar emin
değilse o kadarını da düşer. Az maç = temkinli skor.

## 1. Kazan/kaybet çekirdeği: mu ve sigma

Sistemin temelinde **OpenSkill** adında bir beceri modeli var (satranç ELO'sunun
takım oyunları için geliştirilmiş akrabası). Her oyuncu için iki sayı tutar:

- **mu (μ)** — sistemin senin gücün hakkındaki tahmini. Herkes 25'ten başlar.
  Maç **kazanınca artar, kaybedince düşer**. Ne kadar değişeceği rakibe bağlıdır:
  güçlü bir takımı yenersen çok kazanırsın, zayıf bir takıma kaybedersen çok
  kaybedersin.
- **sigma (σ)** — sistemin bu tahminden ne kadar **emin olmadığı**. Herkes 8.33
  ile başlar; her maçla biraz düşer. Çok maç oynayan oyuncunun sigma'sı küçüktür:
  sistem onu artık tanıyordur.

> Önemli ayrıntı: bu adıma bireysel performans hiç karışmaz. mu yalnızca maçın
> sonucuna (ve iki takımın gücüne) bakar. "İyi oynadım ama kaybettik" bu adımda
> seni kurtarmaz — onun için sonraki adımlar var.

## 2. Maç performans puanı: o maçta ne kadar iyiydin?

Her maçtan sonra, o maçtaki **10 oyuncuya kıyasla** nasıl oynadığın ölçülür.
Beş bileşen vardır; her biri "maçın ortalamasına göre oranın"dır — 1.0 tam
ortalama demektir:

| Bileşen | Ne ölçer | Neye kıyasla |
|---|---|---|
| KDA | (kill + asist) / ölüm | maçtaki 10 kişinin ortalaması |
| Hasar payı | şampiyonlara hasarının takım içindeki payı | eşit pay olan %20'ye oran |
| Gold payı | gold'unun takım içindeki payı | eşit pay olan %20'ye oran |
| CS/dk | dakika başına minyon | maç ortalaması |
| Vizyon | vision score | maç ortalaması |

Beş farklı metrik bilerek seçildi: hasar ve gold carry'yi yakalar, vizyon
support'u, KDA herkesi. Böylece tek bir rol sistematik avantajlı olmaz.

Her bileşen **0.5 ile 2.0 arasına kırpılır** (tek bir çılgın istatistik skoru
uçuramaz), sonra hepsinin ortalaması alınır. Çıkan sayı o maçın **performans
puanıdır**: 1.0 = ortalama oyuncu, 1.3 = maçın iyilerinden, 0.7 = kötü bir gün.

> Bir istatistik kayıtta yoksa (ör. elle girilmiş eski maç) o bileşen hesaba
> katılmaz; hiçbiri yoksa puan nötr kabul edilir (1.0). Kimse veri
> eksikliğinden ceza yemez.

## 3. Kariyer performansı: P_avg

Geçerli tüm maçlarındaki performans puanlarının **ortalaması** alınır. Buna
P_avg denir. Tek bir efsane maç seni taşımaz, tek bir felaket maç da batırmaz —
istikrar kazanır.

## 4. Harman ve görünen skor

Şimdi iki dünya birleşir. Önce performans ortalaması mu ile aynı ölçeğe
çevrilir, sonra **%30 W/L + %70 performans** ağırlığıyla harmanlanır:

```
mu_eff = 0.3 × mu + 0.7 × (25 + 20 × (P_avg − 1))
SKOR   = mu_eff − 2 × sigma
```

"− 2 × sigma" şu demek: sistem, gücünden emin olmadığı kadarını skorundan
**peşinen düşer**. Az maç oynamış birinin skoru bu yüzden baskıdır; maç
oynadıkça sigma düşer ve gerçek gücün skora yansır. Hiç maçı olmayan oyuncu
~8.33'ten başlar (25 − 2 × 8.33 ≈ 8.33) — leaderboard'da nötr görünmesinin
sebebi bu.

> **Ölçek notu:** bu sürüme kadar sigma katsayısı 3 idi ve W/L payı %20'ydi;
> hiç maçı olmayan oyuncu tam 0'dan başlıyordu. Katsayı 3'ten 2'ye inince
> tüm skorlar (herkesinki, aynı oranda) **~7 puan yukarı kaydı** — bu bir
> "herkes birden iyileşti" değil, yalnızca gösterim ölçeğinin değişmesi.
> Sıralama anlamı aynı kalır.

## Uçtan uca bir örnek

16 maç oynamış bir oyuncu düşünelim: mu = 26.29 (25'in üstü → kazanma
bilançosu artıda), sigma = 7.36 (hâlâ epey belirsizlik var), P_avg = 1.27
(maçlarında ortalamanın %27 üstünde oynuyor).

```
mu_eff = 0.3 × 26.29 + 0.7 × (25 + 20 × 0.27)
       = 7.89 + 0.7 × 30.33 = 29.12

SKOR   = 29.12 − 2 × 7.36 = 14.40
```

Dikkat: skorunun 21.2 puanı performanstan, 7.9 puanı W/L'den geliyor — ama
14.7 puan belirsizliğe gitti. Bu oyuncu maç oynamaya devam ettikçe sigma
düşecek ve skoru, oyunu hiç değişmese bile yükselecek.

## Rol skorları: aynı hesap, rol başına ayrı defter

Ana skorun yanında her rol için (TOP, JUNGLE, MID, BOT, SUPPORT) **ayrı bir
skor** tutulur. Formül birebir aynıdır; tek fark, her rolün yalnızca **o rolde
oynadığın maçları** saymasıdır. Bir maçın rol defterine girmesi için 10
oyuncunun da rolünün bilinmesi ve her takımda 5 rolün birer kez bulunması
gerekir.

**Takım dengeleme bu rol skorlarını kullanır:** sistem 10 kişiyi takımlara
ayırırken herkesi en güçlü olduğu role yerleştirmeye çalışarak en adil
eşleşmeyi arar. Yani BOT'ta canavar ama JUNGLE'da turist isen, sistem bunu
bilir.
