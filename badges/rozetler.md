# Rozet Kataloğu — NİHAİ (GÖREV 24, Teoman onayı 2026-08-19)

**Görsel dosya adı = ID.** Bu klasöre `1.png` … `27.png` olarak konur (numarayı ID ile
birebir eşleştir; `01.png` biçimi de kabul — tümünde aynı kalıbı kullan).
Öneri: kare, şeffaf zeminli PNG, ~512×512, koyu arayüzde okunaklı.

**Kademe (bronz/gümüş/altın) GÖRSEL GEREKTİRMEZ.** 01-06 arası rozetler kademelidir;
kademe ayrımını web arayüzü çerçeve + ışıma + etiketle verir (Teoman kararı). Yani
kademeli rozet için de TEK görsel çizilir.

Sıra sınıflara göre gruplu ve **DONDURULMUŞTUR**: görsel üretimi başladıktan sonra
araya rozet girmez, yeni rozet listenin SONUNA eklenir. Kazanım kurallarının kesin
tanımı (eşitlik kırılımları, NULL kuralları, blok ayrıklığı, kademe eşikleri):
`docs/api_contract.md` §2 "Rozetler". Karar günlüğü: `docs/CHANGE_REQUESTS.md` 2026-08-19.

## Rekor rozetleri — KADEMELİ (bronz / gümüş / altın)
| ID | İSİM | AÇIKLAMA | key |
|---|---|---|---|
| 01 | MVP | Kazanan takımın maçtaki en yüksek performans skorlu oyuncusuna verilir | `mvp` |
| 02 | Vizyon Canavarı | Maçtaki en yüksek vizyon skoruna verilir | `vision` |
| 03 | Topçu | Maçta şampiyonlara en çok hasarı verene verilir | `damage` |
| 04 | CS Makinesi | Maçta dakika başına en yüksek CS'e verilir | `cs_per_min` |
| 05 | Kasa | Maçta en çok gold toplayana verilir | `gold` |
| 06 | Koridor Hâkimi | Kendi koridorundaki rakibinin en az 1.5 katı performans gösterene verilir | `role_duel` |

## Rekor kırma — kademesiz
| ID | İSİM | AÇIKLAMA | key |
|---|---|---|---|
| 07 | Rolün Rekoru | Kendi rolünde grubun tek maçlık performans rekorunu kırana verilir | `role_record` |
| 08 | Yeni Zirve | Kendi kariyer performans rekorunu kırana verilir | `pr_perf` |
| 09 | Kişisel Hasar Rekoru | Kendi kariyer dakika başına hasar rekorunu kırana verilir | `pr_damage` |

## Anlatısal rozetler
| ID | İSİM | AÇIKLAMA | key |
|---|---|---|---|
| 10 | Kıyım | Bir maçta 20 veya daha fazla kill alana verilir | `kill_20` |
| 11 | Kusursuz Maç | Maç KDA'sı 10 veya üzeri olana verilir | `kda_10` |
| 12 | Ölümsüz | Hiç ölmeden maç bitirene verilir | `deathless` |
| 13 | Geri Dönüş | Gold'da geride kalıp maçı kazanan takımın oyuncusuna verilir | `comeback` |
| 14 | Talihsiz Kahraman | Kaybeden takımın tek başına en iyi performansını gösterene verilir | `tragic_hero` |
| 15 | Maraton | Bir oyun gecesinde 5 veya daha fazla maç oynayana verilir | `marathon_5` |

## Seri rozetleri (ayrık bloklar, tekrarlanabilir)
| ID | İSİM | AÇIKLAMA | key |
|---|---|---|---|
| 16 | Seri Galip | Üst üste 3 galibiyet alana verilir | `win_streak_3` |
| 17 | Kara Seri | Üst üste 3 mağlubiyet alana verilir | `lose_streak_3` |
| 18 | Sonsuz Bench | Üst üste 2 maç kendi takımının en düşük performansı olana verilir | `bench_2` |

## İlişkisel rozetler (tek seferlik)
| ID | İSİM | AÇIKLAMA | key |
|---|---|---|---|
| 19 | Kabus | Aynı rakibe karşı 6 galibiyet alana verilir | `nemesis_6` |
| 20 | Kader Ortağı | Aynı takım arkadaşıyla 6 galibiyet alana verilir | `duo_6` |

## Kimlik ve kilometre taşları (tek seferlik)
| ID | İSİM | AÇIKLAMA | key |
|---|---|---|---|
| 21 | Çok Yönlü | Beş koridorda da en az bir maç oynayana verilir | `versatile` |
| 22 | Demirbaş 10 | 10 maç tamamlayana verilir | `veteran_10` |
| 23 | Demirbaş 20 | 20 maç tamamlayana verilir | `veteran_20` |
| 24 | Demirbaş 50 | 50 maç tamamlayana verilir (henüz kimsede yok — hedef olarak gösterilir) | `veteran_50` |

## Rulet rozetleri (eğlence modu; `status='roulette'` maçlardan türetilir)
| ID | İSİM | AÇIKLAMA | key |
|---|---|---|---|
| 25 | Rulet Tamamlayıcısı | Rulet maçında atanan iki eşyayı da maç sonunda envanterinde bulundurana verilir | `roulette_complete` |
| 26 | Rulet Galibi | Rulet görevini tamamlayıp maçı da kazanana verilir | `roulette_winner` |
| 27 | Kumarbaz | 5 kez Rulet Galibi olana verilir | `gambler` |

## Notlar
- **Kademeli olanlar yalnız 01-06.** Kademe, rozet sayısının maç başına oranına bakar
  (gümüş 0.20, altın 0.32; en az 8 maç şartı) — çok oynayan otomatik altın olmaz.
- 07-09 "rekor kırma" sınıfı kademelenmez: kendi rekorunu kırmak deneyimle ZORLAŞIR,
  orana bağlı kademe çaylağı ödüllendirirdi.
- Tek seferlik rozetler: 19-24 ve 27. Diğerleri tekrarlanabilir (sayaç taşır).
- Kilitli rozetlerde arayüz ilerleme gösterir (ör. Demirbaş 20 → "17/20").
- Eşikler bu grubun ölçeğine göre kalibre edilmiştir (25 valid maç, 19 oyuncu, 2026-08-19).
  **Yeniden kalibrasyon tetikleyicisi: 50 ve 100 valid maç** — o noktalarda birkaç rozet
  fazla yayılacağı için eşikler yükseltilir (CHANGE_REQUESTS'e işlenerek).
