from datetime import date

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from danhmuc.models import LoaiCho, TuyenDuong


class QuyTacGia(models.Model):
    class LoaiThoiDiem(models.TextChoices):
        NGAY_THUONG = "NGAY_THUONG", "Ngày thường"
        CUOI_TUAN = "CUOI_TUAN", "Cuối tuần"
        LE_TET = "LE_TET", "Lễ, Tết"

    class TrangThai(models.TextChoices):
        DANG_AP_DUNG = "DANG_AP_DUNG", "Đang áp dụng"
        NGUNG_AP_DUNG = "NGUNG_AP_DUNG", "Ngừng áp dụng"

    tuyen_duong = models.ForeignKey(TuyenDuong, on_delete=models.PROTECT, verbose_name="Tuyến đường")
    loai_cho = models.ForeignKey(LoaiCho, on_delete=models.PROTECT, verbose_name="Loại chỗ")
    gia_co_so = models.DecimalField("Giá cơ sở (đ)", max_digits=12, decimal_places=0)
    loai_thoi_diem = models.CharField("Loại thời điểm", max_length=20, choices=LoaiThoiDiem.choices)
    ngay_bat_dau = models.DateField("Ngày bắt đầu")
    ngay_ket_thuc = models.DateField("Ngày kết thúc", null=True, blank=True)
    trang_thai = models.CharField("Trạng thái", max_length=20, choices=TrangThai.choices,
                                  default=TrangThai.DANG_AP_DUNG)
    ghi_chu = models.CharField("Ghi chú", max_length=255, blank=True)
    nguoi_tao = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Người tạo")

    class Meta:
        db_table = "tblQuyTacGia"
        constraints = [
            models.CheckConstraint(condition=Q(gia_co_so__gt=0), name="ck_qtg_gia_duong"),
            models.CheckConstraint(
                condition=Q(ngay_ket_thuc__isnull=True) | Q(ngay_ket_thuc__gte=F("ngay_bat_dau")),
                name="ck_qtg_khoang_ngay",
            ),
        ]
        verbose_name = "quy tắc giá"
        verbose_name_plural = "quy tắc giá"

    def __str__(self):
        return f"#{self.pk} {self.tuyen_duong.ma_tuyen}/{self.loai_cho.ma_loai}/{self.loai_thoi_diem}"


