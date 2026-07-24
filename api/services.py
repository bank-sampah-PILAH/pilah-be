from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import secrets

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from openpyxl import Workbook
import requests
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, BankSampahApprovalLog, DetailTransaksi, JenisSampah, Nasabah, Saldo, Transaksi, User

DEFAULT_WA_TEMPLATE = (
    "Halo {Nama}, setoran sampahmu senilai {Total} sudah kami catat ya.\n"
    "Saldo tabunganmu sekarang adalah Rp {Saldo}.\n"
    "{daftar_item}\n"
    "Terima kasih! 🌿"
)


class AuthService:
    @staticmethod
    def login_with_google(raw_id_token):
        profile = AuthService._verify_google_token(raw_id_token)
        email = profile["email"]
        google_id = profile["sub"]
        name = profile.get("name") or email.split("@")[0]
        role = profile.get("role", User.Role.PENGELOLA)

        user = User.objects.filter(email=email).first()
        is_new_user = user is None
        if is_new_user:
            user = User.objects.create_user(
                email=email,
                google_id=google_id,
                nama=name,
                role=role,
                is_profile_complete=False,
            )
        else:
            updates = []
            if not user.google_id:
                user.google_id = google_id
                updates.append("google_id")
            if not user.nama:
                user.nama = name
                updates.append("nama")
            if updates:
                user.save(update_fields=updates)

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        if user.bank_sampah_id:
            access["bank_sampah_id"] = str(user.bank_sampah_id)
        access["role"] = user.role
        access["email"] = user.email
        state = AuthService.user_state(user)
        return {
            "access_token": str(access),
            "refresh_token": str(refresh),
            "token_type": "Bearer",
            "expires_in": int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            "user": {
                "id": str(user.id),
                "name": user.nama,
                "nama": user.nama,
                "email": user.email,
                "role": user.role,
                "bank_sampah_id": str(user.bank_sampah_id) if user.bank_sampah_id else None,
                "bank_sampah_nama": user.bank_sampah.nama if user.bank_sampah_id else None,
                "bank_sampah_status": user.bank_sampah.status if user.bank_sampah_id else None,
                "is_profile_complete": user.is_profile_complete,
                "is_primary_pengelola": user.is_primary_pengelola,
                "state": state,
            },
            "next_step": state,
            "is_new_user": is_new_user,
        }

    @staticmethod
    def user_state(user):
        if user.role == User.Role.SUPERADMIN:
            return "superadmin_dashboard"
        if not user.is_profile_complete:
            return "complete_profile"
        if not user.bank_sampah_id:
            return "register_bank_sampah"
        if user.bank_sampah.status == BankSampah.Status.PENDING:
            return "approval_pending"
        if user.bank_sampah.status == BankSampah.Status.REJECTED:
            return "registration_rejected"
        return "dashboard"

    @staticmethod
    def _verify_google_token(raw_id_token):
        if settings.PILAH_ALLOW_FAKE_GOOGLE_TOKEN and raw_id_token.startswith("dev-superadmin:"):
            _, email, name = (raw_id_token.split(":", 2) + [""])[:3]
            return {"sub": f"dev-superadmin-{email}", "email": email, "name": name or email.split("@")[0], "role": User.Role.SUPERADMIN}
        if settings.PILAH_ALLOW_FAKE_GOOGLE_TOKEN and raw_id_token.startswith("dev:"):
            _, email, name = (raw_id_token.split(":", 2) + [""])[:3]
            return {"sub": f"dev-{email}", "email": email, "name": name or email.split("@")[0]}
        audience = settings.GOOGLE_CLIENT_ID or None
        try:
            return google_id_token.verify_oauth2_token(raw_id_token, google_requests.Request(), audience)
        except Exception as exc:
            raise serializers.ValidationError({"id_token": ["ID Token invalid atau expired"]}) from exc


class NumberingService:
    @staticmethod
    def next_nasabah_number(bank_sampah):
        count = Nasabah.objects.filter(bank_sampah=bank_sampah).count() + 1
        return f"NAS-{count:04d}"

    @staticmethod
    def next_jenis_number(bank_sampah):
        count = JenisSampah.objects.filter(bank_sampah=bank_sampah).count() + 1
        return f"JS-{count:04d}"


