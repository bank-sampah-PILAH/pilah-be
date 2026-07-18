"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


class ApiTestView(TemplateView):
    template_name = "api_test.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["google_client_id"] = settings.GOOGLE_CLIENT_ID
        return context


def assetlinks(request):
    return JsonResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": "com.mobile.pilahapp",
                    "sha256_cert_fingerprints": [
                        "70:EF:3E:65:35:DD:83:3C:5B:43:79:E9:23:13:84:8E:E9:82:30:4F:A8:C6:E6:5F:A1:E5:3A:8A:6F:D8:EB:FC"
                    ],
                },
            }
        ],
        safe=False,
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path(".well-known/assetlinks.json", assetlinks, name="assetlinks"),
    path("api-test/", ApiTestView.as_view(), name="api-test"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/", include("api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
