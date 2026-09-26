from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.signing import TimestampSigner
from django.db.models import Model, Q, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from api.models import (
    BankSampah,
    BankSampahApprovalLog,
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    NasabahApprovalLog,
    Saldo,
    Transaksi,
    User,
)
from api.validators import normalize_indonesian_phone

# ponytail: compat shims — canonical homes are apps.*.serializers.
from apps.identity.serializers import AuthUserSerializer  # noqa: F401
from apps.ledger.serializers import TransactionListSerializer  # noqa: F401
from apps.notify.serializers import WATemplateSerializer  # noqa: F401


class BankSampahSerializer(serializers.ModelSerializer[Model]):
    pengelola = serializers.SerializerMethodField()

    class Meta:
        model = BankSampah
        fields = [
            "id",
            "nama",
            "alamat",
            "kota",
            "no_hp_pic",
            "wa_gateway_token",
            "foto_logo",
            "status",
            "is_active",
            "created_at",
            "pengelola",
        ]
        read_only_fields = ["id", "status", "is_active", "created_at", "pengelola"]

    def validate_nama(self, value: Any) -> Any:
        if len(value.strip()) < 3:
            raise serializers.ValidationError("Nama bank sampah wajib diisi")
        return value.strip()

    def validate_no_hp_pic(self, value: Any) -> Any:
        try:
            return normalize_indonesian_phone(value)
        except serializers.ValidationError as err:
            raise serializers.ValidationError("Format nomor tidak valid") from err

    def validate_foto_logo(self, value: Any) -> Any:
        return validate_image_upload(value, "Foto logo")

    def get_pengelola(self, obj: Any) -> Any:
        user = obj.users.filter(role="pengelola", is_active=True).first()
        if not user:
            return None
        return {"id": str(user.id), "nama": user.nama, "email": user.email}


class UserProfileSerializer(serializers.ModelSerializer[Model]):
    class Meta:
        model = User
        fields = [
            "id",
            "nama",
            "email",
            "no_hp",
            "jenis_kelamin",
            "tanggal_lahir",
            "role",
            "is_profile_complete",
            "is_primary_pengelola",
        ]
        read_only_fields = ["id", "email", "role", "is_profile_complete", "is_primary_pengelola"]

    def validate_nama(self, value: Any) -> Any:
        value = value.strip()
        if not 3 <= len(value) <= 100:
            raise serializers.ValidationError("Nama minimal 3 karakter")
        return value

    def validate_no_hp(self, value: Any) -> Any:
        return normalize_indonesian_phone(value)

    def validate_jenis_kelamin(self, value: Any) -> Any:
        if value not in [User.Gender.MALE, User.Gender.FEMALE]:
            raise serializers.ValidationError("Jenis kelamin wajib dipilih")
        return value

    def validate_tanggal_lahir(self, value: Any) -> Any:
        if value > timezone.localdate():
            raise serializers.ValidationError("Tanggal lahir tidak boleh di masa depan")
        return value


class BankSampahRegistrationSerializer(serializers.Serializer[Any]):
    nama = serializers.CharField(required=True, max_length=100)
    alamat = serializers.CharField(required=True)
    kota = serializers.CharField(required=False, allow_blank=True, max_length=100)
    no_hp_pic = serializers.CharField(required=True)
    foto_kegiatan = serializers.FileField(required=True)

    def validate_nama(self, value: Any) -> Any:
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Nama Bank Sampah wajib diisi (minimal 3 karakter)")
        return value

    def validate_alamat(self, value: Any) -> Any:
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError(
                "Alamat lengkap wajib diisi untuk keperluan verifikasi lokasi"
            )
        return value

    def validate_no_hp_pic(self, value: Any) -> Any:
        return normalize_indonesian_phone(value)

    def validate_foto_kegiatan(self, value: Any) -> Any:
        if not value:
            raise serializers.ValidationError("Foto kegiatan wajib diunggah sebagai bukti validasi")
        return validate_image_upload(value, "Foto kegiatan")


class TeamMemberSerializer(serializers.ModelSerializer[Model]):
    is_current_user = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "nama",
            "email",
            "role",
            "is_primary_pengelola",
            "is_current_user",
            "created_at",
        ]

    def get_is_current_user(self, obj: Any) -> Any:
        request = self.context.get("request")
        return bool(request and request.user.id == obj.id)


class InviteAcceptSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(required=False, allow_blank=True)
    invite_token = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs: Mapping[str, Any]) -> dict[str, Any]:
        mutable = dict(attrs)
        token = mutable.get("token") or mutable.get("invite_token")
        if not token:
            raise serializers.ValidationError({"token": ["Token undangan wajib diisi"]})
        mutable["token"] = token
        return mutable


class BankSampahApprovalListSerializer(serializers.ModelSerializer[Model]):
    pengelola_utama = serializers.SerializerMethodField()
    foto_kegiatan = serializers.SerializerMethodField()

    class Meta:
        model = BankSampah
        fields = [
            "id",
            "nama",
            "alamat",
            "kota",
            "no_hp_pic",
            "foto_kegiatan",
            "status",
            "created_at",
            "pengelola_utama",
        ]

    def get_pengelola_utama(self, obj: Any) -> Any:
        user = obj.users.filter(is_primary_pengelola=True).first()
        if not user:
            return None
        return {"id": str(user.id), "nama": user.nama, "email": user.email, "no_hp": user.no_hp}

    def get_foto_kegiatan(self, obj: Any) -> str | None:
        if not obj.foto_kegiatan:
            return None
        if settings.GS_BUCKET_NAME:
            return str(obj.foto_kegiatan.url)

        request = self.context.get("request")
        if request is None:
            return None
        token = TimestampSigner(salt="bank-sampah-kegiatan").sign(obj.foto_kegiatan.name)
        return str(
            request.build_absolute_uri(
                reverse("bank-sampah-activity-media", kwargs={"token": token})
            )
        )


