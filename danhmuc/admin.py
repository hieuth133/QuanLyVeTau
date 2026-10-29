from django.contrib import admin

from .models import ChuyenTau, GaTau, GheNgoi, LichTrinh, LoaiCho, Tau, ToaXe, TuyenDuong


@admin.register(GaTau)
class GaTauAdmin(admin.ModelAdmin):
    list_display = ("id", "ten_ga", "tinh_thanh")
    search_fields = ("ten_ga",)


@admin.register(TuyenDuong)
class TuyenDuongAdmin(admin.ModelAdmin):
    list_display = ("ma_tuyen", "ten_tuyen", "ga_di", "ga_den")
    search_fields = ("ma_tuyen", "ten_tuyen")


@admin.register(LoaiCho)
class LoaiChoAdmin(admin.ModelAdmin):
    list_display = ("ma_loai", "ten_loai", "mo_ta")


@admin.register(Tau)
class TauAdmin(admin.ModelAdmin):
    list_display = ("ma_tau", "ten_tau")


@admin.register(ToaXe)
class ToaXeAdmin(admin.ModelAdmin):
    list_display = ("tau", "so_toa", "loai_cho")
    list_filter = ("tau", "loai_cho")


@admin.register(GheNgoi)
class GheNgoiAdmin(admin.ModelAdmin):
    list_display = ("toa_xe", "so_ghe")
    list_filter = ("toa_xe__tau", "toa_xe")


@admin.register(LichTrinh)
class LichTrinhAdmin(admin.ModelAdmin):
    list_display = ("tau", "tuyen_duong", "gio_khoi_hanh", "thoi_gian_chay")
    list_filter = ("tuyen_duong", "tau")


@admin.register(ChuyenTau)
class ChuyenTauAdmin(admin.ModelAdmin):
    list_display = ("lich_trinh", "ngay_khoi_hanh", "trang_thai")
    list_filter = ("trang_thai", "lich_trinh__tuyen_duong", "ngay_khoi_hanh")
    date_hierarchy = "ngay_khoi_hanh"
