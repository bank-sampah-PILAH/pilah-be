from django.test import SimpleTestCase

from shared_kernel.exceptions import api_exception_handler


class ApiExceptionHandlerTests(SimpleTestCase):
    def test_unhandled_exceptions_are_left_to_django(self) -> None:
        self.assertIsNone(api_exception_handler(RuntimeError("boom"), {}))
