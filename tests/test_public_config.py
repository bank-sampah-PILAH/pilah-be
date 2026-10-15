from django.test import SimpleTestCase, override_settings


class PublicRuntimeConfigTests(SimpleTestCase):
    def test_enabled_flag_is_public_and_never_cached(self) -> None:
        with override_settings(DEBUG=False, PILAH_ENABLE_DEMO_LOGIN=True):
            response = self.client.get("/api/public-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"demoLoginEnabled": True})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_debug_does_not_enable_demo_login(self) -> None:
        with override_settings(DEBUG=True, PILAH_ENABLE_DEMO_LOGIN=False):
            response = self.client.get("/api/public-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"demoLoginEnabled": False})
