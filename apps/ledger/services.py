from calendar import monthrange
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, TypeVar, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Exists, F, Model, OuterRef, Q, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import HttpRequest
from django.utils import timezone
from rest_framework import serializers

from api.models import (
    BankSampah,
    DetailTransaksi,
    DraftPencairan,
    DraftPencairanItem,
    Nasabah,
    Pencairan,
    PencairanRevisi,
    Saldo,
    Transaksi,
    TransaksiRevisi,
    User,
)
from apps.nasabah.api import (
    get_eligible_nasabah_map,
    get_locked_nasabah,
    kandidat_pencairan,
)
from apps.waste_catalog.api import get_active_jenis, harga_berlaku
from shared_kernel.kalkulasi import (
    bulatkan_rupiah,
    hitung_potongan,
    hitung_subtotal,
    total_setoran,
)

_NASABAH_TIDAK_AKTIF = "Nasabah tidak ditemukan atau tidak aktif"
_SALDO_KURANG = "Saldo nasabah tidak mencukupi"
_JENIS_TIDAK_AKTIF = "Jenis sampah tidak ditemukan atau tidak aktif"
_HARGA_BELUM_ADA = "Harga jenis sampah belum diatur"
_SUBTOTAL_NOL = "Nilai setoran item kurang dari Rp 1 setelah pembulatan"


class SaldoTidakCukup(Exception):
    """An edit would take the nasabah's saldo below zero."""


class SetoranDibatalkan(Exception):
    """The setoran was voided; a voided setoran is final."""

    def __init__(self) -> None:
        super().__init__("Setoran sudah dibatalkan")