class OnboardingService:
    @staticmethod
    @transaction.atomic
    def complete_profile(user, profile_data):
        if user.is_profile_complete:
            raise ValueError("Profil sudah lengkap")
        for field, value in profile_data.items():
            setattr(user, field, value)
        user.is_profile_complete = True
        user.save(update_fields=["nama", "no_hp", "jenis_kelamin", "tanggal_lahir", "is_profile_complete", "updated_at"])
        return user

    @staticmethod
    @transaction.atomic
    def register_bank_sampah(user, payload):
        if user.role != User.Role.PENGELOLA:
            raise PermissionError("Hanya pengelola yang dapat mendaftarkan bank sampah")
        bank = user.bank_sampah
        if bank and bank.status == BankSampah.Status.ACTIVE:
            raise ValueError("Bank sampah sudah aktif")
        if bank and bank.status == BankSampah.Status.PENDING:
            raise ValueError("Pendaftaran bank sampah sedang diproses")
        if bank is None:
            bank = BankSampah()
        bank.nama = payload["nama"]
        bank.alamat = payload["alamat"]
        bank.kota = payload.get("kota", "")
        bank.no_hp_pic = payload["no_hp_pic"]
        bank.foto_kegiatan = payload["foto_kegiatan"]
        bank.status = BankSampah.Status.PENDING
        bank.is_active = False
        bank.wa_template = bank.wa_template or DEFAULT_WA_TEMPLATE
        bank.save()
        user.bank_sampah = bank
        user.is_primary_pengelola = True
        user.save(update_fields=["bank_sampah", "is_primary_pengelola", "updated_at"])
        return bank

    @staticmethod
    @transaction.atomic
    def accept_invite(user, token):
        bank = BankSampah.objects.filter(invite_token=token, invite_token_expires__gt=timezone.now()).first()
        if not bank or bank.status != BankSampah.Status.ACTIVE:
            raise ValueError("Tautan undangan tidak valid atau sudah kedaluwarsa")
        if user.role != User.Role.PENGELOLA:
            raise PermissionError("Hanya pengelola yang dapat menerima undangan")
        if user.bank_sampah_id == bank.id:
            return bank, "already_member"
        if user.bank_sampah_id and user.bank_sampah.status in [BankSampah.Status.ACTIVE, BankSampah.Status.PENDING]:
            raise ValueError("Akun ini sudah tergabung dengan bank sampah")
        outcome = "join_success"
        user.bank_sampah = bank
        user.is_primary_pengelola = False
        if user.nama and user.no_hp and user.jenis_kelamin and user.tanggal_lahir:
            user.is_profile_complete = True
        user.save(update_fields=["bank_sampah", "is_primary_pengelola", "is_profile_complete", "updated_at"])
        return bank, outcome


class ApprovalService:
    @staticmethod
    @transaction.atomic
    def approve(bank, superadmin, catatan=""):
        bank.status = BankSampah.Status.ACTIVE
        bank.is_active = True
        bank.save(update_fields=["status", "is_active", "updated_at"])
        return BankSampahApprovalLog.objects.create(
            bank_sampah=bank,
            superadmin=superadmin,
            status=BankSampahApprovalLog.Status.APPROVED,
            catatan=catatan,
        )

    @staticmethod
    @transaction.atomic
    def reject(bank, superadmin, catatan=""):
        bank.status = BankSampah.Status.REJECTED
        bank.is_active = False
        bank.save(update_fields=["status", "is_active", "updated_at"])
        return BankSampahApprovalLog.objects.create(
            bank_sampah=bank,
            superadmin=superadmin,
            status=BankSampahApprovalLog.Status.REJECTED,
            catatan=catatan,
        )


class TeamService:
    @staticmethod
    def generate_invite(bank):
        bank.invite_token = secrets.token_urlsafe(32)
        bank.invite_token_expires = timezone.now() + timedelta(days=3)
        bank.save(update_fields=["invite_token", "invite_token_expires", "updated_at"])
        return bank.invite_token


