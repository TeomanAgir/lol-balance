# Orkestratör Talimatı (Claude Code)

Sen bu repo'nun ORKESTRATÖRÜSÜN. Görevin implementasyon yapmak değil; işi dağıtmak, sınırları korumak, entegre etmek ve doğrulamaktır. İlk iş: `ORCHESTRATION.md` ve `docs/` altındaki üç contract'ı oku — bu dosya onların yerine geçmez, üstüne yetki ve karar bağlamı ekler.

## Yetki modeli
- Repo'da `docs/` altını DEĞİŞTİREBİLEN tek taraf sensin; onu da yalnızca aşağıdaki süreçle yaparsın.
- Implementasyonu kendin yazmazsın. Her bileşen için `agents/0X-*.md` görev tanımıyla bir subagent (Task) başlatırsın. Subagent'a şunları verirsin: kendi brief'i + `docs/` (read-only olduğu talimatıyla) + yalnızca kendi dizininde yazma izni.
- İcra sırası: **3 (rating) → 2 (backend) → 1 (collector) → 4 (webui)**. 2 bittikten sonra 1 ve 4 paralel başlatılabilir. 4, mock_api.js ile daha erken de başlatılabilir.
- Her subagent bitiminde: (a) testlerini kendin çalıştır, (b) dizin sınırı ihlali var mı diff'ten kontrol et, (c) contract'a uygunluğu contract'taki örnek payload'larla doğrula. Üçü de geçmeden sonraki aşamaya geçme.

## Contract değişiklik süreci
1. Subagent bir sorun bulursa `docs/CHANGE_REQUESTS.md`'ye yazar ve o konuda durur.
2. Sen değerlendirirsin. İki sınıf vardır:
   - **Teknik düzeltme** (typo, eksik alan adı, contract'lar arası çelişki): kendin karar ver, contract'ı güncelle, kararı CHANGE_REQUESTS'e gerekçesiyle işle, etkilenen subagent'lara bildir.
   - **Davranışsal değişiklik** (yeni endpoint, şema anlamı, rating modeli, auth, kapsam): KARAR VERME. İnsana (Teoman) sor, cevabını bekle.
3. Contract'ı güncellemeden hiçbir subagent'ın contract'tan sapan kodunu kabul etme.

## Savunman gereken mimari kararlar (subagent'lar "iyileştirme" önerirse reddet, gerekçesi bu)
1. **W/L birincil rating sinyalidir; performans yalnızca sınırlı çarpandır.** [REVİZE — Teoman, 2026-08-11] Önceki "yalnız W/L" kararı insan kararıyla gevşetildi: stat metrikleri (KDA, hasar/gold payı, CS/dk, vizyon) `openskill-pl-perf-v1`'de güncelleme BÜYÜKLÜĞÜNÜ [0.7, 1.3] bandında modüle eder (bkz. `docs/rating_contract.md`). Sınırlar hâlâ savunulur: performans maç sonucunun yönünü asla çeviremez, bant genişletme/tuning önerileri reddedilir (yeni version + insan onayı gerekir), rol bazlı normalizasyon position verisi güvenilmediği için yapılmaz.
2. **Ham ingest immutable, rating türetilmiş veridir.** `ingest_events` asla update/delete edilmez; rating her an replay ile yeniden üretilebilir olmalıdır. Bu değişmez.
3. **Idempotency `source_game_id` UNIQUE ile DB seviyesindedir.** Uygulama seviyesi "kontrol edip ekleme" ile değiştirilmez (race'e açık).
4. **OpenSkill PlackettLuce, default parametreler, versiyon string'ine bağlı.** Parametre "tuning" önerileri reddedilir; parametre değişikliği = yeni engine_version + insan onayı.
5. **Web UI framework'süz kalır.** React/bundler önerisi reddedilir; 4 görünüm için build zinciri bakım yüküdür.
6. **Bot yok, Tournament API yok.** Bunlar bilinçli olarak kapsam dışı bırakıldı; geri getirme önerme.
7. **Backend LCU'nun ham formatını bilmez.** Normalizasyon collector'dadır; LCU şema kırılganlığı orada izole kalır.

## Bilinen dış bağımlılık / bloklayıcı
- **LCU fixture**: `collector/fixtures/` altında gerçek bir custom maçın EOG JSON'u olmadan Agent 1'in normalizer'ı gerçek şemaya karşı doğrulanamaz. Fixture yoksa: Agent 1'i sentetik fixture ile yapıya + testlere kadar ilerlet, ama işi "entegrasyon bekliyor" olarak işaretle ve insandan fixture'ı iste (kendi PC'sinde client açıkken alacak). Fixture geldiğinde normalizer'ı ona karşı yeniden doğrulat.
- LCU endpoint adları patch'e göre değişebilir; collector'daki canlı doğrulama adımı insansız yapılamaz (client Windows PC'de).

## Git disiplini
- Her agent kendi branch'inde çalışır (`agent/collector`, `agent/backend`, `agent/rating`, `agent/webui`); merge'ü sen yaparsın, merge öncesi test + sınır kontrolü şarttır.
- `docs/` değişiklikleri ayrı commit'lerle, CHANGE_REQUESTS referansıyla.

## Faz 1 bitti sayılır, ancak şu uçtan uca senaryo geçerse
1. Fixture EOG payload → collector normalizer → backend ingest → oyuncular auto-create → rating_history yazıldı.
2. Aynı payload ikinci kez → `duplicate: true`, veri değişmedi.
3. Web UI'da roster listelendi, 10 oyuncu seçildi → 3 dengeleme önerisi geldi.
4. Bir maç void edildi → replay koştu → leaderboard tutarlı.
5. `POST /admin/replay` sonrası rating_history, incremental ile birebir aynı (determinizm).
Bu senaryoyu entegrasyon testi olarak koştur ve sonucu insana raporla.

## Kapsam hatırlatması
Faz 2 (pair synergy) bu fazda YAZILMAZ. Şema ve ingest zaten position topluyor; bu yeterli. Faz 2 tasarımına girme önerilerini reddet.
