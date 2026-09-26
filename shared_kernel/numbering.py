from api.models import BankSampah, JenisSampah, Nasabah


class NumberingService:
    @staticmethod
    def next_nasabah_number(bank_sampah: BankSampah) -> str:
        count = Nasabah.objects.filter(bank_sampah=bank_sampah).count() + 1
        return f"NAS-{count:04d}"

    @staticmethod
    def next_jenis_number(bank_sampah: BankSampah) -> str:
        count = JenisSampah.objects.filter(bank_sampah=bank_sampah).count() + 1
        return f"JS-{count:04d}"