class TransactionService:
    @staticmethod
    @transaction.atomic
    def create_setoran(
        user: User,
        payload: Mapping[str, Any],
        idempotency_key: UUID | None = None,
        idempotency_request_hash: str = "",
    ) -> Transaksi:
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        nasabah = get_locked_nasabah(bank, payload["nasabah_id"])
        if not nasabah:
            raise serializers.ValidationError({"nasabah_id": [_NASABAH_TIDAK_AKTIF]})

        saldo, _ = Saldo.objects.select_for_update().get_or_create(nasabah=nasabah)
        transaksi = Transaksi.objects.create(
            nasabah=nasabah,
            bank_sampah=bank,
            dicatat_oleh=user,
            # "" — not None: the column is NOT NULL (S6553), and blank means
            # "no note" everywhere the serializer accepts catatan.
            catatan=payload.get("catatan") or "",
            idempotency_key=idempotency_key,
            idempotency_request_hash=idempotency_request_hash,
        )

        subtotal_items: list[Decimal] = []
        for index, item_payload in enumerate(payload["items"]):
            jenis = get_active_jenis(bank, item_payload["jenis_sampah_id"])
            if not jenis:
                raise serializers.ValidationError(
                    {
                        f"items[{index}].jenis_sampah_id": [
                            "Jenis sampah tidak ditemukan atau tidak aktif"
                        ]
                    }
                )
            # Harga diambil di dalam transaksi database, pada waktu transaksi
            # itu sendiri (SDS SD-01 pesan 10), bukan dari nilai yang dikirim client.
            harga = harga_berlaku(jenis, transaksi.tanggal)
            if harga is None:
                raise serializers.ValidationError(
                    {f"items[{index}].jenis_sampah_id": ["Harga jenis sampah belum diatur"]}
                )
            berat = item_payload["berat"]
            subtotal = hitung_subtotal(harga, berat)
            if subtotal <= 0:
                raise serializers.ValidationError(
                    {
                        f"items[{index}].jenis_sampah_id": [
                            "Nilai setoran item kurang dari Rp 1 setelah pembulatan"
                        ]
                    }
                )
            DetailTransaksi.objects.create(
                transaksi=transaksi,
                jenis_sampah=jenis,
                nama_sampah_snapshot=jenis.nama_sampah,
                kategori_snapshot=jenis.kategori,
                harga_snapshot=harga,
                berat=berat,
                subtotal=subtotal,
            )
            subtotal_items.append(subtotal)

        total_nilai = total_setoran(subtotal_items)
        transaksi.total_nilai = total_nilai
        transaksi.save(update_fields=["total_nilai"])
        # Saldo warisan PILAH 1.0 bisa menyimpan sen; rapikan saat disentuh.
        saldo.total_saldo = bulatkan_rupiah(saldo.total_saldo + total_nilai)
        saldo.save(update_fields=["total_saldo", "updated_at"])
        return transaksi

    @staticmethod
    @transaction.atomic
    def edit_setoran(user: User, transaksi: Transaksi, payload: Mapping[str, Any]) -> Transaksi:
        """Correct weight, waste type or note, keeping the replaced version as a TransaksiRevisi.

        `transaksi` comes from the caller's bank-scoped queryset; it is re-read under lock.
        The price of each item is the one in force at the original `tanggal`, so an edit
        never reprices a setoran.
        """
        saldo = Saldo.objects.select_for_update().get(nasabah_id=transaksi.nasabah_id)
        transaksi = TransactionService._kunci_tercatat(transaksi)
        lama = list(transaksi.items.all())
        catatan = payload["catatan"] or "" if "catatan" in payload else transaksi.catatan

        baru = TransactionService._harga_item_edit(transaksi, lama, payload.get("items", []))

        if "items" in payload:
            total_baru = total_setoran([subtotal for *_, subtotal in baru])
            tanpa_perubahan = catatan == transaksi.catatan and sorted(
                (str(i.jenis_sampah_id), i.berat) for i in lama
            ) == sorted((str(jenis.id), berat) for jenis, _, berat, _ in baru)
        else:
            total_baru = transaksi.total_nilai
            tanpa_perubahan = catatan == transaksi.catatan
        if tanpa_perubahan:
            raise serializers.ValidationError({"non_field_errors": ["Tidak ada data yang diubah"]})

        selisih = total_baru - transaksi.total_nilai
        saldo_baru = bulatkan_rupiah(saldo.total_saldo + selisih)
        sesudahnya = TransactionService._geser_pencairan(transaksi, selisih)
        if saldo_baru < 0 or any(cair.saldo_sesudah < 0 for cair in sesudahnya):
            raise SaldoTidakCukup(
                "Perubahan ini membuat saldo nasabah menjadi negatif, "
                "karena sebagian saldo sudah dicairkan"
            )

        TransaksiRevisi.objects.create(
            transaksi=transaksi,
            versi=transaksi.revisi.count() + 1,
            total_nilai=transaksi.total_nilai,
            catatan=transaksi.catatan,
            items=[
                {
                    "nama_sampah": i.nama_sampah_snapshot,
                    "harga": str(i.harga_snapshot),
                    "berat": str(i.berat),
                    "subtotal": str(i.subtotal),
                }
                for i in lama
            ],
            alasan=payload["alasan"],
            diubah_oleh=user,
        )
        if "items" in payload:
            transaksi.items.all().delete()
            DetailTransaksi.objects.bulk_create(
                DetailTransaksi(
                    transaksi=transaksi,
                    jenis_sampah=jenis,
                    nama_sampah_snapshot=jenis.nama_sampah,
                    kategori_snapshot=jenis.kategori,
                    harga_snapshot=harga,
                    berat=berat,
                    subtotal=subtotal,
                )
                for jenis, harga, berat, subtotal in baru
            )
        transaksi.total_nilai = total_baru
        transaksi.catatan = catatan
        transaksi.save(update_fields=["total_nilai", "catatan", "updated_at"])
        Pencairan.objects.bulk_update(sesudahnya, ["saldo_sebelum", "saldo_sesudah"])
        saldo.total_saldo = saldo_baru
        saldo.save(update_fields=["total_saldo", "updated_at"])
        return transaksi

    @staticmethod
    @transaction.atomic
    def batalkan_setoran(user: User, transaksi: Transaksi, alasan: str) -> Transaksi:
        """Void a setoran: keep the row, mark it cancelled, take its total out of the saldo.

        `transaksi` comes from the caller's bank-scoped queryset; it is re-read under lock.
        """
        saldo = Saldo.objects.select_for_update().get(nasabah_id=transaksi.nasabah_id)
        transaksi = TransactionService._kunci_tercatat(transaksi)
        saldo_baru = bulatkan_rupiah(saldo.total_saldo - transaksi.total_nilai)
        sesudahnya = TransactionService._geser_pencairan(transaksi, -transaksi.total_nilai)
        if saldo_baru < 0 or any(cair.saldo_sesudah < 0 for cair in sesudahnya):
            raise SaldoTidakCukup(
                "Setoran ini tidak bisa dibatalkan karena sebagian saldonya sudah dicairkan"
            )
        transaksi.status = Transaksi.Status.DIBATALKAN
        transaksi.alasan_batal = alasan
        transaksi.dibatalkan_oleh = user
        transaksi.dibatalkan_pada = timezone.now()
        transaksi.save(
            update_fields=[
                "status",
                "alasan_batal",
                "dibatalkan_oleh",
                "dibatalkan_pada",
                "updated_at",
            ]
        )
        Pencairan.objects.bulk_update(sesudahnya, ["saldo_sebelum", "saldo_sesudah"])
        saldo.total_saldo = saldo_baru
        saldo.save(update_fields=["total_saldo", "updated_at"])
        return transaksi

    @staticmethod
    def _kunci_tercatat(transaksi: Transaksi) -> Transaksi:
        """Re-read under lock and refuse a setoran that was voided meanwhile."""
        transaksi = Transaksi.objects.select_for_update().get(pk=transaksi.pk)
        if transaksi.status == Transaksi.Status.DIBATALKAN:
            raise SetoranDibatalkan
        return transaksi

    @staticmethod
    def _harga_item_edit(
        transaksi: Transaksi, lama: list[DetailTransaksi], items: Any
    ) -> list[tuple[Any, Decimal, Decimal, Decimal]]:
        """Price the submitted items as on the original setoran date: (jenis, harga, berat, subtotal).

        A jenis deactivated since the setoran stays editable on the items it already has;
        only adding a new one needs it to be active.
        """
        jenis_lama = {i.jenis_sampah_id: i.jenis_sampah for i in lama if i.jenis_sampah}
        hasil: list[tuple[Any, Decimal, Decimal, Decimal]] = []
        for index, item_payload in enumerate(items):
            kunci = f"items[{index}].jenis_sampah_id"
            jenis = jenis_lama.get(item_payload["jenis_sampah_id"]) or get_active_jenis(
                transaksi.bank_sampah, item_payload["jenis_sampah_id"]
            )
            if not jenis:
                raise serializers.ValidationError({kunci: [_JENIS_TIDAK_AKTIF]})
            harga = harga_berlaku(jenis, transaksi.tanggal)
            if harga is None:
                raise serializers.ValidationError({kunci: [_HARGA_BELUM_ADA]})
            subtotal = hitung_subtotal(harga, item_payload["berat"])
            if subtotal <= 0:
                raise serializers.ValidationError({kunci: [_SUBTOTAL_NOL]})
            hasil.append((jenis, harga, item_payload["berat"], subtotal))
        return hasil

    @staticmethod
    def _geser_pencairan(transaksi: Transaksi, selisih: Decimal) -> list[Pencairan]:
        """Shift the snapshots of every pencairan from the setoran onwards by `selisih`.

        They were paid out of a balance this edit moves, so their recorded snapshots (and the
        statement built from them) move by the same amount. Returned unsaved: the caller checks
        none ends up paid from less than it took out, then saves them.
        """
        sesudahnya = list(
            Pencairan.objects.select_for_update().filter(
                bank_sampah_id=transaksi.bank_sampah_id,
                nasabah_id=transaksi.nasabah_id,
                tanggal__gte=transaksi.tanggal,
            )
        )
        for cair in sesudahnya:
            cair.saldo_sebelum += selisih
            cair.saldo_sesudah += selisih
        return sesudahnya


