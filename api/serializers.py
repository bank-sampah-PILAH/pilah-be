"""Serializers for views still living in api.views (PIL-283+ additions).

ponytail: PR48 ports these into apps.* contexts as they stabilize.
"""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Mapping

from django.db.models import Model
from rest_framework import serializers

from api.models import (
    BankSampah,
    DetailTransaksi,
    JadwalKegiatan,
    Nasabah,
    NasabahApprovalLog,
    Pencairan,
    PencairanRevisi,
    Saldo,
    Transaksi,
    User,
)
from api.kalkulasi import format_ribuan


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
