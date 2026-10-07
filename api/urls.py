from django.urls import include, path
from rest_framework.routers import DefaultRouter

# ponytail: views live in their canonical bounded-context homes; routes and
# names are frozen so this compose is behavior-neutral.
from apps.authentication.views import (
    AuthMeView,
    CompleteProfileView,
    GoogleAuthView,
    GoogleOAuthCallbackView,
    GoogleOAuthStartView,
    GoogleRegistrationView,
    LogoutView,
    RefreshTokenView,
)
from apps.bank_sampah.views import (
    AcceptInviteView,
    BankSampahDirectoryView,
    BankSampahMeView,
    GenerateInviteView,
    RegisterBankSampahView,
    SuperAdminBankSampahViewSet,
    TeamView,
)
from apps.jadwal.views import JadwalKegiatanViewSet
from apps.ledger.views import ActivityHistoryView, PencairanViewSet, TransaksiViewSet

# ponytail: views are imported from their canonical bounded-context homes;
# routes and names are frozen so this compose is behavior-neutral.
from apps.nasabah.home import (
    NasabahBalanceView,
    NasabahBankView,
    NasabahHistoryExportPdfView,
    NasabahHistoryView,
    NasabahHomeView,
    NasabahTransactionDetailView,
)
from apps.nasabah.profile import NasabahProfileView
from apps.nasabah.views import NasabahSelfView, NasabahViewSet, RegisterNasabahView, SaldoView
from apps.notification.views import WATemplateView
from apps.reporting.views import DashboardRecentTransactionsView, DashboardStatsView
from apps.waste_catalog.views import JenisSampahViewSet

router = DefaultRouter(trailing_slash=False)
router.register("nasabah", NasabahViewSet, basename="nasabah")
router.register("jenis-sampah", JenisSampahViewSet, basename="jenis-sampah")
router.register("jadwal", JadwalKegiatanViewSet, basename="jadwal")
router.register("transaksi", TransaksiViewSet, basename="transaksi")
router.register("pencairan", PencairanViewSet, basename="pencairan")
router.register(
    "superadmin/bank-sampah", SuperAdminBankSampahViewSet, basename="superadmin-bank-sampah"
)

urlpatterns = [
    path("aktivitas", ActivityHistoryView.as_view(), name="activity-history"),
    path("nasabah/me/beranda", NasabahHomeView.as_view(), name="nasabah-home"),
    path("nasabah/me/saldo", NasabahBalanceView.as_view(), name="nasabah-own-balance"),
    path("nasabah/me/bank-sampah", NasabahBankView.as_view(), name="nasabah-own-bank"),
    path("nasabah/me/riwayat", NasabahHistoryView.as_view(), name="nasabah-own-history"),
    path(
        "nasabah/me/riwayat/export-pdf",
        NasabahHistoryExportPdfView.as_view(),
        name="nasabah-own-history-export-pdf",
    ),
    path(
        "nasabah/me/riwayat/<uuid:pk>",
        NasabahTransactionDetailView.as_view(),
        name="nasabah-own-transaction-detail",
    ),
    path("nasabah/me/profil", NasabahProfileView.as_view(), name="nasabah-own-profile"),
    path("auth/google", GoogleAuthView.as_view(), name="auth-google"),
    path("auth/google/register", GoogleRegistrationView.as_view(), name="auth-google-register"),
    path("auth/google/start", GoogleOAuthStartView.as_view(), name="auth-google-start"),
    path("auth/google/callback", GoogleOAuthCallbackView.as_view(), name="auth-google-callback"),
    path("auth/refresh", RefreshTokenView.as_view(), name="auth-refresh"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/me", AuthMeView.as_view(), name="auth-me"),
    path("onboarding/profile", CompleteProfileView.as_view(), name="onboarding-profile"),
    path("onboarding/bank-sampah", RegisterBankSampahView.as_view(), name="onboarding-bank-sampah"),
    path("onboarding/nasabah", RegisterNasabahView.as_view(), name="onboarding-nasabah"),
    path("invites/accept", AcceptInviteView.as_view(), name="invite-accept"),
    path("bank-sampah/invite/join", AcceptInviteView.as_view(), name="bank-sampah-invite-join"),
    path("bank-sampah/me", BankSampahMeView.as_view(), name="bank-sampah-me"),
    path("bank-sampah", BankSampahDirectoryView.as_view(), name="bank-sampah-directory"),
    path("team", TeamView.as_view(), name="team"),
    path("team/invite", GenerateInviteView.as_view(), name="team-invite"),
    path("nasabah/me", NasabahSelfView.as_view(), name="nasabah-me"),
    path("nasabah/<uuid:pk>/saldo", SaldoView.as_view(), name="nasabah-saldo"),
    path("dashboard/stats", DashboardStatsView.as_view(), name="dashboard-stats"),
    path(
        "dashboard/recent-transactions",
        DashboardRecentTransactionsView.as_view(),
        name="dashboard-recent",
    ),
    path("pengaturan/wa-template", WATemplateView.as_view(), name="wa-template"),
    path("", include(router.urls)),
]