# ponytail: pencairan edit-window constant (PIL-2xx), shared with tests.
BATAS_MUNDUR_TANGGAL_PENCAIRAN_HARI = 7


class PencairanService:
    @staticmethod
    def realisasi(
        *,
        user: User,
        nasabah: Nasabah,
        saldo: Saldo,
        nominal: Decimal,
        metode: str,
        tanggal: datetime,
        keterangan: str,
        potongan: Decimal = Decimal(0),
        draft: DraftPencairan | None = None,
    ) -> Pencairan:
        """Debit `nominal` from the locked `saldo` and record the pencairan.

        The one place a pencairan moves money, shared by the single recording flow and
        draft confirmation. The caller holds the row locks and checked the balance.
        """
        saldo_sebelum = saldo.total_saldo
        # Whole rupiah, rounded down: drops sen left in PILAH 1.0 saldo, matching the setoran rule.
        saldo_sesudah = bulatkan_rupiah(saldo_sebelum - nominal)
        pencairan = Pencairan.objects.create(
            nasabah=nasabah,
            bank_sampah=nasabah.bank_sampah,
            dicatat_oleh=user,
            tanggal=tanggal,
            nominal=nominal,
            metode=metode,
            keterangan=keterangan,
            potongan=potongan,
            draft=draft,
            saldo_sebelum=saldo_sebelum,
            saldo_sesudah=saldo_sesudah,
        )
        saldo.total_saldo = saldo_sesudah
        saldo.save(update_fields=["total_saldo", "updated_at"])
        return pencairan

    @staticmethod
    @transaction.atomic
    def edit_pencairan(user: User, pencairan: Pencairan, payload: Mapping[str, Any]) -> Pencairan:
        """Apply a pengurus correction, keeping the replaced version as a PencairanRevisi.

        `pencairan` comes from the caller's bank-scoped queryset; it is re-read under lock.
        """
        pencairan = Pencairan.objects.select_for_update().get(pk=pencairan.pk)
        nominal = payload.get("nominal", pencairan.nominal)
        tanggal = payload.get("tanggal", pencairan.tanggal)
        metode = payload.get("metode", pencairan.metode)
        keterangan = payload.get("keterangan", pencairan.keterangan) or ""
        if pencairan.potongan > 0:
            # A client that echoes the stored tanggal can lose sub-second digits
            # (web DateTime keeps milliseconds), so a hair's difference is no edit.
            if abs(tanggal - pencairan.tanggal) < timedelta(seconds=1):
                tanggal = pencairan.tanggal
        if pencairan.potongan > 0:
            diubah = [
                nama
                for nama, baru, lama in (
                    ("nominal", nominal, pencairan.nominal),
                    ("tanggal", tanggal, pencairan.tanggal),
                )
                if baru != lama
            ]
            if diubah:
                pesan = "Pencairan berpotongan hanya boleh diubah metode dan keterangannya"
                raise serializers.ValidationError({nama: [pesan] for nama in diubah})
        if (nominal, tanggal, metode, keterangan) == (
            pencairan.nominal,
            pencairan.tanggal,
            pencairan.metode,
            pencairan.keterangan,
        ):
            raise serializers.ValidationError({"non_field_errors": ["Tidak ada data yang diubah"]})
        if tanggal < PencairanService.tanggal_edit_minimum(pencairan):
            raise serializers.ValidationError(
                {
                    "tanggal": [
                        "Tanggal pencairan hanya bisa dimundurkan maksimal "
                        f"{BATAS_MUNDUR_TANGGAL_PENCAIRAN_HARI} hari dari tanggal awal"
                    ]
                }
            )

        PencairanRevisi.objects.create(
            pencairan=pencairan,
            versi=pencairan.revisi.count() + 1,
            tanggal=pencairan.tanggal,
            nominal=pencairan.nominal,
            metode=pencairan.metode,
            keterangan=pencairan.keterangan,
            saldo_sebelum=pencairan.saldo_sebelum,
            saldo_sesudah=pencairan.saldo_sesudah,
            alasan=payload["alasan"],
            diubah_oleh=user,
        )
        if nominal != pencairan.nominal or tanggal != pencairan.tanggal:
            PencairanService._hitung_ulang_saldo(pencairan, nominal, tanggal)
        pencairan.nominal = nominal
        pencairan.tanggal = tanggal
        pencairan.metode = metode
        pencairan.keterangan = keterangan
        pencairan.save()
        return pencairan

    @staticmethod
    def dengan_info_revisi(queryset: QuerySet[Pencairan]) -> QuerySet[Pencairan]:
        """Annotate what `diperbarui` and `tanggal_edit_minimum` need, one query for all rows."""
        revisi = PencairanRevisi.objects.filter(pencairan=OuterRef("pk"))
        return queryset.annotate(
            ada_revisi=Exists(revisi),
            tanggal_versi_awal=Subquery(revisi.filter(versi=1).values("tanggal")[:1]),
        )

    @staticmethod
    def diperbarui(pencairan: Pencairan) -> bool:
        if hasattr(pencairan, "ada_revisi"):
            return bool(pencairan.ada_revisi)
        return pencairan.revisi.exists()

    @staticmethod
    def tanggal_edit_minimum(pencairan: Pencairan) -> datetime:
        """Earliest tanggal an edit may set, counted from the tanggal first recorded."""
        if hasattr(pencairan, "tanggal_versi_awal"):
            tanggal_awal = pencairan.tanggal_versi_awal or pencairan.tanggal
        else:
            versi_awal = pencairan.revisi.order_by("versi").first()
            tanggal_awal = versi_awal.tanggal if versi_awal else pencairan.tanggal
        return tanggal_awal - timedelta(days=BATAS_MUNDUR_TANGGAL_PENCAIRAN_HARI)

    @staticmethod
    def _hitung_ulang_saldo(pencairan: Pencairan, nominal: Decimal, tanggal: datetime) -> None:
        """Replay the nasabah's ledger from the earliest affected moment with the edited
        pencairan, rewriting every later pencairan snapshot and moving Saldo by the difference.

        Sets the edited pencairan's own snapshots; the caller saves it.
        """
        mulai = min(pencairan.tanggal, tanggal)
        ledger = {"bank_sampah_id": pencairan.bank_sampah_id, "nasabah_id": pencairan.nasabah_id}
        saldo = Saldo.objects.select_for_update().get(nasabah_id=pencairan.nasabah_id)
        lainnya = list(
            Pencairan.objects.select_for_update()
            .filter(tanggal__gte=mulai, **ledger)
            .exclude(pk=pencairan.pk)
        )
        setoran = list(
            Transaksi.objects.filter(
                tanggal__gte=mulai, status=Transaksi.Status.TERCATAT, **ledger
            ).values_list("id", "tanggal", "total_nilai")
        )

        # PILAH 1.0 opening balances have no transaksi behind them, so the replay starts
        # from a stored snapshot: the first pencairan at or after `mulai`, minus the
        # setoran ordered before it (a setoran at the same instant comes first).
        pertama = min([pencairan, *lainnya], key=lambda cair: (cair.tanggal, str(cair.pk)))
        awal = pertama.saldo_sebelum - sum(
            (nilai for _, waktu, nilai in setoran if waktu <= pertama.tanggal), Decimal(0)
        )

        def putar(
            nominal_ini: Decimal, tanggal_ini: datetime
        ) -> tuple[Decimal, dict[UUID, tuple[Decimal, Decimal]]]:
            peristiwa: list[tuple[datetime, int, str, Decimal, UUID | None]] = [
                (waktu, 0, str(id_), nilai, None) for id_, waktu, nilai in setoran
            ]
            peristiwa += [
                (cair.tanggal, 1, str(cair.pk), cair.nominal, cair.pk) for cair in lainnya
            ]
            peristiwa.append((tanggal_ini, 1, str(pencairan.pk), nominal_ini, pencairan.pk))
            saldo_berjalan = awal
            snapshot: dict[UUID, tuple[Decimal, Decimal]] = {}
            for _, _, _, nilai, pencairan_id in sorted(peristiwa, key=lambda item: item[:3]):
                if pencairan_id is None:
                    saldo_berjalan += nilai
                    continue
                if nilai > saldo_berjalan:
                    raise serializers.ValidationError(
                        {"nominal": ["Saldo nasabah tidak mencukupi untuk perubahan ini"]}
                    )
                # Per pencairan, not once at the end: legacy setoran can carry sen, and
                # recording dropped it at each pencairan too.
                sesudah = bulatkan_rupiah(saldo_berjalan - nilai)
                snapshot[pencairan_id] = (saldo_berjalan, sesudah)
                saldo_berjalan = sesudah
            return saldo_berjalan, snapshot

        akhir_lama, _ = putar(pencairan.nominal, pencairan.tanggal)
        akhir_baru, snapshot = putar(nominal, tanggal)
        berubah = []
        for cair in lainnya:
            if (cair.saldo_sebelum, cair.saldo_sesudah) != snapshot[cair.pk]:
                cair.saldo_sebelum, cair.saldo_sesudah = snapshot[cair.pk]
                berubah.append(cair)
        Pencairan.objects.bulk_update(berubah, ["saldo_sebelum", "saldo_sesudah"])
        pencairan.saldo_sebelum, pencairan.saldo_sesudah = snapshot[pencairan.pk]
        saldo.total_saldo += akhir_baru - akhir_lama
        saldo.save(update_fields=["total_saldo", "updated_at"])


