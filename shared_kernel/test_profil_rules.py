"""Kontrak `ProfilFieldRules`: satu aturan, satu rumusan, satu enum per model.

`allowed_genders` adalah satu-satunya langkah yang diserahkan ke subclass,
jadi kelalaian mendefinisikannya harus gagal keras dan awal. Tes di sini
menjaga penegakannya, bukan hanya mendokumentasikannya.
"""

from django.test import SimpleTestCase

from shared_kernel.profil_rules import ProfilFieldRules


class ProfilFieldRulesKontrakTests(SimpleTestCase):
    def test_subclass_tanpa_allowed_genders_gagal_saat_didefinisikan(self) -> None:
        """Kegagalannya pada waktu impor, bukan saat sebuah request masuk."""
        with self.assertRaises(TypeError) as ditangkap:

            class TanpaGender(ProfilFieldRules):
                pass

        self.assertIn("allowed_genders", str(ditangkap.exception))
        self.assertIn("TanpaGender", str(ditangkap.exception))

    def test_subclass_dengan_allowed_genders_lolos(self) -> None:
        class DenganGender(ProfilFieldRules):
            def allowed_genders(self) -> tuple[str, ...]:
                return ("laki-laki", "perempuan")

        self.assertEqual(DenganGender().allowed_genders(), ("laki-laki", "perempuan"))

    def test_allowed_genders_mewarisi_dari_base_antara(self) -> None:
        """Penegakannya memeriksa MRO, jadi base antara tetap sah."""

        class BaseAntara(ProfilFieldRules):
            def allowed_genders(self) -> tuple[str, ...]:
                return ("laki-laki",)

        class Turunan(BaseAntara):
            pass

        self.assertEqual(Turunan().allowed_genders(), ("laki-laki",))

    def test_base_sendiri_tetap_menolak_dipakai_langsung(self) -> None:
        with self.assertRaises(NotImplementedError):
            ProfilFieldRules().allowed_genders()

    def test_jenis_kelamin_di_luar_enum_model_ditolak(self) -> None:
        class HanyaPerempuan(ProfilFieldRules):
            def allowed_genders(self) -> tuple[str, ...]:
                return ("perempuan",)

        rules = HanyaPerempuan()
        self.assertEqual(rules.validate_jenis_kelamin("perempuan"), "perempuan")
        with self.assertRaises(Exception) as ditangkap:
            rules.validate_jenis_kelamin("laki-laki")
        self.assertIn("Jenis kelamin wajib dipilih", str(ditangkap.exception))
