from django.conf import settings
from django.core.cache import caches
from rest_framework.throttling import UserRateThrottle


class NasabahListThrottle(UserRateThrottle):
    """Basic per-user overuse budget, shared across application workers.

    DRF's cache operations are not atomic. Edge/WAF controls are still required
    for strict concurrent limits and denial-of-service protection.
    """

    scope = "nasabah_list"
    cache = caches["auth_rate_limit"]

    def get_rate(self) -> str:
        return str(settings.NASABAH_LIST_RATE)
