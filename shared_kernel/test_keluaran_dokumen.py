"""Setiap konteks keluaran harus menetralkan karakter yang mengakhiri konteksnya."""

import json
from typing import Any

from django.test import SimpleTestCase

from shared_kernel.keluaran_dokumen import LITERAL_SKRIP, SEMUA_KONTEKS, TEKS_HTML

PEMBOBOL = "</pre><script>alert(document.domain)</script>"


class KonteksKeluaranTests(SimpleTestCase):
    def test_setiap_konteks_menetralkan_pembuka_tag(self) -> None:
        """Termasuk konteks yang ditambahkan sesudah test ini ditulis.

        `assertTrue` ada karena perulangan atas tuple kosong lulus secara
        hampa — satu-satunya cara test ini bisa berhenti menguji apa pun.
        """
        self.assertTrue(SEMUA_KONTEKS, "himpunan konteks tidak boleh kosong")
        for konteks in SEMUA_KONTEKS:
            with self.subTest(konteks=konteks.nama):
                hasil = konteks.loloskan({"error": PEMBOBOL})
                self.assertNotIn("<", hasil)
                self.assertNotIn(">", hasil)

    def test_teks_html_memakai_entitas(self) -> None:
        hasil = TEKS_HTML.loloskan({"error": PEMBOBOL})
        self.assertIn("&lt;/pre&gt;", hasil)

    def test_literal_skrip_tetap_json_yang_sah(self) -> None:
        """Meloloskan bukan menyaring: `\\u003C` dibaca kembali sebagai `<`."""
        nilai: Any = {"error": PEMBOBOL}
        hasil = LITERAL_SKRIP.loloskan(nilai)
        self.assertIn("\\u003C", hasil)
        self.assertEqual(json.loads(hasil), nilai)
