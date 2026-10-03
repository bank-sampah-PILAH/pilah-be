from typing import Any

from rest_framework import serializers


class WATemplateSerializer(serializers.Serializer[Any]):
    template = serializers.CharField(required=True, allow_blank=False)
