"""Give seeded pending banks a real activity-proof photo.

Registration makes `foto_kegiatan` mandatory, so every real pending bank has
one. The synthetic review and demo banks are created without going through that
form, and leaving the field blank made the superadmin "Lihat Bukti" dialog show
its empty state — the approval screen could not be validated at all.
"""

import struct
import zlib

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from api.models import BankSampah

PROOF_PHOTO_PATH = "bank_sampah/kegiatan/bukti-kegiatan-seed.png"
_WIDTH = 640
_HEIGHT = 360
_TOP = (46, 125, 50)
_BOTTOM = (200, 230, 201)


def _png() -> bytes:
    """A two-tone rectangle: obviously an image, but not a real person's photo."""
    rows = b"".join(
        b"\x00" + bytes(_TOP if y < _HEIGHT // 2 else _BOTTOM) * _WIDTH for y in range(_HEIGHT)
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", _WIDTH, _HEIGHT, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def ensure_proof_photo(bank: BankSampah) -> None:
    """Attach the seeded proof image when the bank has none yet. Idempotent."""
    if bank.foto_kegiatan:
        return
    name = PROOF_PHOTO_PATH
    if not default_storage.exists(name):
        name = default_storage.save(name, ContentFile(_png()))
    bank.foto_kegiatan = name
    bank.save(update_fields=["foto_kegiatan", "updated_at"])