class KhuyenMai(models.Model):
    class HinhThucGiam(models.TextChoices):
        PHAN_TRAM = "PHAN_TRAM", "Theo phần trăm"
        SO_TIEN = "SO_TIEN", "Theo số tiền"

    class TrangThai(models.TextChoices):
        SAP_AP_DUNG = "SAP_AP_DUNG", "Sắp áp dụng"
        DANG_AP_DUNG = "DANG_AP_DUNG", "Đang áp dụng"
        DA_KET_THUC = "DA_KET_THUC", "Đã kết thúc"

    ma_khuyen_mai = models.CharField("Mã khuyến mãi", max_length=30, unique=True)
    ten = models.CharField("Tên chương trình", max_length=150)
    hinh_thuc_giam = models.CharField("Hình thức giảm", max_length=10, choices=HinhThucGiam.choices)
    gia_tri_giam = models.DecimalField("Giá trị giảm", max_digits=12, decimal_places=2)
    muc_giam_toi_da = models.DecimalField("Mức giảm tối đa (đ)", max_digits=12, decimal_places=0,
                                          null=True, blank=True)
    ngay_bat_dau = models.DateField("Ngày bắt đầu")
    ngay_ket_thuc = models.DateField("Ngày kết thúc")
    tuyen_duong = models.ForeignKey(TuyenDuong, on_delete=models.PROTECT, null=True, blank=True,
                                    verbose_name="Tuyến đường")
    loai_cho = models.ForeignKey(LoaiCho, on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="Loại chỗ")
    doi_tuong_ap_dung = models.CharField("Đối tượng áp dụng", max_length=20, blank=True)  # rỗng = mọi đối tượng
    so_ngay_dat_truoc = models.PositiveIntegerField("Đặt trước tối thiểu (ngày)", default=0)
    so_luot_toi_da = models.PositiveIntegerField("Số lượt tối đa", null=True, blank=True)
    so_luot_da_dung = models.PositiveIntegerField("Số lượt đã dùng", default=0)
    bat_buoc_nhap_ma = models.BooleanField("Bắt buộc nhập mã", default=False)  # bổ sung so với báo cáo, xem mục 12
    trang_thai = models.CharField("Trạng thái", max_length=20, choices=TrangThai.choices,
                                  default=TrangThai.SAP_AP_DUNG)

    class Meta:
        db_table = "tblKhuyenMai"
        constraints = [
            models.CheckConstraint(condition=Q(gia_tri_giam__gt=0), name="ck_km_gia_tri_duong"),
            models.CheckConstraint(
                condition=~Q(hinh_thuc_giam="PHAN_TRAM") | Q(gia_tri_giam__lte=100),
                name="ck_km_phan_tram_toi_da",
            ),
            models.CheckConstraint(condition=Q(ngay_ket_thuc__gte=F("ngay_bat_dau")), name="ck_km_khoang_ngay"),
            models.CheckConstraint(
                condition=Q(so_luot_toi_da__isnull=True) | Q(so_luot_da_dung__lte=F("so_luot_toi_da")),
                name="ck_km_so_luot",
            ),
        ]
        verbose_name = "khuyến mãi"
        verbose_name_plural = "khuyến mãi"

    def __str__(self):
        return f"{self.ma_khuyen_mai} – {self.ten}"

    def trang_thai_hien_thi(self, hom_nay: date | None = None) -> str:
        """Trạng thái suy ra từ ngày (mục 5.4); DA_KET_THUC cũng đúng khi Quản lý chủ động kết thúc."""
        hom_nay = hom_nay or timezone.localdate()
        if self.trang_thai == self.TrangThai.DA_KET_THUC or hom_nay > self.ngay_ket_thuc:
            return self.TrangThai.DA_KET_THUC
        if hom_nay < self.ngay_bat_dau:
            return self.TrangThai.SAP_AP_DUNG
        return self.TrangThai.DANG_AP_DUNG

    @property
    def ten_doi_tuong(self) -> str:
        if not self.doi_tuong_ap_dung:
            return "Mọi đối tượng"
        from datve.models import Ve  # import muộn để tránh vòng giữa hai app

        try:
            return Ve.DoiTuong(self.doi_tuong_ap_dung).label
        except ValueError:
            return self.doi_tuong_ap_dung

    @property
    def nhan_trang_thai(self) -> str:
        return self.TrangThai(self.trang_thai_hien_thi()).label


class NhatKyThayDoi(models.Model):
    class HanhDong(models.TextChoices):
        THEM = "THEM", "Thêm"
        SUA = "SUA", "Sửa"
        NGUNG_AP_DUNG = "NGUNG_AP_DUNG", "Ngừng áp dụng"
        KET_THUC = "KET_THUC", "Kết thúc"
        XOA = "XOA", "Xóa"

    thoi_gian = models.DateTimeField("Thời gian", auto_now_add=True)
    hanh_dong = models.CharField("Hành động", max_length=20, choices=HanhDong.choices)
    loai_doi_tuong = models.CharField("Loại đối tượng", max_length=30)  # "QuyTacGia" hoặc "KhuyenMai"
    doi_tuong_id = models.IntegerField("Mã đối tượng")
    gia_tri_cu = models.JSONField("Giá trị cũ", null=True, blank=True, encoder=DjangoJSONEncoder)
    gia_tri_moi = models.JSONField("Giá trị mới", encoder=DjangoJSONEncoder)
    nguoi_thuc_hien = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                        verbose_name="Người thực hiện")

    class Meta:
        db_table = "tblNhatKyThayDoi"
        ordering = ["-thoi_gian"]
        verbose_name = "nhật ký thay đổi"
        verbose_name_plural = "nhật ký thay đổi"

    def __str__(self):
        return f"{self.thoi_gian:%d/%m/%Y %H:%M} {self.hanh_dong} {self.loai_doi_tuong}#{self.doi_tuong_id}"