def validate_image_upload(value: Any, label: str) -> Any:
    name = getattr(value, "name", str(value)).lower()
    if not name.endswith((".jpg", ".jpeg", ".png")):
        raise serializers.ValidationError(f"{label} harus berformat JPG, JPEG, atau PNG")
    if getattr(value, "size", 0) > 5 * 1024 * 1024:
        raise serializers.ValidationError(f"Ukuran {label.lower()} maksimal 5 MB")
    return value


class ApprovalDecisionSerializer(serializers.Serializer[Any]):
    catatan = serializers.CharField(required=False, allow_blank=True)


class ApprovalLogSerializer(serializers.ModelSerializer[Model]):
    superadmin_email = serializers.EmailField(source="superadmin.email")

    class Meta:
        model = BankSampahApprovalLog
        fields = ["id", "bank_sampah_id", "superadmin_email", "status", "catatan", "created_at"]


class NasabahApprovalLogSerializer(serializers.ModelSerializer[Model]):
    pengurus_email = serializers.EmailField(source="pengurus.email")

    class Meta:
        model = NasabahApprovalLog
        fields = ["id", "nasabah_id", "pengurus_email", "status", "catatan", "created_at"]


class GoogleAuthSerializer(serializers.Serializer[Any]):
    id_token = serializers.CharField(required=True)


class RefreshTokenSerializer(serializers.Serializer[Any]):
    refresh_token = serializers.CharField(required=True)


class LogoutSerializer(serializers.Serializer[Any]):
    refresh_token = serializers.CharField(required=False, allow_blank=True)


class NasabahSerializer(serializers.ModelSerializer[Model]):
    kode = serializers.CharField(source="nomor", required=True, max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    total_saldo = serializers.SerializerMethodField()

    class Meta:
        model = Nasabah
        fields = [
            "id",
            "kode",
            "email",
            "nama",
            "jenis_kelamin",
            "tanggal_lahir",
            "no_hp",
            "alamat",
            "tanggal_daftar",
            "is_active",
            "status",
            "total_saldo",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "tanggal_daftar",
            "is_active",
            "status",
            "total_saldo",
            "created_at",
        ]

    def validate_email(self, value: Any) -> Any:
        if value is None:
            return None
        value = value.strip().lower()
        return value or None

    def validate_kode(self, value: Any) -> Any:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("ID Nasabah wajib diisi")
        return value

    def validate_nama(self, value: Any) -> Any:
        value = value.strip()
        if not 3 <= len(value) <= 100:
            raise serializers.ValidationError("Nama minimal 3 karakter")
        return value

    def validate_no_hp(self, value: Any) -> Any:
        return normalize_indonesian_phone(value)

    def validate_jenis_kelamin(self, value: Any) -> Any:
        if value not in [Nasabah.Gender.MALE, Nasabah.Gender.FEMALE]:
            raise serializers.ValidationError("Jenis kelamin wajib dipilih")
        return value

    def validate_tanggal_lahir(self, value: Any) -> Any:
        if value > timezone.localdate():
            raise serializers.ValidationError("Tanggal lahir tidak boleh di masa depan")
        return value

    def validate_alamat(self, value: Any) -> Any:
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError("Alamat wajib diisi")
        return value

    def get_total_saldo(self, obj: Any) -> Any:
        return getattr(getattr(obj, "saldo", None), "total_saldo", Decimal("0.00"))


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


class TransactionItemInputSerializer(serializers.Serializer[Any]):
    jenis_sampah_id = serializers.UUIDField(required=True)
    berat = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"))
    harga_per_kg = serializers.DecimalField(
        max_digits=11, decimal_places=2, min_value=Decimal("0.01"), required=False
    )


class TransactionCreateSerializer(serializers.Serializer[Any]):
    nasabah_id = serializers.UUIDField(required=True)
    items = TransactionItemInputSerializer(many=True, required=True)
    catatan = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_items(self, value: Any) -> Any:
        if not value:
            raise serializers.ValidationError("Minimal 1 item setoran diperlukan")
        return value


class DetailTransaksiSerializer(serializers.ModelSerializer[Model]):
    jenis_sampah_id = serializers.UUIDField(source="jenis_sampah.id")

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


class TransactionDetailSerializer(serializers.ModelSerializer[Model]):
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
        return (
            Transaksi.objects.filter(bank_sampah=obj.bank_sampah, nasabah=obj.nasabah)
            .filter(Q(tanggal__lt=obj.tanggal) | Q(tanggal=obj.tanggal, id__lte=obj.id))
            .aggregate(total=Coalesce(Sum("total_nilai"), Decimal("0.00")))["total"]
        )


class SaldoSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")

    class Meta:
        model = Saldo
        fields = ["nasabah_id", "nasabah_nama", "total_saldo", "updated_at"]
