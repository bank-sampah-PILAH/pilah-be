import json

from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.http import urlencode
import requests
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, JenisSampah, Nasabah, Saldo, Transaksi, User
from api.permissions import IsActivePengelola, IsPengelola, IsPrimaryPengelola, IsSuperAdmin
from api.serializers import (
    ApprovalDecisionSerializer,
    ApprovalLogSerializer,
    AuthUserSerializer,
    BankSampahSerializer,
    BankSampahApprovalListSerializer,
    BankSampahRegistrationSerializer,
    GoogleAuthSerializer,
    InviteAcceptSerializer,
    JenisSampahSerializer,
    LogoutSerializer,
    NasabahDetailSerializer,
    NasabahSerializer,
    RefreshTokenSerializer,
    SaldoSerializer,
    StatusSerializer,
    TeamMemberSerializer,
    TransactionCreateSerializer,
    TransactionDetailSerializer,
    TransactionListSerializer,
    UserProfileSerializer,
    WATemplateSerializer,
)
from api.services import (
    ApprovalService,
    AuthService,
    DashboardService,
    NumberingService,
    OnboardingService,
    TeamService,
    TransactionFilterService,
    TransactionService,
    WhatsAppService,
)


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]
    serializer_class = GoogleAuthSerializer

    def post(self, request):
        token = request.data.get("id_token")
        if not token:
            return Response({"errors": {"id_token": ["Google ID Token wajib diisi"]}}, status=422)
        try:
            return Response(AuthService.login_with_google(token))
        except Exception:
            return Response({"error": "ID Token invalid atau expired"}, status=401)


class GoogleOAuthStartView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            return Response({"error": "Google OAuth client is not configured"}, status=503)
        redirect_uri = settings.GOOGLE_REDIRECT_URI or request.build_absolute_uri("/api/v1/auth/google/callback")
        next_url = request.GET.get("next") or "/api-test/"
        if not next_url.startswith("/"):
            next_url = "/api-test/"
        state = TimestampSigner().sign(next_url)
        params = urlencode(
            {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "prompt": "select_account",
            }
        )
        return HttpResponseRedirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


class GoogleOAuthCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if request.GET.get("error"):
            return self._popup_response(False, {"error": request.GET.get("error")})
        code = request.GET.get("code")
        raw_state = request.GET.get("state", "")
        if not code:
            return self._popup_response(False, {"error": "Missing Google authorization code"})
        try:
            next_url = TimestampSigner().unsign(raw_state, max_age=600)
        except (BadSignature, SignatureExpired):
            next_url = "/api-test/"
        if not next_url.startswith("/"):
            next_url = "/api-test/"

        redirect_uri = settings.GOOGLE_REDIRECT_URI or request.build_absolute_uri("/api/v1/auth/google/callback")
        try:
            token_response = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                timeout=10,
            )
            token_payload = token_response.json()
            if token_response.status_code >= 400:
                return self._popup_response(False, token_payload, next_url)
            id_token = token_payload.get("id_token")
            if not id_token:
                return self._popup_response(False, {"error": "Google did not return an ID token"}, next_url)
            return self._popup_response(True, AuthService.login_with_google(id_token), next_url)
        except Exception as exc:
            return self._popup_response(False, {"error": str(exc)}, next_url)

    @staticmethod
    def _popup_response(ok, payload, next_url="/api-test/"):
        message = json.dumps({"type": "pilah-google-oauth", "ok": ok, "payload": payload})
        fallback = json.dumps(payload, indent=2)
        html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>PILAH Google OAuth</title></head>
<body>
<pre>{fallback}</pre>
<script>
  const message = {message};
  if (window.opener) {{
    window.opener.postMessage(message, window.location.origin);
    window.close();
  }} else {{
    window.location.href = {json.dumps(next_url)};
  }}
