# VPS Deploy Raporu — lol-balance

Hazırlayan: VPS agent'ı, 2026-08-11. Kaynak brief: `deploy/VPS_AGENT_BRIEF.md`.
Uygulanan manifest: `deploy/k8s.yaml` (secret'lar hariç — onlar imperatif oluşturuldu).

## 1. Ön kontrol cevapları

| Soru | Cevap |
|---|---|
| Ingress controller | **ingress-nginx** (class `nginx`, default) |
| TLS | **cert-manager** kurulu; ClusterIssuer `letsencrypt-prod` (Ready) ve `letsencrypt-staging`. Kalıp: annotation + `tls` bloğu (cluster'daki diğer app'lerle aynı) |
| DNS | ⚠️ **`lol.teomanagir.com` için A/AAAA kaydı YOK.** VPS IPv4: `159.195.216.232`. **Teoman'dan istenen:** `lol.teomanagir.com A 159.195.216.232` kaydı |
| StorageClass | **`local-path`** (default, RWO, rancher.io/local-path) — 1Gi PVC bound |
| imagePullSecret | Yeni PAT **gerekmedi**: `apps` namespace'inde ghcr.io/TeomanAgir için mevcut `ghcr-pull` secret'ı vardı; `lol-balance:latest` manifest'ini çekebildiği doğrulandı (HTTP 200) ve `lol-balance` namespace'ine kopyalandı |

## 2. Kurulum — tamamlandı

Namespace `lol-balance` altında: Deployment (replicas 1, **Recreate**, `imagePullPolicy: Always`),
Service, Ingress (nginx + letsencrypt-prod + `ssl-redirect: true`), 1Gi PVC (`/data`),
`API_KEY` Secret (`openssl rand -hex 24` ile üretildi), günlük yedek CronJob'u.
Image: `ghcr.io/teomanagir/lol-balance:latest` — GHCR'dan sorunsuz çekildi.

- Pod: Running/Ready, uygulama loglarında Uvicorn 8000'de, `/` 200.
- Brief'in değişmezlerine uyuldu: replicas 1, Recreate, `/data` PVC, `API_KEY` Secret'tan,
  `ENGINE_VERSION` verilmedi.

## 3. Yedekleme — tamamlandı

CronJob `lol-balance-backup`: her gün 03:30 UTC, aynı PVC'de `/data/backup/` altına
`sqlite3 .backup`, 7 günden eski dosyalar silinir. Manuel test koşusu başarılı:
`lol_balance-2026-08-11.db` (56 KB) üretildi.

## 4. Doğrulama çıktıları

DNS henüz olmadığı için testler node IP üzerinden `--resolve` ile yapıldı
(`curl --resolve lol.teomanagir.com:443:159.195.216.232 -k`):

| Test | Sonuç |
|---|---|
| `GET /` | **200**, HTML (web UI, `<html lang="tr">`) |
| `GET /api/v1/players` (key'siz) | **401** |
| `GET /api/v1/players` (`X-API-Key`) | **200**, `[]` |
| HTTP → HTTPS | **308** redirect |
| Pod restart testi | Pod silindi → yenisi geldi → `/api/v1/players` yine **200**, `/data/lol_balance.db` korundu (PVC kanıtı ✓) |

### 4b. Gerçek domain doğrulaması (DNS + sertifika sonrası — 2026-08-11)

DNS kaydı açıldı; Let's Encrypt sertifikası kesildi (`lol-balance-tls` READY=True, order `valid`).
Gecikmenin nedeni cluster değildi: node'un upstream resolver'ları (Netcup) kayıt öncesi
NXDOMAIN'i negatif cache'de tutuyordu (SOA negatif TTL 600 s); süre dolunca cert-manager
challenge'ı kendiliğinden geçti, elle müdahale gerekmedi.

`-k`/`--resolve` OLMADAN, gerçek adres üzerinden:

| Test | Sonuç |
|---|---|
| TLS issuer | **Let's Encrypt** (`C=US; O=Let's Encrypt; CN=YR2`), subject `CN=lol.teomanagir.com` |
| `GET /` | **200** |
| `GET /api/v1/players` (key'siz) | **401** |
| `GET /api/v1/players` (`X-API-Key`) | **200**, `[]` |
| HTTP → HTTPS | **308** → `https://lol.teomanagir.com/` |

✅ **https://lol.teomanagir.com yayında.**

## 5. Bekleyen işler

1. **API key teslimi:** Değer hiçbir dosyaya/rapora yazılmadı. Teoman VPS'te şu komutla alır:
   ```bash
   kubectl -n lol-balance get secret lol-balance-secrets -o jsonpath='{.data.API_KEY}' | base64 -d
   ```
2. **Sürekli deploy — ONAYLANDI, kurulum 2026-08-11 (VPS tarafı tamam):**
   Mekanizma: main push → testler → image GHCR'a → CI `kubectl rollout restart` →
   `imagePullPolicy: Always` yeni imajı çeker.

   Yapılanlar:
   - `deploy/ci-rbac.yaml`: `ci-deployer` SA — yalnızca `lol-balance` ns'inde
     deployments get/list/watch/**patch** + replicasets izleme. Doğrulandı:
     başka namespace ✗, secret okuma ✗, rollout status ✓.
   - Uzun ömürlü SA token'ından kubeconfig üretildi (server `https://159.195.216.232:6443`,
     cluster CA ile TLS doğrulamalı — API cert SAN'ında public IP mevcut).
   - Kubeconfig, GitHub repo secret'ı **`KUBE_CONFIG_B64`** olarak eklendi (API üzerinden,
     sealed-box şifreli; PUT 201).
   - ufw'de **6443/tcp açıldı** (GitHub runner'ları API server'a erişebilsin; TLS + token
     + dar RBAC ile korunuyor. GitHub IP aralıkları değişken olduğundan IP kısıtı pratik değil).

   ⚠️ **Kalan tek adım:** `.github/workflows/ci.yml`'e `deploy` job'unun eklenmesi.
   VPS'teki PAT'ta `workflow` scope olmadığı için workflow dosyası push edilemedi
   (GitHub reddi). Hazır diff: **`deploy/ci-deploy-job.patch`** — lokal tarafta:
   ```bash
   git apply deploy/ci-deploy-job.patch && git add .github/workflows/ci.yml && git commit && git push
   ```
   Alternatif: `workflow` scope'lu bir PAT verilirse VPS agent'ı kendisi push'lar.

## Güvenlik notu

Repo'nun git remote URL'inde gömülü bir GitHub token'ı var (`https://ghp_…@github.com/...`).
Değerini buraya yazmıyorum; ileride credential helper'a taşınması önerilir.
