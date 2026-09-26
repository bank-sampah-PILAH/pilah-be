import json
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from api.models import BankSampah, DetailTransaksi, Transaksi

DEFAULT_WA_TEMPLATE = (
    "Halo {Nama}, setoran sampahmu senilai {Total} sudah kami catat ya.\n"
    "Saldo tabunganmu sekarang adalah Rp {Saldo}.\n"
    "{daftar_item}\n"
    "Terima kasih! 🌿"
)


class WhatsAppService:
    @staticmethod
    def get_template(bank_sampah: BankSampah) -> str:
        return bank_sampah.wa_template or DEFAULT_WA_TEMPLATE

    @staticmethod
    def preview(bank_sampah: BankSampah) -> str:
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
                    "harga_snapshot": Decimal(3500),
                    "subtotal": Decimal(18200),
                }
            ]
        )
        message = WhatsAppService.render(
            WhatsAppService.get_template(bank_sampah),
            nama="Budi Santoso",
            total=Decimal(15600),
            saldo=Decimal(125000),
            tanggal=timezone.localdate(),
            daftar_item=daftar_item,
            daftar_item_harga=daftar_item_harga,
        )
        return message

    @staticmethod
    def notify(transaksi: Transaksi) -> dict[str, Any]:
        if not transaksi.nasabah.no_hp:
            transaksi.status_wa = Transaksi.StatusWA.GAGAL
            transaksi.save(update_fields=["status_wa"])
            return {
                "success": False,
                "status_wa": transaksi.status_wa,
                "error": "Nomor tidak aktif di WhatsApp",
            }
        message = WhatsAppService.message_for_transaction(transaksi)
        has_twilio_auth = settings.TWILIO_AUTH_TOKEN or (
            settings.TWILIO_API_KEY_SID and settings.TWILIO_API_KEY_SECRET
        )
        has_any_twilio_env = any(
            [
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN,
                settings.TWILIO_API_KEY_SID,
                settings.TWILIO_API_KEY_SECRET,
                settings.TWILIO_WHATSAPP_FROM,
                settings.TWILIO_MESSAGING_SERVICE_SID,
                settings.TWILIO_CONTENT_SID,
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
                    return {
                        "success": False,
                        "status_wa": transaksi.status_wa,
                        "error": response.text or "Gagal kirim WhatsApp",
                    }
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
    def notify_twilio(transaksi: Transaksi, message: str) -> dict[str, Any]:
        if not settings.TWILIO_WHATSAPP_FROM and not settings.TWILIO_MESSAGING_SERVICE_SID:
            transaksi.status_wa = Transaksi.StatusWA.GAGAL
            transaksi.save(update_fields=["status_wa"])
            return {
                "success": False,
                "status_wa": transaksi.status_wa,
                "error": "TWILIO_WHATSAPP_FROM atau TWILIO_MESSAGING_SERVICE_SID wajib diisi",
            }

        payload = {"To": WhatsAppService.twilio_whatsapp_number(transaksi.nasabah.no_hp)}
        if settings.TWILIO_CONTENT_SID:
            payload.update(
                {
                    "ContentSid": settings.TWILIO_CONTENT_SID,
                    "ContentVariables": json.dumps(
                        WhatsAppService.content_variables_for_transaction(transaksi),
                        ensure_ascii=False,
                    ),
                }
            )
        else:
            payload["Body"] = message
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
                    "error": response_payload.get("message")
                    or response.text
                    or "Gagal kirim WhatsApp via Twilio",
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
            return {
                "success": False,
                "status_wa": transaksi.status_wa,
                "error": str(exc),
                "provider": "twilio",
            }

    @staticmethod
    def content_variables_for_transaction(transaksi: Transaksi) -> dict[str, str]:
        return {
            "1": transaksi.nasabah.nama,
            "2": WhatsAppService.format_daftar_item(transaksi.items.all()),
        }

    @staticmethod
    def twilio_whatsapp_number(phone: str) -> str:
        phone = str(phone).strip()
        return phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

    @staticmethod
    def gateway_headers(bank_sampah: BankSampah) -> dict[str, str]:
        token = bank_sampah.wa_gateway_token or settings.WHATSAPP_GATEWAY_TOKEN
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def message_for_transaction(transaksi: Transaksi) -> str:
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
    def render(
        template: str,
        nama: str,
        total: Decimal,
        saldo: Decimal,
        tanggal: date,
        daftar_item: str,
        daftar_item_harga: str = "",
    ) -> str:
        return (
            template.replace("{Nama}", nama)
            .replace("{Total}", WhatsAppService.format_rupiah(total))
            .replace("{Saldo}", WhatsAppService.format_rupiah(saldo))
            .replace("{Tanggal}", tanggal.isoformat())
            .replace("{daftar_item_harga}", daftar_item_harga)
            .replace("{daftar_item}", daftar_item)
        )

    @staticmethod
    def format_rupiah(value: Decimal) -> str:
        return f"Rp {int(value):,}".replace(",", ".")

    @staticmethod
    def format_kg(value: Decimal) -> str:
        rounded = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        normalized = rounded.normalize()
        if normalized == normalized.to_integral():
            text = f"{normalized:.0f}"
        else:
            text = format(normalized, "f")
        return text.replace(".", ",")

    @staticmethod
    def format_daftar_item(items: Iterable[Mapping[str, Any] | DetailTransaksi]) -> str:
        return "\n".join(
            (
                f"- {WhatsAppService.get_item_value(item, 'nama_sampah_snapshot')} "
                f"{WhatsAppService.format_kg(WhatsAppService.get_item_value(item, 'berat'))} kg"
            )
            for item in items
        )

    @staticmethod
    def format_daftar_item_harga(items: Iterable[Mapping[str, Any] | DetailTransaksi]) -> str:
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
    def get_item_value(item: Mapping[str, Any] | DetailTransaksi, field: str) -> Any:
        if isinstance(item, dict):
            return item[field]
        return getattr(item, field)
