"""TinhGiaService + QuyTacGiaDAO.tim_gia_ap_dung (M4). Dùng ngày cố định (năm 2030) và truyền hom_nay."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from datve.exceptions import KhongCoGia, MaKhuyenMaiKhongHopLe
from datve.services import TinhGiaService
from giave.dao import QuyTacGiaDAO
from giave.models import KhuyenMai, QuyTacGia

pytestmark = pytest.mark.django_db

HOM_NAY = date(2030, 2, 1)
THU_HAI = date(2030, 3, 4)      # thứ Hai
THU_BAY = date(2030, 3, 9)
CHU_NHAT = date(2030, 3, 10)
LT = QuyTacGia.LoaiThoiDiem
KM = KhuyenMai.HinhThucGiam


@pytest.fixture
def gia_theo_loai(tao_quy_tac, dm):
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 450_000, date(2030, 1, 1))
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, date(2030, 1, 1))
    tao_quy_tac(dm.nm, LT.LE_TET, 585_000, date(2030, 3, 9), date(2030, 3, 10))


def _chuyen(tao_chuyen, ngay):
    return tao_chuyen(ngay)


def _tinh(chuyen, dm, doi_tuong="NGUOI_LON", ma=None, hom_nay=HOM_NAY, ghe=None):
    return TinhGiaService.tinh_gia_ve(chuyen, ghe or dm.ghe1[0], doi_tuong, ma, hom_nay)


def test_ngay_thuong_lay_ngay_thuong(gia_theo_loai, dm, tao_chuyen):
    ve = _tinh(_chuyen(tao_chuyen, THU_HAI), dm)
    assert ve.gia_co_so == 450_000
    assert ve.quy_tac_gia.loai_thoi_diem == LT.NGAY_THUONG


def test_thu_bay_lay_cuoi_tuan(gia_theo_loai, dm, tao_chuyen):
    ngay = date(2030, 3, 16)  # thứ Bảy, ngoài đợt lễ
    assert ngay.weekday() == 5
    ve = _tinh(_chuyen(tao_chuyen, ngay), dm)
    assert ve.gia_co_so == 500_000 and ve.quy_tac_gia.loai_thoi_diem == LT.CUOI_TUAN


def test_chu_nhat_lay_cuoi_tuan(gia_theo_loai, dm, tao_chuyen):
    ngay = date(2030, 3, 17)
    assert ngay.weekday() == 6
    assert _tinh(_chuyen(tao_chuyen, ngay), dm).quy_tac_gia.loai_thoi_diem == LT.CUOI_TUAN


@pytest.mark.parametrize("ngay", [THU_BAY, CHU_NHAT])
def test_le_tet_uu_tien_ke_ca_khi_la_cuoi_tuan(gia_theo_loai, dm, tao_chuyen, ngay):
    assert ngay.weekday() >= 5
    ve = _tinh(_chuyen(tao_chuyen, ngay), dm)
    assert ve.quy_tac_gia.loai_thoi_diem == LT.LE_TET and ve.gia_co_so == 585_000


def test_cuoi_tuan_khong_co_quy_tac_thi_dung_ngay_thuong(tao_quy_tac, dm):
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 450_000, date(2030, 1, 1))
    qt = QuyTacGiaDAO.tim_gia_ap_dung(dm.tuyen.id, dm.nm.id, THU_BAY)
    assert qt.loai_thoi_diem == LT.NGAY_THUONG


def test_khong_co_quy_tac_nem_khong_co_gia(gia_theo_loai, dm, tao_chuyen):
    # Toa 2 là loại K4, chưa có quy tắc giá nào
    with pytest.raises(KhongCoGia):
        _tinh(_chuyen(tao_chuyen, THU_HAI), dm, ghe=dm.ghe2[0])


def test_quy_tac_ngung_ap_dung_khong_duoc_dung(tao_quy_tac, dm, tao_chuyen):
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 450_000, date(2030, 1, 1), trang_thai=QuyTacGia.TrangThai.NGUNG_AP_DUNG)
    with pytest.raises(KhongCoGia):
        _tinh(_chuyen(tao_chuyen, THU_HAI), dm)


def test_quy_tac_chua_den_ngay_khong_duoc_dung(tao_quy_tac, dm, tao_chuyen):
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 450_000, date(2030, 6, 1))
    with pytest.raises(KhongCoGia):
        _tinh(_chuyen(tao_chuyen, THU_HAI), dm)


def test_giam_phan_tram_bi_chan_boi_muc_toi_da(gia_theo_loai, dm, tao_chuyen, tao_km):
    km = tao_km(ma_khuyen_mai="GIAM50", gia_tri_giam=Decimal(50), muc_giam_toi_da=Decimal(100_000),
                ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    ve = _tinh(_chuyen(tao_chuyen, THU_HAI), dm)
    assert ve.khuyen_mai == km
    assert ve.so_tien_giam == 100_000 and ve.gia_ve == 350_000   # 50% = 225.000 nhưng tối đa 100.000


def test_lam_tron_xuong_den_nghin(tao_quy_tac, dm, tao_chuyen, tao_km):
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 455_500, date(2030, 1, 1))
    tao_km(gia_tri_giam=Decimal(10), ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    ve = _tinh(_chuyen(tao_chuyen, THU_HAI), dm)
    assert ve.so_tien_giam == 45_000          # 45.550 -> 45.000
    assert ve.gia_ve == 410_500


def test_giam_so_tien_khong_vuot_gia_co_so(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(hinh_thuc_giam=KM.SO_TIEN, gia_tri_giam=Decimal(900_000),
           ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    ve = _tinh(_chuyen(tao_chuyen, THU_HAI), dm)
    assert ve.gia_ve == 0 and ve.so_tien_giam == 450_000


def test_chon_khuyen_mai_giam_nhieu_nhat(gia_theo_loai, dm, tao_chuyen, tao_km):
    ngay = dict(ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    tao_km(ma_khuyen_mai="NHO", gia_tri_giam=Decimal(5), **ngay)                         # 22.500 -> 22.000
    lon = tao_km(ma_khuyen_mai="LON", hinh_thuc_giam=KM.SO_TIEN, gia_tri_giam=Decimal(60_000), **ngay)
    tao_km(ma_khuyen_mai="TRUNG", gia_tri_giam=Decimal(10), **ngay)                      # 45.000
    ve = _tinh(_chuyen(tao_chuyen, THU_HAI), dm)
    assert ve.khuyen_mai == lon and ve.so_tien_giam == 60_000


def test_so_ngay_dat_truoc_loai_khuyen_mai_khi_dat_sat_ngay(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(so_ngay_dat_truoc=7, ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    chuyen = _chuyen(tao_chuyen, THU_HAI)
    sat = _tinh(chuyen, dm, hom_nay=THU_HAI - timedelta(days=3))
    xa = _tinh(chuyen, dm, hom_nay=THU_HAI - timedelta(days=7))
    assert sat.khuyen_mai is None and sat.so_tien_giam == 0
    assert xa.khuyen_mai is not None and xa.so_tien_giam == 45_000


def test_ma_sinh_vien_khong_ap_dung_cho_nguoi_lon(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(ma_khuyen_mai="SV80K", hinh_thuc_giam=KM.SO_TIEN, gia_tri_giam=Decimal(80_000),
           doi_tuong_ap_dung="SINH_VIEN", bat_buoc_nhap_ma=True,
           ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    chuyen = _chuyen(tao_chuyen, THU_HAI)
    nguoi_lon = _tinh(chuyen, dm, "NGUOI_LON", "SV80K")      # mã hợp lệ nhưng vé này không được giảm, không báo lỗi
    sinh_vien = _tinh(chuyen, dm, "SINH_VIEN", "sv80k ")     # chuẩn hóa chữ hoa / khoảng trắng
    assert nguoi_lon.so_tien_giam == 0 and nguoi_lon.khuyen_mai is None
    assert sinh_vien.so_tien_giam == 80_000 and sinh_vien.khuyen_mai.ma_khuyen_mai == "SV80K"


def test_khuyen_mai_bat_buoc_nhap_ma_khong_tu_ap_dung(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(ma_khuyen_mai="CHIMA", bat_buoc_nhap_ma=True, ngay_bat_dau=date(2030, 1, 1),
           ngay_ket_thuc=date(2030, 12, 31))
    chuyen = _chuyen(tao_chuyen, THU_HAI)
    assert _tinh(chuyen, dm).so_tien_giam == 0
    assert _tinh(chuyen, dm, ma="CHIMA").so_tien_giam == 45_000


def test_ma_khong_ton_tai_bao_loi(gia_theo_loai, dm, tao_chuyen):
    with pytest.raises(MaKhuyenMaiKhongHopLe):
        _tinh(_chuyen(tao_chuyen, THU_HAI), dm, ma="KHONGCO")


def test_ma_het_han_hoac_chua_den_ngay_bao_loi(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(ma_khuyen_mai="CU", ngay_bat_dau=date(2029, 1, 1), ngay_ket_thuc=date(2029, 12, 31))
    tao_km(ma_khuyen_mai="SAP", ngay_bat_dau=date(2030, 6, 1), ngay_ket_thuc=date(2030, 12, 31))
    chuyen = _chuyen(tao_chuyen, THU_HAI)
    for ma in ("CU", "SAP"):
        with pytest.raises(MaKhuyenMaiKhongHopLe):
            _tinh(chuyen, dm, ma=ma)


def test_ma_da_ket_thuc_chu_dong_bao_loi(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(ma_khuyen_mai="DONG", trang_thai=KhuyenMai.TrangThai.DA_KET_THUC,
           ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    with pytest.raises(MaKhuyenMaiKhongHopLe):
        _tinh(_chuyen(tao_chuyen, THU_HAI), dm, ma="DONG")


def test_ma_het_luot_bao_loi(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(ma_khuyen_mai="HET", so_luot_toi_da=3, so_luot_da_dung=3,
           ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    with pytest.raises(MaKhuyenMaiKhongHopLe):
        _tinh(_chuyen(tao_chuyen, THU_HAI), dm, ma="HET")


def test_ma_ngoai_pham_vi_tuyen_hoac_loai_cho_bao_loi(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(ma_khuyen_mai="TUYEN2", tuyen_duong=dm.tuyen2, ngay_bat_dau=date(2030, 1, 1),
           ngay_ket_thuc=date(2030, 12, 31))
    tao_km(ma_khuyen_mai="CHOK4", loai_cho=dm.k4, ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    chuyen = _chuyen(tao_chuyen, THU_HAI)
    for ma in ("TUYEN2", "CHOK4"):
        with pytest.raises(MaKhuyenMaiKhongHopLe):
            _tinh(chuyen, dm, ma=ma)


def test_ma_trung_voi_khuyen_mai_tu_dong_khong_tinh_hai_lan(gia_theo_loai, dm, tao_chuyen, tao_km):
    km = tao_km(ma_khuyen_mai="TUDONG", ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    ve = _tinh(_chuyen(tao_chuyen, THU_HAI), dm, ma="TUDONG")
    assert ve.khuyen_mai == km and ve.so_tien_giam == 45_000        # chỉ một khuyến mãi, không cộng dồn


def test_gia_ve_bang_gia_co_so_tru_giam(gia_theo_loai, dm, tao_chuyen, tao_km):
    tao_km(ngay_bat_dau=date(2030, 1, 1), ngay_ket_thuc=date(2030, 12, 31))
    ve = _tinh(_chuyen(tao_chuyen, THU_HAI), dm)
    assert ve.gia_ve == ve.gia_co_so - ve.so_tien_giam
