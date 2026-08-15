# Devir Notu — Kök Faz Tamamlandı (2026-08-11)

Yeni oturum/agent için mevcut durumun tek sayfalık özeti. Ayrıntı: `CLAUDE.md`
(orkestrasyon yetki modeli), `ORCHESTRATION.md`, `docs/` (contract'lar),
`docs/CHANGE_REQUESTS.md` (tüm kararlar, gerekçeli).

## Ne yayında

- **https://lol.teomanagir.com** — VPS Kubernetes'te tek container (backend+webui),
  Let's Encrypt TLS, 1Gi PVC (SQLite), günlük 03:30 UTC yedek CronJob'u.
  10 gerçek maç + 14 oyuncu yüklü. API key cluster Secret'ında (`lol-balance-secrets`);
  web UI kullanıcıları key'i modal'a bir kez girer.
- **CI/CD (uçtan uca otomatik):** GitHub `TeomanAgir/lol-balance` (private) → her
  push/PR'da 3 test paketi (rating/backend/collector); `main`'de GHCR imajı + VPS'e
  otomatik rollout (deploy job'ı, dar yetkili `ci-deployer` SA ile — `deploy/ci-rbac.yaml`,
  kubeconfig GitHub secret `KUBE_CONFIG_B64`). Yani: main'e push = canlıya çıkış.
  K8s manifest'leri: `deploy/k8s.yaml`; VPS kurulum raporu: `deploy/VPS_DEPLOY_REPORT.md`.
- **Teoman'ın PC'sinde** (Windows, bu repo): "LoL Balance Collector" zamanlanmış görevi
  logon'da canlı modda çalışır, VPS'e gönderir. "LoL Balance Backend" görevi DEVRE DIŞI
  (VPS'e geçildi; gerekirse Enable-ScheduledTask ile döner).

## Aktif rating modeli

`openskill-pl-blend50-v1` (spec: `docs/rating_contract.md` "Harman Engine"):
saf W/L OpenSkill çekirdeği + kariyer performans ortalaması;
`score = [0.5·mu + 0.5·(25 + 20·(P_avg−1))] − 3·sigma`. Leaderboard ve dengeleme
score kullanır. Eski versionlar (`openskill-pl-v1`, `openskill-pl-perf-v1`) tanımlı,
aktif değil. Sabitler version'a dondurulmuş — tuning = yeni version + Teoman onayı.

## Açık maddeler

1. ~~**Canlı EOG doğrulaması**~~ **KAPANDI (2026-08-12):** İlk gerçek custom gecesi
   (gameId 1734664864) canlı EOG hattı uçtan uca insansız çalıştı; payload
   `collector/fixtures/eog_custom_real.json` yapılıp EOG yolu 12 regresyon testiyle
   gerçek şemaya kilitlendi. Bulgular: gerçek EOG'de `selectedPosition` dolu geliyor
   (rol tahmini canlıda gerekmedi); `played_at` artık `endOfGameTimestamp`'ten
   (CHANGE_REQUESTS 2026-08-12).
2. **ERTELENDİ (Teoman):** sıra-dışı ingest'te backend auto-replay — çoklu-PC
   kurulumu gündeme gelince (bkz. CHANGE_REQUESTS).
3. Kozmetik: webui mock'unda `puuid` alanı yok; CI action'larında Node 20
   deprecation uyarısı (v5/v6'ya yükseltme bekliyor).

## Yerel ortam tuzakları (bilinmezse zaman yakar)

- PATH'te `python`/`py` YOK. Her şey `backend\.venv\Scripts\python.exe`
  (backend+collector) ve `backend\rating\.venv\Scripts\python.exe` (rating) ile koşar.
- rating paketi backend venv'ine **kopya** kurulur; `backend/rating/` değişince
  `pip install ./rating` tekrarlanmalı (editable kurulum klasör gölgelemesiyle bozuk).
- `gh` tam yolda: `C:\Program Files\GitHub CLI\gh.exe` (TeomanAgir yetkili).
- LoL kurulumu: `F:\Riot Games\League of Legends` (collector/.env'de; .env gitignore'da).
- Gerçek fixture'lar (`collector/fixtures/*_real.json`) gerçek puuid/Riot ID içerir →
  repo private kalmalı.

## Süreç kuralları (özet — tam hâli CLAUDE.md)

Orkestratör implementasyon yazmaz, subagent'lara dağıtır (dizin sınırlı); `docs/`
yalnız orkestratör + CHANGE_REQUESTS süreciyle değişir; davranışsal kararlar
Teoman'a sorulur; Faz 2 (pair synergy) hâlâ kapsam dışı.
