from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from danhmuc.models import ChuyenTau, GheNgoi
from giave.models import KhuyenMai, QuyTacGia


class KhachHang(models.Model):
    ho_ten = models.CharField("Họ tên", max_length=100)
    so_dien_thoai = models.CharField("Số điện thoại", max_length=15, unique=True)
    email = models.EmailField("Email", blank=True)

    class Meta:
        db_table = "tblKhachHang"
        verbose_name = "khách hàng"
        verbose_name_plural = "khách hàng"

    def __str__(self):
        return f"{self.ho_ten} ({self.so_dien_thoai})"


class DonDatCho(models.Model):
    class TrangThai(models.TextChoices):
        DANG_GIU = "DANG_GIU", "Đang giữ chỗ"
        DA_THANH_TOAN = "DA_THANH_TOAN", "Đã thanh toán"
        HET_HAN = "HET_HAN", "Hết hạn"
        DA_HUY = "DA_HUY", "Đã hủy"

    ma_dat_cho = models.CharField("Mã đặt chỗ", max_length=8, unique=True)
    khach_hang = models.ForeignKey(KhachHang, on_delete=models.PROTECT, verbose_name="Khách hàng")
    thoi_gian_dat = models.DateTimeField("Thời gian đặt", default=timezone.now)
    thoi_diem_het_han = models.DateTimeField("Hết hạn giữ chỗ")
    tong_tien = models.DecimalField("Tổng tiền (đ)", max_digits=12, decimal_places=0)
    trang_thai = models.CharField("Trạng thái", max_length=20, choices=TrangThai.choices,
                                  default=TrangThai.DANG_GIU)

    class Meta:
        db_table = "tblDonDatCho"
        indexes = [models.Index(fields=["trang_thai", "thoi_diem_het_han"], name="ix_don_het_han")]
        constraints = [models.CheckConstraint(condition=Q(tong_tien__gte=0), name="ck_don_tong_tien")]
        verbose_name = "đơn đặt chỗ"
        verbose_name_plural = "đơn đặt chỗ"

    def __str__(self):
        return self.ma_dat_cho


class Ve(models.Model):
    class TrangThai(models.TextChoices):
        DANG_GIU = "DANG_GIU", "Đang giữ"
        DA_THANH_TOAN = "DA_THANH_TOAN", "Đã thanh toán"
        DA_HUY = "DA_HUY", "Đã hủy"

    class DoiTuong(models.TextChoices):
        NGUOI_LON = "NGUOI_LON", "Người lớn"
        TRE_EM = "TRE_EM", "Trẻ em"
        SINH_VIEN = "SINH_VIEN", "Sinh viên"
        NGUOI_CAO_TUOI = "NGUOI_CAO_TUOI", "Người cao tuổi"

    CON_HIEU_LUC = [TrangThai.DANG_GIU, TrangThai.DA_THANH_TOAN]

    don_dat_cho = models.ForeignKey(DonDatCho, on_delete=models.CASCADE, related_name="ds_ve",
                                    verbose_name="Đơn đặt chỗ")
    chuyen_tau = models.ForeignKey(ChuyenTau, on_delete=models.PROTECT, verbose_name="Chuyến tàu")
    ghe_ngoi = models.ForeignKey(GheNgoi, on_delete=models.PROTECT, verbose_name="Ghế")
    ho_ten_hanh_khach = models.CharField("Hành khách", max_length=100)
    doi_tuong = models.CharField("Đối tượng", max_length=20, choices=DoiTuong.choices)
    so_giay_to = models.CharField("Số giấy tờ", max_length=20)
    gia_co_so = models.DecimalField("Giá cơ sở (đ)", max_digits=12, decimal_places=0)
    so_tien_giam = models.DecimalField("Số tiền giảm (đ)", max_digits=12, decimal_places=0, default=0)
    gia_ve = models.DecimalField("Giá vé (đ)", max_digits=12, decimal_places=0)
    quy_tac_gia = models.ForeignKey(QuyTacGia, on_delete=models.PROTECT, related_name="ds_ve",
                                    verbose_name="Quy tắc giá")
    khuyen_mai = models.ForeignKey(KhuyenMai, on_delete=models.PROTECT, null=True, blank=True,
                                   verbose_name="Khuyến mãi")
    trang_thai = models.CharField("Trạng thái", max_length=20, choices=TrangThai.choices,
                                  default=TrangThai.DANG_GIU)

    class Meta:
        db_table = "tblVe"
        constraints = [
            models.UniqueConstraint(
                fields=["chuyen_tau", "ghe_ngoi"],
                condition=Q(trang_thai__in=["DANG_GIU", "DA_THANH_TOAN"]),
                name="uq_ve_cho_con_hieu_luc",
            ),
            models.CheckConstraint(condition=Q(so_tien_giam__gte=0), name="ck_ve_giam_khong_am"),
            models.CheckConstraint(condition=Q(gia_ve=F("gia_co_so") - F("so_tien_giam")), name="ck_ve_gia"),
            models.CheckConstraint(condition=Q(gia_ve__gte=0), name="ck_ve_gia_khong_am"),
        ]
        verbose_name = "vé"
        verbose_name_plural = "vé"

    def __str__(self):
        return f"Vé #{self.pk} – {self.ho_ten_hanh_khach}"
