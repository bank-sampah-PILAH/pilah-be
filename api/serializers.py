from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers

from api.models import (
    BankSampah,
    BankSampahApprovalLog,
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    Saldo,
    Transaksi,
    User,
)
from api.validators import get_initials, normalize_indonesian_phone


class BankSampahSerializer(serializers.ModelSerializer):
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

    def validate_nama(self, value):
        if len(value.strip()) < 3:
            raise serializers.ValidationError("Nama bank sampah wajib diisi")
        return value.strip()

    def validate_no_hp_pic(self, value):
        try:
            return normalize_indonesian_phone(value)
        except serializers.ValidationError as err:
            raise serializers.ValidationError("Format nomor tidak valid") from err

    def validate_foto_logo(self, value):
        return validate_image_upload(value, "Foto logo")

    def get_pengelola(self, obj):
        user = obj.users.filter(role="pengelola", is_active=True).first()
        if not user:
            return None
        return {"id": str(user.id), "nama": user.nama, "email": user.email}


class UserProfileSerializer(serializers.ModelSerializer):
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

    def validate_nama(self, value):
        value = value.strip()
        if not 3 <= len(value) <= 100:
            raise serializers.ValidationError("Nama minimal 3 karakter")
        return value

    def validate_no_hp(self, value):
        return normalize_indonesian_phone(value)

    def validate_jenis_kelamin(self, value):
        if value not in [User.Gender.MALE, User.Gender.FEMALE]:
            raise serializers.ValidationError("Jenis kelamin wajib dipilih")
        return value

    def validate_tanggal_lahir(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Tanggal lahir tidak boleh di masa depan")
        return value


class BankSampahRegistrationSerializer(serializers.Serializer):
    nama = serializers.CharField(required=True, max_length=100)
    alamat = serializers.CharField(required=True)
    kota = serializers.CharField(required=False, allow_blank=True, max_length=100)
    no_hp_pic = serializers.CharField(required=True)
    foto_kegiatan = serializers.FileField(required=True)

    def validate_nama(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Nama Bank Sampah wajib diisi (minimal 3 karakter)")
        return value

    def validate_alamat(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError(
                "Alamat lengkap wajib diisi untuk keperluan verifikasi lokasi"
            )
        return value

    def validate_no_hp_pic(self, value):
        return normalize_indonesian_phone(value)

    def validate_foto_kegiatan(self, value):
        if not value:
            raise serializers.ValidationError("Foto kegiatan wajib diunggah sebagai bukti validasi")
        return validate_image_upload(value, "Foto kegiatan")


class AuthUserSerializer(serializers.ModelSerializer):
    bank_sampah_id = serializers.UUIDField(source="bank_sampah.id", allow_null=True)
    bank_sampah_nama = serializers.CharField(source="bank_sampah.nama", allow_null=True)
    bank_sampah_status = serializers.CharField(source="bank_sampah.status", allow_null=True)

    class Meta:
        model = User
        fields = [
            "id",
            "nama",
            "email",
            "role",
            "bank_sampah_id",
            "bank_sampah_nama",
            "bank_sampah_status",
            "is_profile_complete",
            "is_primary_pengelola",
        ]


class TeamMemberSerializer(serializers.ModelSerializer):
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

    def get_is_current_user(self, obj):
        request = self.context.get("request")
        return bool(request and request.user.id == obj.id)


class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(required=False, allow_blank=True)
    invite_token = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs):
        token = attrs.get("token") or attrs.get("invite_token")
        if not token:
            raise serializers.ValidationError({"token": ["Token undangan wajib diisi"]})
        attrs["token"] = token
        return attrs


class BankSampahApprovalListSerializer(serializers.ModelSerializer):
    pengelola_utama = serializers.SerializerMethodField()

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

    def get_pengelola_utama(self, obj):
        user = obj.users.filter(is_primary_pengelola=True).first()
        if not user:
            return None
        return {"id": str(user.id), "nama": user.nama, "email": user.email, "no_hp": user.no_hp}


def validate_image_upload(value, label):
    name = getattr(value, "name", str(value)).lower()
    if not name.endswith((".jpg", ".jpeg", ".png")):
        raise serializers.ValidationError(f"{label} harus berformat JPG, JPEG, atau PNG")
    if getattr(value, "size", 0) > 5 * 1024 * 1024:
        raise serializers.ValidationError(f"Ukuran {label.lower()} maksimal 5 MB")
    return value


class ApprovalDecisionSerializer(serializers.Serializer):
    catatan = serializers.CharField(required=False, allow_blank=True)


class ApprovalLogSerializer(serializers.ModelSerializer):
    superadmin_email = serializers.EmailField(source="superadmin.email")

    class Meta:
        model = BankSampahApprovalLog
        fields = ["id", "bank_sampah_id", "superadmin_email", "status", "catatan", "created_at"]


class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True)


class RefreshTokenSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=True)


class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=False, allow_blank=True)


