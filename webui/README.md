# Web UI

Backend'in `/` altından servis ettiği, build-tool'suz tek sayfalık arayüz. `docs/api_contract.md`'nin ince istemcisidir; iş mantığı içermez.

## Dosyalar

| Dosya | Görev |
|---|---|
| `index.html` | Sayfa iskeleti, 4 görünüm, tek satır config |
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

Mock, 14 kişilik gerçekçi bir roster (her oyuncuda 5 anahtarlı `role_ratings`), 8 maçlık geçmiş ve rol atamalı 3 dengeleme önerisi döner; API anahtarı olarak boş olmayan herhangi bir değer kabul eder (401 akışını denemek için anahtar istemini boş geçebilirsin).

Mock'ta bilerek bırakılmış kenar durumlar: bir maçta iki katılımcının `rating_change`'i `null` (delta "—"), başka bir maçta iki katılımcının `position`'ı `null` (rol "—", o maç rol evrenine girmez). `PUT /matches/{id}/positions` mock'u yerel maç state'ini günceller ve `{updated, role_matches_replayed}` döner — rol ratinglerini yeniden hesaplamaz (gerçek replay backend'de).

## Backend'e bağlama

1. `index.html`'de `USE_MOCK: false` yap.
2. Backend'i çalıştır — `webui/` dosyalarını FastAPI StaticFiles ile `/` altından servis eder, ekstra bir şey gerekmez.
3. İlk açılışta sorulan API anahtarı, backend'in `.env`'indeki shared secret'tır; `localStorage`'a yazılır, 401 dönerse tekrar sorulur.

`API_BASE` göreli (`/api/v1`) olduğu için UI hangi origin'den servis edilirse backend'i orada arar; ayrı bir host'a bağlanmak gerekirse config'e tam URL yazılabilir (`"http://sunucu:8000/api/v1"`).

## Notlar

- Gösterilen birincil rating değeri `rating.score`'dur (harman engine); sıralama tablosunda skorun altında W/L çekirdeği (`ordinal`) ve `perf_avg` soluk ikincil satır olarak görünür, `perf_avg` null ise (harman-dışı version, score = ordinal) bu satır gizlenir.
- Rol ratingleri (`role_ratings`, GÖREV 0) iki yerde görünür: dengeleme ekranındaki oyuncu kartlarında kompakt şerit, sıralama tablosunda oyuncu adına dokununca açılan satır. Her kutu rol · puan (1 ondalık) · o roldeki maç sayısıdır; `matches = 0` olan rol soluk gösterilir (default prior, gerçek veri değil). Alan yoksa şerit hiç çizilmez.
- Dengeleme yanıtı her zaman rol atamalıdır: `team_100`/`team_200` = `[{player_id, position}]`. Takımlar TOP → JUNGLE → MIDDLE → BOTTOM → UTILITY sırasıyla, Türkçe etiketlerle (Üst/Orman/Orta/Alt/Destek) listelenir.
- Rol düzeltme: maç kartındaki "Rolleri düzenle" 10 katılımcı için rol seçici açar; "Rolleri Kaydet" yalnız **değişen** rolleri `PUT /api/v1/matches/{id}/positions` ile gönderir (`{"positions": {"<player_id>": "TOP"|null}}`) ve yanıttaki `updated` / `role_matches_replayed` bilgisini toast'ta gösterir. Ana rating etkilenmez; kaydedince maç listesi ve roster önbelleği tazelenir. Manuel girilen maçlarda roller boş geldiğinden bu panel o maçları rol evrenine sokmanın yoludur.
- "Dengele" butonu tam 10 seçim olmadan aktifleşmez (asıl doğrulama backend'de, `422`).
- Maç void etme onay dialogu ile korunur; void geri alınamaz ve rating replay tetikler.
- Hata yanıtlarındaki `detail` alanı kullanıcıya aynen gösterilir (backend Türkçe döner).
- `GET /matches` yanıtının alan bazlı şekli contract'ta örneklenmediği için varsayılan şekil `docs/CHANGE_REQUESTS.md`'ye yazıldı.
