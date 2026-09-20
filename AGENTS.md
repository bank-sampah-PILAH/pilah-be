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
