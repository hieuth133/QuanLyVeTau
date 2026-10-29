from django.db import models

from .thoi_gian import thoi_diem_den, thoi_diem_khoi_hanh, thoi_diem_ngung_ban


class GaTau(models.Model):
    ten_ga = models.CharField("Tên ga", max_length=100)
    tinh_thanh = models.CharField("Tỉnh/thành", max_length=100, blank=True)

    class Meta:
        db_table = "tblGaTau"
        verbose_name = "ga tàu"
        verbose_name_plural = "ga tàu"

    def __str__(self):
        return self.ten_ga


class TuyenDuong(models.Model):
    ma_tuyen = models.CharField("Mã tuyến", max_length=20, unique=True)
    ten_tuyen = models.CharField("Tên tuyến", max_length=150)
    ga_di = models.ForeignKey(GaTau, on_delete=models.PROTECT, related_name="tuyen_di", verbose_name="Ga đi")
    ga_den = models.ForeignKey(GaTau, on_delete=models.PROTECT, related_name="tuyen_den", verbose_name="Ga đến")

    class Meta:
        db_table = "tblTuyenDuong"
        verbose_name = "tuyến đường"
        verbose_name_plural = "tuyến đường"

    def __str__(self):
        return f"{self.ma_tuyen} – {self.ten_tuyen}"


class LoaiCho(models.Model):
    ma_loai = models.CharField("Mã loại", max_length=10, unique=True)
    ten_loai = models.CharField("Tên loại", max_length=100)
    mo_ta = models.CharField("Mô tả", max_length=255, blank=True)

    class Meta:
        db_table = "tblLoaiCho"
        verbose_name = "loại chỗ"
        verbose_name_plural = "loại chỗ"

    def __str__(self):
        return self.ten_loai

    @property
    def la_toa_nam(self) -> bool:
        """Toa nằm (giường) hiển thị 2 cột, toa ngồi hiển thị 4 cột."""
        return "nằm" in self.ten_loai.lower() or self.ma_loai.upper().startswith(("K", "G"))

    @property
    def so_cot_ghe(self) -> int:
        return 2 if self.la_toa_nam else 4


class Tau(models.Model):
    ma_tau = models.CharField("Mã tàu", max_length=10, unique=True)
    ten_tau = models.CharField("Tên tàu", max_length=100)

    class Meta:
        db_table = "tblTau"
        verbose_name = "tàu"
        verbose_name_plural = "tàu"

    def __str__(self):
        return self.ma_tau


class ToaXe(models.Model):
    tau = models.ForeignKey(Tau, on_delete=models.CASCADE, related_name="ds_toa", verbose_name="Tàu")
    so_toa = models.PositiveSmallIntegerField("Số toa")
    loai_cho = models.ForeignKey(LoaiCho, on_delete=models.PROTECT, verbose_name="Loại chỗ")

    class Meta:
        db_table = "tblToaXe"
        constraints = [models.UniqueConstraint(fields=["tau", "so_toa"], name="uq_toa_trong_tau")]
        verbose_name = "toa xe"
        verbose_name_plural = "toa xe"

    def __str__(self):
        return f"{self.tau.ma_tau} – toa {self.so_toa}"


class GheNgoi(models.Model):
    toa_xe = models.ForeignKey(ToaXe, on_delete=models.CASCADE, related_name="ds_ghe", verbose_name="Toa")
    so_ghe = models.CharField("Số ghế", max_length=5)

    class Meta:
        db_table = "tblGheNgoi"
        constraints = [models.UniqueConstraint(fields=["toa_xe", "so_ghe"], name="uq_ghe_trong_toa")]
        verbose_name = "ghế ngồi"
        verbose_name_plural = "ghế ngồi"

    def __str__(self):
        return f"Toa {self.toa_xe.so_toa} – ghế {self.so_ghe}"


class LichTrinh(models.Model):
    tuyen_duong = models.ForeignKey(TuyenDuong, on_delete=models.PROTECT, verbose_name="Tuyến")
    tau = models.ForeignKey(Tau, on_delete=models.PROTECT, verbose_name="Tàu")
    gio_khoi_hanh = models.TimeField("Giờ khởi hành")
    thoi_gian_chay = models.PositiveIntegerField("Thời gian chạy (phút)", help_text="Số phút")

    class Meta:
        db_table = "tblLichTrinh"
        verbose_name = "lịch trình"
        verbose_name_plural = "lịch trình"

    def __str__(self):
        return f"{self.tau.ma_tau} {self.tuyen_duong.ma_tuyen} {self.gio_khoi_hanh:%H:%M}"


class ChuyenTau(models.Model):
    class TrangThai(models.TextChoices):
        MO_BAN = "MO_BAN", "Mở bán"
        NGUNG_BAN = "NGUNG_BAN", "Ngừng bán"
        DA_CHAY = "DA_CHAY", "Đã chạy"

    lich_trinh = models.ForeignKey(LichTrinh, on_delete=models.PROTECT, verbose_name="Lịch trình")
    ngay_khoi_hanh = models.DateField("Ngày khởi hành")
    trang_thai = models.CharField("Trạng thái", max_length=20, choices=TrangThai.choices, default=TrangThai.MO_BAN)

    class Meta:
        db_table = "tblChuyenTau"
        constraints = [models.UniqueConstraint(fields=["lich_trinh", "ngay_khoi_hanh"], name="uq_chuyen_moi_ngay")]
        verbose_name = "chuyến tàu"
        verbose_name_plural = "chuyến tàu"

    def __str__(self):
        return f"{self.lich_trinh.tau.ma_tau} {self.ngay_khoi_hanh:%d/%m/%Y} {self.lich_trinh.gio_khoi_hanh:%H:%M}"

    @property
    def thoi_diem_khoi_hanh(self):
        return thoi_diem_khoi_hanh(self)

    @property
    def thoi_diem_den(self):
        return thoi_diem_den(self)

    @property
    def thoi_diem_ngung_ban(self):
        return thoi_diem_ngung_ban(self)
