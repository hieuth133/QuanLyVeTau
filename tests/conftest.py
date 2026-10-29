"""Fixture dùng chung. Mọi ngày tháng đều tính tương đối (hoặc truyền `hom_nay`) để test không phụ thuộc ngày chạy."""
import itertools
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from danhmuc.models import ChuyenTau, GaTau, GheNgoi, LichTrinh, LoaiCho, Tau, ToaXe, TuyenDuong
from giave.models import KhuyenMai, QuyTacGia
from taikhoan.models import ThanhVien

_dem = itertools.count(1)


@pytest.fixture
def hom_nay() -> date:
    return timezone.localdate()


@pytest.fixture
def quan_ly(db):
    return ThanhVien.objects.create_user(
        "quanly_test", password="Matkhau@123", ho_ten="Quản Lý Test", vai_tro=ThanhVien.VaiTro.QUAN_LY)


@pytest.fixture
def nhan_vien(db):
    return ThanhVien.objects.create_user(
        "nhanvien_test", password="Matkhau@123", ho_ten="Nhân Viên Test",
        vai_tro=ThanhVien.VaiTro.NHAN_VIEN_BAN_VE)


@pytest.fixture
def dm(db):
    """Danh mục tối thiểu: 1 tuyến, 1 tàu, toa 1 ngồi mềm (8 ghế), toa 2 nằm khoang 4 (4 giường)."""
    ga_a = GaTau.objects.create(ten_ga="Ga A", tinh_thanh="A")
    ga_b = GaTau.objects.create(ten_ga="Ga B", tinh_thanh="B")
    tuyen = TuyenDuong.objects.create(ma_tuyen="T1", ten_tuyen="A - B", ga_di=ga_a, ga_den=ga_b)
    tuyen2 = TuyenDuong.objects.create(ma_tuyen="T2", ten_tuyen="B - A", ga_di=ga_b, ga_den=ga_a)
    nm = LoaiCho.objects.create(ma_loai="NM", ten_loai="Ngồi mềm điều hòa")
    k4 = LoaiCho.objects.create(ma_loai="K4", ten_loai="Nằm khoang 4 điều hòa")
    tau = Tau.objects.create(ma_tau="T01", ten_tau="Tàu 01")
    toa1 = ToaXe.objects.create(tau=tau, so_toa=1, loai_cho=nm)
    toa2 = ToaXe.objects.create(tau=tau, so_toa=2, loai_cho=k4)
    ghe1 = [GheNgoi.objects.create(toa_xe=toa1, so_ghe=str(i)) for i in range(1, 9)]
    ghe2 = [GheNgoi.objects.create(toa_xe=toa2, so_ghe=str(i)) for i in range(1, 5)]
    lich = LichTrinh.objects.create(tuyen_duong=tuyen, tau=tau, gio_khoi_hanh=time(20, 5), thoi_gian_chay=600)
    return SimpleNamespace(ga_a=ga_a, ga_b=ga_b, tuyen=tuyen, tuyen2=tuyen2, nm=nm, k4=k4, tau=tau,
                           toa1=toa1, toa2=toa2, ghe1=ghe1, ghe2=ghe2, lich=lich)


@pytest.fixture
def tao_chuyen(dm):
    def _tao(ngay: date, trang_thai=ChuyenTau.TrangThai.MO_BAN, lich=None) -> ChuyenTau:
        return ChuyenTau.objects.create(lich_trinh=lich or dm.lich, ngay_khoi_hanh=ngay, trang_thai=trang_thai)
    return _tao


@pytest.fixture
def tao_quy_tac(dm, quan_ly):
    def _tao(loai_cho=None, loai_td=QuyTacGia.LoaiThoiDiem.NGAY_THUONG, gia=450_000, bat_dau=date(2020, 1, 1),
             ket_thuc=None, tuyen=None, trang_thai=QuyTacGia.TrangThai.DANG_AP_DUNG) -> QuyTacGia:
        return QuyTacGia.objects.create(
            tuyen_duong=tuyen or dm.tuyen, loai_cho=loai_cho or dm.nm, gia_co_so=Decimal(gia),
            loai_thoi_diem=loai_td, ngay_bat_dau=bat_dau, ngay_ket_thuc=ket_thuc, trang_thai=trang_thai,
            nguoi_tao=quan_ly)
    return _tao


@pytest.fixture
def gia_day_du(tao_quy_tac, dm):
    """Giá ngày thường: NM 450.000 đ, K4 750.000 đ (hiệu lực từ lâu, không kết thúc)."""
    return SimpleNamespace(nm=tao_quy_tac(dm.nm, gia=450_000), k4=tao_quy_tac(dm.k4, gia=750_000))


@pytest.fixture
def tao_km(hom_nay):
    def _tao(**kw) -> KhuyenMai:
        n = next(_dem)
        du_lieu = dict(
            ma_khuyen_mai=f"KM{n}", ten=f"Khuyến mãi {n}", hinh_thuc_giam=KhuyenMai.HinhThucGiam.PHAN_TRAM,
            gia_tri_giam=Decimal(10), ngay_bat_dau=hom_nay - timedelta(days=1),
            ngay_ket_thuc=hom_nay + timedelta(days=30), trang_thai=KhuyenMai.TrangThai.DANG_AP_DUNG)
        du_lieu.update(kw)
        return KhuyenMai.objects.create(**du_lieu)
    return _tao


@pytest.fixture
def chuyen(tao_chuyen, hom_nay, gia_day_du):
    """Chuyến mở bán sau 10 ngày, đã có giá cho cả hai loại chỗ."""
    return tao_chuyen(hom_nay + timedelta(days=10))


@pytest.fixture
def nguoi_dat():
    return {"ho_ten": "Nguyễn Văn A", "so_dien_thoai": "0912345678", "email": "a@example.com"}
