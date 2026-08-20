# Devir Notu (2026-08-15)

Yeni oturum/orkestratör için tek sayfalık özet. Otorite sırası: `CLAUDE.md`
(yetki modeli + savunulan kararlar) → `docs/ORCHESTRATION.md` → `docs/` contract'ları →
`docs/CHANGE_REQUESTS.md` (tüm kararlar, gerekçeli). Yaşayan durum: `context/90-durum.md`.
Bağlam aktarımı worker'lara HER ZAMAN `context/` üzerinden (protokol: `context/README.md`).

## Ne yayında

- **https://lol.teomanagir.com** — VPS K8s'te tek container (backend+webui), TLS,
  günlük yedek. Repo **PUBLIC**; fixture'lar ANONİM (PlayerNN#FAKE, testle kilitli).
- **CI/CD:** push/PR = 3 test paketi; `main` merge = GHCR imajı + SSH deploy
  (`cideploy@`, zorunlu-komut) → **main'e merge = canlıya çıkış.** İmaj kurulumu
  Data Dragon varlıklarını da indirir (`deploy/fetch_ddragon.py`, sürüm sabitli).
- **Collector dağıtımı GitHub Releases'tan:** `v*` etiketi → `release.yml` Windows'ta
  `build.bat` (testli) koşturur, exe Release'e ekler. Exe açılışta releases/latest'i
  yoklar, yeni sürümde pencerede "İndir" bandı gösterir. İlk release: v0.3.0.
- **Collector 0.3.0:** çift tık = tkinter penceresi (gömülü log; Canlı/Tara/Eşya/Rol
  doldurma butonları — son ikisi dry-run→Uygula onaylı; sihirbaz diyaloglarla);
  CLI komutları ve `--console` aynen. Heartbeat + CLIENT_ID + items toplama içinde.

## Aktif rating modeli

`openskill-pl-blend25-v1` (Teoman, 2026-08-20; spec: rating_contract "Harman Engine — blend25"):
`score = [0.25·mu + 0.75·(25 + 20·(P_avg−1))] − 3·sigma`. Rol evreni ayrı tablo, birebir
aynı formül. Sabitler version'a donuk — tuning = yeni version + Teoman onayı.
Geçiş canlıda `POST /admin/replay` GEREKTİRDİ (iki evren; replay'e dek herkes nötr görünür).
Faz 2 (pair synergy rating) hâlâ kapsam dışı; sinerji yalnız gösterim.

## Orkestratör işletim defteri (bu oturumların pahalı dersleri)

**Git/PR disiplini**
- `git commit` sonrası ÇIKTIYI DOĞRULA (`[branch hash]` + dosya sayısı). Bir kez
  commit sessiz düştü, PR docs-only merge oldu (PR #39→#40 olayı).
- `gh pr create` gövdesi HER ZAMAN `--body-file` ile (here-string native exe'ye
  bölünüyor — iki kez yaşandı). Genel kural: gh'a çok satırlı metni dosyayla ver.
- Merge önerisinden önce PR head SHA'sı == push'ladığın son commit mi kontrol et
  (Teoman hızlı merge'ler; PR #29'da portre commit'i merge'e yetişemedi → ayrı PR).
- `git add` PATH BAZLI yap; pathspec hatası TÜM add'i iptal eder (referans
  güncellemeleri commit dışı kaldı). `git add -A` YASAK: working tree ortak —
  Teoman elle dosya taşıyabilir/ekleyebilir (ORCHESTRATION.md taşıma olayı,
  image.png). Commit öncesi `git status --porcelain` oku, sahiplenme.
- İş bitince working tree'yi MAIN'de bırak (`checkout main && pull`): Teoman
  terminale elle komut girer; `git tag` o anki HEAD'e yapışır. Etiket tarifi:
  `git checkout main && git pull && git tag vX.Y.Z && git push origin vX.Y.Z`
  (workflow tanımı ETİKETLENEN commit'ten okunur — yan branch'te release.yml yoksa
  run sessizce doğmaz; v0.3.0'da yaşandı, etiket taşınarak çözüldü).
- `gh pr merge` orkestratörde izin sınıflandırıcısına takılır → merge Teoman'da.
  Şablon: `! & "C:\Program Files\GitHub CLI\gh.exe" pr merge N --merge --delete-branch`
- Release rutini: `collector/__init__.py` sürümünü yükselt → commit/PR → merge →
  etiket. release.yml etiket≠sürüm ise düşer (bilerek).

**Worker yönetimi**
- Paralel worker'lar AYNI working tree'de koşar: brief'e "git status'ta başkalarının
  dosyalarını görürsün, DOKUNMA" yaz; dizinler çakışacaksa sıralı çalıştır ya da
  branch'i istifle (webui'de aynı dosyaya iki iş = istif, sonra rebase).
- Worker raporundaki "contract'ta tanımsız" maddeler: teknik düzeltmeyse contract'a
  işle + CHANGE_REQUESTS'e "Ek [worker → orkestratör] ONAY" satırı düş.
- Teoman büyük UI işlerinde ÖNCE KONSEPT ister (artifact'lar, numaralı; GÖREV 9'da
  10+5, META'da 3) — seçer, bazen harmanlatır; sonra tam iş.

**Doğrulama**
- Tarayıcı E2E'de sekme geçişi KOORDİNATLA DEĞİL
  `document.querySelector('[data-view="..."]').click()` ile (viewport oynuyor,
  koordinat tıkları yanlış öğeye gitti, sahte alarm üretti).
- Sıralı scratchpad portları (8123+) kullan; iş bitince uvicorn'u öldür, sekmeyi kapat.
- localStorage: `apiKey` = scratchpad backend'in `API_KEY`'i.

## Yerel ortam (bilinmezse zaman yakar)

- PATH'te `python`/`node` YOK: `backend\.venv\Scripts\python.exe` (backend+collector),
  `backend\rating\.venv\Scripts\python.exe` (rating). rating paketi backend venv'ine
  KOPYA kurulur (editable bozuk).
- `gh`: `C:\Program Files\GitHub CLI\gh.exe`. LoL: `F:\Riot Games\League of Legends`.
- PowerShell 5.1: çok satırlı python'ı DOSYAYA yazıp koş; `&&` yok; konsolda Türkçe
  bozuk görünür (veri sağlam).
- `new_modules.md` (görev listesi) ve kökteki teşhis dosyaları YEREL-ONLY/gitignore.
- Yerel `backend/data/lol_balance.db` canlı DEĞİL (eski kopya); E2E scratch kopyayla.

## Açık maddeler (2026-08-15)

- GÖREV 17 (sinerji formülüne performans katkısı) tartışma aşamasında.
- GÖREV IMPOSSIBLE (mobil app/hesap/lobi) uzak vizyon — savunulan kararların
  revizyonunu gerektirir, başlamadı.
- Data Dragon patch güncellemesi: `fetch_ddragon.py` DDRAGON_VERSION + redeploy;
  META verisi: `fetch_meta.py` → fark → `--write` → commit (onaysız yazmaz).
