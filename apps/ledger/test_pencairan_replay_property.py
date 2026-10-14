from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.utils import timezone
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase
from rest_framework.exceptions import ValidationError

from api.models import BankSampah, Nasabah, Pencairan, Saldo, Transaksi, User
from apps.ledger.services import PencairanService

# Few distinct instants, so setoran and pencairan often land on the same one.
_JAM = st.integers(min_value=0, max_value=3)
_SETORAN = st.lists(
    st.tuples(_JAM, st.integers(min_value=10_000, max_value=60_000)), min_size=1, max_size=4
)
_PENCAIRAN = st.lists(
    st.tuples(_JAM, st.integers(min_value=1, max_value=30_000)), min_size=1, max_size=4
)


def _urut(setoran: list[tuple[int, int, str]], pencairan: list[tuple[int, int, str]]):
    """Ledger order: by instant, a setoran before a pencairan, pencairan by id."""
    peristiwa = [(jam, 0, kunci, nilai) for jam, nilai, kunci in setoran]
    peristiwa += [(jam, 1, kunci, nilai) for jam, nilai, kunci in pencairan]
    return sorted(peristiwa, key=lambda item: item[:3])


def _putar(
    setoran: list[tuple[int, int, str]], pencairan: list[tuple[int, int, str]]
) -> tuple[int, dict[str, tuple[int, int]]] | None:
    """Final saldo and each pencairan's snapshot, or None when one overdraws."""
    saldo = 0
    snapshot: dict[str, tuple[int, int]] = {}
    for _, jenis, kunci, nilai in _urut(setoran, pencairan):
        if jenis == 0:
            saldo += nilai
            continue
        if nilai > saldo:
            return None
        snapshot[kunci] = (saldo, saldo - nilai)
        saldo -= nilai
    return saldo, snapshot


class EditPencairanReplayPropertyTests(TestCase):
    """Edit result must match an independent replay of the whole ledger."""

    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Melati", no_hp_pic="08123456789")
        self.pengurus = User.objects.create_user(
            email="pengurus@example.test", nama="Pengurus", bank_sampah=self.bank
        )
        self.nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="001",
            nama="N001",
            alamat="Depok",
            no_hp="0812001",
            email="n001@example.test",
        )
        self.dasar = timezone.now().replace(microsecond=0) - timedelta(hours=10)

    def _jam(self, jam: int) -> datetime:
        return self.dasar + timedelta(hours=jam)

    # mutmut runs this test in a forked process after running it in the parent, which
    # Hypothesis reports as differing executors.
    @settings(
        max_examples=150,
        deadline=None,
        suppress_health_check=[HealthCheck.differing_executors],
    )
    @given(
        setoran=_SETORAN,
        pencairan=_PENCAIRAN,
        pilihan=st.integers(min_value=0, max_value=3),
        nominal_baru=st.integers(min_value=1, max_value=90_000),
        jam_baru=_JAM,
    )
    def test_edit_cocok_dengan_putar_ulang_ledger(
        self,
        setoran: list[tuple[int, int]],
        pencairan: list[tuple[int, int]],
        pilihan: int,
        nominal_baru: int,
        jam_baru: int,
    ) -> None:
        setoran_k = [(jam, nilai, f"s{i}") for i, (jam, nilai) in enumerate(setoran)]
        # Pencairan ids are small ints so their string order is the ledger's tie-break.
        pencairan_k = [
            (jam, nilai, str(UUID(int=i + 1))) for i, (jam, nilai) in enumerate(pencairan)
        ]
        # Keep only pencairan the starting ledger can pay, so the start is consistent.
        layak: list[tuple[int, int, str]] = []
        for calon in pencairan_k:
            if _putar(setoran_k, [*layak, calon]) is not None:
                layak.append(calon)
        assume(layak)
        akhir, awal = _putar(setoran_k, layak)  # type: ignore[misc]

        for jam, nilai, _ in setoran_k:
            Transaksi.objects.create(
                nasabah=self.nasabah,
                bank_sampah=self.bank,
                dicatat_oleh=self.pengurus,
                tanggal=self._jam(jam),
                total_nilai=Decimal(nilai),
            )
        for jam, nilai, kunci in layak:
            sebelum, sesudah = awal[kunci]
            Pencairan.objects.create(
                id=UUID(kunci),
                nasabah=self.nasabah,
                bank_sampah=self.bank,
                dicatat_oleh=self.pengurus,
                tanggal=self._jam(jam),
                nominal=Decimal(nilai),
                metode="tunai",
                saldo_sebelum=Decimal(sebelum),
                saldo_sesudah=Decimal(sesudah),
            )
        Saldo.objects.create(nasabah=self.nasabah, total_saldo=Decimal(akhir))

        jam_lama, nominal_lama, kunci = layak[pilihan % len(layak)]
        assume((nominal_baru, jam_baru) != (nominal_lama, jam_lama))
        diedit = Pencairan.objects.get(pk=UUID(kunci))
        harapan = _putar(
            setoran_k,
            [(jam_baru, nominal_baru, kunci) if k == kunci else (j, n, k) for j, n, k in layak],
        )

        payload = {
            "nominal": Decimal(nominal_baru),
            "tanggal": self._jam(jam_baru),
            "alasan": "Salah ketik",
        }
        if harapan is None:
            with self.assertRaises(ValidationError):
                PencairanService.edit_pencairan(self.pengurus, diedit, payload)
            return
        PencairanService.edit_pencairan(self.pengurus, diedit, payload)

        akhir_baru, snapshot = harapan
        self.assertEqual(Saldo.objects.get(nasabah=self.nasabah).total_saldo, akhir_baru)
        for _, _, k in layak:
            baris = Pencairan.objects.get(pk=UUID(k))
            self.assertEqual(
                (baris.saldo_sebelum, baris.saldo_sesudah),
                (Decimal(snapshot[k][0]), Decimal(snapshot[k][1])),
            )
