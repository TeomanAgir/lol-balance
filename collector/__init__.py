"""LCU Collector — biten custom maçları LCU API'den toplayıp backend'e gönderir."""

# Sürüm damgası heartbeat'le panele gider; her exe dağıtımından önce yükseltilir.
# Yayın: `git tag v<bu değer>` — .github/workflows/release.yml etiket/sürüm eşitliğini
# doğrular ve uyuşmazsa derlemeyi kırar.
# 0.2.0 — GÖREV 13 (kimlik+heartbeat) + GÖREV 14 (items) dağıtımı.
# 0.3.0 — GÖREV 16: tkinter arayüzü, güncelleme bildirimi, --windowed exe.
__version__ = "0.3.0"
