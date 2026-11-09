from django.conf import settings
from django.db import models
from django.db.models import Q


class DeviceToken(models.Model):
    token = models.CharField(max_length=1024, unique=True)
    platform = models.CharField(max_length=20)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        app_label = "api"
        db_table = "api_devicetoken"


class PushNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "api"
        db_table = "api_pushnotification"
        indexes = [
            models.Index(fields=["user", "-created_at", "-id"], name="pushnotif_user_created_idx")
        ]


class PushDelivery(models.Model):
    notification = models.ForeignKey(PushNotification, on_delete=models.CASCADE)
    device = models.ForeignKey(DeviceToken, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=16, default="pending")
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        app_label = "api"
        db_table = "api_pushdelivery"
        constraints = [
            models.UniqueConstraint(fields=["notification", "device"], name="unique_push_delivery")
        ]
        indexes = [
            models.Index(
                fields=["next_attempt_at", "id"],
                condition=Q(status="pending"),
                name="pushdel_pending_idx",
            )
        ]
