# 40 — Rating paketi haritası (`backend/rating/`)

Yazma izni: yalnız `backend/rating/`. Test: `backend\rating\.venv\Scripts\python.exe -m
pytest backend/rating`. DEĞİŞİKLİK SONRASI backend venv'ine yeniden kur (kopya kurulum,
bkz. 00-ortak). 145 test.

## Çekirdek (`rating/` paketi)
- Engine'ler versiyon string'ine DONDURULMUŞTUR: `openskill-pl-v1`,
  `openskill-pl-perf-v1`, aktif `openskill-pl-blend50-v1`
  (`mu_eff = 0.5*mu + 0.5*(25 + 20*(P_avg-1))`, `score = mu_eff - 3*sigma`).
  Sabit/formül "tuning"i YASAK — yeni version + Teoman onayı gerekir (CLAUDE.md #1, #4).
- `balancer.py` — `ROLES` kanonik sırası, `RoleBalanceSuggestion`,
  `balance_roles(ratings_by_role, top_n)` (126 ayrım × takım başına 120 permütasyon,
  ordinal toplam maksimizasyonu, deterministik ilk-maksimum),
  `balance_roles_constrained(..., separate=(i,j), fixed_role)` (nemesis: 70 ayrım × 24 perm).
  Çağıran, blended mu_eff'i Rating.mu olarak geçirir; `separate` POZİSYON indeksleridir.

## Kurallar
- Rol bazlı normalizasyon perf BİLEŞENLERİNDE yapılmaz (position güvenilmez);
  rol evreni ayrı STATE uzayıdır, normalizasyon değildir (CLAUDE.md #8).
- mu güncellemesinde performans çift sayılmaz (blend yalnız efektif skorda).
- Determinizm: aynı girdi → bit-bit aynı çıktı; testler permütasyon/eşitlik
  kırılımlarını sabitler.
