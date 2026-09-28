"""Serializers for views still living in api.views (PIL-283+ additions).

ponytail: PR48 ports these into apps.* contexts as they stabilize.
"""
from datetime import date, datetime, time

from django.utils import timezone
from decimal import Decimal
from typing import Any, Mapping, cast

from django.db.models import Model
from rest_framework import serializers

from api.models import (
    BankSampah,
    DetailTransaksi,
    JadwalKegiatan,
    JenisSampah,
    Nasabah,
    NasabahApprovalLog,
    Pencairan,
    PencairanRevisi,
    Saldo,
    Transaksi,
    User,
)
from api.kalkulasi import bulatkan_rupiah, format_ribuan
from apps.ledger.services import BalanceService, PencairanService
from apps.membership.serializers import NasabahSerializer
from shared_kernel.validators import get_initials


def _validate_tanggal_pencairan(value: datetime) -> datetime:
    if value > timezone.now():
        raise serializers.ValidationError("Tanggal pencairan tidak boleh di masa depan")
    return value


def _validate_nominal_pencairan(value: Decimal) -> Decimal:
    if value <= 0:
        raise serializers.ValidationError("Nominal harus lebih dari nol")
    if value != value.to_integral_value():
        raise serializers.ValidationError("Nominal harus dalam rupiah bulat tanpa desimal")
    return value

class PencairanCreateSerializer(serializers.Serializer[Any]):
    nasabah_id = serializers.UUIDField(required=True)
    nominal = serializers.DecimalField(max_digits=14, decimal_places=2, required=True)
    metode = serializers.ChoiceField(choices=Pencairan.Metode.choices, required=True)
    tanggal = serializers.DateTimeField(required=False)
    keterangan = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255
    )

    def validate_nominal(self, value: Decimal) -> Decimal:
        return _validate_nominal_pencairan(value)

    def validate_tanggal(self, value: datetime) -> datetime:
        return _validate_tanggal_pencairan(value)




class PencairanEditSerializer(serializers.Serializer[Any]):
    nominal = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    metode = serializers.ChoiceField(choices=Pencairan.Metode.choices, required=False)
    tanggal = serializers.DateTimeField(required=False)
    keterangan = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255
    )
    alasan = serializers.CharField(
        required=True,
        max_length=255,
        error_messages={
            "required": "Alasan perubahan wajib diisi",
            "blank": "Alasan perubahan wajib diisi",
        },
    )

    def validate_nominal(self, value: Decimal) -> Decimal:
        return _validate_nominal_pencairan(value)

    def validate_tanggal(self, value: datetime) -> datetime:
        return _validate_tanggal_pencairan(value)




class PencairanDetailSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")
    bank_sampah_id = serializers.UUIDField(source="bank_sampah.id")
    bank_sampah_nama = serializers.CharField(source="bank_sampah.nama")
    dicatat_oleh = serializers.UUIDField(source="dicatat_oleh.id")
    dicatat_oleh_nama = serializers.CharField(source="dicatat_oleh.nama")
    diperbarui = serializers.SerializerMethodField()
    tanggal_edit_minimum = serializers.SerializerMethodField()

    class Meta:
        model = Pencairan
        fields = [
            "id",
            "nasabah_id",
            "nasabah_nama",
            "bank_sampah_id",
            "bank_sampah_nama",
            "dicatat_oleh",
            "dicatat_oleh_nama",
            "tanggal",
            "nominal",
            "metode",
            "keterangan",
            "status",
            "saldo_sebelum",
            "saldo_sesudah",
            "diperbarui",
            "tanggal_edit_minimum",
            "created_at",
        ]

    def get_diperbarui(self, obj: Pencairan) -> bool:
        return PencairanService.diperbarui(obj)

    def get_tanggal_edit_minimum(self, obj: Pencairan) -> str:
        return serializers.DateTimeField().to_representation(
            PencairanService.tanggal_edit_minimum(obj)
        )




class PencairanRevisiSerializer(serializers.ModelSerializer[Model]):
    diubah_oleh = serializers.UUIDField(source="diubah_oleh.id")
    diubah_oleh_nama = serializers.CharField(source="diubah_oleh.nama")

    class Meta:
        model = PencairanRevisi
        fields = [
            "versi",
            "tanggal",
            "nominal",
            "metode",
            "keterangan",
            "saldo_sebelum",
            "saldo_sesudah",
            "alasan",
            "diubah_oleh",
            "diubah_oleh_nama",
            "diubah_pada",
        ]




class GoogleRegistrationSerializer(serializers.Serializer[Any]):
    registration_token = serializers.CharField(required=True)
    role = serializers.ChoiceField(choices=User.GOOGLE_REGISTRATION_ROLES)