class TransactionService:
    @staticmethod
    @transaction.atomic
    def create_setoran(user, payload):
        bank = user.bank_sampah
        nasabah = Nasabah.objects.select_for_update().filter(
            id=payload["nasabah_id"], bank_sampah=bank, is_active=True
        ).first()
        if not nasabah:
            raise serializers.ValidationError({"nasabah_id": ["Nasabah tidak ditemukan atau tidak aktif"]})

        saldo, _ = Saldo.objects.select_for_update().get_or_create(nasabah=nasabah)
        transaksi = Transaksi.objects.create(
            nasabah=nasabah,
            bank_sampah=bank,
            dicatat_oleh=user,
            catatan=payload.get("catatan") or None,
        )

        total_nilai = Decimal("0.00")
        for index, item_payload in enumerate(payload["items"]):
            jenis = JenisSampah.objects.filter(
                id=item_payload["jenis_sampah_id"], bank_sampah=bank, is_active=True
            ).first()
            if not jenis:
                raise serializers.ValidationError({f"items[{index}].jenis_sampah_id": ["Jenis sampah tidak ditemukan atau tidak aktif"]})
            harga = item_payload.get("harga_per_kg") or jenis.harga_per_kg
            berat = item_payload["berat"]
            subtotal = (harga * berat).quantize(Decimal("0.01"))
            DetailTransaksi.objects.create(
                transaksi=transaksi,
                jenis_sampah=jenis,
                nama_sampah_snapshot=jenis.nama_sampah,
                kategori_snapshot=jenis.kategori,
                harga_snapshot=harga,
                berat=berat,
                subtotal=subtotal,
            )
            total_nilai += subtotal

        transaksi.total_nilai = total_nilai
        transaksi.save(update_fields=["total_nilai"])
        saldo.total_saldo += total_nilai
        saldo.save(update_fields=["total_saldo", "updated_at"])
        return transaksi


class TransactionFilterService:
    @staticmethod
    def apply_period(queryset, request):
        periode = request.query_params.get("periode", "hari_ini")
        today = timezone.localdate()
        if periode == "hari_ini":
            start, end = today, today
        elif periode == "minggu_ini":
            start, end = today - timedelta(days=today.weekday()), today
        elif periode == "bulan_ini":
            start, end = today.replace(day=1), today
        elif periode == "bulan_lalu":
            first_this_month = today.replace(day=1)
            last_previous_month = first_this_month - timedelta(days=1)
            start = last_previous_month.replace(day=1)
            end = last_previous_month
        elif periode == "custom":
            start = TransactionFilterService._parse_date(request.query_params.get("dari_tanggal"))
            end = TransactionFilterService._parse_date(request.query_params.get("sampai_tanggal"))
            if not start or not end:
                raise serializers.ValidationError({"error": "dari_tanggal dan sampai_tanggal wajib diisi"})
            if end < start:
                raise ValueError("Tanggal akhir tidak boleh lebih awal dari tanggal awal")
        else:
            return queryset

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(end, time.max), tz)
        return queryset.filter(tanggal__range=(start_dt, end_dt))

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise serializers.ValidationError({"error": "Format tanggal harus YYYY-MM-DD"}) from exc


class DashboardService:
    @staticmethod
    def stats(user):
        today = timezone.localdate()
        start = today.replace(day=1)
        end = today.replace(day=monthrange(today.year, today.month)[1])
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(start, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(end, time.max), tz)

        transaksi = Transaksi.objects.filter(bank_sampah=user.bank_sampah, tanggal__range=(start_dt, end_dt))
        totals = DetailTransaksi.objects.filter(transaksi__in=transaksi).aggregate(
            total_kg=Coalesce(Sum("berat"), Decimal("0")),
        )
        nilai = transaksi.aggregate(total=Coalesce(Sum("total_nilai"), Decimal("0")))["total"]
        return {
            "bank_sampah_nama": user.bank_sampah.nama,
            "pengelola_nama": user.nama,
            "periode": today.strftime("%Y-%m"),
            "nasabah_aktif": Nasabah.objects.filter(bank_sampah=user.bank_sampah, is_active=True).count(),
            "transaksi_bulan_ini": transaksi.count(),
            "total_sampah_kg_bulan_ini": totals["total_kg"],
            "total_nilai_bulan_ini": nilai,
        }


