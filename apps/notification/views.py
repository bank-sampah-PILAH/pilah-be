from typing import Any

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notification.models import DeviceToken, PushNotification
from apps.notification.serializers import WATemplateSerializer
from apps.notification.services import WhatsAppService
from shared_kernel.permissions import IsActivePengelola
from shared_kernel.scoping import current_bank, current_user


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


class DeviceTokenSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(max_length=1024)
    platform = serializers.ChoiceField(choices=["android", "ios", "web"])


class DeviceTokenView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeviceTokenSerializer

    def post(self, request: Request) -> Response:
        data = DeviceTokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        DeviceToken.objects.update_or_create(
            token=data.validated_data["token"],
            defaults={"user": current_user(request), "platform": data.validated_data["platform"]},
        )
        return Response(status=200)

    def delete(self, request: Request) -> Response:
        token = request.data.get("token") if isinstance(request.data, dict) else None
        if not isinstance(token, str) or not token or len(token) > 1024:
            raise serializers.ValidationError({"token": "Token tidak valid"})
        DeviceToken.objects.filter(user=current_user(request), token=token).delete()
        return Response(status=204)


class NotificationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        notifications = PushNotification.objects.filter(user=current_user(request)).order_by(
            "-created_at", "-pk"
        )
        return Response(list(notifications.values("id", "title", "body", "created_at", "read_at")))


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        notification = get_object_or_404(PushNotification, pk=pk, user=current_user(request))
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(status=204)
