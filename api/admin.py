from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from api.models import BankSampah, BankSampahApprovalLog, DetailTransaksi, JenisSampah, Nasabah, Saldo, Transaksi, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "nama", "role", "bank_sampah", "is_profile_complete", "is_primary_pengelola", "is_active")
    list_filter = ("role", "is_profile_complete", "is_primary_pengelola", "is_active")
    search_fields = ("email", "nama")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("nama", "google_id", "no_hp", "jenis_kelamin", "tanggal_lahir")}),
        ("Access", {"fields": ("role", "bank_sampah", "is_profile_complete", "is_primary_pengelola", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "nama", "password1", "password2", "role", "is_staff", "is_superuser")}),
    )


admin.site.register(BankSampah)
admin.site.register(Nasabah)
admin.site.register(Saldo)
admin.site.register(JenisSampah)
admin.site.register(Transaksi)
admin.site.register(DetailTransaksi)
admin.site.register(BankSampahApprovalLog)
