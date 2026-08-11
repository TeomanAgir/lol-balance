# Web UI

Backend'in `/` altından servis ettiği, build-tool'suz tek sayfalık arayüz. `docs/api_contract.md`'nin ince istemcisidir; iş mantığı içermez.

## Dosyalar

| Dosya | Görev |
|---|---|
| `index.html` | Sayfa iskeleti, 5 sekme + profil detay görünümü, tek satır config |
| `app.js` | API istemcisi + görünüm mantığı |
| `style.css` | Stil (tek koyu tema, mobil öncelikli) |
| `mock_api.js` | Backend hazır değilken kullanılan fetch stub'ı |

## Mock ile çalıştırma

`index.html`'deki config satırı varsayılan olarak mock'tadır:

```html
<script>window.APP_CONFIG = { USE_MOCK: true, API_BASE: "/api/v1" };</script>
```

Statik bir sunucuyla aç (fetch stub'ı `file://` ile de çalışır ama sunucu daha gerçekçidir):

```
cd webui
python -m http.server 8080
# http://localhost:8080
```

Mock, 14 kişilik gerçekçi bir roster (her oyuncuda 5 anahtarlı `role_ratings`), 14 maçlık geçmiş (8 karışık kadro + 6 sabit kadrolu "rekabet" maçı, bkz. nemesis notu) ve rol atamalı 3 dengeleme önerisi döner; API anahtarı olarak boş olmayan herhangi bir değer kabul eder (401 akışını denemek için anahtar istemini boş geçebilirsin).

Mock'ta bilerek bırakılmış kenar durumlar: bir maçta iki katılımcının `rating_change`'i `null` (delta "—"), başka bir maçta iki katılımcının `position`'ı `null` (rol "—", o maç rol evrenine girmez). `PUT /matches/{id}/positions` mock'u yerel maç state'ini günceller ve `{updated, role_matches_replayed}` döner — rol ratinglerini yeniden hesaplamaz (gerçek replay backend'de).

`GET /highlights/weekly` mock'u da pencereyi maç geçmişinden türetir (contract'taki kural: son 7 gün; o pencerede maç yoksa `end` = en son valid maç ve `fallback: true`). Mock maçlar 2026-08-02..09 tarihli olduğundan tarih ilerledikçe fallback yolu kendiliğinden devreye girer. Dosyanın başındaki iki bayrakla senaryo zorlanabilir: `HL_FORCE_FALLBACK = true` (pencereyi son maç haftasına kaydırır), `HL_EMPTY = true` (hiç valid maç yokmuş gibi davranır → UI boş durum).

`GET /nemesis` ve `POST /balance/nemesis` mock'ları da maç geçmişinden **türetilir** (aday birim = (çift, rol), eşik `encounters >= 3`, `weekly` aynı pencere kuralıyla). Ana geçmişte her çift bir rolde yalnız 1 kez karşılaştığı için mock'a sabit kadrolu 6 "rekabet maçı" eklendi (2026-07-30 … 08-09); ilk ikisi haftalık pencerenin dışında kalır, böylece `weekly` çift `all_time`'dan farklı çıkar ve UI'daki "Bu haftanın çifti" notu gerçekten test edilir. Beklenen: `all_time` = Teoman–Kaan (Orta, 3–3, %100), `weekly` = Baran–Emir (Üst, 2–2, %100), `active: "weekly"`. Dosyadaki iki bayrakla senaryo değiştirilir: `NEM_NONE = true` (çift yok → boş durum, düğme çizilmez), `NEM_WEEKLY_OFF = true` (`weekly` bastırılır → `active: "all_time"`, haftalık not çizilmez). `POST /balance/nemesis` mock'u 10 seçim / aktif çift / çiftin seçimde olması doğrulamalarını yapar (`422`, `409`) ve çifti karşı takımlara ayırıp ikisini de nemesis rolüne sabitleyerek 3 öneri döner.