class WhatsAppService:
    @staticmethod
    def get_template(bank_sampah):
        return bank_sampah.wa_template or DEFAULT_WA_TEMPLATE

    @staticmethod
    def preview(bank_sampah):
        daftar_item = WhatsAppService.format_daftar_item(
            [
                {
                    "nama_sampah_snapshot": "Plastik PET",
                    "berat": Decimal("5.200"),
                }
            ]
        )
        daftar_item_harga = WhatsAppService.format_daftar_item_harga(
            [
                {
                    "nama_sampah_snapshot": "Plastik PET",
                    "berat": Decimal("5.200"),
                    "harga_snapshot": Decimal("3500"),
                    "subtotal": Decimal("18200"),
                }
            ]
        )
        message = WhatsAppService.render(
            WhatsAppService.get_template(bank_sampah),
            nama="Budi Santoso",
            total=Decimal("15600"),
            saldo=Decimal("125000"),
            tanggal=timezone.localdate(),
            daftar_item=daftar_item,
            daftar_item_harga=daftar_item_harga,
        )
        return message

    @staticmethod
    def notify(transaksi):
        if not transaksi.nasabah.no_hp:
            transaksi.status_wa = Transaksi.StatusWA.GAGAL
            transaksi.save(update_fields=["status_wa"])
            return {"success": False, "status_wa": transaksi.status_wa, "error": "Nomor tidak aktif di WhatsApp"}
        message = WhatsAppService.message_for_transaction(transaksi)
        has_twilio_auth = settings.TWILIO_AUTH_TOKEN or (settings.TWILIO_API_KEY_SID and settings.TWILIO_API_KEY_SECRET)
        has_any_twilio_env = any(
            [
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN,
                settings.TWILIO_API_KEY_SID,
                settings.TWILIO_API_KEY_SECRET,
                settings.TWILIO_WHATSAPP_FROM,
                settings.TWILIO_MESSAGING_SERVICE_SID,
            ]
        )
        if settings.TWILIO_ACCOUNT_SID and has_twilio_auth:
            return WhatsAppService.notify_twilio(transaksi, message)
        if has_any_twilio_env:
            transaksi.status_wa = Transaksi.StatusWA.GAGAL
            transaksi.save(update_fields=["status_wa"])
            return {
                "success": False,
                "status_wa": transaksi.status_wa,
                "error": "Konfigurasi Twilio belum lengkap",
            }
        if settings.WHATSAPP_GATEWAY_URL:
            try:
                response = requests.post(
                    settings.WHATSAPP_GATEWAY_URL,
                    json={"to": transaksi.nasabah.no_hp, "message": message},
                    headers=WhatsAppService.gateway_headers(transaksi.bank_sampah),
                    timeout=settings.WHATSAPP_GATEWAY_TIMEOUT,
                )
                if response.status_code >= 400:
                    transaksi.status_wa = Transaksi.StatusWA.GAGAL
                    transaksi.save(update_fields=["status_wa"])
                    return {"success": False, "status_wa": transaksi.status_wa, "error": response.text or "Gagal kirim WhatsApp"}
                transaksi.status_wa = Transaksi.StatusWA.TERKIRIM
                transaksi.save(update_fields=["status_wa"])
                return {
                    "success": True,
                    "status_wa": transaksi.status_wa,
                    "message": "Notifikasi WhatsApp berhasil dikirim",
                    "provider": "gateway",
                }
            except requests.RequestException as exc:
                transaksi.status_wa = Transaksi.StatusWA.GAGAL
                transaksi.save(update_fields=["status_wa"])
                return {"success": False, "status_wa": transaksi.status_wa, "error": str(exc)}
        transaksi.status_wa = Transaksi.StatusWA.GAGAL
        transaksi.save(update_fields=["status_wa"])
        return {
            "success": False,
            "status_wa": transaksi.status_wa,
            "error": "Konfigurasi WhatsApp/Twilio belum diisi",
        }

    @staticmethod
    def notify_twilio(transaksi, message):
        if not settings.TWILIO_WHATSAPP_FROM and not settings.TWILIO_MESSAGING_SERVICE_SID:
            transaksi.status_wa = Transaksi.StatusWA.GAGAL
            transaksi.save(update_fields=["status_wa"])
            return {
                "success": False,
                "status_wa": transaksi.status_wa,
                "error": "TWILIO_WHATSAPP_FROM atau TWILIO_MESSAGING_SERVICE_SID wajib diisi",
            }

        payload = {
            "To": WhatsAppService.twilio_whatsapp_number(transaksi.nasabah.no_hp),
            "Body": message,
        }
        if settings.TWILIO_MESSAGING_SERVICE_SID:
            payload["MessagingServiceSid"] = settings.TWILIO_MESSAGING_SERVICE_SID
        else:
            payload["From"] = settings.TWILIO_WHATSAPP_FROM

        auth_user = settings.TWILIO_API_KEY_SID or settings.TWILIO_ACCOUNT_SID
        auth_password = settings.TWILIO_API_KEY_SECRET or settings.TWILIO_AUTH_TOKEN
        try:
            response = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json",
                data=payload,
                auth=(auth_user, auth_password),
                timeout=settings.WHATSAPP_GATEWAY_TIMEOUT,
            )
            try:
                response_payload = response.json()
            except ValueError:
                response_payload = {}
            if response.status_code >= 400:
                transaksi.status_wa = Transaksi.StatusWA.GAGAL
                transaksi.save(update_fields=["status_wa"])
                return {
                    "success": False,
                    "status_wa": transaksi.status_wa,
                    "error": response_payload.get("message") or response.text or "Gagal kirim WhatsApp via Twilio",
                    "provider": "twilio",
                }
            transaksi.status_wa = Transaksi.StatusWA.TERKIRIM
            transaksi.save(update_fields=["status_wa"])
            return {
                "success": True,
                "status_wa": transaksi.status_wa,
                "message": "Notifikasi WhatsApp berhasil dikirim",
                "provider": "twilio",
                "provider_message_id": response_payload.get("sid"),
            }
        except requests.RequestException as exc:
            transaksi.status_wa = Transaksi.StatusWA.GAGAL
            transaksi.save(update_fields=["status_wa"])
            return {"success": False, "status_wa": transaksi.status_wa, "error": str(exc), "provider": "twilio"}

    @staticmethod
    def twilio_whatsapp_number(phone):
        phone = str(phone).strip()
        return phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

    @staticmethod
    def gateway_headers(bank_sampah):
        token = bank_sampah.wa_gateway_token or settings.WHATSAPP_GATEWAY_TOKEN
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def message_for_transaction(transaksi):
        items = list(transaksi.items.all())
        daftar_item = WhatsAppService.format_daftar_item(items)
        daftar_item_harga = WhatsAppService.format_daftar_item_harga(items)
        return WhatsAppService.render(
            WhatsAppService.get_template(transaksi.bank_sampah),
            nama=transaksi.nasabah.nama,
            total=transaksi.total_nilai,
            saldo=transaksi.nasabah.saldo.total_saldo,
            tanggal=timezone.localtime(transaksi.tanggal).date(),
            daftar_item=daftar_item,
            daftar_item_harga=daftar_item_harga,
        )

    @staticmethod
    def render(template, nama, total, saldo, tanggal, daftar_item, daftar_item_harga=""):
        return (
            template.replace("{Nama}", nama)
            .replace("{Total}", WhatsAppService.format_rupiah(total))
            .replace("{Saldo}", WhatsAppService.format_rupiah(saldo))
            .replace("{Tanggal}", tanggal.isoformat())
            .replace("{daftar_item_harga}", daftar_item_harga)
            .replace("{daftar_item}", daftar_item)
        )

    @staticmethod
    def format_rupiah(value):
        return f"Rp {int(value):,}".replace(",", ".")

    @staticmethod
    def format_kg(value):
        rounded = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        normalized = rounded.normalize()
        if normalized == normalized.to_integral():
            text = f"{normalized:.0f}"
        else:
            text = format(normalized, "f")
        return text.replace(".", ",")

    @staticmethod
    def format_daftar_item(items):
        return "\n".join(
            (
                f"- {WhatsAppService.get_item_value(item, 'nama_sampah_snapshot')} "
                f"{WhatsAppService.format_kg(WhatsAppService.get_item_value(item, 'berat'))} kg"
            )
            for item in items
        )

    @staticmethod
    def format_daftar_item_harga(items):
        return "\n".join(
            (
                f"- {WhatsAppService.get_item_value(item, 'nama_sampah_snapshot')} "
                f"{WhatsAppService.format_kg(WhatsAppService.get_item_value(item, 'berat'))} kg x "
                f"{WhatsAppService.format_rupiah(WhatsAppService.get_item_value(item, 'harga_snapshot'))} = "
                f"{WhatsAppService.format_rupiah(WhatsAppService.get_item_value(item, 'subtotal'))}"
            )
            for item in items
        )

    @staticmethod
    def get_item_value(item, field):
        if isinstance(item, dict):
            return item[field]
        return getattr(item, field)


def _month_label():
    return timezone.localdate().strftime("%B_%Y")


class TransactionExportMixin:
    pass


def _export_excel(queryset):
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan"
    ws.append(["Jenis", "Sampah", "Harga per kg", "Jumlah kg", "Total"])
    rows = (
        DetailTransaksi.objects.filter(transaksi__in=queryset)
        .values("kategori_snapshot", "nama_sampah_snapshot", "harga_snapshot")
        .annotate(total_kg=Sum("berat"))
        .order_by("kategori_snapshot", "nama_sampah_snapshot")
    )
    current_row = 2
    for row in rows:
        ws.append(
            [
                row["kategori_snapshot"],
                row["nama_sampah_snapshot"],
                float(row["harga_snapshot"]),
                float(row["total_kg"]),
                f"=C{current_row}*D{current_row}",
            ]
        )
        current_row += 1
    ws.append(["", "", "", "TOTAL", f"=SUM(E2:E{current_row - 1})"])
    for column in ["A", "B", "C", "D", "E"]:
        ws.column_dimensions[column].width = 22
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue(), f"PILAH_Laporan_{_month_label()}.xlsx"


TransactionService.export_excel = staticmethod(_export_excel)
