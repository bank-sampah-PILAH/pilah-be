from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.http import HttpRequest

from api.models import (
    BankSampah,
    BankSampahApprovalLog,
    DetailTransaksi,
    JenisSampah,
    Nasabah,
    Pencairan,
    PencairanRevisi,
    Saldo,
    Transaksi,
    User,
)


def _prepare_admin_roles(user: User, role: str) -> None:
    # Admin exposes the primary role, not the assignment list. Prepare that
    # hidden value before ModelForm calls User.clean(), preserving other roles.
    if user._state.adding and user.roles == []:
        user.roles = [role]
    elif isinstance(user.roles, list) and role in User.Role.values and role not in user.roles:
        user.roles = [*user.roles, role]


class AssignedRolesCreationForm(AdminUserCreationForm):  # type: ignore[type-arg]
    def clean(self) -> dict[str, Any] | None:
        data = super().clean()
        _prepare_admin_roles(self.instance, self.cleaned_data.get("role", self.instance.role))
        return data


class AssignedRolesChangeForm(UserChangeForm):  # type: ignore[type-arg]
    def clean(self) -> dict[str, Any] | None:
        data = super().clean()
        _prepare_admin_roles(self.instance, self.cleaned_data.get("role", self.instance.role))
        return data


@admin.register(User)
class UserAdmin(BaseUserAdmin):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    add_form = AssignedRolesCreationForm
    form = AssignedRolesChangeForm
    ordering = ("email",)
    list_display = (
        "email",
        "nama",
        "role",
        "bank_sampah",
        "is_profile_complete",
        "is_primary_pengelola",
        "is_active",
    )
    list_filter = ("role", "is_profile_complete", "is_primary_pengelola", "is_active")
    search_fields = ("email", "nama")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("nama", "google_id", "no_hp", "jenis_kelamin", "tanggal_lahir")}),
        (
            "Access",
            {
                "fields": (
                    "role",
                    "bank_sampah",
                    "is_profile_complete",
                    "is_primary_pengelola",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "nama",
                    "password1",
                    "password2",
                    "role",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )


admin.site.register(BankSampah)
admin.site.register(Nasabah)
admin.site.register(Saldo)
admin.site.register(JenisSampah)
admin.site.register(Transaksi)
admin.site.register(DetailTransaksi)
admin.site.register(BankSampahApprovalLog)


@admin.register(Pencairan)
class PencairanAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    # Read-only: writes must go through PencairanService so Saldo moves with the row.
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Pencairan | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Pencairan | None = None) -> bool:
        return False


@admin.register(PencairanRevisi)
class PencairanRevisiAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # stubs are generic, runtime is not
    # Append-only audit trail: admins may read old versions, never change them.
    list_display = ("pencairan", "versi", "nominal", "tanggal", "alasan", "diubah_oleh")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: PencairanRevisi | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: PencairanRevisi | None = None
    ) -> bool:
        return False
