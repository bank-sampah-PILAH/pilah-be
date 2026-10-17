from typing import Any, cast

from django.db.models import Model
from rest_framework import serializers

from api.models import JadwalKegiatan, Nasabah, User

# Nested `source` path shared with the other contexts' serializers.
_BANK_SAMPAH_ID = "bank_sampah.id"


class JadwalKegiatanSerializer(serializers.ModelSerializer[Model]):
    bank_sampah_id = serializers.UUIDField(source=_BANK_SAMPAH_ID, read_only=True)
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
