from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction

from .dao import KhuyenMaiDAO, NhatKyDAO, QuyTacGiaDAO
from .models import KhuyenMai, NhatKyThayDoi, QuyTacGia

HD = NhatKyThayDoi.HanhDong


class _GhiNhatKyAdminMixin:
    """Mọi thay đổi qua Django Admin cũng được ghi NhatKyThayDoi (UC14: mọi thay đổi đều có nhật ký)."""

    loai_doi_tuong = ""

    def save_model(self, request, obj, form, change):
        cu = None
        if change:
            cu = NhatKyDAO.chup(self.model.objects.get(pk=obj.pk))      # đọc lại từ CSDL trước khi lưu
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            NhatKyDAO.ghi(HD.SUA if change else HD.THEM, self.loai_doi_tuong, obj.pk, cu,
                          NhatKyDAO.chup(obj), request.user)

    def delete_model(self, request, obj):
        cu, pk = NhatKyDAO.chup(obj), obj.pk
        with transaction.atomic():
            super().delete_model(request, obj)
            NhatKyDAO.ghi(HD.XOA, self.loai_doi_tuong, pk, cu, {}, request.user)

    def delete_queryset(self, request, queryset):
        ban_ghi = [(o.pk, NhatKyDAO.chup(o)) for o in queryset]
        with transaction.atomic():
            super().delete_queryset(request, queryset)
            for pk, cu in ban_ghi:
                NhatKyDAO.ghi(HD.XOA, self.loai_doi_tuong, pk, cu, {}, request.user)


class QuyTacGiaAdminForm(forms.ModelForm):
    """Kiểm tra như UC14 (E1, E2) để Admin không trả 500 khi trùng thời gian áp dụng."""

    class Meta:
        model = QuyTacGia
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        gia, bd, kt = cleaned.get("gia_co_so"), cleaned.get("ngay_bat_dau"), cleaned.get("ngay_ket_thuc")
        if gia is not None and gia <= 0:
            self.add_error("gia_co_so", "Giá cơ sở phải lớn hơn 0.")
        if bd and kt and kt < bd:
            self.add_error("ngay_ket_thuc", "Ngày kết thúc không được trước ngày bắt đầu.")
        if self.errors:
            return cleaned
        if (cleaned.get("trang_thai") == QuyTacGia.TrangThai.DANG_AP_DUNG and bd and cleaned.get("tuyen_duong")
                and cleaned.get("loai_cho") and cleaned.get("loai_thoi_diem")):
            qt = QuyTacGia(pk=self.instance.pk, tuyen_duong=cleaned["tuyen_duong"], loai_cho=cleaned["loai_cho"],
                           loai_thoi_diem=cleaned["loai_thoi_diem"], ngay_bat_dau=bd, ngay_ket_thuc=kt)
            trung = QuyTacGiaDAO.tim_quy_tac_trung(qt)
            if trung:
                ds = "; ".join(
                    f"#{q.id} ({q.ngay_bat_dau:%d/%m/%Y} - {q.ngay_ket_thuc:%d/%m/%Y})" if q.ngay_ket_thuc
                    else f"#{q.id} (từ {q.ngay_bat_dau:%d/%m/%Y}, không giới hạn)" for q in trung)
                raise ValidationError(
                    "Thời gian áp dụng bị trùng với quy tắc đang áp dụng cùng tuyến, loại chỗ, loại thời điểm: " + ds)
        return cleaned


@admin.register(QuyTacGia)
class QuyTacGiaAdmin(_GhiNhatKyAdminMixin, admin.ModelAdmin):
    loai_doi_tuong = "QuyTacGia"
    form = QuyTacGiaAdminForm
    readonly_fields = ("nguoi_tao",)
    list_display = ("id", "tuyen_duong", "loai_cho", "loai_thoi_diem", "gia_co_so", "ngay_bat_dau",
                    "ngay_ket_thuc", "trang_thai")
    list_filter = ("trang_thai", "loai_thoi_diem", "tuyen_duong", "loai_cho")
    search_fields = ("ghi_chu",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.nguoi_tao = request.user
        super().save_model(request, obj, form, change)


@admin.register(KhuyenMai)
class KhuyenMaiAdmin(_GhiNhatKyAdminMixin, admin.ModelAdmin):
    loai_doi_tuong = "KhuyenMai"
    list_display = ("ma_khuyen_mai", "ten", "hinh_thuc_giam", "gia_tri_giam", "ngay_bat_dau", "ngay_ket_thuc",
                    "so_luot_da_dung", "so_luot_toi_da", "bat_buoc_nhap_ma", "trang_thai")
    list_filter = ("hinh_thuc_giam", "bat_buoc_nhap_ma", "trang_thai")
    search_fields = ("ma_khuyen_mai", "ten")


@admin.register(NhatKyThayDoi)
class NhatKyThayDoiAdmin(admin.ModelAdmin):
    """Nhật ký chỉ đọc: không thêm, sửa, xóa qua giao diện quản trị."""

    list_display = ("thoi_gian", "nguoi_thuc_hien", "hanh_dong", "loai_doi_tuong", "doi_tuong_id")
    list_filter = ("hanh_dong", "loai_doi_tuong", "nguoi_thuc_hien")
    readonly_fields = ("thoi_gian", "hanh_dong", "loai_doi_tuong", "doi_tuong_id", "gia_tri_cu", "gia_tri_moi",
                       "nguoi_thuc_hien")
    date_hierarchy = "thoi_gian"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
