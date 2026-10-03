from decimal import Decimal
from typing import Any

from django.db.models import Model
from django.utils import timezone
from rest_framework import serializers

from api.models import DetailTransaksi, Nasabah, NasabahApprovalLog, Saldo
from apps.nasabah.keanggotaan import profil_akun, profil_berbeda, punya_akun
from shared_kernel.validators import normalize_indonesian_phone


class NasabahApprovalLogSerializer(serializers.ModelSerializer[Model]):
    pengurus_email = serializers.EmailField(source="pengurus.email")

    class Meta:
        model = NasabahApprovalLog
        fields = ["id", "nasabah_id", "pengurus_email", "status", "catatan", "created_at"]


class NasabahSerializer(serializers.ModelSerializer[Model]):
    kode = serializers.CharField(source="nomor", required=True, max_length=20)
    email = serializers.EmailField(required=True)
    total_saldo = serializers.SerializerMethodField()
    punya_akun = serializers.SerializerMethodField()

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
            "punya_akun",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "tanggal_daftar",
            "is_active",
            "status",
            "total_saldo",
            "punya_akun",
            "created_at",
        ]

    def validate_email(self, value: Any) -> Any:
        value = value.strip().lower()
        if not value:
            raise serializers.ValidationError("Email wajib diisi")
        return value

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

    def get_punya_akun(self, obj: Any) -> bool:
        """Menyatakan keanggotaan ini sudah tertaut ke akun nasabah.

        Hanya penanda tampilan, supaya layar pengurus dapat menonaktifkan field
        email, satu-satunya yang terkunci begitu akun tertaut. Wewenangnya tetap
        ditegakkan di server oleh ``apps.nasabah.keanggotaan.email_terkunci``
        (PIL-288), bukan klien.
        """
        return punya_akun(obj)

    def get_total_saldo(self, obj: Any) -> Any:
        return getattr(getattr(obj, "saldo", None), "total_saldo", Decimal("0.00"))


class NasabahDetailSerializer(NasabahSerializer):
    ringkasan_transaksi = serializers.SerializerMethodField()
    profil_akun = serializers.SerializerMethodField()
    profil_berbeda = serializers.SerializerMethodField()

    class Meta(NasabahSerializer.Meta):
        fields = NasabahSerializer.Meta.fields + [
            "ringkasan_transaksi",
            "profil_akun",
            "profil_berbeda",
        ]

    def get_profil_akun(self, obj: Any) -> Any:
        """Profil yang diisikan nasabah sendiri, supaya pengurus dapat
        membandingkannya dengan catatan bank sampahnya. ``None`` tanpa akun."""
        return profil_akun(obj)

    def get_profil_berbeda(self, obj: Any) -> list[str]:
        return profil_berbeda(obj)

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


class SaldoSerializer(serializers.ModelSerializer[Model]):
    nasabah_id = serializers.UUIDField(source="nasabah.id")
    nasabah_nama = serializers.CharField(source="nasabah.nama")

    class Meta:
        model = Saldo
        fields = ["nasabah_id", "nasabah_nama", "total_saldo", "updated_at"]
