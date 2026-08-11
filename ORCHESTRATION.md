# LoL Custom Match Balancer — Orkestrasyon Planı

## Amaç
Arkadaş grubunun 5v5 custom maçları için: LCU'dan otomatik veri toplama → rating (OpenSkill) → takım dengeleme → web UI üzerinden kullanım (lokalde, sonra VPS).

## Repo yapısı (monorepo)
```
lol-balance/
  docs/                  # CONTRACT'LAR — tek doğruluk kaynağı (source of truth)
    api_contract.md      # Backend REST API sözleşmesi
    ingest_contract.md   # LCU Collector → Backend payload sözleşmesi
    db_schema.md         # Veritabanı şeması + tasarım kararları
  collector/             # Agent 1'in çalışma alanı (Windows, LCU)
  backend/               # Agent 2'nin çalışma alanı (FastAPI + SQLite)
    rating/              # Agent 3'ün çalışma alanı (saf Python kütüphanesi)
  webui/                 # Agent 4'ün çalışma alanı (statik tek sayfa, backend servis eder)
  agents/                # Görev tanımları (bu dosyalar Claude Code'a verilecek)
```

## Agent'lar ve sıra

| # | Agent | Dizin | Ortam | Bağımlılık |
|---|-------|-------|-------|------------|
| 1 | LCU Collector | `collector/` | Windows (LoL client'ın olduğu PC), Python 3.11+ | ingest_contract.md |
| 2 | Backend API | `backend/` | Cross-platform, Python 3.11 + FastAPI + SQLite | api_contract, ingest_contract, db_schema |
| 3 | Rating Engine | `backend/rating/` | Saf Python paketi, I/O yok | db_schema (kavramsal), OpenSkill |
| 4 | Web UI | `webui/` | Vanilla HTML/JS, build-tool'suz; backend `/`'den servis eder | api_contract.md |

**Önerilen icra sırası:** 3 → 2 → 1 → 4.
Rating engine saf ve bağımsız olduğu için önce yazılıp test edilir; backend onu tüketir; collector backend'e veri basar; web UI en dışta kaldığı için sondadır. 1 ve 4, 2 bittikten sonra paralel koşabilir.

## Orkestrasyon kuralları (her agent'ın brief'inde tekrarlanır)

1. **Contract'lar dondurulmuştur.** `docs/` altındaki dosyalar hiçbir agent tarafından tek taraflı değiştirilemez. Contract'ta hata/eksik bulan agent, işini durdurup değişiklik önerisini `docs/CHANGE_REQUESTS.md` dosyasına yazar; kararı orkestratör (insan + ana Claude oturumu) verir.
2. **Dizin sınırı.** Her agent yalnızca kendi dizininde dosya oluşturur/değiştirir. `docs/` herkese read-only.
3. **Mock ile geliştirme.** Hiçbir agent başka bir agent'ın kodunun bitmesini beklemez; karşı tarafı contract'taki örnek payload'larla mock'lar. Entegrasyon en sonda yapılır.
4. **Test zorunlu.** Her agent kendi bileşeni için pytest testleri yazar; contract'taki örnek payload'lar test fixture'ı olarak kullanılır.
5. **Idempotency her katmanda.** Aynı maçın iki kez gönderilmesi/işlenmesi asla çift kayıt üretmez (bkz. contract'lardaki `source_game_id`).

## Claude Code kullanım şekli
Her agent için ayrı bir Claude Code oturumu aç. Oturuma şunu ver:
- İlgili `agents/0X-*.md` dosyası (görev tanımı)
- `docs/` klasörünün tamamı (read-only referans)
- Çalışma dizini olarak yalnızca kendi klasörü

Aynı repo'da paralel çalıştıracaksan `git worktree` kullan (her agent ayrı branch + worktree; merge'ü sen yaparsın). Sıralı çalıştıracaksan tek branch yeter.

## Faz 2 notu
Çift sinerjisi (pair terms) bu fazın kapsamı DIŞINDA, ama şema ve ingest contract'ı rol/pozisyon verisini şimdiden topladığı için ileride migration gerektirmeyecek.
