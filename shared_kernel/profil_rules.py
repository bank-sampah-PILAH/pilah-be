"""Aturan field profil yang dipakai lebih dari satu serializer.

Profil seseorang muncul di dua tempat (lihat `AGENTS.md`, "Aturan data
nasabah"): di akun (`User`) dan di catatan satu bank sampah (`Nasabah`).
Keduanya memegang `nama`, `jenis_kelamin`, `tanggal_lahir`, dan `no_hp`, dan
aturan untuk keempatnya sama di mana pun field itu ditulis.

Masalah yang diperbaiki di sini: keempat aturan itu disalin utuh di
`NasabahSerializer` dan `UserProfileSerializer`, lengkap dengan bunyi
pesannya. Salinan seperti itu tidak bertahan sama: PIL-478 menemukan
pembanding tanggal lahir melempar `TypeError` di dua tempat sekaligus karena
keduanya ditulis ulang dari ingatan, dan menemukan satu serializer lain yang
kehilangan aturannya sama sekali.
"""

from datetime import date
from typing import Any

from rest_framework import serializers

from shared_kernel.validators import normalize_indonesian_phone, tanggal_lahir_valid


class ProfilFieldRules:
    """Template Method untuk keempat aturan field profil.

    Yang tetap ada di sini: urutan pemeriksaan tiap field dan bunyi pesannya,
    supaya satu aturan punya satu rumusan. Yang diserahkan ke subclass hanya
    langkah yang memang berbeda antar model, yaitu [allowed_genders]:
    `Nasabah.Gender` dan `User.Gender` adalah dua enum terpisah meski isinya
    sama, dan `shared_kernel` tidak boleh mengimpor model untuk memilih salah
    satu.

    Dipasang di depan `ModelSerializer` supaya DRF menemukan `validate_*` di
    sini lewat MRO, dan sebuah serializer tetap bebas menimpa satu aturan bila
    memang perlu.

    Sengaja TIDAK dipakai `NasabahProfileSerializer`
    (`apps/nasabah/profile.py`). Serializer itu hanya memeriksa `no_hp` dan
    `tanggal_lahir`; memasang mixin ini ke sana akan sekaligus menambahkan
    pemeriksaan `nama` dan `jenis_kelamin` yang sebelumnya tidak ada, dan itu
    pengetatan perilaku, bukan refactor. Kalau pengetatan itu diinginkan,
    tempatnya commit sendiri.
    """

    def allowed_genders(self) -> tuple[str, ...]:
        """Nilai `jenis_kelamin` yang berlaku untuk model serializer ini."""
        raise NotImplementedError

    def validate_nama(self, value: Any) -> Any:
        value = value.strip()
        if not 3 <= len(value) <= 100:
            raise serializers.ValidationError("Nama minimal 3 karakter")
        return value

    def validate_no_hp(self, value: Any) -> Any:
        return normalize_indonesian_phone(value)

    def validate_jenis_kelamin(self, value: Any) -> Any:
        if value not in self.allowed_genders():
            raise serializers.ValidationError("Jenis kelamin wajib dipilih")
        return value

    def validate_tanggal_lahir(self, value: date | None) -> date | None:
        return tanggal_lahir_valid(value)
