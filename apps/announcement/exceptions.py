"""Domain exceptions for the announcement context."""


class TransisiStatusTidakValid(Exception):
    """A status transition the announcement's workflow does not allow.

    Views map this to the raw 400 {"error": ...} shape used by the jadwal
    transitions; payload problems use serializers.ValidationError (422) instead.
    """

    def __init__(self, message: str = "Perubahan status pengumuman tidak diizinkan") -> None:
        super().__init__(message)
        self.message = message
