from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from api.models import BankSampah, JadwalKegiatan, Nasabah, Pencairan, User
from apps.jadwal.views import JadwalKegiatanViewSet
from apps.ledger.views import PencairanViewSet


class ActiveRoleScopingTest(TestCase):
    def setUp(self) -> None:
        self.bank = BankSampah.objects.create(nama="Bank A", no_hp_pic="+628123456789")
        self.user = User.objects.create_user(
            email="scoping@example.com",
            bank_sampah=self.bank,
            roles=["pengelola", "nasabah"],
            is_profile_complete=True,
        )
        self.member = Nasabah.objects.create(
            user=self.user,
            bank_sampah=self.bank,
            nomor="NAS-001",
            nama="Member",
            alamat="Jl. Test",
            no_hp="+628123456789",
            email=self.user.email,
        )

    def request(self, role: str) -> Request:
        request = Request(APIRequestFactory().get("/"))
        request.user = self.user
        request.auth = {"role": role}
        return request

    def test_withdrawal_reads_use_customer_ownership_in_nasabah_mode(self) -> None:
        other_member = Nasabah.objects.create(
            bank_sampah=self.bank,
            nomor="NAS-002",
            nama="Other",
            alamat="Jl. Other",
            no_hp="+628123456780",
            email="other@example.com",
        )
        own, other = [
            Pencairan.objects.create(
                nasabah=member,
                bank_sampah=self.bank,
                dicatat_oleh=self.user,
                nominal=100,
                metode="tunai",
                saldo_sebelum=100,
                saldo_sesudah=0,
            )
            for member in (self.member, other_member)
        ]
        view = PencairanViewSet()
        view.request = self.request("nasabah")
        self.assertEqual(set(view.get_queryset().values_list("pk", flat=True)), {own.pk})
        view.request = self.request("pengelola")
        self.assertEqual(set(view.get_queryset().values_list("pk", flat=True)), {own.pk, other.pk})

    def test_nasabah_mode_cannot_read_manager_schedule_drafts(self) -> None:
        now = timezone.now()
        published, draft = [
            JadwalKegiatan.objects.create(
                bank_sampah=self.bank,
                dibuat_oleh=self.user,
                jenis_kegiatan="penimbangan",
                mulai_pada=now + timedelta(days=1),
                selesai_pada=now + timedelta(days=2),
                lokasi="Bank A",
                status=status,
            )
            for status in ("diterbitkan", "draft")
        ]
        view = JadwalKegiatanViewSet()
        view.action = "list"
        view.request = self.request("nasabah")
        self.assertEqual(set(view.get_queryset().values_list("pk", flat=True)), {published.pk})
        view.request = self.request("pengelola")
        self.assertEqual(
            set(view.get_queryset().values_list("pk", flat=True)), {published.pk, draft.pk}
        )
