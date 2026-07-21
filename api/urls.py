from django.urls import include, path
from rest_framework.routers import DefaultRouter

from api.views import (
    BankSampahMeView,
    AcceptInviteView,
    AuthMeView,
    CompleteProfileView,
    DashboardRecentTransactionsView,
    DashboardStatsView,
    GenerateInviteView,
    GoogleAuthView,
    GoogleOAuthCallbackView,
    GoogleOAuthStartView,
    JenisSampahViewSet,
    LogoutView,
    NasabahViewSet,
    RegisterBankSampahView,
    RefreshTokenView,
    SaldoView,
    SuperAdminBankSampahViewSet,
    TeamView,
    TransaksiViewSet,
    WATemplateView,
)

router = DefaultRouter(trailing_slash=False)
router.register("nasabah", NasabahViewSet, basename="nasabah")
router.register("jenis-sampah", JenisSampahViewSet, basename="jenis-sampah")
router.register("transaksi", TransaksiViewSet, basename="transaksi")
router.register("superadmin/bank-sampah", SuperAdminBankSampahViewSet, basename="superadmin-bank-sampah")

urlpatterns = [
    path("auth/google", GoogleAuthView.as_view(), name="auth-google"),
    path("auth/google/start", GoogleOAuthStartView.as_view(), name="auth-google-start"),
    path("auth/google/callback", GoogleOAuthCallbackView.as_view(), name="auth-google-callback"),
    path("auth/refresh", RefreshTokenView.as_view(), name="auth-refresh"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/me", AuthMeView.as_view(), name="auth-me"),
    path("onboarding/profile", CompleteProfileView.as_view(), name="onboarding-profile"),
    path("onboarding/bank-sampah", RegisterBankSampahView.as_view(), name="onboarding-bank-sampah"),
    path("invites/accept", AcceptInviteView.as_view(), name="invite-accept"),
    path("bank-sampah/invite/join", AcceptInviteView.as_view(), name="bank-sampah-invite-join"),
    path("bank-sampah/me", BankSampahMeView.as_view(), name="bank-sampah-me"),
    path("team", TeamView.as_view(), name="team"),
    path("team/invite", GenerateInviteView.as_view(), name="team-invite"),
    path("nasabah/<uuid:pk>/saldo", SaldoView.as_view(), name="nasabah-saldo"),
    path("dashboard/stats", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("dashboard/recent-transactions", DashboardRecentTransactionsView.as_view(), name="dashboard-recent"),
    path("pengaturan/wa-template", WATemplateView.as_view(), name="wa-template"),
    path("", include(router.urls)),
]