class NasabahSerializer(serializers.ModelSerializer):
    kode = serializers.CharField(source="nomor", required=True, max_length=20)
    total_saldo = serializers.SerializerMethodField()

    class Meta:
        model = Nasabah
        fields = [
            "id",
            "kode",
            "nama",
            "jenis_kelamin",
            "tanggal_lahir",
            "no_hp",
            "alamat",
            "tanggal_daftar",
            "is_active",
            "total_saldo",
            "created_at",
        ]
        read_only_fields = ["id", "tanggal_daftar", "is_active", "total_saldo", "created_at"]

    def validate_kode(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("ID Nasabah wajib diisi")
        return value

    def validate_nama(self, value):
        value = value.strip()
        if not 3 <= len(value) <= 100:
            raise serializers.ValidationError("Nama minimal 3 karakter")
        return value

    def validate_no_hp(self, value):
        return normalize_indonesian_phone(value)

    def validate_jenis_kelamin(self, value):
        if value not in [Nasabah.Gender.MALE, Nasabah.Gender.FEMALE]:
            raise serializers.ValidationError("Jenis kelamin wajib dipilih")
        return value

    def validate_tanggal_lahir(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Tanggal lahir tidak boleh di masa depan")
        return value

    def validate_alamat(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError("Alamat wajib diisi")
        return value

    def get_total_saldo(self, obj):
        return getattr(getattr(obj, "saldo", None), "total_saldo", Decimal("0.00"))


class NasabahDetailSerializer(NasabahSerializer):
    ringkasan_transaksi = serializers.SerializerMethodField()

    class Meta(NasabahSerializer.Meta):
        fields = NasabahSerializer.Meta.fields + ["ringkasan_transaksi"]

    def get_ringkasan_transaksi(self, obj):
        items = DetailTransaksi.objects.filter(transaksi__nasabah=obj)
        total_kg = sum((item.berat for item in items), Decimal(0))
        last_transaction = obj.transaksi.order_by("-tanggal").first()
        return {
            "jumlah_transaksi": obj.transaksi.count(),
            "total_kg": total_kg,
            "tanggal_transaksi_terakhir": last_transaction.tanggal if last_transaction else None,
        }


class StatusSerializer(serializers.Serializer):
    is_active = serializers.BooleanField(required=True)


class JenisSampahSerializer(serializers.ModelSerializer):
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

    def validate_kode(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Kode sampah wajib diisi")
        return value

    def validate_nama_sampah(self, value):
        value = value.strip()
        if not 2 <= len(value) <= 50:
            raise serializers.ValidationError("Nama jenis sampah wajib diisi")
        return value

    def validate_deskripsi(self, value):
        if value and len(value) > 200:
            raise serializers.ValidationError("Deskripsi maksimal 200 karakter")
        return value

    def validate_harga_per_kg(self, value):
        if value <= 0:
            raise serializers.ValidationError("Harga harus berupa angka positif")
        if value >= Decimal(1000000000):
            raise serializers.ValidationError("Harga maksimal 9 digit")
        return value

    def get_satuan(self, obj):
        return "kg"


class TransactionItemInputSerializer(serializers.Serializer):
    jenis_sampah_id = serializers.UUIDField(required=True)
    berat = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"))
    harga_per_kg = serializers.DecimalField(
        max_digits=11, decimal_places=2, min_value=Decimal("0.01"), required=False
    )


class TransactionCreateSerializer(serializers.Serializer):
    nasabah_id = serializers.UUIDField(required=True)
    items = TransactionItemInputSerializer(many=True, required=True)
    catatan = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Minimal 1 item setoran diperlukan")
        return value


class DetailTransaksiSerializer(serializers.ModelSerializer):
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


class TransactionDetailSerializer(serializers.ModelSerializer):
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

    def get_saldo_setelah_transaksi(self, obj):
        return (
            Transaksi.objects.filter(bank_sampah=obj.bank_sampah, nasabah=obj.nasabah)
            .filter(Q(tanggal__lt=obj.tanggal) | Q(tanggal=obj.tanggal, id__lte=obj.id))
            .aggregate(total=Coalesce(Sum("total_nilai"), Decimal("0.00")))["total"]
        )


class TransactionListSerializer(serializers.ModelSerializer):
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

    def get_nasabah_inisial(self, obj):
        return get_initials(obj.nasabah.nama)

    def get_jenis_sampah_utama(self, obj):
        item = max(obj.items.all(), key=lambda detail: detail.berat, default=None)
        return item.nama_sampah_snapshot if item else None

    def get_total_berat_kg(self, obj):
        return sum((item.berat for item in obj.items.all()), Decimal(0))


class SaldoSerializer(serializers.ModelSerializer):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")

    class Meta:
        model = Saldo
        fields = ["nasabah_id", "nasabah_nama", "total_saldo", "updated_at"]


class WATemplateSerializer(serializers.Serializer):
    template = serializers.CharField(required=True, allow_blank=False)
