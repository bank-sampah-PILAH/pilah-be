from decimal import Decimal
from typing import Any

from django.db.models import Model
from rest_framework import serializers

from api.models import Transaksi
from shared_kernel.validators import get_initials


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
