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

Mock, 14 kişilik gerçekçi bir roster, 8 maçlık geçmiş ve 3 dengeleme önerisi döner; API anahtarı olarak boş olmayan herhangi bir değer kabul eder (401 akışını denemek için anahtar istemini boş geçebilirsin).

## Backend'e bağlama

1. `index.html`'de `USE_MOCK: false` yap.
2. Backend'i çalıştır — `webui/` dosyalarını FastAPI StaticFiles ile `/` altından servis eder, ekstra bir şey gerekmez.
3. İlk açılışta sorulan API anahtarı, backend'in `.env`'indeki shared secret'tır; `localStorage`'a yazılır, 401 dönerse tekrar sorulur.

`API_BASE` göreli (`/api/v1`) olduğu için UI hangi origin'den servis edilirse backend'i orada arar; ayrı bir host'a bağlanmak gerekirse config'e tam URL yazılabilir (`"http://sunucu:8000/api/v1"`).

## Notlar

- "Dengele" butonu tam 10 seçim olmadan aktifleşmez (asıl doğrulama backend'de, `422`).
- Maç void etme onay dialogu ile korunur; void geri alınamaz ve rating replay tetikler.
- Hata yanıtlarındaki `detail` alanı kullanıcıya aynen gösterilir (backend Türkçe döner).
- `GET /matches` yanıtının alan bazlı şekli contract'ta örneklenmediği için varsayılan şekil `docs/CHANGE_REQUESTS.md`'ye yazıldı.
