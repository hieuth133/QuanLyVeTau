"""Tạo dữ liệu mẫu cho buổi demo. Chạy lại nhiều lần không bị nhân đôi."""
from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from danhmuc.models import ChuyenTau, GaTau, GheNgoi, LichTrinh, LoaiCho, Tau, ToaXe, TuyenDuong
from giave.models import KhuyenMai, QuyTacGia
from taikhoan.models import ThanhVien

TAI_KHOAN = [
    # username, mật khẩu, họ tên, vai trò, superuser
    ("quantri", "Quantri@123", "Quản trị hệ thống", ThanhVien.VaiTro.QUAN_TRI, True),
    ("quanly", "Quanly@123", "Nguyễn Quản Lý", ThanhVien.VaiTro.QUAN_LY, False),
    ("nhanvien", "Nhanvien@123", "Trần Nhân Viên", ThanhVien.VaiTro.NHAN_VIEN_BAN_VE, False),
]

# (mã tuyến, giá ngày thường NM, K4, giá cuối tuần NM, K4)
GIA = {
    "HN-DN": {"NM": (450_000, 500_000), "K4": (750_000, 820_000)},
    "HN-SG": {"NM": (900_000, 990_000), "K4": (1_500_000, 1_650_000)},
}


class Command(BaseCommand):
    help = "Tạo dữ liệu mẫu (tài khoản, danh mục, chuyến tàu, quy tắc giá, khuyến mãi). Chạy lại không nhân đôi."

    @transaction.atomic
    def handle(self, *args, **options):
        hom_nay = timezone.localdate()
        quan_ly = self._tai_khoan()
        ga = {ten: GaTau.objects.get_or_create(ten_ga=ten, defaults={"tinh_thanh": ten})[0]
              for ten in ("Hà Nội", "Đà Nẵng", "Sài Gòn")}
        tuyen = {
            "HN-DN": self._tuyen("HN-DN", "Hà Nội – Đà Nẵng", ga["Hà Nội"], ga["Đà Nẵng"]),
            "HN-SG": self._tuyen("HN-SG", "Hà Nội – Sài Gòn", ga["Hà Nội"], ga["Sài Gòn"]),
        }
        loai = {
            "NM": LoaiCho.objects.get_or_create(ma_loai="NM", defaults={
                "ten_loai": "Ngồi mềm điều hòa", "mo_ta": "Ghế ngồi mềm, có điều hòa"})[0],
            "K4": LoaiCho.objects.get_or_create(ma_loai="K4", defaults={
                "ten_loai": "Nằm khoang 4 điều hòa", "mo_ta": "Khoang 4 giường nằm, có điều hòa"})[0],
        }
        tau = {}
        for ma, ten in (("SE19", "Tàu SE19"), ("SE1", "Tàu SE1")):
            tau[ma] = Tau.objects.get_or_create(ma_tau=ma, defaults={"ten_tau": ten})[0]
            self._toa(tau[ma], 1, loai["NM"], 24)
            self._toa(tau[ma], 2, loai["K4"], 16)

        lich = [
            self._lich(tuyen["HN-DN"], tau["SE19"], time(20, 5), 900),
            self._lich(tuyen["HN-SG"], tau["SE1"], time(19, 30), 1980),
        ]
        so_chuyen = 0
        for lt in lich:
            for d in range(0, 15):
                _, tao = ChuyenTau.objects.get_or_create(
                    lich_trinh=lt, ngay_khoi_hanh=hom_nay + timedelta(days=d),
                    defaults={"trang_thai": ChuyenTau.TrangThai.MO_BAN})
                so_chuyen += tao

        so_qt = self._quy_tac_gia(tuyen, loai, quan_ly, hom_nay)
        so_km = self._khuyen_mai(hom_nay)
        self.stdout.write(self.style.SUCCESS(
            f"Hoàn tất: +{so_chuyen} chuyến, +{so_qt} quy tắc giá, +{so_km} khuyến mãi."))
        self.stdout.write("Tài khoản: quantri / Quantri@123, quanly / Quanly@123, nhanvien / Nhanvien@123")

    # --- các bước nhỏ -------------------------------------------------------------------
    def _tai_khoan(self) -> ThanhVien:
        ket_qua = None
        for ten, mat_khau, ho_ten, vai_tro, la_super in TAI_KHOAN:
            u = ThanhVien.objects.filter(username=ten).first()
            if u is None:
                if la_super:
                    u = ThanhVien.objects.create_superuser(ten, "", mat_khau, ho_ten=ho_ten, vai_tro=vai_tro)
                else:
                    u = ThanhVien.objects.create_user(ten, "", mat_khau, ho_ten=ho_ten, vai_tro=vai_tro)
            if ten == "quanly":
                ket_qua = u
        return ket_qua

    @staticmethod
    def _tuyen(ma, ten, ga_di, ga_den):
        return TuyenDuong.objects.get_or_create(
            ma_tuyen=ma, defaults={"ten_tuyen": ten, "ga_di": ga_di, "ga_den": ga_den})[0]

    @staticmethod
    def _toa(tau, so_toa, loai_cho, so_ghe):
        toa = ToaXe.objects.get_or_create(tau=tau, so_toa=so_toa, defaults={"loai_cho": loai_cho})[0]
        for i in range(1, so_ghe + 1):
            GheNgoi.objects.get_or_create(toa_xe=toa, so_ghe=str(i))
        return toa

    @staticmethod
    def _lich(tuyen, tau, gio, phut):
        lt = LichTrinh.objects.filter(tuyen_duong=tuyen, tau=tau, gio_khoi_hanh=gio).first()
        return lt or LichTrinh.objects.create(tuyen_duong=tuyen, tau=tau, gio_khoi_hanh=gio, thoi_gian_chay=phut)

    @staticmethod
    def _quy_tac_gia(tuyen, loai, quan_ly, hom_nay) -> int:
        """Mỗi (tuyến, loại chỗ, loại thời điểm) chỉ tạo khi chưa có quy tắc nào, để chạy lại không vi phạm
        ràng buộc EXCLUDE và không ghi đè các quy tắc Quản lý đã sửa."""
        LT = QuyTacGia.LoaiThoiDiem
        so_tao = 0
        for ma_tuyen, theo_loai in GIA.items():
            for ma_loai, (thuong, cuoi_tuan) in theo_loai.items():
                cac_gia = [
                    (LT.NGAY_THUONG, Decimal(thuong), hom_nay, None, "Giá ngày thường"),
                    (LT.CUOI_TUAN, Decimal(cuoi_tuan), hom_nay, None, "Giá cuối tuần"),
                    (LT.LE_TET, Decimal(thuong * 13 // 10), hom_nay + timedelta(days=10),
                     hom_nay + timedelta(days=12), "Đợt lễ giả lập, tăng 30%"),
                ]
                for loai_td, gia, bat_dau, ket_thuc, ghi_chu in cac_gia:
                    da_co = QuyTacGia.objects.filter(
                        tuyen_duong=tuyen[ma_tuyen], loai_cho=loai[ma_loai], loai_thoi_diem=loai_td).exists()
                    if da_co:
                        continue
                    QuyTacGia.objects.create(
                        tuyen_duong=tuyen[ma_tuyen], loai_cho=loai[ma_loai], loai_thoi_diem=loai_td,
                        gia_co_so=gia, ngay_bat_dau=bat_dau, ngay_ket_thuc=ket_thuc, ghi_chu=ghi_chu,
                        nguoi_tao=quan_ly)
                    so_tao += 1
        return so_tao

    @staticmethod
    def _khuyen_mai(hom_nay) -> int:
        KM = KhuyenMai
        mau = [
            dict(ma_khuyen_mai="DATSOM10", ten="Đặt sớm giảm 10%", hinh_thuc_giam=KM.HinhThucGiam.PHAN_TRAM,
                 gia_tri_giam=Decimal(10), muc_giam_toi_da=Decimal(100_000), so_ngay_dat_truoc=7,
                 bat_buoc_nhap_ma=False, doi_tuong_ap_dung="", so_luot_toi_da=None),
            dict(ma_khuyen_mai="SV80K", ten="Sinh viên giảm 80.000 đ", hinh_thuc_giam=KM.HinhThucGiam.SO_TIEN,
                 gia_tri_giam=Decimal(80_000), muc_giam_toi_da=None, so_ngay_dat_truoc=0,
                 bat_buoc_nhap_ma=True, doi_tuong_ap_dung="SINH_VIEN", so_luot_toi_da=100),
        ]
        so_tao = 0
        for m in mau:
            ma = m.pop("ma_khuyen_mai")
            _, tao = KM.objects.get_or_create(ma_khuyen_mai=ma, defaults={
                **m, "ngay_bat_dau": hom_nay, "ngay_ket_thuc": hom_nay + timedelta(days=30),
                "trang_thai": KM.TrangThai.DANG_AP_DUNG})
            so_tao += tao
        return so_tao
