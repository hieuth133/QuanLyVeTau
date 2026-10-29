from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class ThanhVien(AbstractUser):
    class VaiTro(models.TextChoices):
        NHAN_VIEN_BAN_VE = "NHAN_VIEN_BAN_VE", "Nhân viên bán vé"
        QUAN_LY = "QUAN_LY", "Quản lý"
        QUAN_TRI = "QUAN_TRI", "Quản trị hệ thống"

    username = models.CharField("Tên đăng nhập", max_length=50, unique=True, db_column="ten_dang_nhap")
    password = models.CharField("Mật khẩu", max_length=128, db_column="mat_khau")
    first_name = None
    last_name = None
    ho_ten = models.CharField("Họ tên", max_length=100)
    vai_tro = models.CharField("Vai trò", max_length=20, choices=VaiTro.choices, default=VaiTro.NHAN_VIEN_BAN_VE)

    REQUIRED_FIELDS = ["ho_ten"]

    class Meta:
        db_table = "tblThanhVien"
        verbose_name = "thành viên"
        verbose_name_plural = "thành viên"

    def __str__(self):
        return f"{self.ho_ten} ({self.username})"

    def get_full_name(self):
        return self.ho_ten

    def get_short_name(self):
        return self.ho_ten

    @property
    def la_quan_ly(self) -> bool:
        """Được vào chức năng quản lý giá (Quản lý hoặc superuser)."""
        return self.is_authenticated and (self.is_superuser or self.vai_tro == self.VaiTro.QUAN_LY)


class QuanLyManager(UserManager):
    def get_queryset(self):
        return super().get_queryset().filter(vai_tro=ThanhVien.VaiTro.QUAN_LY)


class QuanLy(ThanhVien):
    """Lớp QuanLy kế thừa ThanhVien như trong báo cáo; dùng chung bảng tblThanhVien."""

    objects = QuanLyManager()

    class Meta:
        proxy = True
        verbose_name = "quản lý"
        verbose_name_plural = "quản lý"
