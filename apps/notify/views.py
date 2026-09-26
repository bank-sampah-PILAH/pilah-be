from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notify.serializers import WATemplateSerializer
from apps.notify.services import WhatsAppService
from shared_kernel.permissions import IsActivePengelola
from shared_kernel.scoping import current_bank


class WATemplateView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = WATemplateSerializer

    def get(self, request: Request) -> Response:
        bank = current_bank(request)
        return Response(
            {
                "template": WhatsAppService.get_template(bank),
                "variabel_tersedia": [
                    "{Nama}",
                    "{Total}",
                    "{Saldo}",
                    "{Tanggal}",
                    "{daftar_item}",
                    "{daftar_item_harga}",
                ],
                "preview_contoh": WhatsAppService.preview(bank),
            }
        )

    def put(self, request: Request) -> Response:
        serializer = WATemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = current_bank(request)
        bank.wa_template = serializer.validated_data["template"]
        bank.save(update_fields=["wa_template", "updated_at"])
        return Response({"template": bank.wa_template, "message": "Template berhasil disimpan"})
