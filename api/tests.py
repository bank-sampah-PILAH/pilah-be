from decimal import Decimal
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import BankSampah, BankSampahApprovalLog, JenisSampah, Nasabah, Saldo, User


class APISpecTests(APITestCase):
    def setUp(self):
        self.bank = BankSampah.objects.create(nama="Bank Sampah BTH", alamat="Depok", kota="Depok", no_hp_pic="+628123456789")
        self.user = User.objects.create_user(
            email="sari@example.com",
            nama="Ibu Sari",
            bank_sampah=self.bank,
            is_profile_complete=True,
            is_primary_pengelola=True,
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_bank_profile_update_normalizes_phone(self):
        response = self.client.put(
            "/api/v1/bank-sampah/me",
            {"nama": "Bank Sampah BTH", "alamat": "Kel. Kukusan", "kota": "Depok", "no_hp_pic": "081234567890"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["no_hp_pic"], "+6281234567890")
        self.assertEqual(response.data["pengelola"]["email"], "sari@example.com")

    def test_nasabah_create_list_detail_status_and_saldo(self):
        created = self.client.post(
            "/api/v1/nasabah",
            {
                "kode": "NAS-0001",
                "nama": "Budi Santoso",
                "jenis_kelamin": "laki-laki",
                "tanggal_lahir": "1990-01-01",
                "no_hp": "081234567890",
                "alamat": "Jl. Anggrek No. 3",
            },
            format="json",
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["kode"], "NAS-0001")
        self.assertEqual(created.data["total_saldo"], Decimal("0.00"))

        listed = self.client.get("/api/v1/nasabah?status=aktif")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)

        detail = self.client.get(f"/api/v1/nasabah/{created.data['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["ringkasan_transaksi"]["jumlah_transaksi"], 0)

        patched = self.client.patch(f"/api/v1/nasabah/{created.data['id']}/status", {"is_active": False}, format="json")
        self.assertEqual(patched.status_code, 200)
        self.assertFalse(patched.data["is_active"])

        inactive_update = self.client.put(
            f"/api/v1/nasabah/{created.data['id']}",
            {
                "kode": "NAS-0001",
                "nama": "Budi Santoso",
                "jenis_kelamin": "laki-laki",
                "tanggal_lahir": "1990-01-01",
                "no_hp": "081234567890",
                "alamat": "Jl. Anggrek No. 3",
            },
            format="json",
        )
        self.assertEqual(inactive_update.status_code, 403)

    def test_nasabah_duplicate_phone_returns_validation_error(self):
        first = self.client.post(
            "/api/v1/nasabah",
            {
                "kode": "NAS-0001",
                "nama": "Budi Santoso",
                "jenis_kelamin": "laki-laki",
                "tanggal_lahir": "1990-01-01",
                "no_hp": "081234567890",
                "alamat": "Jl. Anggrek No. 3",
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201)

        duplicate_create = self.client.post(
            "/api/v1/nasabah",
            {
                "kode": "NAS-0002",
                "nama": "Dewi Lestari",
                "jenis_kelamin": "perempuan",
                "tanggal_lahir": "1992-02-02",
                "no_hp": "+6281234567890",
                "alamat": "Jl. Melati No. 7",
            },
            format="json",
        )
        self.assertEqual(duplicate_create.status_code, 422)
        self.assertEqual(duplicate_create.data["errors"]["no_hp"], ["Nomor HP nasabah sudah digunakan"])

        second = self.client.post(
            "/api/v1/nasabah",
            {
                "kode": "NAS-0002",
                "nama": "Dewi Lestari",
                "jenis_kelamin": "perempuan",
                "tanggal_lahir": "1992-02-02",
                "no_hp": "081999999999",
                "alamat": "Jl. Melati No. 7",
            },
            format="json",
        )
        self.assertEqual(second.status_code, 201)

        duplicate_update = self.client.put(
            f"/api/v1/nasabah/{second.data['id']}",
            {
                "kode": "NAS-0002",
                "nama": "Dewi Lestari",
                "jenis_kelamin": "perempuan",
                "tanggal_lahir": "1992-02-02",
                "no_hp": "081234567890",
                "alamat": "Jl. Melati No. 7",
            },
            format="json",
        )
        self.assertEqual(duplicate_update.status_code, 422)
        self.assertEqual(duplicate_update.data["errors"]["no_hp"], ["Nomor HP nasabah sudah digunakan"])

    def test_jenis_sampah_and_transaction_update_saldo(self):
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0001",
            nama="Ahmad Ridwan",
            no_hp="+628123456789",
            alamat="Jl. Mawar No. 12",
        )
        Saldo.objects.create(nasabah=nasabah)
        jenis = self.client.post(
            "/api/v1/jenis-sampah",
            {"kode": "PLS-001", "nama_sampah": "Plastik PET", "kategori": "plastik", "deskripsi": "Botol bening", "harga_per_kg": 3500},
            format="json",
        )
        self.assertEqual(jenis.status_code, 201)

        transaksi = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": jenis.data["id"], "berat": "2.500"}],
                "catatan": "Setoran rutin",
            },
            format="json",
        )
        self.assertEqual(transaksi.status_code, 201)
        self.assertEqual(transaksi.data["total_nilai"], "8750.00")
        self.assertEqual(transaksi.data["saldo_setelah_transaksi"], Decimal("8750.00"))
        self.assertEqual(transaksi.data["items"][0]["harga_snapshot"], "3500.00")

        saldo = self.client.get(f"/api/v1/nasabah/{nasabah.id}/saldo")
        self.assertEqual(saldo.status_code, 200)
        self.assertEqual(saldo.data["total_saldo"], "8750.00")

        with self.settings(
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_API_KEY_SID="",
            TWILIO_API_KEY_SECRET="",
            TWILIO_WHATSAPP_FROM="",
            TWILIO_MESSAGING_SERVICE_SID="",
            WHATSAPP_GATEWAY_URL="",
        ):
            notify = self.client.post(f"/api/v1/transaksi/{transaksi.data['id']}/notify-wa")
        self.assertEqual(notify.status_code, 400)
        self.assertEqual(notify.data["status_wa"], "gagal")
        self.assertEqual(notify.data["error"], "Konfigurasi WhatsApp/Twilio belum diisi")

        export = self.client.get("/api/v1/transaksi/export?periode=bulan_ini")
        self.assertEqual(export.status_code, 200)
        self.assertEqual(
            export["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @patch("api.services.requests.post")
    def test_transaction_notify_wa_uses_twilio(self, post):
        post.return_value = Mock(status_code=201, json=lambda: {"sid": "SM123"}, text="")
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-0002",
            nama="Dewi Lestari",
            no_hp="+628111111111",
            alamat="Jl. Melati No. 9",
        )
        Saldo.objects.create(nasabah=nasabah)
        jenis = JenisSampah.objects.create(
            bank_sampah=self.bank,
            nomor="JS-0002",
            nama_sampah="Kardus",
            kategori="kertas",
            harga_per_kg=Decimal("2000"),
        )
        transaksi = self.client.post(
            "/api/v1/transaksi",
            {
                "nasabah_id": str(nasabah.id),
                "items": [{"jenis_sampah_id": str(jenis.id), "berat": "1.000"}],
            },
            format="json",
        )

        with self.settings(
            TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            TWILIO_AUTH_TOKEN="",
            TWILIO_API_KEY_SID="SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            TWILIO_API_KEY_SECRET="secret",
            TWILIO_WHATSAPP_FROM="whatsapp:+14155238886",
            TWILIO_MESSAGING_SERVICE_SID="",
            WHATSAPP_GATEWAY_URL="",
        ):
            notify = self.client.post(f"/api/v1/transaksi/{transaksi.data['id']}/notify-wa")

        self.assertEqual(notify.status_code, 200)
        self.assertEqual(notify.data["status_wa"], "terkirim")
        self.assertEqual(notify.data["provider"], "twilio")
        post.assert_called_once_with(
            "https://api.twilio.com/2010-04-01/Accounts/ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/Messages.json",
            data={
                "To": "whatsapp:+628111111111",
                "Body": post.call_args.kwargs["data"]["Body"],
                "From": "whatsapp:+14155238886",
            },
            auth=("SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "secret"),
            timeout=10,
        )

    def test_dashboard_and_wa_template(self):
        stats = self.client.get("/api/v1/dashboard/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.data["bank_sampah_nama"], "Bank Sampah BTH")

        template = self.client.get("/api/v1/pengaturan/wa-template")
        self.assertEqual(template.status_code, 200)
        self.assertIn("{Nama}", template.data["variabel_tersedia"])

        updated = self.client.put("/api/v1/pengaturan/wa-template", {"template": "Halo {Nama}, saldo {Saldo}"}, format="json")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["message"], "Template berhasil disimpan")

    def test_google_dev_auth(self):
        response = self.client.post("/api/v1/auth/google", {"id_token": "dev:new@example.com:New User"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["token_type"], "Bearer")
        self.assertTrue(response.data["is_new_user"])
        self.assertIsNone(response.data["user"]["bank_sampah_id"])
        self.assertEqual(response.data["next_step"], "complete_profile")

    def test_onboarding_superadmin_approval_and_invite_flow(self):
        self.client.credentials()
        login = self.client.post("/api/v1/auth/google", {"id_token": "dev:onboard@example.com:Onboard User"}, format="json")
        self.assertEqual(login.status_code, 200)
        token = login.data["access_token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        blocked = self.client.get("/api/v1/dashboard/stats")
        self.assertEqual(blocked.status_code, 403)

        profile = self.client.put(
            "/api/v1/onboarding/profile",
            {
                "nama": "Onboard User",
                "jenis_kelamin": "laki-laki",
                "tanggal_lahir": "1990-01-01",
                "no_hp": "081234567892",
            },
            format="json",
        )
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["next_step"], "register_bank_sampah")

        registration = self.client.post(
            "/api/v1/onboarding/bank-sampah",
            {
                "nama": "Bank Sampah Pending",
                "alamat": "Jl. Pending No. 1, Kukusan",
                "kota": "Depok",
                "no_hp_pic": "081234567893",
                "foto_kegiatan": SimpleUploadedFile("pending.png", b"png", content_type="image/png"),
            },
            format="multipart",
        )
        self.assertEqual(registration.status_code, 201)
        self.assertEqual(registration.data["status"], "pending")
        self.assertEqual(registration.data["next_step"], "approval_pending")

        pending_block = self.client.get("/api/v1/nasabah")
        self.assertEqual(pending_block.status_code, 403)

        superadmin = User.objects.create_user(
            email="super@example.com",
            nama="Super Admin",
            role=User.Role.SUPERADMIN,
            is_profile_complete=True,
        )
        super_refresh = RefreshToken.for_user(superadmin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {super_refresh.access_token}")

        queue = self.client.get("/api/v1/superadmin/bank-sampah?status=pending")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(queue.data["count"], 1)

        approval = self.client.post(
            f"/api/v1/superadmin/bank-sampah/{registration.data['id']}/approve",
            {"catatan": "Valid"},
            format="json",
        )
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(approval.data["bank_sampah"]["status"], "active")
        self.assertEqual(BankSampahApprovalLog.objects.count(), 1)

        refreshed = self.client.post("/api/v1/auth/refresh", {"refresh_token": login.data["refresh_token"]}, format="json")
        self.assertEqual(refreshed.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed.data['access_token']}")

        active_dashboard = self.client.get("/api/v1/dashboard/stats")
        self.assertEqual(active_dashboard.status_code, 200)

        invite = self.client.post("/api/v1/team/invite")
        self.assertEqual(invite.status_code, 201)
        self.assertIn("token", invite.data)

        self.client.credentials()
        invited_login = self.client.post("/api/v1/auth/google", {"id_token": "dev:invited@example.com:Invited User"}, format="json")
        self.assertEqual(invited_login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {invited_login.data['access_token']}")
        invited_profile = self.client.put(
            "/api/v1/onboarding/profile",
            {
                "nama": "Invited User",
                "jenis_kelamin": "perempuan",
                "tanggal_lahir": "1992-02-02",
                "no_hp": "081234567894",
            },
            format="json",
        )
        self.assertEqual(invited_profile.status_code, 200)
        accepted = self.client.post("/api/v1/invites/accept", {"token": invite.data["token"]}, format="json")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.data["next_step"], "dashboard")

        team = self.client.get("/api/v1/team")
        self.assertEqual(team.status_code, 200)
        self.assertEqual(len(team.data["members"]), 2)

        denied_invite = self.client.post("/api/v1/team/invite")
        self.assertEqual(denied_invite.status_code, 403)

    def test_superadmin_cannot_use_pengelola_endpoints(self):
        self.client.credentials()
        response = self.client.post("/api/v1/auth/google", {"id_token": "dev-superadmin:root@example.com:Root Admin"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["role"], "superadmin")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access_token']}")

        dashboard = self.client.get("/api/v1/dashboard/stats")
        self.assertEqual(dashboard.status_code, 403)

        approvals = self.client.get("/api/v1/superadmin/bank-sampah")
        self.assertEqual(approvals.status_code, 200)