_Dated = TypeVar("_Dated", bound=Model)  # Model imported at use site


class TransactionFilterService:
    @staticmethod
    def apply_period(
        queryset: QuerySet[_Dated],
        request: HttpRequest,
        default: str | None = "hari_ini",
    ) -> QuerySet[_Dated]:
        """Filter a queryset with a `tanggal` field by the `periode` query param.

        Without `periode`, [default] applies; `None` means no date filter.
        """
        periode = request.GET.get("periode", default)
        if periode is None or periode == "semua":
            return queryset
        today = timezone.localdate()
        if periode == "hari_ini":
            start, end = today, today
        elif periode == "minggu_ini":
            start, end = today - timedelta(days=today.weekday()), today
        elif periode == "bulan_ini":
            start, end = today.replace(day=1), today
        elif periode == "bulan_lalu":
            first_this_month = today.replace(day=1)
            last_previous_month = first_this_month - timedelta(days=1)
            start = last_previous_month.replace(day=1)
            end = last_previous_month
        elif periode in {"1_bulan", "3_bulan", "6_bulan", "12_bulan"}:
            months = int(periode.split("_")[0])
            month_index = today.year * 12 + today.month - 1 - months
            year, month_zero = divmod(month_index, 12)
            month = month_zero + 1
            start = date(year, month, min(today.day, monthrange(year, month)[1]))
            end = today
        elif periode == "custom":
            parsed_start = TransactionFilterService._parse_date(request.GET.get("dari_tanggal"))
            parsed_end = TransactionFilterService._parse_date(request.GET.get("sampai_tanggal"))
            if not parsed_start or not parsed_end:
                raise serializers.ValidationError(
                    {"error": "dari_tanggal dan sampai_tanggal wajib diisi"}
                )
            if parsed_end < parsed_start:
                raise ValueError("Tanggal akhir tidak boleh lebih awal dari tanggal awal")
            start, end = parsed_start, parsed_end
        else:
            raise serializers.ValidationError({"periode": "Periode tidak valid"})

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(end, time.max), tz)
        return queryset.filter(tanggal__range=(start_dt, end_dt))

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise serializers.ValidationError({"error": "Format tanggal harus YYYY-MM-DD"}) from exc


