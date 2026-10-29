"""Lệnh quản trị: seed_demo (chạy lại không nhân đôi), giai_phong_cho."""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from danhmuc.models import ChuyenTau, GheNgoi
from datve.models import DonDatCho, Ve
from datve.services import DatVeService
from giave.models import KhuyenMai, QuyTacGia
from taikhoan.models import ThanhVien
from tien_ich import cho

pytestmark = pytest.mark.django_db


def test_seed_demo_chay_hai_lan_khong_nhan_doi():
    call_command("seed_demo", stdout=StringIO())
    dem = lambda: (ThanhVien.objects.count(), ChuyenTau.objects.count(), GheNgoi.objects.count(),  # noqa: E731
                   QuyTacGia.objects.count(), KhuyenMai.objects.count())
    lan1 = dem()
    call_command("seed_demo", stdout=StringIO())
    assert dem() == lan1 == (3, 30, 80, 12, 2)
    quanly = ThanhVien.objects.get(username="quanly")
    assert quanly.vai_tro == ThanhVien.VaiTro.QUAN_LY and quanly.check_password("Quanly@123")
    assert ThanhVien.objects.get(username="quantri").is_superuser
    assert ThanhVien.objects.get(username="nhanvien").vai_tro == ThanhVien.VaiTro.NHAN_VIEN_BAN_VE


def test_seed_demo_du_lieu_dung_mo_ta():
    call_command("seed_demo", stdout=StringIO())
    sv = KhuyenMai.objects.get(ma_khuyen_mai="SV80K")
    assert sv.bat_buoc_nhap_ma and sv.so_luot_toi_da == 100 and sv.doi_tuong_ap_dung == "SINH_VIEN"
    ds = KhuyenMai.objects.get(ma_khuyen_mai="DATSOM10")
    assert not ds.bat_buoc_nhap_ma and ds.so_ngay_dat_truoc == 7 and ds.muc_giam_toi_da == 100_000
    nm = QuyTacGia.objects.get(tuyen_duong__ma_tuyen="HN-DN", loai_cho__ma_loai="NM", loai_thoi_diem="NGAY_THUONG")
    assert nm.gia_co_so == 450_000
    le = QuyTacGia.objects.get(tuyen_duong__ma_tuyen="HN-DN", loai_cho__ma_loai="NM", loai_thoi_diem="LE_TET")
    assert le.gia_co_so == 585_000 and (le.ngay_ket_thuc - le.ngay_bat_dau).days == 2


def test_seed_demo_cho_phep_dat_ve_ngay_sau_khi_seed(nguoi_dat):
    call_command("seed_demo", stdout=StringIO())
    chuyen = ChuyenTau.objects.filter(ngay_khoi_hanh=timezone.localdate() + timedelta(days=8),
                                      lich_trinh__tau__ma_tau="SE19").get()
    ghe = GheNgoi.objects.filter(toa_xe__tau__ma_tau="SE19", toa_xe__so_toa=1).order_by("id")[:2]
    don = DatVeService.giu_cho(chuyen.id, [cho(ghe[0]), cho(ghe[1], doi_tuong="SINH_VIEN", so_giay_to="987654321")],
                               nguoi_dat, "SV80K")
    ve = list(don.ds_ve.order_by("id"))
    # kịch bản demo bước 7: người lớn giảm DATSOM10, sinh viên giảm SV80K vì 80.000 đ > 10% giá ngồi mềm
    assert ve[0].khuyen_mai.ma_khuyen_mai == "DATSOM10" and ve[0].so_tien_giam == ve[0].gia_co_so // 10 // 1000 * 1000
    assert ve[1].khuyen_mai.ma_khuyen_mai == "SV80K" and ve[1].so_tien_giam == 80_000


def test_lenh_giai_phong_cho(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    DonDatCho.objects.filter(pk=don.pk).update(thoi_diem_het_han=timezone.now() - timedelta(minutes=1))
    out = StringIO()
    call_command("giai_phong_cho", stdout=out)
    assert "Đã giải phóng 1 đơn" in out.getvalue()
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.HET_HAN
    assert Ve.objects.get().trang_thai == Ve.TrangThai.DA_HUY
    out = StringIO()
    call_command("giai_phong_cho", stdout=out)
    assert "Đã giải phóng 0 đơn" in out.getvalue()