`GET /players/{id}/stats` mock'u istatistikleri maç geçmişinden **türetir** (yalnız `status: "valid"` maçlar), böylece bir maçı void edince profil de tutarlı biçimde değişir. Maçsız oyuncu **Ece** (`matches_played: 0`) hiçbir mock maçına girmez ve contract'taki tüm boş yolları temsil eder: `winrate: null`, `kda: null`, `favorite_champion: null`, `favorite_role: null`, `synergy: []`. Bilinmeyen id → `404`.

## Backend'e bağlama

1. `index.html`'de `USE_MOCK: false` yap.
2. Backend'i çalıştır — `webui/` dosyalarını FastAPI StaticFiles ile `/` altından servis eder, ekstra bir şey gerekmez.
3. İlk açılışta sorulan API anahtarı, backend'in `.env`'indeki shared secret'tır; `localStorage`'a yazılır, 401 dönerse tekrar sorulur.

`API_BASE` göreli (`/api/v1`) olduğu için UI hangi origin'den servis edilirse backend'i orada arar; ayrı bir host'a bağlanmak gerekirse config'e tam URL yazılabilir (`"http://sunucu:8000/api/v1"`).

## Notlar

- Gösterilen birincil rating değeri `rating.score`'dur (harman engine); sıralama tablosunda skorun altında W/L çekirdeği (`ordinal`) ve `perf_avg` soluk ikincil satır olarak görünür, `perf_avg` null ise (harman-dışı version, score = ordinal) bu satır gizlenir.
- Rol ratingleri (`role_ratings`, GÖREV 0) iki yerde görünür: dengeleme ekranındaki oyuncu kartlarında kompakt şerit, oyuncu profilinde geniş şerit. Her kutu rol · puan (1 ondalık) · o roldeki maç sayısıdır; `matches = 0` olan rol soluk gösterilir (default prior, gerçek veri değil). Alan yoksa şerit hiç çizilmez.
- **Oyuncu profili (GÖREV 1):** sıralamada oyuncu adına dokununca `GET /players/{id}/stats` ile açılan, sekmesiz "detay" görünümü (`#view-profile`); üstteki "← Sıralamaya dön" ile kapanır, alt sekme çubuğunda Sıralama aktif kalır. Gösterilenler: maç & W/L, ortalama KDA, favori karakter, favori koridor (Türkçe rol adı), rol rating şeridi ve en yüksek sinerji (ilki vurgulu, kalan iki kayıt liste). Sinerji listesindeki isimler o oyuncunun profiline geçer. Contract'taki null durumları kısa notlarla karşılanır: `kda: null` → "İstatistikli maç yok", favoriler `null` → "—" + veri yok notu, `synergy: []` → "En az 2 ortak maç gerekiyor", maçsız oyuncu → "Henüz maç yok". Puan ve rol şeridi `GET /players` önbelleğinden gelir (profil isteği yalnız istatistikleri taşır).
- **Haftanın enleri (GÖREV 2):** "Enler" sekmesi (`#view-highlights`), tek istek `GET /highlights/weekly`. Üstte pencere satırı ("5–12 Ağu arası"; ay sınırını aşarsa "30 Tem – 6 Ağu arası"), `window.fallback: true` ise yanında pirinç renkli "(son maç haftası)" notu. Altında sırayla: **Haftanın Oyuncusu** (vurgulu büyük kart — ad, güncel puan, "pencerede N maç"), **Yıldız Rukisi** (ad, 2 ondalıklı delta — pozitif yeşil / negatif kırmızı, "pencerede N maç") ve **Rol enleri** (Üst/Orman/Orta/Alt/Destek kartları; ad, rol puanı, o roldeki maç sayısı). Dolu kartlar `<button>`'dır ve oyuncu profiline gider; `null` alanlar dokunulamaz, soluk "—" kartı olarak kalır (`.hl-none`; global `.empty` sınıfı kart içinde kullanılmaz, o ortalı boş-durum paragrafı içindir). Üç alan da null ise (hiç valid maç yok) tek satır boş durum yazılır.
- **Nemesis (GÖREV 3):** Enler ekranının en altındaki bölüm, tek istek `GET /nemesis` (Enler yüklenirken `/highlights/weekly` ile paralel çekilir; **bu istek düşerse bölüm hiç çizilmez**, ekranın kalanı çalışmaya devam eder — `/nemesis` bilmeyen bir backend'e karşı güvenli). Gösterilen çift **tüm zamanların** çiftidir: iki isim karşılıklı (ikisi de profile gider), ortada koridor + galibiyet skoru (`wins[0]–wins[1]`) + karşılaşma sayısı, altında `closeness` yüzdesi ("%100 başa baş"). `weekly` doluysa ve all_time'dan farklıysa (rol + çift karşılaştırması) tek satır not düşülür: "Bu haftanın çifti: … ". Maç kurmada kullanılacak çift (`active`) her iki yerde de "maç bu çiftle kurulur" rozetiyle işaretlenir. `all_time` null ise bölüm "Nemesis için en az 3 koridor karşılaşması gerekiyor." yazar. "Nemesis maçı kur" düğmesi yalnız `active != null` iken çizilir.
- **Nemesis modu (Dengele):** "Nemesis maçı kur" Dengele sekmesine geçip modu açar. Rozet (`#nemesis-mode`) çifti ve koridoru yazar, çiftin ikisi de seçili değilse eksik isimleri sayar; sağdaki × modu kapatır (önceki öneriler de temizlenir). Modda çiftin roster kartları kesik çizgili ve pirinç adla işaretlenir. "Dengele" düğmesi `POST /balance/nemesis`'e gider; yanıt `/balance` ile aynı şekilde çizilir, ek olarak öneri başlığının altına "Nemesis maçı: A vs B — Rol (bu haftanın/tüm zamanların çifti)" notu düşer ve çiftin satırları vurgulanır. `422` (çift seçimin dışında) ve diğer hatalarda `detail` her zamanki gibi toast'ta gösterilir; `409` (aktif çift kalmamış) durumunda ek olarak mod otomatik kapatılır ve mesaja "Nemesis modu kapatıldı." eklenir. Seçim akışı ve 10 kişi kuralı değişmez.
- Profil görünümü artık iki yerden açılır (sıralama, enler); geldiği görünümün sekmesi aktif kalır ve geri düğmesi ona göre "← Sıralamaya dön" / "← Enlere dön" yazar (`state.profileFrom`).
- Alt çubuk 5 sekmeye çıktı. Etiketler kısa tutuldu ("Enler"), ölçek 14px → 12px'e (≤400px genişlikte 11px) indirildi; en geniş etiket ("SIRALAMA") 320px'lik ekranda bile sekme payına sığar, ikon/kaydırma gerekmedi.
- Sıralama satırındaki eski rol açılırı (chevron) kaldırıldı: aynı şeridi profil daha geniş biçimde gösteriyor, tek satırda iki ayrı dokunma hedefi tutmanın karşılığı yoktu. Ada dokunma artık tek anlam taşır: profili aç.
- Dengeleme yanıtı her zaman rol atamalıdır: `team_100`/`team_200` = `[{player_id, position}]`. Takımlar TOP → JUNGLE → MIDDLE → BOTTOM → UTILITY sırasıyla, Türkçe etiketlerle (Üst/Orman/Orta/Alt/Destek) listelenir.
- Rol düzeltme: maç kartındaki "Rolleri düzenle" 10 katılımcı için rol seçici açar; "Rolleri Kaydet" yalnız **değişen** rolleri `PUT /api/v1/matches/{id}/positions` ile gönderir (`{"positions": {"<player_id>": "TOP"|null}}`) ve yanıttaki `updated` / `role_matches_replayed` bilgisini toast'ta gösterir. Ana rating etkilenmez; kaydedince maç listesi ve roster önbelleği tazelenir. Manuel girilen maçlarda roller boş geldiğinden bu panel o maçları rol evrenine sokmanın yoludur.
- "Dengele" butonu tam 10 seçim olmadan aktifleşmez (asıl doğrulama backend'de, `422`).
- Maç void etme onay dialogu ile korunur; void geri alınamaz ve rating replay tetikler.
- Hata yanıtlarındaki `detail` alanı kullanıcıya aynen gösterilir (backend Türkçe döner).
- `GET /matches` yanıtının alan bazlı şekli contract'ta örneklenmediği için varsayılan şekil `docs/CHANGE_REQUESTS.md`'ye yazıldı.
