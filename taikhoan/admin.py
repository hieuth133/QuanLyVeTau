from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ThanhVien


@admin.register(ThanhVien)
class ThanhVienAdmin(UserAdmin):
    list_display = ("username", "ho_ten", "vai_tro", "is_staff", "is_active")
    list_filter = ("vai_tro", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "ho_ten", "email")
    ordering = ("username",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Thông tin", {"fields": ("ho_ten", "email", "vai_tro")}),
        ("Phân quyền", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Mốc thời gian", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "ho_ten", "vai_tro", "password1", "password2"),
        }),
    )
