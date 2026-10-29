from django.contrib import admin

from .models import DonDatCho, KhachHang, Ve


class VeInline(admin.TabularInline):
    model = Ve
    extra = 0
    raw_id_fields = ("chuyen_tau", "ghe_ngoi", "quy_tac_gia", "khuyen_mai")


@admin.register(KhachHang)
class KhachHangAdmin(admin.ModelAdmin):
    list_display = ("ho_ten", "so_dien_thoai", "email")
    search_fields = ("ho_ten", "so_dien_thoai", "email")


@admin.register(DonDatCho)
class DonDatChoAdmin(admin.ModelAdmin):
    list_display = ("ma_dat_cho", "khach_hang", "thoi_gian_dat", "thoi_diem_het_han", "tong_tien", "trang_thai")
    list_filter = ("trang_thai",)
    search_fields = ("ma_dat_cho", "khach_hang__ho_ten", "khach_hang__so_dien_thoai")
    inlines = [VeInline]


@admin.register(Ve)
class VeAdmin(admin.ModelAdmin):
    list_display = ("id", "don_dat_cho", "chuyen_tau", "ghe_ngoi", "ho_ten_hanh_khach", "doi_tuong", "gia_ve",
                    "trang_thai")
    list_filter = ("trang_thai", "doi_tuong")
    search_fields = ("ho_ten_hanh_khach", "so_giay_to", "don_dat_cho__ma_dat_cho")
    raw_id_fields = ("don_dat_cho", "chuyen_tau", "ghe_ngoi", "quy_tac_gia", "khuyen_mai")