class BalanceService:
    """Running saldo for a nasabah: setoran added, pencairan subtracted."""

    @staticmethod
    def saldo_at(
        bank_sampah: BankSampah, nasabah_id: UUID, until: datetime, until_id: UUID
    ) -> Decimal:
        setoran = Transaksi.objects.filter(
            bank_sampah=bank_sampah, nasabah_id=nasabah_id, status=Transaksi.Status.TERCATAT
        ).filter(Q(tanggal__lt=until) | Q(tanggal=until, id__lte=until_id))
        # At an equal tanggal a pencairan is ordered after the setoran, so it is
        # excluded here; the export's merge below applies the same rule.
        pencairan = Pencairan.objects.filter(
            bank_sampah=bank_sampah, nasabah_id=nasabah_id, tanggal__lt=until
        )
        masuk = setoran.aggregate(total=Coalesce(Sum("total_nilai"), Decimal("0.00")))["total"]
        # A pencairan debits what left the saldo: the nominal plus any sen its
        # rounding dropped, so history lands on the stored Saldo.
        keluar = pencairan.aggregate(
            total=Coalesce(Sum(F("saldo_sebelum") - F("saldo_sesudah")), Decimal("0.00"))
        )["total"]
        return cast(Decimal, masuk - keluar)


# The server runs on UTC, but a pengurus reads the name on a clock in WIB.
ZONA_PENGURUS = ZoneInfo("Asia/Jakarta")

