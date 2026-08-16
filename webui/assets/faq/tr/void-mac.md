# Maç iptal (void) edilirse ne olur?

O maç hesaptan tamamen çıkarılır ve **tüm geçmiş yeniden hesaplanır** — sanki
o maç hiç oynanmamış gibi.

Bu, sistemin temel bir ilkesidir: ham maç kayıtları hiç değiştirilmez, rating
ise her an o kayıtlardan sıfırdan yeniden üretilebilir. Void sonrası herkesin
mu'su, sigma'sı ve P_avg'ı, kalan maçlar sırayla yeniden oynatılarak (replay)
baştan hesaplanır; leaderboard da buna göre güncellenir.

Bu yüzden void geri alınamaz bir işlemdir ve maç geçmişi ekranında onay
istenir.
