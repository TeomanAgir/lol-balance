# VPS Sertleştirme — public repo öncesi yapılacaklar

Bu dosya VPS'te uygulanacak adımların listesidir. Bilerek IP, secret veya mevcut
yapılandırma değeri İÇERMEZ — repo public olduğunda da burada kalabilir.
(Karar kaydı: `docs/CHANGE_REQUESTS.md` GÖREV 7 + 2026-08-13 revizyonu.)

## 1. Kubernetes API portunu (6443) kısıtla — EN ÖNEMLİ ADIM

**Önce bil:** CI/CD şu an GitHub Actions'tan `kubectl` ile doğrudan 6443'e
bağlanıyor (`KUBE_CONFIG_B64` secret'ı). 6443'ü herkese kapatırsan **main-push
deploy kırılır.** İki seçenek:

**Seçenek A — kalıcı (önerilen):** Deploy adımını SSH tabanlıya çevirelim
(Actions VPS'e SSH ile bağlanır, `kubectl` VPS'in içinde koşar). O zaman 6443
dışarıya tamamen kapanır, yalnız senin ev IP'ne açık kalır. Workflow
değişikliğini istediğinde orkestratör hazırlar — bu adımı UYGULAMADAN ÖNCE
workflow değişmiş olmalı.

**Seçenek B — geçici:** 6443'ü kendi ev IP'n + GitHub Actions IP aralıklarına
aç. Aralıklar geniştir ve değişir (bkz. `https://api.github.com/meta`,
`actions` listesi) — bakım ister; A'ya geçene kadar ara çözüm.

UFW ile (Seçenek A uygulandıktan sonra):
```bash
sudo ufw status numbered                     # mevcut kuralları gör
sudo ufw allow from <EV_IP> to any port 6443 proto tcp
sudo ufw deny 6443/tcp
sudo ufw status numbered                     # allow satırı deny'dan ÜSTTE olmalı
```
Sağlayıcının panel firewall'u varsa (Hetzner Cloud Firewall vb.) aynı kuralı
orada da uygula — panel firewall'u UFW'den önce gelir.

**Doğrulama** (VPS dışından, ör. telefon hotspot'u):
```bash
nc -vz -w3 <domain> 6443    # timeout/refused beklenir; kendi ev IP'nden ise bağlanır
```

## 2. PAT hijyeni

- **Zorunlu değil** — repo tarihçesinde hiçbir PAT/secret yok (bağımsız denetim,
  CHANGE_REQUESTS GÖREV 7). Bu bir temizlik adımıdır.
- `github.com/settings/tokens` → kullanmadığın eski token'ları sil.
- **DİKKAT:** `ghcr-pull` secret'ının kullandığı PAT'i REVOKE ETME — VPS image
  çekemez olur ve bir sonraki rollout'ta pod ayağa kalkmaz.
- Rotasyon istersen sıra: yeni PAT (yalnız `read:packages` yetkisi) →
  ```bash
  kubectl -n lol-balance delete secret ghcr-pull
  kubectl -n lol-balance create secret docker-registry ghcr-pull \
    --docker-server=ghcr.io --docker-username=<github-kullanici> \
    --docker-password=<YENI_PAT>
  ```
  → sonra eski PAT'i revoke et.

## 3. API_KEY rotasyon prosedürü (şimdi değil — sızıntı şüphesinde)

Anahtar repo'da yok; bu prosedür yalnız "anahtar sızdı" şüphesi için hazır dursun:
```bash
kubectl -n lol-balance delete secret lol-balance-secrets
kubectl -n lol-balance create secret generic lol-balance-secrets \
  --from-literal=API_KEY=<YENI_DEGER>
kubectl -n lol-balance rollout restart deployment/lol-balance
```
Sonra: web UI'da yeni anahtarı gir (her kullanıcı bir kez) + collector
`.env`'lerinde `API_KEY` güncelle (arkadaşlara ayrı kanaldan ilet).

## 4. Hızlı genel kontrol

```bash
sudo ss -tlnp        # dışa açık portlar: 22, 80, 443 (+6443 kural gereği) dışında
                     # public dinleyen varsa değerlendir
```
- SSH: `PasswordAuthentication no` (yalnız anahtarla giriş) öneririm; `fail2ban`
  opsiyonel.

## 5. Public flip öncesi repo tarafı (VPS'te iş yok, hatırlatma)

- `deploy/VPS_AGENT_BRIEF.md` ve `deploy/VPS_DEPLOY_REPORT.md` repo'dan
  kaldırılacak (orkestratör görevi; bu dosya — VPS_HARDENING.md — kalabilir).
- `collector/seed_roster.json` → example şablon; `*_real.json` fixture'ları
  anonimleştirilecek; PR/issue metinleri gözden geçirilecek.
- GitHub ayarları: main branch protection, Actions "fork PR onayı", GHCR
  paketinin private kaldığının teyidi.