class NasabahSelfRegistrationSerializer(serializers.Serializer[Any]):
    """Input for a calon nasabah applying to join a bank sampah (PIL-204).

    Only `bank_sampah_id` is asked for here: `nama`, `jenis_kelamin`,
    `tanggal_lahir`, `no_hp`, and `alamat` were already collected on the
    shared `complete_profile` onboarding step and are copied from the User
    by the service.
    """

    bank_sampah_id = serializers.UUIDField()
    # Only meaningful when reapplying after a rejection (PIL-232's appeal
    # action) — ignored on a first-time application, nothing to appeal yet.
    pesan = serializers.CharField(required=False, allow_blank=True, default="")




class NasabahSelfBankSampahSerializer(serializers.ModelSerializer[Model]):
    """The bank sampah facet of a nasabah's own membership listing.

    Deliberately smaller than `BankSampahSerializer` — a nasabah viewing
    their own membership has no use for the owning pengelola's contact
    details, only enough to identify which bank the row belongs to.
    """

    class Meta:
        model = BankSampah
        fields = ["id", "nama", "kota", "alamat"]
        read_only_fields = fields




class NasabahSelfApprovalLogSerializer(serializers.ModelSerializer[Model]):
    """One decision entry in a membership row's approval history, as shown
    to the nasabah themself (PIL-232). Deliberately smaller than
    `NasabahApprovalLogSerializer` (used pengurus-side), which also exposes
    `id`, `nasabah_id`, and `pengurus_email` that a nasabah has no use for.
    """

    class Meta:
        model = NasabahApprovalLog
        fields = ["status", "catatan", "created_at"]
        read_only_fields = fields




class NasabahSelfViewSerializer(serializers.ModelSerializer[Model]):
    """A calon/active nasabah's own membership row (PIL-204's beranda-first
    onboarding): status, and — only while rejected — the pengurus's reason,
    so the beranda can show it and let the user appeal by reapplying.
    """

    bank_sampah = NasabahSelfBankSampahSerializer(read_only=True)
    alasan_penolakan = serializers.SerializerMethodField()
    riwayat_persetujuan = serializers.SerializerMethodField()

    class Meta:
        model = Nasabah
        fields = [
            "id",
            "bank_sampah",
            "status",
            "is_active",
            "alasan_penolakan",
            "riwayat_persetujuan",
        ]
        read_only_fields = fields

    def get_alasan_penolakan(self, obj: Nasabah) -> str | None:
        if obj.status != Nasabah.Status.REJECTED:
            return None
        log = obj.approval_logs.filter(status=NasabahApprovalLog.Status.REJECTED).first()
        return log.catatan if log else None

    def get_riwayat_persetujuan(self, obj: Nasabah) -> Any:
        return NasabahSelfApprovalLogSerializer(obj.approval_logs.all(), many=True).data


class NasabahDetailSerializer(NasabahSerializer):
    ringkasan_transaksi = serializers.SerializerMethodField()

    class Meta(NasabahSerializer.Meta):
        fields = NasabahSerializer.Meta.fields + ["ringkasan_transaksi"]

    def get_ringkasan_transaksi(self, obj: Any) -> Any:
        items = DetailTransaksi.objects.filter(transaksi__nasabah=obj)
        total_kg = sum((item.berat for item in items), Decimal(0))
        last_transaction = obj.transaksi.order_by("-tanggal").first()
        return {
            "jumlah_transaksi": obj.transaksi.count(),
            "total_kg": total_kg,
            "tanggal_transaksi_terakhir": last_transaction.tanggal if last_transaction else None,
        }


class StatusSerializer(serializers.Serializer[Any]):
    is_active = serializers.BooleanField(required=True)


