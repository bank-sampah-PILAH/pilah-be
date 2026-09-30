# PILAH Backend Instructions

## Scope

- This repository is the `pilah-be` application submodule of the PILAH
  workspace.
- Keep backend implementation changes here, not in the workspace root or the
  mobile repository.
- Keep the canonical checkout on `staging`; use `staging` as the worktree
  baseline and pull request target unless the request explicitly names another
  branch. Never infer `main` as the baseline.

## Development

- The backend uses Python 3.12, Django 6, and Django REST Framework.
- Prefer `uv` for local setup when available: `uv venv` followed by
  `uv pip install -r requirements.txt`; fall back to a virtual environment and
  `pip install -r requirements.txt` when `uv` is unavailable.
- Docker setup and environment variables are documented in `README.md`.

## Aturan data nasabah

- Akun dan keanggotaan adalah dua data yang terpisah, dan tidak ada
  penyalinan di antara keduanya setelah baris keanggotaan dibuat. Profil akun
  (`User`: `nama`, `jenis_kelamin`, `tanggal_lahir`, `alamat`, `no_hp`) milik
  nasabah; baris `Nasabah` adalah catatan satu bank sampah tentang nasabah itu,
  bersama nomor anggota (`kode`), `is_active`, dan `status`. Nasabah yang
  menyimpan profilnya tidak menimpa catatan pengurus, dan perbaikan pengurus
  tidak menyentuh akun atau keanggotaan di bank sampah lain. Satu-satunya
  penyalinan adalah saat pendaftaran keanggotaan (`register_nasabah`, termasuk
  ajukan ulang setelah ditolak). Nasabah boleh menyimpan ulang profilnya kapan
  saja; hanya pengelola yang dibatasi satu kali.
- Pengurus boleh memperbaiki catatan nasabah berakun, karena ialah yang
  bertemu nasabah di lapangan. Hanya `email` yang terkunci begitu
  `Nasabah.user` terisi, dan perubahannya ditolak dengan 403 (PIL-288 merevisi
  PIL-223, OWASP A01). Email adalah kunci penautan akun dan tidak dijaga oleh
  apa pun selain aturan ini. Daftar field yang terkunci ada di
  `FIELD_TERKUNCI`.
- Pengurus melihat profil yang diisikan nasabah sendiri lewat `profil_akun` dan
  `profil_berbeda` pada detail nasabah (`api/keanggotaan.py`), dan dapat
  menyamakan catatannya dengan `POST /nasabah/{id}/sinkron-profil`. Salinan itu
  satu arah (akun ke baris), hanya untuk bank sampah pemanggil, dan sesudahnya
  catatan tetap dapat disunting. Jangan menambah penyalinan otomatis.
- Nomor HP unik per bank sampah pada tabel keanggotaan saja, dan hanya
  diperiksa pada baris yang sedang ditulis. `User.no_hp` tidak unik.
- Respons nasabah membawa `punya_akun` (read-only) supaya klien dapat
  menampilkan profil sebagai read-only alih-alih menunggu 403. Penanda
  tampilan saja; jangan pindahkan keputusan wewenang ke klien (PIL-281).
- Nasabah tanpa akun tetap dapat dikelola penuh oleh pengurus, karena itulah
  satu-satunya pihak yang memegang datanya.
- Semua pemeriksaan wewenang atas data nasabah lewat `api/keanggotaan.py`;
  jangan menuliskan daftar field terkunci di view.
- Bandingkan `serializer.validated_data`, bukan `request.data`, saat memeriksa
  perubahan: nomor HP dinormalisasi ke +62 dan tanggal dikonversi ke `date`.

## Aturan nilai uang

- Rupiah adalah bilangan bulat. Satuan terkecil Rp 1; tidak ada sen maupun
  setengah rupiah.
- Setiap perhitungan nilai uang dibulatkan **ke bawah** ke rupiah penuh,
  mengikuti pola `int()` yang sudah dipakai pada teks WhatsApp dan export
  Excel.
- Gunakan `api/kalkulasi.py` untuk semua perhitungan dan pembulatan nilai
  setoran. Jangan memanggil `quantize()` tanpa mode pembulatan: default Python
  adalah half-even, bukan pembulatan ke bawah.
- Harga transaksi selalu berasal dari master `JenisSampah` lewat
  `harga_berlaku()`. Request yang mengirim harga per item ditolak, bukan
  diabaikan.
- Pembulatan dilakukan per item, lalu subtotal dijumlahkan menjadi total,
  supaya total selalu sama dengan angka yang tampil di riwayat dan notifikasi.
- Data lama dari PILAH 1.0 dapat berisi sen. Bulatkan ke bawah saat nilainya
  diperbarui, jangan lakukan migrasi massal atas saldo nasabah.
- Berat (kg) bukan nilai uang: `format_kg` tetap memakai `ROUND_HALF_UP`.

## Aturan input setoran

- Berat boleh desimal hingga 3 angka di belakang koma dan harus lebih dari
  0 kg.
- Berat satu item maksimal 500 kg (`BERAT_MAKS_PER_ITEM`) dan total satu
  setoran maksimal 1.000 kg (`BERAT_MAKS_PER_SETORAN`). Input di atas batas
  ditolak dengan 422; ubah angkanya hanya lewat konstanta di
  `api/serializers.py`.
- Harga master harus positif dan dipertahankan presisinya sampai dikalikan
  dengan berat. Bulatkan subtotal setiap item ke bawah; tolak item yang
  subtotalnya menjadi Rp 0 supaya transaksi tidak mencatat item tanpa nilai.
- Peringatan untuk item di atas 100 kg belum dikerjakan; jika dibuat, tempatnya
  di layar tinjauan setoran pada aplikasi, bukan penolakan di backend.

## Validation

- Run `uv run --with-requirements requirements.txt python manage.py test` when
  `uv` is available; otherwise run `python manage.py test`.
- The Docker equivalent is `docker compose exec web python manage.py test`.
- Do not commit `.env`, credentials, local databases, media, or generated
  runtime files.

## Delivery

- For Linear-linked work, use `feature/<issue-id>` with the lowercase issue
  identifier, for example `feature/eng-123`.
- Use the local `.agents/skills/ship` skill with the global `ship` workflow for
  feature or fix branches in sibling `pilah-be-worktrees` directories.
- Use the local `.agents/skills/lgtm` skill with the global `lgtm` workflow for
  merge and cleanup.
