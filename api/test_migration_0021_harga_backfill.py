from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class Harga0021BackfillTests(TransactionTestCase):
    """Migration 0021 moves every jenis sampah price into HargaSampah and drops
    JenisSampah.harga_per_kg, so price versions become the only source of
    prices (SDS 7.1.2). Reversing it restores the column from the price in
    effect."""

    migrate_from = [("api", "0020_harga_sampah")]
    migrate_to = [("api", "0021_backfill_harga_sampah_drop_harga_per_kg")]

    def setUp(self) -> None:
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.old_apps = self.executor.loader.project_state(self.migrate_from).apps
        self._seed_old_state()

        self.executor = MigrationExecutor(connection)
        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        self.new_apps = self.executor.loader.project_state(self.migrate_to).apps

    def tearDown(self) -> None:
        call_command("migrate", verbosity=0)

    def _seed_old_state(self) -> None:
        BankSampah = self.old_apps.get_model("api", "BankSampah")
        JenisSampah = self.old_apps.get_model("api", "JenisSampah")
        User = self.old_apps.get_model("api", "User")
        Nasabah = self.old_apps.get_model("api", "Nasabah")
        Transaksi = self.old_apps.get_model("api", "Transaksi")
        DetailTransaksi = self.old_apps.get_model("api", "DetailTransaksi")

        self.bank = BankSampah.objects.create(
            nama="Bank A", alamat="Jl A", kota="Depok", no_hp_pic="+6281"
        )
        self.dipakai = JenisSampah.objects.create(
            bank_sampah=self.bank,
            nomor="PLS-001",
            nama_sampah="Plastik",
            kategori="plastik",
            harga_per_kg=Decimal("3500.50"),
        )
        self.baru = JenisSampah.objects.create(
            bank_sampah=self.bank,
            nomor="KRT-001",
            nama_sampah="Kertas",
            kategori="kertas",
            harga_per_kg=Decimal(2000),
        )
        self.diubah_pada = timezone.now() - timedelta(days=3)
        JenisSampah.objects.update(updated_at=self.diubah_pada)

        pengurus = User.objects.create(email="p@example.com", nama="P", no_hp="+6280")
        nasabah = Nasabah.objects.create(
            bank_sampah=self.bank, nomor="N1", nama="N", no_hp="+6288", email="n@example.com"
        )
        # Setoran tercatat sebelum harga terakhir disunting: harga awal harus
        # sudah berlaku sejak setoran pertama itu.
        self.setoran_pertama = timezone.now() - timedelta(days=30)
        transaksi = Transaksi.objects.create(
            nasabah=nasabah,
            bank_sampah=self.bank,
            dicatat_oleh=pengurus,
            tanggal=self.setoran_pertama,
        )
        DetailTransaksi.objects.create(
            transaksi=transaksi,
            jenis_sampah=self.dipakai,
            nama_sampah_snapshot="Plastik",
            kategori_snapshot="plastik",
            harga_snapshot=Decimal(3000),
            berat=Decimal(1),
            subtotal=Decimal(3000),
        )

    def test_each_jenis_gets_its_price_as_a_version_from_its_earliest_known_use(self) -> None:
        HargaSampah = self.new_apps.get_model("api", "HargaSampah")

        dipakai = HargaSampah.objects.get(jenis_sampah_id=self.dipakai.id)
        baru = HargaSampah.objects.get(jenis_sampah_id=self.baru.id)

        self.assertEqual(dipakai.harga_per_kg, Decimal("3500.50"))
        self.assertEqual(dipakai.berlaku_mulai, self.setoran_pertama)
        self.assertEqual(dipakai.bank_sampah_id, self.bank.id)
        self.assertIsNone(dipakai.dibuat_oleh_id)
        self.assertEqual(baru.harga_per_kg, 2000)
        self.assertEqual(baru.berlaku_mulai, self.diubah_pada)

    def test_column_is_dropped(self) -> None:
        JenisSampah = self.new_apps.get_model("api", "JenisSampah")

        self.assertNotIn("harga_per_kg", {f.name for f in JenisSampah._meta.get_fields()})

    def test_reverse_restores_the_column_from_the_price_in_effect(self) -> None:
        HargaSampah = self.new_apps.get_model("api", "HargaSampah")
        HargaSampah.objects.create(
            jenis_sampah_id=self.dipakai.id,
            bank_sampah_id=self.bank.id,
            harga_per_kg=Decimal(4000),
            berlaku_mulai=timezone.now() - timedelta(hours=1),
        )
        HargaSampah.objects.create(
            jenis_sampah_id=self.dipakai.id,
            bank_sampah_id=self.bank.id,
            harga_per_kg=Decimal(9000),
            berlaku_mulai=timezone.now() + timedelta(days=5),
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.migrate_from)
        JenisSampah = executor.loader.project_state(self.migrate_from).apps.get_model(
            "api", "JenisSampah"
        )

        self.assertEqual(JenisSampah.objects.get(id=self.dipakai.id).harga_per_kg, 4000)
        self.assertEqual(JenisSampah.objects.get(id=self.baru.id).harga_per_kg, 2000)
