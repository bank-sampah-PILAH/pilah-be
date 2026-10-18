from typing import Any, cast

from django.db.models import Model
from django.utils import timezone
from rest_framework import serializers

from api.models import Pengumuman

# Nested `source` path shared with the other contexts' serializers.
_BANK_SAMPAH_ID = "bank_sampah.id"


class PengumumanNasabahListSerializer(serializers.ModelSerializer[Pengumuman]):
    """Nasabah-facing row: no staff audit fields, carries the read flag.

    The view annotates _dibaca / _dibaca_pada per row; the fallbacks below
    cover direct (un-annotated) serializer use.
    """

    dibaca = serializers.SerializerMethodField()
    dibaca_pada = serializers.SerializerMethodField()

    class Meta:
        model = Pengumuman
        fields = ["id", "judul", "isi", "terbit_pada", "dibaca", "dibaca_pada"]
        read_only_fields = fields

    def get_dibaca(self, obj: Pengumuman) -> bool:
        return bool(getattr(obj, "_dibaca", False))

    def get_dibaca_pada(self, obj: Pengumuman) -> Any:
        return getattr(obj, "_dibaca_pada", None)


class PengumumanBerandaSerializer(serializers.ModelSerializer[Pengumuman]):
    """Compact row for the beranda summary (PIL-333).

    isi comes along so tapping a beranda row can open the detail without a
    second round trip.
    """

    dibaca = serializers.SerializerMethodField()
    dibaca_pada = serializers.SerializerMethodField()

    class Meta:
        model = Pengumuman
        fields = ["id", "judul", "isi", "terbit_pada", "dibaca", "dibaca_pada"]
        read_only_fields = fields

    def get_dibaca_pada(self, obj: Pengumuman) -> Any:
        return getattr(obj, "_dibaca_pada", None)

    def get_dibaca(self, obj: Pengumuman) -> bool:
        return bool(getattr(obj, "_dibaca", False))


class TerbitkanSerializer(serializers.Serializer[Any]):
    """Publish-now or schedule payload for POST /pengumuman/{id}/terbitkan.

    terbit_pada omitted = publish now; a future value schedules. masa
    consistency against the instance's draft values is enforced in
    PengumumanService, which knows the resolved values.
    """

    terbit_pada = serializers.DateTimeField(required=False, allow_null=True)
    masa_berlaku_hingga = serializers.DateTimeField(required=False, allow_null=True)

    def validate_terbit_pada(self, value: Any) -> Any:
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("Waktu terbit harus di masa datang")
        return value


class PengumumanSerializer(serializers.ModelSerializer[Model]):
    bank_sampah_id = serializers.UUIDField(source=_BANK_SAMPAH_ID, read_only=True)
    dibuat_oleh_id = serializers.UUIDField(source="dibuat_oleh.id", read_only=True)
    diterbitkan_oleh_id = serializers.UUIDField(
        source="diterbitkan_oleh.id", read_only=True, allow_null=True
    )
    ditarik_oleh_id = serializers.UUIDField(
        source="ditarik_oleh.id", read_only=True, allow_null=True
    )
    status = serializers.SerializerMethodField()

    class Meta:
        model = Pengumuman
        fields = [
            "id",
            "bank_sampah_id",
            "dibuat_oleh_id",
            "diterbitkan_oleh_id",
            "ditarik_oleh_id",
            "judul",
            "isi",
            "terbit_pada",
            "masa_berlaku_hingga",
            "ditarik_pada",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "bank_sampah_id",
            "dibuat_oleh_id",
            "diterbitkan_oleh_id",
            "ditarik_oleh_id",
            "ditarik_pada",
            "status",
            "created_at",
            "updated_at",
        ]

    def get_status(self, obj: Pengumuman) -> str:
        return obj.status_efektif()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = cast(Pengumuman | None, self.instance)
        now = timezone.now()
        # A schedule may only be set by the terbitkan action: reject any
        # terbit_pada a draft would carry (new or edited), so a draft can
        # never sit labeled terjadwal without ever publishing it (review
        # finding PIL-243).
        is_draft = instance is None or instance.status == Pengumuman.Status.DRAFT
        if (
            is_draft
            and attrs.get("terbit_pada", getattr(instance, "terbit_pada", None)) is not None
        ):
            raise serializers.ValidationError(
                {"terbit_pada": "Jadwal hanya boleh diatur lewat terbitkan"}
            )
        masa_berlaku = attrs.get(
            "masa_berlaku_hingga", getattr(instance, "masa_berlaku_hingga", None)
        )
        if masa_berlaku is not None:
            terkait = attrs.get("terbit_pada", getattr(instance, "terbit_pada", None)) or now
            if masa_berlaku <= terkait:
                raise serializers.ValidationError(
                    {"masa_berlaku_hingga": "Masa berlaku harus setelah waktu terbit"}
                )
        return attrs
