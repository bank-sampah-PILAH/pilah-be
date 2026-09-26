import json
from typing import Any

import requests
from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.http import urlencode
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, User
from apps.identity.serializers import (
    AuthUserSerializer,
    GoogleAuthSerializer,
    InviteAcceptSerializer,
    LogoutSerializer,
    RefreshTokenSerializer,
    TeamMemberSerializer,
    UserProfileSerializer,
)
from apps.identity.services import AuthService, OnboardingService, TeamService
from apps.organization.serializers import (
    BankSampahRegistrationSerializer,
    BankSampahSerializer,
)
from shared_kernel.permissions import IsActivePengelola, IsPengelola, IsPrimaryPengelola


def _user(request: Request) -> User:
    # ponytail: dup of api.views._user; the close phase extracts one shared
    # request helper once all views have moved.
    assert isinstance(request.user, User)
    return request.user


def _bank_sampah(request: Request) -> BankSampah:
    bank = _user(request).bank_sampah
    assert bank is not None
    return bank


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]
    serializer_class = GoogleAuthSerializer

    def post(self, request: Request) -> Response:
        token = request.data.get("id_token")  # type: ignore[union-attr]  # DRF types request.data as dict | list; these payloads are objects
        if not token:
            return Response({"errors": {"id_token": ["Google ID Token wajib diisi"]}}, status=422)
        try:
            return Response(AuthService.login_with_google(token))
        except Exception:
            return Response({"error": "ID Token invalid atau expired"}, status=401)


class GoogleOAuthStartView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> HttpResponseRedirect | Response:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            return Response({"error": "Google OAuth client is not configured"}, status=503)
        redirect_uri = settings.GOOGLE_REDIRECT_URI or request.build_absolute_uri(
            "/api/v1/auth/google/callback"
        )
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

    def get(self, request: Request) -> HttpResponse:
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

        redirect_uri = settings.GOOGLE_REDIRECT_URI or request.build_absolute_uri(
            "/api/v1/auth/google/callback"
        )
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
                return self._popup_response(
                    False, {"error": "Google did not return an ID token"}, next_url
                )
            return self._popup_response(True, AuthService.login_with_google(id_token), next_url)
        except Exception as exc:
            return self._popup_response(False, {"error": str(exc)}, next_url)

    @staticmethod
    def _popup_response(ok: bool, payload: Any, next_url: str = "/api-test/") -> HttpResponse:
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

    def post(self, request: Request) -> Response:
        raw_refresh = request.data.get("refresh_token")  # type: ignore[union-attr]  # DRF types request.data as dict | list; these payloads are objects
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

    def post(self, request: Request) -> Response:
        raw_refresh = request.data.get("refresh_token")  # type: ignore[union-attr]  # DRF types request.data as dict | list; these payloads are objects
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except Exception:
                pass
        return Response({"message": "Logout berhasil"})


class AuthMeView(APIView):
    serializer_class = AuthUserSerializer

    def get(self, request: Request) -> Response:
        data = AuthUserSerializer(_user(request)).data
        data["state"] = AuthService.user_state(_user(request))
        return Response(data)


class CompleteProfileView(APIView):
    permission_classes = [IsPengelola]
    serializer_class = UserProfileSerializer

    def put(self, request: Request) -> Response:
        serializer = UserProfileSerializer(_user(request), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            user = OnboardingService.complete_profile(_user(request), serializer.validated_data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = UserProfileSerializer(user).data
        data["next_step"] = AuthService.user_state(user)
        return Response(data)


class RegisterBankSampahView(APIView):
    permission_classes = [IsPengelola]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = BankSampahRegistrationSerializer

    def post(self, request: Request) -> Response:
        serializer = BankSampahRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bank = OnboardingService.register_bank_sampah(_user(request), serializer.validated_data)
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = BankSampahSerializer(bank).data
        data["next_step"] = AuthService.user_state(_user(request))
        return Response(data, status=201)


class AcceptInviteView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InviteAcceptSerializer

    def post(self, request: Request) -> Response:
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bank, outcome = OnboardingService.accept_invite(
                _user(request), serializer.validated_data["token"]
            )
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        data = BankSampahSerializer(bank).data
        data["next_step"] = AuthService.user_state(_user(request))
        data["outcome"] = outcome
        data["bank_sampah_id"] = str(bank.id)
        data["bank_sampah_nama"] = bank.nama
        if outcome == "already_member":
            data["message"] = "Anda sudah terdaftar pada bank sampah ini"
        else:
            data["message"] = f"Berhasil bergabung ke Bank Sampah {bank.nama}"
        return Response(data)


class TeamView(APIView):
    permission_classes = [IsActivePengelola]
    serializer_class = TeamMemberSerializer

    def get(self, request: Request) -> Response:
        members = User.objects.filter(
            bank_sampah=_bank_sampah(request), role=User.Role.PENGELOLA, is_active=True
        ).order_by("-is_primary_pengelola", "nama")
        return Response(
            {"members": TeamMemberSerializer(members, many=True, context={"request": request}).data}
        )


class GenerateInviteView(APIView):
    permission_classes = [IsPrimaryPengelola]
    serializer_class = InviteAcceptSerializer

    def post(self, request: Request) -> Response:
        bank = _bank_sampah(request)
        token = TeamService.generate_invite(bank)
        invite_path = f"/invite?{urlencode({'token': token})}"
        base_url = request.build_absolute_uri("/")[:-1]
        public_base = getattr(settings, "PILAH_PUBLIC_APP_URL", "") or base_url
        return Response(
            {
                "token": token,
                "invite_url": f"{public_base}{invite_path}",
                "expires_at": bank.invite_token_expires,
            },
            status=201,
        )