class JenisSampahSerializer(serializers.ModelSerializer[Model]):
    satuan = serializers.SerializerMethodField()
    kode = serializers.CharField(source="nomor", required=True, max_length=20)

    class Meta:
        model = JenisSampah
        fields = [
            "id",
            "kode",
            "nama_sampah",
            "kategori",
            "deskripsi",
            "satuan",
            "harga_per_kg",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["id", "satuan", "is_active", "updated_at"]

    def validate_kode(self, value: Any) -> Any:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Kode sampah wajib diisi")
        return value

    def validate_nama_sampah(self, value: Any) -> Any:
        value = value.strip()
        if not 2 <= len(value) <= 50:
            raise serializers.ValidationError("Nama jenis sampah wajib diisi")
        return value

    def validate_deskripsi(self, value: Any) -> Any:
        if value and len(value) > 200:
            raise serializers.ValidationError("Deskripsi maksimal 200 karakter")
        return value

    def validate_harga_per_kg(self, value: Any) -> Any:
        if value <= 0:
            raise serializers.ValidationError("Harga harus berupa angka positif")
        if value >= Decimal(1000000000):
            raise serializers.ValidationError("Harga maksimal 9 digit")
        return value

    def get_satuan(self, obj: Any) -> Any:
        return "kg"


# Batas berat dari PM (PIL-224): di atas angka ini hampir pasti salah ketik.
BERAT_MAKS_PER_ITEM = Decimal(500)
BERAT_MAKS_PER_SETORAN = Decimal(1000)


class TransactionItemInputSerializer(serializers.Serializer[Any]):
    jenis_sampah_id = serializers.UUIDField(required=True)
    berat = serializers.DecimalField(
        max_digits=10,
        decimal_places=3,
        min_value=Decimal("0.001"),
        max_value=BERAT_MAKS_PER_ITEM,
        error_messages={
            "max_value": f"Berat maksimal {format_ribuan(BERAT_MAKS_PER_ITEM)} kg untuk satu jenis sampah"
        },
    )


class TransactionCreateSerializer(serializers.Serializer[Any]):
    nasabah_id = serializers.UUIDField(required=True)
    items = TransactionItemInputSerializer(many=True, required=True)
    catatan = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_items(self, value: Any) -> Any:
        if not value:
            raise serializers.ValidationError("Minimal 1 item setoran diperlukan")
        if sum(item["berat"] for item in value) > BERAT_MAKS_PER_SETORAN:
            raise serializers.ValidationError(
                f"Total berat satu setoran maksimal {format_ribuan(BERAT_MAKS_PER_SETORAN)} kg"
            )
        return value

    def validate(self, attrs: Any) -> Any:
        # Harga hanya boleh berasal dari master jenis sampah. Menerima harga
        # dari client membuat nilai setoran bisa diatur dari luar sistem, jadi
        # request yang masih mengirimnya ditolak, bukan diabaikan diam-diam.
        raw_items = self.initial_data.get("items")
        if isinstance(raw_items, list):
            item_errors: list[dict[str, list[str]]] = [
                {"harga_per_kg": ["Harga diambil dari master jenis sampah dan tidak dapat dikirim"]}
                if isinstance(item, dict) and "harga_per_kg" in item
                else {}
                for item in raw_items
            ]
            if any(item_errors):
                raise serializers.ValidationError({"items": item_errors})
        return attrs


class DetailTransaksiSerializer(serializers.ModelSerializer[Model]):
    jenis_sampah_id = serializers.UUIDField()

    class Meta:
        model = DetailTransaksi
        fields = [
            "id",
            "jenis_sampah_id",
            "nama_sampah_snapshot",
            "harga_snapshot",
            "berat",
            "subtotal",
        ]


class TransactionDetailSerializer(serializers.ModelSerializer[Transaksi]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")
    bank_sampah_id = serializers.UUIDField(source="bank_sampah.id")
    dicatat_oleh = serializers.UUIDField(source="dicatat_oleh.id")
    items = DetailTransaksiSerializer(many=True)
    saldo_setelah_transaksi = serializers.SerializerMethodField()

    class Meta:
        model = Transaksi
        fields = [
            "id",
            "nasabah_id",
            "nasabah_nama",
            "bank_sampah_id",
            "dicatat_oleh",
            "tanggal",
            "total_nilai",
            "catatan",
            "status_wa",
            "items",
            "saldo_setelah_transaksi",
        ]

    def get_saldo_setelah_transaksi(self, obj: Any) -> Any:
        return bulatkan_rupiah(
            BalanceService.saldo_at(obj.bank_sampah, obj.nasabah_id, obj.tanggal, obj.id)
        )


class TransactionListSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")
    nasabah_inisial = serializers.SerializerMethodField()
    jenis_sampah_utama = serializers.SerializerMethodField()
    total_berat_kg = serializers.SerializerMethodField()
    dicatat_oleh = serializers.UUIDField(source="dicatat_oleh.id")

    class Meta:
        model = Transaksi
        fields = [
            "id",
            "nasabah_id",
            "nasabah_nama",
            "nasabah_inisial",
            "jenis_sampah_utama",
            "total_berat_kg",
            "total_nilai",
            "tanggal",
            "status_wa",
            "dicatat_oleh",
        ]

    def get_nasabah_inisial(self, obj: Any) -> Any:
        return get_initials(obj.nasabah.nama)

    def get_jenis_sampah_utama(self, obj: Any) -> Any:
        item = max(obj.items.all(), key=lambda detail: detail.berat, default=None)
        return item.nama_sampah_snapshot if item else None

    def get_total_berat_kg(self, obj: Any) -> Any:
        return sum((item.berat for item in obj.items.all()), Decimal(0))


class SaldoSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")

    class Meta:
        model = Saldo
        fields = ["nasabah_id", "nasabah_nama", "total_saldo", "updated_at"]


class WATemplateSerializer(serializers.Serializer[Any]):
    template = serializers.CharField(required=True, allow_blank=False)


class JadwalKegiatanSerializer(serializers.ModelSerializer[Model]):
    bank_sampah_id = serializers.UUIDField(source="bank_sampah.id", read_only=True)
    dibuat_oleh_id = serializers.UUIDField(source="dibuat_oleh.id", read_only=True)
    penerima_ids = serializers.PrimaryKeyRelatedField(
        source="penerima",
        queryset=Nasabah.objects.all(),
        many=True,
        required=False,
    )
    peringatan_jadwal_bertumpuk = serializers.SerializerMethodField()

    class Meta:
        model = JadwalKegiatan
        fields = [
            "id",
            "bank_sampah_id",
            "dibuat_oleh_id",
            "jenis_kegiatan",
            "mulai_pada",
            "selesai_pada",
            "lokasi",
            "keterangan",
            "cakupan_penerima",
            "penerima_ids",
            "status",
            "peringatan_jadwal_bertumpuk",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "bank_sampah_id",
            "dibuat_oleh_id",
            "status",
            "peringatan_jadwal_bertumpuk",
            "created_at",
            "updated_at",
        ]

    def get_fields(self) -> dict[str, serializers.Field[Any, Any, Any, Any]]:
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if getattr(user, "role", None) == User.Role.NASABAH:
            fields.pop("penerima_ids", None)
            fields.pop("peringatan_jadwal_bertumpuk", None)
            return fields

        bank = getattr(user, "bank_sampah", None)
        eligible_recipients = (
            Nasabah.objects.filter(
                bank_sampah=bank,
                is_active=True,
                status=Nasabah.Status.APPROVED,
            )
            if bank is not None
            else Nasabah.objects.none()
        )
        fields["penerima_ids"] = serializers.PrimaryKeyRelatedField(
            source="penerima",
            queryset=eligible_recipients,
            many=True,
            required=False,
        )
        return fields

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = cast(JadwalKegiatan | None, self.instance)
        mulai_pada = attrs.get("mulai_pada", getattr(instance, "mulai_pada", None))
        selesai_pada = attrs.get("selesai_pada", getattr(instance, "selesai_pada", None))
        if mulai_pada and selesai_pada and selesai_pada <= mulai_pada:
            raise serializers.ValidationError(
                {"selesai_pada": "Waktu selesai harus setelah waktu mulai"}
            )

        request = self.context.get("request")
        bank = getattr(getattr(request, "user", None), "bank_sampah", None)
        penerima = attrs.get("penerima")
        cakupan = attrs.get(
            "cakupan_penerima",
            getattr(instance, "cakupan_penerima", JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH),
        )
        if penerima and any(item.bank_sampah_id != getattr(bank, "id", None) for item in penerima):
            raise serializers.ValidationError(
                {"penerima_ids": "Penerima harus berasal dari bank sampah yang sama"}
            )
        if cakupan == JadwalKegiatan.CakupanPenerima.NASABAH_TERPILIH and not penerima:
            if "penerima" in attrs or instance is None or not instance.penerima.exists():
                raise serializers.ValidationError({"penerima_ids": "Pilih minimal satu nasabah"})
        if cakupan == JadwalKegiatan.CakupanPenerima.SEMUA_NASABAH:
            attrs["penerima"] = []
        return attrs

    def get_peringatan_jadwal_bertumpuk(self, obj: JadwalKegiatan) -> bool:
        annotated = getattr(obj, "_peringatan_jadwal_bertumpuk", None)
        if annotated is not None:
            return bool(annotated)
        return (
            JadwalKegiatan.objects.filter(
                bank_sampah=obj.bank_sampah,
                lokasi__iexact=obj.lokasi,
                mulai_pada__lt=obj.selesai_pada,
                selesai_pada__gt=obj.mulai_pada,
            )
            .exclude(pk=obj.pk)
            .exclude(status=JadwalKegiatan.Status.DIBATALKAN)
            .exists()
        )


class BankSampahDirectorySerializer(serializers.ModelSerializer[Model]):
    """Public-facing listing for the calon-nasabah bank-sampah picker.

    Deliberately excludes `pengelola`, `no_hp_pic`, and `wa_gateway_token` —
    `BankSampahSerializer` carries those for the owning pengelola, not for a
    prospective member browsing banks to join.
    """

    class Meta:
        model = BankSampah
        fields = ["id", "nama", "alamat", "kota", "foto_logo"]
        read_only_fields = fields

# ponytail: canonical home is apps.organization.serializers.
from apps.organization.serializers import BankSampahApprovalListSerializer  # noqa: F401
