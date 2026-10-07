from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any, TypeVar, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Exists, F, Max, Model, OuterRef, Q, QuerySet, Subquery, Sum
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
    User,
)
from apps.nasabah.api import get_eligible_nasabah, get_locked_nasabah, kandidat_pencairan
from apps.waste_catalog.api import get_active_jenis
from shared_kernel.kalkulasi import (
    bulatkan_rupiah,
    harga_berlaku,
    hitung_potongan,
    hitung_subtotal,
    total_setoran,
)


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
            raise serializers.ValidationError(
                {"nasabah_id": ["Nasabah tidak ditemukan atau tidak aktif"]}
            )

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
            harga = harga_berlaku(jenis)
            if harga <= 0:
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


# ponytail: pencairan edit-window constant (PIL-2xx), shared with tests.
BATAS_MUNDUR_TANGGAL_PENCAIRAN_HARI = 7


class PencairanService:
    @staticmethod
    @transaction.atomic
    def create_pencairan(user: User, payload: Mapping[str, Any]) -> Pencairan:
        bank = user.bank_sampah
        assert bank is not None  # ponytail: views gate on IsActivePengelola
        nasabah = get_locked_nasabah(bank, payload["nasabah_id"])
        if not nasabah:
            raise serializers.ValidationError(
                {"nasabah_id": ["Nasabah tidak ditemukan atau tidak aktif"]}
            )

        tanggal = payload.get("tanggal") or timezone.now()
        # The balance check below reads the current saldo, which is only the saldo
        # at `tanggal` when nothing was recorded after it.
        aktivitas = [
            model.objects.filter(bank_sampah=bank, nasabah=nasabah).aggregate(
                terakhir=Max("tanggal")
            )["terakhir"]
            for model in (Transaksi, Pencairan)
        ]
        terakhir = max((value for value in aktivitas if value), default=None)
        if terakhir and tanggal < terakhir:
            raise serializers.ValidationError(
                {"tanggal": ["Tanggal pencairan tidak boleh sebelum transaksi terakhir nasabah"]}
            )

        saldo, _ = Saldo.objects.select_for_update().get_or_create(nasabah=nasabah)
        nominal = payload["nominal"]
        if nominal > saldo.total_saldo:
            raise serializers.ValidationError({"nominal": ["Saldo nasabah tidak mencukupi"]})
        return PencairanService.realisasi(
            user=user,
            nasabah=nasabah,
            saldo=saldo,
            nominal=nominal,
            metode=payload["metode"],
            tanggal=tanggal,
            keterangan=payload.get("keterangan") or "",
        )

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
            Transaksi.objects.filter(tanggal__gte=mulai, **ledger).values_list(
                "id", "tanggal", "total_nilai"
            )
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
                sesudah = (saldo_berjalan - nilai).quantize(Decimal(1), rounding=ROUND_DOWN)
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
        if periode is None:
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
            return queryset

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
        setoran = Transaksi.objects.filter(bank_sampah=bank_sampah, nasabah_id=nasabah_id).filter(
            Q(tanggal__lt=until) | Q(tanggal=until, id__lte=until_id)
        )
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
            ids = [nasabah.id for nasabah in kandidat_pencairan(bank)]
        else:
            ids = list(dict.fromkeys(payload["nasabah_ids"]))
        if len(ids) > DraftPencairan.MAKSIMAL_ITEM:
            # Checked before the per-nasabah work, so an oversized request stays cheap.
            raise serializers.ValidationError(
                {
                    "nasabah_ids": [
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
            alasan = DraftPencairanService._alasan_dilewati(bank, nasabah_id, jenis, nilai)
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
    def _alasan_dilewati(bank: BankSampah, nasabah_id: UUID, jenis: str, nilai: Decimal) -> str:
        nasabah = get_eligible_nasabah(bank, nasabah_id)
        if nasabah is None:
            return "Nasabah tidak ditemukan atau tidak aktif"
        saldo = Saldo.objects.filter(nasabah=nasabah).first()
        nominal = bulatkan_rupiah(saldo.total_saldo) if saldo else Decimal(0)
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
        hasil: list[DraftPencairanItem] = []
        for index, data in enumerate(payload_items):
            nasabah = get_eligible_nasabah(bank, data["nasabah_id"])
            if nasabah is None:
                raise serializers.ValidationError(
                    {f"items[{index}].nasabah_id": ["Nasabah tidak ditemukan atau tidak aktif"]}
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
    def _nominal(nasabah: Nasabah, diminta: Decimal | None, index: int) -> Decimal:
        """Requested nominal, or the whole saldo; never above the saldo, never zero."""
        saldo = Saldo.objects.filter(nasabah=nasabah).first()
        tersedia = bulatkan_rupiah(saldo.total_saldo) if saldo else Decimal(0)
        nominal = tersedia if diminta is None else diminta
        if nominal <= 0:
            raise serializers.ValidationError({f"items[{index}].nominal": ["Saldo nasabah kosong"]})
        if nominal > tersedia:
            raise serializers.ValidationError(
                {f"items[{index}].nominal": ["Saldo nasabah tidak mencukupi"]}
            )
        return nominal
