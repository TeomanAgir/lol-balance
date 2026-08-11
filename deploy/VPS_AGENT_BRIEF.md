# VPS Deploy Brief — lol-balance (Kubernetes)

Bu dosya, VPS'te çalışan Claude agent'ına yönelik iş tanımıdır. Hazırlayan: lokal
orkestratör oturumu (Teoman'ın PC'si), 2026-08-11.

## Uygulama özeti

- **Tek container:** FastAPI backend + statik web UI (backend `/`'den servis eder,
  API `/api/v1` prefix'inde). Image tanımı: `backend/Dockerfile` (build context REPO KÖKÜ).
- **Veri:** SQLite (WAL). Tek yazar varsayımı → **replicas: 1 zorunlu, strategy: Recreate.**
  HPA/çoklu replika ASLA kurulmayacak.
- **Auth:** tüm `/api/v1` istekleri `X-API-Key` başlığı ister (tek paylaşılan secret,
  `API_KEY` env). Statik UI açıktır; UI, kullanıcıdan key'i modal ile alır (localStorage).
- **Veri göçü GEREKMEZ:** boş DB ile açılır; maç geçmişi, Teoman'ın PC'sindeki collector
  `--backfill` ile yeniden gönderilir (idempotent + kronolojik; rating deterministik
  yeniden hesaplanır). VPS tarafında hiçbir seed/import işi yok.

## VPS agent'ından istenenler

### 1. Ön kontrol — cevapları rapor et
- [ ] Cluster'da Ingress controller hangisi? (nginx/traefik/other) TLS nasıl sağlanıyor
      (cert-manager var mı)?
- [ ] RWO destekleyen bir StorageClass var mı, adı ne? (1 Gi yeter)
- [ ] Image registry: cluster hangi registry'den çekiyor? Build VPS'te mi yapılacak
      (docker/podman/kaniko) yoksa hazır image mi push edilecek? Tercihini bildir;
      repo erişimi gerekiyorsa söyle.
- [ ] Leaderboard'un servis edileceği hostname/subdomain önerisi (ör. `lol.<domain>`).

### 2. Kurulum
Aşağıdaki manifest iskeleti temel alınabilir; cluster gerçeklerine (ingress class,
storage class, registry yolu) uyarlaman beklenir. **Değişmezler:** replicas 1,
Recreate, `/data` kalıcı volume, `API_KEY` Secret'tan.

```yaml
apiVersion: v1
kind: Namespace
metadata: { name: lol-balance }
---
apiVersion: v1
kind: Secret
metadata: { name: lol-balance-secrets, namespace: lol-balance }
stringData:
  API_KEY: "<GÜÇLÜ-RASTGELE-SECRET-ÜRET>"   # openssl rand -hex 24; raporunda DEĞERİ YAZMA
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: lol-balance-data, namespace: lol-balance }
spec:
  accessModes: [ReadWriteOnce]
  resources: { requests: { storage: 1Gi } }
  # storageClassName: <cluster'daki-sinif>
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: lol-balance, namespace: lol-balance }
spec:
  replicas: 1                    # SQLite tek yazar — asla artırma
  strategy: { type: Recreate }   # eski pod ölmeden yenisi DB'ye dokunmasın
  selector: { matchLabels: { app: lol-balance } }
  template:
    metadata: { labels: { app: lol-balance } }
    spec:
      containers:
        - name: app
          image: <registry>/lol-balance:<tag>
          ports: [{ containerPort: 8000 }]
          envFrom: [{ secretRef: { name: lol-balance-secrets } }]
          # DB_PATH ve WEBUI_DIR image içinde tanımlı (/data/lol_balance.db, /app/webui)
          # ENGINE_VERSION verme: image default'u aktif version'dır (openskill-pl-blend50-v1)
          volumeMounts: [{ name: data, mountPath: /data }]
          readinessProbe:
            httpGet: { path: /, port: 8000 }
            initialDelaySeconds: 3
          livenessProbe:
            httpGet: { path: /, port: 8000 }
            periodSeconds: 30
          resources:
            requests: { cpu: 50m, memory: 128Mi }
            limits: { cpu: "500m", memory: 512Mi }
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: lol-balance-data }
---
apiVersion: v1
kind: Service
metadata: { name: lol-balance, namespace: lol-balance }
spec:
  selector: { app: lol-balance }
  ports: [{ port: 80, targetPort: 8000 }]
---
# Ingress: cluster'ın kendi kalıbına göre yaz (class, TLS/cert-manager annotation'ları).
# Host: 1. adımda önerdiğin subdomain. HTTPS ZORUNLU (API key düz metin taşınıyor).
```

### 3. Yedekleme
- `/data/lol_balance.db` için günlük yedek CronJob'u kur (aynı PVC'yi mount edip
  `sqlite3 /data/lol_balance.db ".backup /data/backup/lol_balance-$(date +%F).db"`
  veya cluster'daki mevcut yedekleme düzenine bağla; 7 gün sakla).
- Not: ham veri (`ingest_events`) immutable'dır ve rating'ler replay ile yeniden
  üretilebilir; yedek kaybı felaket değildir ama maç geçmişi DB'de tekildir.

### 4. Doğrulama (deploy sonrası, raporuna ekle)
```bash
curl -s https://<host>/                                   # 200, HTML (web UI)
curl -s https://<host>/api/v1/players                     # 401 (key'siz reddetmeli)
curl -s -H "X-API-Key: $KEY" https://<host>/api/v1/players # 200, [] (boş liste)
```
- Pod restart testi: pod'u sil, yeniden geldiğinde `schema_migrations`'ın korunduğunu
  (`/api/v1/players` hâlâ 200) doğrula — PVC bağlı mı kanıtı.

### 5. Geri bildirim — lokal orkestratöre iletilecekler
1. Public URL (https://<host>)
2. API key'in Teoman'a güvenli bir kanaldan iletildiği bilgisi (değeri bu dosyaya/rapora yazma)
3. 4. adımdaki doğrulama çıktıları
4. Registry/build kararı ve image tag'i

Bu bilgiler geldikten sonra lokal tarafta yapılacaklar (bizim işimiz, senin değil):
collector `.env`'inde `BACKEND_URL` VPS adresine çevrilecek, `--backfill` ile maç
geçmişi VPS'e basılacak, lokal "LoL Balance Backend" zamanlanmış görevi devre dışı
bırakılacak.

## Kapsam dışı (yapma)
- Çoklu replika, HPA, PostgreSQL'e geçiş önerisi (bilinçli SQLite kararı, contract: docs/db_schema.md)
- Kullanıcı bazlı auth / OAuth (bilinçli kapsam dışı, contract: docs/api_contract.md)
- Rating/engine konfigürasyonu değişikliği (ENGINE_VERSION'a dokunma)
