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

- Profil nasabah (`nama`, `jenis_kelamin`, `tanggal_lahir`, `alamat`, `no_hp`)
  milik pemilik akun dan berlaku lintas bank sampah. Nomor anggota (`kode`),
  `is_active`, dan `status` adalah data keanggotaan pada satu bank sampah.
- Begitu `Nasabah.user` terisi, pengurus hanya boleh mengubah data keanggotaan.
  Perubahan profil ditolak dengan 403 (PIL-223, OWASP A01).
- Nasabah tanpa akun tetap dapat dikelola penuh oleh pengurus, karena itulah
  satu-satunya pihak yang memegang datanya.
- Semua pemeriksaan wewenang atas data nasabah lewat `api/keanggotaan.py`;
  jangan menuliskan daftar field terkunci di view. Ketika PIL-154 masuk,
  tambahkan `email` ke `FIELD_PROFIL_GLOBAL` karena email adalah kunci
  penautan akun.
- Bandingkan `serializer.validated_data`, bukan `request.data`, saat memeriksa
  perubahan: nomor HP dinormalisasi ke +62 dan tanggal dikonversi ke `date`.

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
