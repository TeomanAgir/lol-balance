# context/ — Orkestratör ↔ Worker bağlam paketi

**Amaç:** Orkestratör, worker (subagent) başlatırken bağlamı prompt'a KOPYALAMAZ;
worker'ı buradaki dosyalara YÖNLENDİRİR. Böylece her görevde aynı bilgi yeniden
üretilip token yakılmaz.

## Orkestratör protokolü

Worker prompt'u şu iskeletle sınırlı tutulur (~15-25 satır):

```
Sen lol-balance projesinin <BILEŞEN> subagent'ısın. Kök: <repo yolu>
1) ÖNCE OKU: context/00-ortak.md + context/<NN>-<bileşen>.md
   (görevle ilgiliyse ek: docs/<ilgili contract> — READ-ONLY)
2) GÖREV: <yalnız bu göreve özgü tanım, kabul ölçütleri>
3) Sınır/ortam/test komutları 00-ortak.md'de; onlara uy.
4) Final rapor: değişen dosyalar + test önce/sonra + sapmalar.
```

Kurallar:
- Worker'a bağlam SORUSU düşerse cevap önce bu dosyalara eklenir, sonra
  worker'a "tekrar oku" denir — prompt'a yapıştırılmaz.
- Her merge sonrası orkestratör `90-durum.md`'yi ve (haritası değiştiyse)
  ilgili bileşen dosyasını tazeler. Bu klasör İŞARETÇİDİR: içerik kopyalamak
  yerine dosya/fonksiyon adı gösterir; şişirmek yasaktır.
- Karar geçmişi burada TUTULMAZ — o `docs/CHANGE_REQUESTS.md`'dedir.
  Mimari otorite `CLAUDE.md`'dedir. Çelişkide onlar kazanır.

## Dosyalar

| Dosya | İçerik | Kim okur |
|---|---|---|
| `00-ortak.md` | Ortam, sınırlar, süreç, test komutları | HER worker |
| `10-backend.md` | Backend haritası + değişmezler | backend worker |
| `20-collector.md` | Collector haritası + rol önceliği + paketleme | collector worker |
| `30-webui.md` | Web UI haritası + i18n kalıbı + tuzaklar | webui worker |
| `40-rating.md` | Rating paketi + dondurma kuralları | rating worker |
| `90-durum.md` | Güncel proje durumu (yaşayan dosya) | orkestratör + gerekirse worker |