</script>
</body>
</html>"""
        return HttpResponse(html, status=200 if ok else 400)


class RefreshTokenView(APIView):
    permission_classes = [AllowAny]
    serializer_class = RefreshTokenSerializer

    def post(self, request):
        raw_refresh = request.data.get("refresh_token")
        if not raw_refresh:
            return Response({"error": "Refresh token invalid / expired"}, status=401)
        try:
            refresh = RefreshToken(raw_refresh)
            access = refresh.access_token
            user = User.objects.filter(id=refresh["user_id"]).first()
            if user:
                if user.bank_sampah_id:
                    access["bank_sampah_id"] = str(user.bank_sampah_id)
                access["role"] = user.role
                access["email"] = user.email
            return Response({"access_token": str(access), "expires_in": 86400})
        except Exception:
            return Response({"error": "Refresh token invalid / expired"}, status=401)


class LogoutView(APIView):
    serializer_class = LogoutSerializer

    def post(self, request):
        raw_refresh = request.data.get("refresh_token")
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except Exception:
                pass
        return Response({"message": "Logout berhasil"})


class AuthMeView(APIView):
    serializer_class = AuthUserSerializer

    def get(self, request):
        data = AuthUserSerializer(request.user).data
        data["state"] = AuthService.user_state(request.user)
        return Response(data)


class CompleteProfileView(APIView):
    permission_classes = [IsPengelola]
    serializer_class = UserProfileSerializer

    def put(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            user = OnboardingService.complete_profile(request.user, serializer.validated_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = UserProfileSerializer(user).data
        data["next_step"] = AuthService.user_state(user)
        return Response(data)


class RegisterBankSampahView(APIView):
    permission_classes = [IsPengelola]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = BankSampahRegistrationSerializer

    def post(self, request):
        serializer = BankSampahRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bank = OnboardingService.register_bank_sampah(request.user, serializer.validated_data)
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = BankSampahSerializer(bank).data
        data["next_step"] = AuthService.user_state(request.user)
        return Response(data, status=201)


class AcceptInviteView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InviteAcceptSerializer

    def post(self, request):
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bank, outcome = OnboardingService.accept_invite(request.user, serializer.validated_data["token"])
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = BankSampahSerializer(bank).data
        data["next_step"] = AuthService.user_state(request.user)
        data["outcome"] = outcome
        data["bank_sampah_id"] = str(bank.id)
        data["bank_sampah_nama"] = bank.nama
        if outcome == "already_member":
            data["message"] = "Anda sudah terdaftar pada bank sampah ini"
        else:
            data["message"] = f"Berhasil bergabung ke Bank Sampah {bank.nama}"
        return Response(data)


class BankSampahMeView(APIView):
    permission_classes = [IsActivePengelola]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = BankSampahSerializer

    def get(self, request):
        return Response(BankSampahSerializer(request.user.bank_sampah).data)

    def put(self, request):
        serializer = BankSampahSerializer(request.user.bank_sampah, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class NasabahViewSet(viewsets.ModelViewSet):
    permission_classes = [IsActivePengelola]
    serializer_class = NasabahSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        qs = Nasabah.objects.filter(bank_sampah=self.request.user.bank_sampah).select_related("saldo")
        search = self.request.query_params.get("search", "")
        status_filter = self.request.query_params.get("status", "aktif")
        if self.action == "list" and len(search) >= 2:
            qs = qs.filter(Q(nama__icontains=search) | Q(no_hp__icontains=search))
        if self.action == "list":
            if status_filter == "aktif":
                qs = qs.filter(is_active=True)
            elif status_filter == "tidak_aktif":
                qs = qs.filter(is_active=False)
        return qs.order_by("nomor")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return NasabahDetailSerializer
        return NasabahSerializer

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nomor = serializer.validated_data["nomor"]
        no_hp = serializer.validated_data["no_hp"]
        if Nasabah.objects.filter(bank_sampah=request.user.bank_sampah, nomor=nomor).exists():
            return Response({"errors": {"kode": ["ID Nasabah sudah digunakan"]}}, status=422)
        if Nasabah.objects.filter(bank_sampah=request.user.bank_sampah, no_hp=no_hp).exists():
            return Response({"errors": {"no_hp": ["Nomor HP nasabah sudah digunakan"]}}, status=422)
        nasabah = serializer.save(
            bank_sampah=request.user.bank_sampah,
        )
        Saldo.objects.create(nasabah=nasabah)
        return Response(self.get_serializer(nasabah).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.is_active:
            return Response({"error": "Nasabah nonaktif tidak bisa diedit"}, status=403)
        nomor = request.data.get("kode")
        if nomor and Nasabah.objects.filter(bank_sampah=request.user.bank_sampah, nomor=nomor).exclude(id=instance.id).exists():
            return Response({"errors": {"kode": ["ID Nasabah sudah digunakan"]}}, status=422)
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop("partial", False))
        serializer.is_valid(raise_exception=True)
        no_hp = serializer.validated_data.get("no_hp")
        if no_hp and Nasabah.objects.filter(bank_sampah=request.user.bank_sampah, no_hp=no_hp).exclude(id=instance.id).exists():
            return Response({"errors": {"no_hp": ["Nomor HP nasabah sudah digunakan"]}}, status=422)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        nasabah = self.get_object()
        serializer = StatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nasabah.is_active = serializer.validated_data["is_active"]
        nasabah.save(update_fields=["is_active", "updated_at"])
        state = "diaktifkan" if nasabah.is_active else "dinonaktifkan"
        return Response({"id": str(nasabah.id), "is_active": nasabah.is_active, "message": f"Nasabah berhasil {state}"})


class JenisSampahViewSet(viewsets.ModelViewSet):
    permission_classes = [IsActivePengelola]
    serializer_class = JenisSampahSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        qs = JenisSampah.objects.filter(bank_sampah=self.request.user.bank_sampah)
        search = self.request.query_params.get("search", "")
        status_filter = self.request.query_params.get("status", "aktif")
        kategori = self.request.query_params.get("kategori")
        if self.action == "list" and len(search) >= 2:
            qs = qs.filter(nama_sampah__icontains=search)
        if self.action == "list":
            if status_filter == "aktif":
                qs = qs.filter(is_active=True)
            elif status_filter == "tidak_aktif":
                qs = qs.filter(is_active=False)
        if self.action == "list" and kategori:
            qs = qs.filter(kategori=kategori)
        return qs.order_by("nomor")

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        nomor = serializer.validated_data["nomor"]
        if JenisSampah.objects.filter(bank_sampah=request.user.bank_sampah, nomor=nomor).exists():
            return Response({"errors": {"kode": ["Kode sampah sudah digunakan"]}}, status=422)
        jenis = serializer.save(
            bank_sampah=request.user.bank_sampah,
        )
        return Response(self.get_serializer(jenis).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        nomor = request.data.get("kode")
        if nomor and JenisSampah.objects.filter(bank_sampah=request.user.bank_sampah, nomor=nomor).exclude(id=instance.id).exists():
            return Response({"errors": {"kode": ["Kode sampah sudah digunakan"]}}, status=422)
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        jenis = self.get_object()
        serializer = StatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        jenis.is_active = serializer.validated_data["is_active"]
        jenis.save(update_fields=["is_active", "updated_at"])
        state = "diaktifkan" if jenis.is_active else "dinonaktifkan"
        return Response({"id": str(jenis.id), "is_active": jenis.is_active, "message": f"Jenis sampah berhasil {state}"})


class TransaksiViewSet(viewsets.GenericViewSet):
    permission_classes = [IsActivePengelola]
    serializer_class = TransactionListSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return TransactionCreateSerializer
        if self.action == "retrieve":
            return TransactionDetailSerializer
        return TransactionListSerializer

    def get_queryset(self):
        qs = (
            Transaksi.objects.filter(bank_sampah=self.request.user.bank_sampah)
            .select_related("nasabah", "bank_sampah", "dicatat_oleh")
            .prefetch_related("items")
        )
        search = self.request.query_params.get("search", "")
        nasabah_id = self.request.query_params.get("nasabah_id")
        if len(search) >= 2:
            qs = qs.filter(nasabah__nama__icontains=search)
        if nasabah_id:
            qs = qs.filter(nasabah_id=nasabah_id)
        return qs

    def list(self, request):
        qs = self.get_queryset()
        try:
            qs = TransactionFilterService.apply_period(qs, request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        page = self.paginate_queryset(qs)
        serializer = TransactionListSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        qs = self.get_queryset()
        try:
            qs = TransactionFilterService.apply_period(qs, request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        if not qs.exists():
            return Response({"error": "Tidak ada data pada periode ini"}, status=400)
        content, filename = TransactionService.export_excel(qs)
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def create(self, request):
        serializer = TransactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaksi = TransactionService.create_setoran(request.user, serializer.validated_data)
        return Response(TransactionDetailSerializer(transaksi).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        transaksi = self.get_object()
        return Response(TransactionDetailSerializer(transaksi).data)

    @action(detail=True, methods=["post"], url_path="notify-wa")
    def notify_wa(self, request, pk=None):
        transaksi = self.get_object()
        result = WhatsAppService.notify(transaksi)
        return Response(result, status=200 if result["success"] else 400)


class SaldoView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = SaldoSerializer

    def get(self, request, pk):
        nasabah = Nasabah.objects.filter(id=pk, bank_sampah=request.user.bank_sampah).first()
        if not nasabah:
            return Response({"error": "Resource tidak ditemukan"}, status=404)
        saldo, _ = Saldo.objects.get_or_create(nasabah=nasabah)
        return Response(SaldoSerializer(saldo).data)


class DashboardStatsView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = AuthUserSerializer

    def get(self, request):
        return Response(DashboardService.stats(request.user))


class DashboardRecentTransactionsView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = TransactionListSerializer

    def get(self, request):
        qs = (
            Transaksi.objects.filter(bank_sampah=request.user.bank_sampah)
            .select_related("nasabah", "dicatat_oleh")
            .prefetch_related("items")
            .order_by("-tanggal")[:3]
        )
        return Response({"transactions": TransactionListSerializer(qs, many=True).data})


class WATemplateView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = WATemplateSerializer

    def get(self, request):
        bank = request.user.bank_sampah
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

    def put(self, request):
        serializer = WATemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = request.user.bank_sampah
        bank.wa_template = serializer.validated_data["template"]
        bank.save(update_fields=["wa_template", "updated_at"])
        return Response({"template": bank.wa_template, "message": "Template berhasil disimpan"})


class TeamView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = TeamMemberSerializer

    def get(self, request):
        members = User.objects.filter(bank_sampah=request.user.bank_sampah, role=User.Role.PENGELOLA, is_active=True).order_by(
            "-is_primary_pengelola", "nama"
        )
        return Response({"members": TeamMemberSerializer(members, many=True, context={"request": request}).data})


class GenerateInviteView(APIView):
    permission_classes = [IsPrimaryPengelola]
    serializer_class = InviteAcceptSerializer

    def post(self, request):
        token = TeamService.generate_invite(request.user.bank_sampah)
        invite_path = f"/invite?{urlencode({'token': token})}"
        base_url = request.build_absolute_uri("/")[:-1]
        public_base = getattr(settings, "PILAH_PUBLIC_APP_URL", "") or base_url
        return Response(
            {
                "token": token,
                "invite_url": f"{public_base}{invite_path}",
                "expires_at": request.user.bank_sampah.invite_token_expires,
            },
            status=201,
        )


class SuperAdminBankSampahViewSet(viewsets.GenericViewSet):
    permission_classes = [IsSuperAdmin]
    serializer_class = BankSampahApprovalListSerializer
    queryset = BankSampah.objects.all().order_by("created_at")

    def list(self, request):
        status_filter = request.query_params.get("status", BankSampah.Status.PENDING)
        qs = self.get_queryset()
        if status_filter in [BankSampah.Status.PENDING, BankSampah.Status.ACTIVE, BankSampah.Status.REJECTED]:
            qs = qs.filter(status=status_filter)
        serializer = self.get_serializer(qs, many=True)
        return Response({"count": qs.count(), "results": serializer.data})

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        bank = self.get_object()
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = ApprovalService.approve(bank, request.user, serializer.validated_data.get("catatan", ""))
        return Response({"bank_sampah": self.get_serializer(bank).data, "approval_log": ApprovalLogSerializer(log).data})

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        bank = self.get_object()
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = ApprovalService.reject(bank, request.user, serializer.validated_data.get("catatan", ""))
        return Response({"bank_sampah": self.get_serializer(bank).data, "approval_log": ApprovalLogSerializer(log).data})
