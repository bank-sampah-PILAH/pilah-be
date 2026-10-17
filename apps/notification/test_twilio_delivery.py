from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.test import override_settings
from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, Transaksi, User
from apps.waste_catalog.api import buat_jenis_sampah

TWILIO = {
    "TWILIO_ACCOUNT_SID": "ACx",
    "TWILIO_AUTH_TOKEN": "tok",
    "TWILIO_API_KEY_SID": "",
    "TWILIO_API_KEY_SECRET": "",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+1000",
    "TWILIO_MESSAGING_SERVICE_SID": "",
    "TWILIO_CONTENT_SID": "",
    "WHATSAPP_GATEWAY_URL": "",
}


class TwilioDeliveryTests(APITestCase):
    def setUp(self) -> None:
        bank = BankSampah.objects.create(nama="Bank WA", alamat="Depok", kota="Depok")
        pengelola = User.objects.create_user(
            email="wa@example.test",
            nama="Pengurus",
            bank_sampah=bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        nasabah = Nasabah.objects.create(
            bank_sampah=bank, nomor="NAS-0001", nama="Budi", no_hp="+628123456789"
        )
        jenis = buat_jenis_sampah(
            bank_sampah=bank, nomor="PET", nama_sampah="Botol PET", harga_per_kg=Decimal(3000)
        )
        self.client.force_authenticate(pengelola)
        created = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": str(jenis.id), "berat": "2.000"}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.url = f"/api/v1/transaksi/{created.data['id']}/notify-wa"
        self.transaksi_id = created.data["id"]

    def _notify(self, post: Mock) -> object:
        with patch("apps.notification.services.requests.post", post):
            return self.client.post(self.url, {}, format="json")

    @override_settings(**{**TWILIO, "TWILIO_MESSAGING_SERVICE_SID": "MG123"})
    def test_messaging_service_replaces_the_from_number(self) -> None:
        post = Mock(return_value=Mock(status_code=201, json=Mock(return_value={"sid": "SM1"})))

        response = self._notify(post)

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["MessagingServiceSid"], "MG123")
        self.assertNotIn("From", data)

    @override_settings(**TWILIO)
    def test_non_json_success_response_is_still_a_delivery(self) -> None:
        post = Mock(return_value=Mock(status_code=201, json=Mock(side_effect=ValueError)))

        response = self._notify(post)

        self.assertEqual(response.status_code, 200)  # type: ignore[attr-defined]
        self.assertIsNone(response.data["provider_message_id"])  # type: ignore[attr-defined]

    @override_settings(**TWILIO)
    def test_non_json_error_response_reports_the_response_text(self) -> None:
        post = Mock(
            return_value=Mock(
                status_code=502, text="Bad Gateway", json=Mock(side_effect=ValueError)
            )
        )

        response = self._notify(post)

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]
        self.assertEqual(response.data["error"], "Bad Gateway")  # type: ignore[attr-defined]

    @override_settings(**TWILIO)
    def test_network_failure_marks_the_receipt_as_failed(self) -> None:
        post = Mock(side_effect=requests.ConnectionError("unreachable"))

        response = self._notify(post)

        self.assertEqual(response.status_code, 400)  # type: ignore[attr-defined]
        self.assertEqual(response.data["error"], "unreachable")  # type: ignore[attr-defined]
        self.assertEqual(
            Transaksi.objects.get(pk=self.transaksi_id).status_wa, Transaksi.StatusWA.GAGAL
        )