_BULAN_SINGKAT = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
)


class DraftTidakBisaDiubah(Exception):
    """The draft left `draft` status: a confirmed or cancelled one is final."""


class DraftPencairanService:
    @staticmethod
    def nama_default() -> str:
        sekarang = timezone.localtime(timezone=ZONA_PENGURUS)
        return (
            f"Pencairan {sekarang.day} {_BULAN_SINGKAT[sekarang.month - 1]} {sekarang.year}, "
            f"{sekarang:%H:%M}"
        )

    @staticmethod
    @transaction.atomic
    def buat_draft(user: User, payload: Mapping[str, Any]) -> DraftPencairan:
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        draft = DraftPencairan.objects.create(
            bank_sampah=bank,
            nama=DraftPencairanService._nama(payload.get("nama")),
            dibuat_oleh=user,
            diubah_oleh=user,
            potongan_jenis=payload.get("potongan_jenis", DraftPencairan.PotonganJenis.PERSEN),
            potongan_nilai=payload.get("potongan_nilai", Decimal(0)),
            jumlah_jenis=payload.get("jumlah_jenis") or "",
            jumlah_nilai=payload.get("jumlah_nilai"),
        )
        items = DraftPencairanService._sinkronkan_item(draft, payload["items"])
        DraftPencairanService._periksa_potongan(items)
        return draft

    @staticmethod
    @transaction.atomic
    def buat_batch(
        user: User, payload: Mapping[str, Any]
    ) -> tuple[DraftPencairan, list[dict[str, str]]]:
        """Draft for many nasabah at once; those that cannot be paid are skipped, with a reason.

        Each nasabah gets the whole saldo and the draft-level potongan. A nasabah that
        fails (not eligible, no saldo, potongan above the nominal) never blocks the rest.
        """
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        if payload["semua"]:
            # The candidates already carry their saldo, and by construction are eligible.
            layak = {nasabah.id: nasabah for nasabah in kandidat_pencairan(bank)}
            ids = list(layak)
            kunci = "semua"
        else:
            ids = list(dict.fromkeys(payload["nasabah_ids"]))
            layak = get_eligible_nasabah_map(bank, ids)
            kunci = "nasabah_ids"
        if len(ids) > DraftPencairan.MAKSIMAL_ITEM:
            # Checked before the per-nasabah work, so an oversized request stays cheap.
            raise serializers.ValidationError(
                {
                    kunci: [
                        f"Satu draft paling banyak {DraftPencairan.MAKSIMAL_ITEM} nasabah. "
                        "Pilih lebih sedikit atau bagi menjadi beberapa draft."
                    ]
                }
            )
        jenis = payload.get("potongan_jenis", DraftPencairan.PotonganJenis.PERSEN)
        nilai = payload.get("potongan_nilai", Decimal(0))
        items: list[dict[str, Any]] = []
        dilewati: list[dict[str, str]] = []
        for nasabah_id in ids:
            alasan = DraftPencairanService._alasan_dilewati(layak.get(nasabah_id), jenis, nilai)
            if alasan:
                dilewati.append({"nasabah_id": str(nasabah_id), "alasan": alasan})
            else:
                items.append({"nasabah_id": nasabah_id, "metode": payload["metode"]})
        if not items:
            raise serializers.ValidationError(
                {"nasabah_ids": ["Tidak ada nasabah yang dapat dicairkan"], "dilewati": dilewati}
            )
        draft = DraftPencairanService.buat_draft(user, {**payload, "items": items})
        return draft, dilewati

    @staticmethod
    def _alasan_dilewati(nasabah: Nasabah | None, jenis: str, nilai: Decimal) -> str:
        if nasabah is None:
            return _NASABAH_TIDAK_AKTIF
        nominal = DraftPencairanService._saldo_tersedia(nasabah)
        if nominal <= 0:
            return "Saldo nasabah kosong"
        if hitung_potongan(nominal, jenis, nilai) > nominal:
            return "Potongan melebihi nominal pencairan"
        return ""

    @staticmethod
    @transaction.atomic
    def ubah_draft(user: User, draft: DraftPencairan, payload: Mapping[str, Any]) -> DraftPencairan:
        """Apply an edit; `items`, when sent, is the full desired list (omitted ones are removed).

        `draft` comes from the caller's bank-scoped queryset; it is re-read under lock.
        """
        draft = DraftPencairanService._kunci_draft(draft)
        if "nama" in payload:
            draft.nama = DraftPencairanService._nama(payload["nama"])
        if "potongan_jenis" in payload:
            draft.potongan_jenis = payload["potongan_jenis"]
            draft.potongan_nilai = payload["potongan_nilai"]
        if "jumlah_jenis" in payload:
            draft.jumlah_jenis = payload["jumlah_jenis"] or ""
            draft.jumlah_nilai = payload.get("jumlah_nilai")
        draft.diubah_oleh = user
        draft.save()
        if "items" in payload:
            items = DraftPencairanService._sinkronkan_item(draft, payload["items"])
        else:
            items = list(draft.items.select_related("draft"))
        DraftPencairanService._periksa_potongan(items)
        return draft

    @staticmethod
    @transaction.atomic
    def konfirmasi_draft(user: User, draft: DraftPencairan) -> DraftPencairan:
        """Record the payment: debit every item and write its pencairan, all or nothing.

        Items are re-validated against the saldo as it is now, since it may have moved
        since the draft was made. Every failing item is reported before anything is written.
        """
        draft = DraftPencairanService._kunci_draft(draft)
        items = list(draft.items.select_related("nasabah", "draft"))
        ids = sorted(item.nasabah_id for item in items)
        # Lock in id order so two confirmations sharing nasabah cannot deadlock.
        nasabah_terkunci = {
            n.id: n for n in Nasabah.objects.select_for_update().filter(id__in=ids).order_by("id")
        }
        saldo_terkunci = {
            s.nasabah_id: s
            for s in Saldo.objects.select_for_update()
            .filter(nasabah_id__in=ids)
            .order_by("nasabah_id")
        }
        galat: dict[str, list[str]] = {}
        for index, item in enumerate(items):
            nasabah = nasabah_terkunci[item.nasabah_id]
            saldo = saldo_terkunci.get(item.nasabah_id)
            if not (nasabah.is_active and nasabah.status == Nasabah.Status.APPROVED):
                galat[f"items[{index}].nasabah_id"] = [_NASABAH_TIDAK_AKTIF]
            elif saldo is None or item.nominal > saldo.total_saldo:
                galat[f"items[{index}].nominal"] = [_SALDO_KURANG]
        if galat:
            raise serializers.ValidationError(galat)
        tanggal = timezone.now()
        for item in items:
            item.saldo_sebelum = saldo_terkunci[item.nasabah_id].total_saldo
            item.save(update_fields=["saldo_sebelum", "updated_at"])
            PencairanService.realisasi(
                user=user,
                nasabah=nasabah_terkunci[item.nasabah_id],
                saldo=saldo_terkunci[item.nasabah_id],
                nominal=item.nominal,
                metode=item.metode,
                tanggal=tanggal,
                keterangan=f"Draft: {draft.nama}"[:255],
                potongan=item.potongan,
                draft=draft,
            )
        draft.status = DraftPencairan.Status.DIKONFIRMASI
        draft.diubah_oleh = user
        draft.save(update_fields=["status", "diubah_oleh", "updated_at"])
        return draft

    @staticmethod
    @transaction.atomic
    def batalkan_draft(user: User, draft: DraftPencairan) -> DraftPencairan:
        draft = DraftPencairanService._kunci_draft(draft)
        draft.status = DraftPencairan.Status.DIBATALKAN
        draft.diubah_oleh = user
        draft.save(update_fields=["status", "diubah_oleh", "updated_at"])
        return draft

    @staticmethod
    def _kunci_draft(draft: DraftPencairan) -> DraftPencairan:
        """Re-read under lock and refuse anything no longer in `draft` status."""
        draft = DraftPencairan.objects.select_for_update().get(pk=draft.pk)
        if draft.status != DraftPencairan.Status.DRAFT:
            raise DraftTidakBisaDiubah(f"Draft sudah {draft.get_status_display().lower()}")
        return draft

    @staticmethod
    def _nama(nama: str | None) -> str:
        return (nama or "").strip() or DraftPencairanService.nama_default()

    @staticmethod
    def _sinkronkan_item(
        draft: DraftPencairan, payload_items: list[Mapping[str, Any]]
    ) -> list[DraftPencairanItem]:
        """Upsert items by nasabah in request order and drop the ones not sent.

        A field the request leaves out keeps its stored value; a null potongan pair
        clears the item's override so it follows the draft default again.
        """
        bank = draft.bank_sampah
        ada = {item.nasabah_id: item for item in draft.items.select_related("draft")}
        layak = get_eligible_nasabah_map(bank, [data["nasabah_id"] for data in payload_items])
        hasil: list[DraftPencairanItem] = []
        for index, data in enumerate(payload_items):
            nasabah = layak.get(data["nasabah_id"])
            if nasabah is None:
                raise serializers.ValidationError(
                    {f"items[{index}].nasabah_id": [_NASABAH_TIDAK_AKTIF]}
                )
            current = ada.pop(nasabah.id, None)
            item = current or DraftPencairanItem(draft=draft, nasabah=nasabah)
            diminta = data.get("nominal", current.nominal if current else None)
            item.nominal = DraftPencairanService._nominal(nasabah, diminta, index)
            item.metode = data.get("metode", current.metode if current else Pencairan.Metode.TUNAI)
            if "potongan_jenis" in data:
                item.potongan_jenis = data["potongan_jenis"] or ""
                item.potongan_nilai = data.get("potongan_nilai")
            item.save()
            hasil.append(item)
        for sisa in ada.values():
            sisa.delete()
        return hasil

    @staticmethod
    def _periksa_potongan(items: list[DraftPencairanItem]) -> None:
        """Reject a draft whose effective potongan on any item exceeds its nominal.

        `items` keeps the request order so a reported index matches the client's list.
        """
        for index, item in enumerate(items):
            if item.potongan > item.nominal:
                raise serializers.ValidationError(
                    {f"items[{index}].potongan_nilai": ["Potongan melebihi nominal pencairan"]}
                )

    @staticmethod
    def _saldo_tersedia(nasabah: Nasabah) -> Decimal:
        """Whole rupiah the nasabah holds; a nasabah who never transacted has no Saldo row."""
        try:
            return bulatkan_rupiah(nasabah.saldo.total_saldo)
        except ObjectDoesNotExist:
            return Decimal(0)

    @staticmethod
    def _nominal(nasabah: Nasabah, diminta: Decimal | None, index: int) -> Decimal:
        """Requested nominal, or the whole saldo; never above the saldo, never zero."""
        tersedia = DraftPencairanService._saldo_tersedia(nasabah)
        nominal = tersedia if diminta is None else diminta
        if nominal <= 0:
            raise serializers.ValidationError({f"items[{index}].nominal": ["Saldo nasabah kosong"]})
        if nominal > tersedia:
            raise serializers.ValidationError({f"items[{index}].nominal": [_SALDO_KURANG]})
        return nominal
