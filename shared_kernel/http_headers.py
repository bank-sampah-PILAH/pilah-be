"""Satu-satunya tempat nama header HTTP kustom milik API ini didefinisikan.

Nama header kustom hidup di dua tempat yang tidak saling mengetahui: view yang
membacanya, dan setelan CORS yang mengizinkannya lewat preflight browser.
Keduanya pernah berbeda. ``Idempotency-Key`` dibaca di
``apps/ledger/views.py`` tetapi tidak pernah masuk ``CORS_ALLOW_HEADERS``,
sehingga setiap setoran dari browser gagal berbulan-bulan sementara aplikasi
native tetap berjalan, karena CORS hanya ada di browser.

Modul ini membuat kedua sisi berasal dari satu nilai. Menambah header kustom
baru cukup dilakukan di sini, dan test di
``tests/regression/identity/test_cors.py`` menjaga agar setiap entri registry
benar-benar lolos preflight. Modul sengaja tidak mengimpor Django apa pun
supaya aman dibaca dari ``config/settings.py`` saat setelan dimuat.
"""

IDEMPOTENCY_KEY = "Idempotency-Key"
CONTENT_DISPOSITION = "Content-Disposition"

HEADER_PERMINTAAN_KUSTOM: tuple[str, ...] = (IDEMPOTENCY_KEY,)
"""Header kustom yang dibaca API dari permintaan klien.

Setiap entri harus lolos preflight, jadi ``CORS_ALLOW_HEADERS`` diturunkan
dari tuple ini alih-alih menuliskan ulang namanya.
"""

HEADER_RESPONS_TEREKSPOS: tuple[str, ...] = (CONTENT_DISPOSITION,)
"""Header respons yang boleh dibaca JavaScript di browser.

Browser menyembunyikan header respons dari JavaScript kecuali disebut di
``Access-Control-Expose-Headers``, yang diturunkan dari tuple ini.
"""
