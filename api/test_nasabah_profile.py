from rest_framework.test import APITestCase

from api.models import BankSampah, Nasabah, User


class NasabahProfileTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="siti@example.test", nama="Siti Aminah", role=User.Role.NASABAH
        )
        self.client.force_authenticate(self.user)
        self.url = "/api/v1/nasabah/me/profil"

    def test_profile_returns_only_signed_in_identity(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "id": str(self.user.id),
                "nama": "Siti Aminah",
                "email": "siti@example.test",
                "no_hp": "",
                "jenis_kelamin": "",
                "tanggal_lahir": None,
                "alamat": "",
                "role": "nasabah",
            },
        )

    def test_identity_changes_with_authenticated_user(self) -> None:
        other = User.objects.create_user(
            email="budi@example.test", nama="Budi", role=User.Role.NASABAH
        )
        self.client.force_authenticate(other)
        response = self.client.get(self.url, {"user_id": str(self.user.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(other.id))
        self.assertEqual(response.data["nama"], "Budi")

    def test_profile_does_not_require_membership(self) -> None:
        self.assertFalse(self.user.keanggotaan_nasabah.exists())
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_anonymous_and_management_roles_cannot_access(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        for role in (User.Role.PENGELOLA, User.Role.PENGELOLA_INDUK, User.Role.SUPERADMIN):
            user = User.objects.create_user(
                email=f"{role}@example.test", nama="Pengurus", role=role
            )
            self.client.force_authenticate(user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.data, {"error": "Endpoint ini hanya untuk nasabah"})

    def test_post_put_delete_are_not_allowed(self) -> None:
        for method in (self.client.post, self.client.put, self.client.delete):
            self.assertEqual(method(self.url, {"nama": "Changed"}).status_code, 405)
        self.user.refresh_from_db()
        self.assertEqual(self.user.nama, "Siti Aminah")

    def test_patch_updates_editable_field(self) -> None:
        response = self.client.patch(self.url, {"alamat": "Jl. Merdeka 10"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["alamat"], "Jl. Merdeka 10")
        self.user.refresh_from_db()
        self.assertEqual(self.user.alamat, "Jl. Merdeka 10")

    def test_patch_normalizes_no_hp(self) -> None:
        response = self.client.patch(self.url, {"no_hp": "081234567890"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["no_hp"], "+6281234567890")
        self.user.refresh_from_db()
        self.assertEqual(self.user.no_hp, "+6281234567890")

    def test_patch_propagates_profile_to_linked_memberships(self) -> None:
        bank = BankSampah.objects.create(
            nama="Bank A", no_hp_pic="08123", is_active=True, status=BankSampah.Status.ACTIVE
        )
        member = Nasabah.objects.create(
            email="fixture-2@example.test",
            user=self.user,
            bank_sampah=bank,
            nomor="002",
            nama="Siti Aminah",
            alamat="Old address",
            no_hp="08111",
        )
        response = self.client.patch(self.url, {"alamat": "Jl. Merdeka 10", "nama": "Siti A."})
        self.assertEqual(response.status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.alamat, "Jl. Merdeka 10")
        self.assertEqual(member.nama, "Siti A.")

    def test_patch_cannot_change_identity_fields(self) -> None:
        original_id = str(self.user.id)
        response = self.client.patch(
            self.url,
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "email": "hijacked@example.test",
                "role": User.Role.SUPERADMIN,
                "nama": "Siti Updated",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], original_id)
        self.assertEqual(response.data["email"], "siti@example.test")
        self.assertEqual(response.data["role"], "nasabah")
        self.user.refresh_from_db()
        self.assertEqual(str(self.user.id), original_id)
        self.assertEqual(self.user.email, "siti@example.test")
        self.assertEqual(self.user.role, User.Role.NASABAH)
        self.assertEqual(self.user.nama, "Siti Updated")

    def test_patch_rejects_invalid_jenis_kelamin(self) -> None:
        response = self.client.patch(self.url, {"jenis_kelamin": "bukan-pilihan"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("jenis_kelamin", response.data["errors"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.jenis_kelamin, "")

    def test_patch_rejects_invalid_tanggal_lahir(self) -> None:
        response = self.client.patch(self.url, {"tanggal_lahir": "not-a-date"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("tanggal_lahir", response.data["errors"])
        self.user.refresh_from_db()
        self.assertIsNone(self.user.tanggal_lahir)

    def test_jwt_authentication(self) -> None:
        from rest_framework_simplejwt.tokens import AccessToken

        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_profile_allows_ineligible_membership_and_bank(self) -> None:
        bank = BankSampah.objects.create(
            nama="Inactive bank",
            no_hp_pic="08123",
            is_active=False,
            status=BankSampah.Status.REJECTED,
        )
        member = Nasabah.objects.create(
            email="fixture-1@example.test",
            user=self.user,
            bank_sampah=bank,
            nomor="001",
            nama="Siti",
            alamat="Depok",
            no_hp="08123",
            is_active=False,
        )
        for status in (Nasabah.Status.PENDING, Nasabah.Status.REJECTED):
            member.status = status
            member.save()
            with self.subTest(status=status):
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["id"], str(self.user.id))
