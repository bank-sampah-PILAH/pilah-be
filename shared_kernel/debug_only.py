from collections.abc import Callable
from functools import wraps
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponseBase


def debug_only(view: Callable[..., HttpResponseBase]) -> Callable[..., HttpResponseBase]:
    """Serve a developer-only view only when DEBUG is on; otherwise answer 404.

    Fail-closed: DEBUG defaults to false, so a deploy that forgets to configure
    it hides the view instead of exposing it.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not settings.DEBUG:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper
