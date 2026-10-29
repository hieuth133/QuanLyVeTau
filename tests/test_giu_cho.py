"""UC02: giữ chỗ (service, DAO, tác vụ giải phóng) và luồng HTTP (A1-A8)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from danhmuc.dao import ChuyenTauDAO, GheNgoiDAO
from danhmuc.models import ChuyenTau
from datve.dao import DonDatChoDAO, KhachHangDAO
from datve.exceptions import (ChoDaBiGiu, ChuyenKhongMoBan, DonKhongThanhToanDuoc, KhongCoGia, KhuyenMaiHetLuot,
                              MaKhuyenMaiKhongHopLe)
from datve.forms import HanhKhachForm, ThongTinDatVeForm
from datve.models import DonDatCho, KhachHang, Ve
from datve.services import DatVeService, sinh_ma_dat_cho
from datve.tasks import GiaiPhongChoTask
from giave.models import KhuyenMai
from tien_ich import cho, thoi_diem_khoi_hanh_sau

pytestmark = pytest.mark.django_db


def het_han(don, phut=5):
    """Đẩy thời điểm hết hạn của đơn về quá khứ."""
    DonDatCho.objects.filter(pk=don.pk).update(thoi_diem_het_han=timezone.now() - timedelta(minutes=phut))


# --------------------------------------------------------------------------- DatVeService.giu_cho
def test_giu_cho_thanh_cong(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, None)
    assert don.trang_thai == DonDatCho.TrangThai.DANG_GIU and len(don.ma_dat_cho) == 8
    ds_ve = list(don.ds_ve.all())
    assert len(ds_ve) == 2 and all(v.trang_thai == Ve.TrangThai.DANG_GIU for v in ds_ve)
    assert don.tong_tien == sum(v.gia_ve for v in ds_ve) == 900_000
    assert abs((don.thoi_diem_het_han - timezone.now()) - timedelta(minutes=settings.GIU_CHO_PHUT)) < timedelta(seconds=30)
    kh = don.khach_hang
    assert (kh.ho_ten, kh.so_dien_thoai, kh.email) == ("Nguyễn Văn A", "0912345678", "a@example.com")


def test_gia_ve_duoc_chot_vao_ve(dm, chuyen, nguoi_dat, gia_day_du):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe2[0])], nguoi_dat, None)
    ve = don.ds_ve.get()
    assert ve.quy_tac_gia_id == gia_day_du.k4.id and ve.gia_co_so == 750_000 and ve.gia_ve == 750_000


def test_ghe_da_co_ve_nem_cho_da_bi_giu_va_khong_tao_don(dm, chuyen, nguoi_dat):
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    truoc = (DonDatCho.objects.count(), Ve.objects.count())
    with pytest.raises(ChoDaBiGiu) as e:
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[1]), cho(dm.ghe1[0])],
                             {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    assert e.value.ds_ghe_id == [dm.ghe1[0].id]
    assert (DonDatCho.objects.count(), Ve.objects.count()) == truoc            # hoàn tác toàn bộ (A6)
    assert not KhachHang.objects.filter(so_dien_thoai="0987654321").exists()
    assert not Ve.objects.filter(ghe_ngoi=dm.ghe1[1]).exists()


def test_cung_ghe_o_chuyen_khac_dat_duoc(dm, chuyen, tao_chuyen, hom_nay, nguoi_dat):
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    khac = tao_chuyen(hom_nay + timedelta(days=11))
    DatVeService.giu_cho(khac.id, [cho(dm.ghe1[0])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)


def test_vuot_max_cho_moi_don_bi_tu_choi(dm, chuyen, nguoi_dat, settings):
    settings.MAX_CHO_MOI_DON = 2
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [cho(g) for g in dm.ghe1[:3]], nguoi_dat, None)
    assert DonDatCho.objects.count() == 0
    DatVeService.giu_cho(chuyen.id, [cho(g) for g in dm.ghe1[:2]], nguoi_dat, None)      # đúng bằng mức tối đa


def test_khong_chon_cho_nao_bi_tu_choi(chuyen, nguoi_dat):
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [], nguoi_dat, None)


def test_ghe_trung_lap_trong_cung_yeu_cau_bi_tu_choi(dm, chuyen, nguoi_dat):
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[0], so_giay_to="987654321")], nguoi_dat, None)
    assert DonDatCho.objects.count() == 0


def test_ghe_khong_thuoc_doan_tau_bi_tu_choi_khong_keyerror(dm, chuyen, nguoi_dat):
    from danhmuc.models import GheNgoi, Tau, ToaXe
    tau2 = Tau.objects.create(ma_tau="T02", ten_tau="Tàu 02")
    toa = ToaXe.objects.create(tau=tau2, so_toa=1, loai_cho=dm.nm)
    ghe_la = GheNgoi.objects.create(toa_xe=toa, so_ghe="1")
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [cho(ghe_la)], nguoi_dat, None)
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [{"ghe_id": 10 ** 9, "ho_ten": "X", "doi_tuong": "NGUOI_LON",
                                          "so_giay_to": "123456"}], nguoi_dat, None)


def test_doi_tuong_khong_hop_le_bi_tu_choi(dm, chuyen, nguoi_dat):
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0], doi_tuong="SIEU_NHAN")], nguoi_dat, None)


def test_chuyen_ngung_ban_bi_tu_choi(dm, tao_chuyen, hom_nay, nguoi_dat):
    c = tao_chuyen(hom_nay + timedelta(days=5), ChuyenTau.TrangThai.NGUNG_BAN)
    with pytest.raises(ChuyenKhongMoBan):
        DatVeService.giu_cho(c.id, [cho(dm.ghe1[0])], nguoi_dat, None)


def test_chuyen_qua_thoi_diem_ngung_ban_bi_tu_choi(dm, gia_day_du, tao_chuyen, nguoi_dat):
    from danhmuc.models import LichTrinh
    ngay, gio = thoi_diem_khoi_hanh_sau(30)          # còn 30 phút, ngừng bán trước 60 phút
    lich = LichTrinh.objects.create(tuyen_duong=dm.tuyen, tau=dm.tau, gio_khoi_hanh=gio, thoi_gian_chay=60)
    c = tao_chuyen(ngay, lich=lich)
    with pytest.raises(ChuyenKhongMoBan):
        DatVeService.giu_cho(c.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    assert ChuyenTauDAO.tim_chuyen_tau(dm.ga_a.id, dm.ga_b.id, ngay) == []


def test_chuyen_khong_ton_tai_bi_tu_choi(nguoi_dat, dm):
    with pytest.raises(ChuyenKhongMoBan):
        DatVeService.giu_cho(10 ** 9, [cho(dm.ghe1[0])], nguoi_dat, None)


def test_thoi_diem_het_han_khong_vuot_thoi_diem_ngung_ban(dm, gia_day_du, tao_chuyen, nguoi_dat, settings):
    from danhmuc.models import LichTrinh
    settings.GIU_CHO_PHUT = 120
    ngay, gio = thoi_diem_khoi_hanh_sau(90)          # ngừng bán sau ~30 phút nữa
    lich = LichTrinh.objects.create(tuyen_duong=dm.tuyen, tau=dm.tau, gio_khoi_hanh=gio, thoi_gian_chay=60)
    c = tao_chuyen(ngay, lich=lich)
    don = DatVeService.giu_cho(c.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    assert don.thoi_diem_het_han <= c.thoi_diem_ngung_ban
    assert don.thoi_diem_het_han < timezone.now() + timedelta(minutes=60)


def test_chuyen_chua_co_gia_nem_khong_co_gia(dm, tao_chuyen, hom_nay, nguoi_dat):
    c = tao_chuyen(hom_nay + timedelta(days=6))        # không có fixture giá
    with pytest.raises(KhongCoGia):
        DatVeService.giu_cho(c.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    assert DonDatCho.objects.count() == 0


# --------------------------------------------------------------------------- Khuyến mãi khi giữ chỗ
def test_giu_cho_tang_luot_khuyen_mai_va_tong_tien(dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="SV80K", hinh_thuc_giam="SO_TIEN", gia_tri_giam=Decimal(80_000),
                doi_tuong_ap_dung="SINH_VIEN", bat_buoc_nhap_ma=True, so_luot_toi_da=100)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0], doi_tuong="SINH_VIEN"),
                                           cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, "sv80k")
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1                       # chỉ vé sinh viên dùng mã
    assert don.tong_tien == (450_000 - 80_000) + 450_000


def test_ma_sai_nem_loi_va_khong_tao_don(dm, chuyen, nguoi_dat):
    with pytest.raises(MaKhuyenMaiKhongHopLe):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, "KHONGCO")
    assert DonDatCho.objects.count() == 0 and Ve.objects.count() == 0


def test_khuyen_mai_con_it_luot_hon_so_ve_chi_giam_du_so_luot_con_lai(dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="CON1", so_luot_toi_da=3, so_luot_da_dung=2, bat_buoc_nhap_ma=True)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, "CON1")
    km.refresh_from_db()
    assert km.so_luot_da_dung == 3                                  # chỉ 1 lượt còn lại -> chỉ 1 vé được giảm
    assert sorted(v.so_tien_giam for v in don.ds_ve.all()) == [0, 45_000] and don.tong_tien == 855_000


def test_khuyen_mai_het_luot_do_tranh_chap_hoan_tac_giao_dich(dm, chuyen, nguoi_dat, tao_km, monkeypatch):
    from giave.dao import KhuyenMaiDAO
    km = tao_km(ma_khuyen_mai="CON1", so_luot_toi_da=3, so_luot_da_dung=2, bat_buoc_nhap_ma=True)
    # mô phỏng người khác vừa lấy mất lượt cuối giữa lúc tính giá và lúc ghi (lưới an toàn của tang_luot_dung)
    monkeypatch.setattr(KhuyenMaiDAO, "tang_luot_dung", staticmethod(lambda id, so_luot: False))
    with pytest.raises(KhuyenMaiHetLuot):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, "CON1")
    km.refresh_from_db()
    assert km.so_luot_da_dung == 2 and DonDatCho.objects.count() == 0 and Ve.objects.count() == 0


# --------------------------------------------------------------------------- Sơ đồ chỗ và hết hạn (A7)
def test_so_do_cho_ba_trang_thai_va_toa_chua_co_gia(dm, chuyen, nguoi_dat, tao_quy_tac):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    DatVeService.thanh_toan_gia_lap(don.ma_dat_cho)
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[1], so_giay_to="987654321")],
                         {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    so_do = {g["so_ghe"]: g for g in GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)}
    assert [so_do[str(i)]["trang_thai"] for i in (1, 2, 3)] == ["DA_BAN", "DANG_GIU", "TRONG"]
    assert so_do["3"]["gia"] == 450_000 and len(so_do) == 8
    sorted_ids = [g["so_ghe"] for g in GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)]
    assert sorted_ids == [str(i) for i in range(1, 9)]                                  # sắp theo số
    # Toa 2 (K4) không có giá: gia = None
    from giave.models import QuyTacGia
    QuyTacGia.objects.filter(loai_cho=dm.k4).delete()
    assert all(g["gia"] is None for g in GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa2.id))
    assert GheNgoiDAO.lay_ds_toa(chuyen.id)[1].gia_co_so is None


def test_don_qua_han_hien_trong_va_dat_lai_duoc(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    het_han(don)
    so_do = GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)
    assert so_do[0]["trang_thai"] == "TRONG"                          # chưa chạy tác vụ nền vẫn hiển thị trống
    assert GheNgoiDAO.lay_ghe_dang_chiem(chuyen.id, [dm.ghe1[0].id]) == []
    don2 = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.HET_HAN                # được giải phóng ngay trong giao dịch giữ chỗ
    assert don.ds_ve.get().trang_thai == Ve.TrangThai.DA_HUY
    assert don2.trang_thai == DonDatCho.TrangThai.DANG_GIU


def test_giai_phong_cho_task_chuyen_het_han_huy_ve_va_hoan_luot_km(dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="GIAM10", so_luot_toi_da=10)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, None)
    km.refresh_from_db()
    assert km.so_luot_da_dung == 2
    con_han = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[2])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    het_han(don)
    assert GiaiPhongChoTask.chay() == 1
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.HET_HAN
    assert all(v.trang_thai == Ve.TrangThai.DA_HUY for v in don.ds_ve.all())
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1                                      # hoàn 2 lượt của đơn hết hạn, còn 1 của đơn kia
    con_han.refresh_from_db()
    assert con_han.trang_thai == DonDatCho.TrangThai.DANG_GIU
    assert GiaiPhongChoTask.chay() == 0                                 # chạy lại không làm gì thêm
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1


def test_giai_phong_khong_dong_vao_don_da_thanh_toan_hoac_chua_het_han(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    assert DonDatChoDAO.giai_phong(don) is False               # chưa hết hạn
    DatVeService.thanh_toan_gia_lap(don.ma_dat_cho)
    het_han(don)
    assert GiaiPhongChoTask.chay() == 0
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DA_THANH_TOAN


# --------------------------------------------------------------------------- Thanh toán giả lập, khách hàng, mã
def test_thanh_toan_gia_lap(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    DatVeService.thanh_toan_gia_lap(don.ma_dat_cho)
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DA_THANH_TOAN
    assert don.ds_ve.get().trang_thai == Ve.TrangThai.DA_THANH_TOAN
    with pytest.raises(DonKhongThanhToanDuoc):                 # không thanh toán hai lần
        DatVeService.thanh_toan_gia_lap(don.ma_dat_cho)


def test_khong_thanh_toan_duoc_don_het_han(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    het_han(don)
    with pytest.raises(DonKhongThanhToanDuoc):
        DatVeService.thanh_toan_gia_lap(don.ma_dat_cho)
    with pytest.raises(DonKhongThanhToanDuoc):
        DatVeService.thanh_toan_gia_lap("KHONGCO1")
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DANG_GIU


def test_tim_hoac_tao_khach_hang_theo_so_dien_thoai_va_cap_nhat():
    a = KhachHangDAO.tim_hoac_tao("Nguyễn A", "0912345678", "a@x.vn")
    b = KhachHangDAO.tim_hoac_tao("Nguyễn Văn A", "0912345678", "moi@x.vn")
    assert a.id == b.id and KhachHang.objects.count() == 1
    b.refresh_from_db()
    assert (b.ho_ten, b.email) == ("Nguyễn Văn A", "moi@x.vn")
    c = KhachHangDAO.tim_hoac_tao("Trần B", "0987654321", "")
    assert c.id != a.id and KhachHang.objects.count() == 2


def test_sinh_ma_dat_cho_dung_bang_chu_cai_khong_nham_lan():
    for _ in range(50):
        ma = sinh_ma_dat_cho()
        assert len(ma) == 8 and not set(ma) & set("0O1I") and ma == ma.upper()


# --------------------------------------------------------------------------- DAO tìm chuyến
def test_tim_chuyen_dem_cho_trong(dm, chuyen, nguoi_dat):
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe2[0], so_giay_to="987654321")], nguoi_dat, None)
    ds = ChuyenTauDAO.tim_chuyen_tau(dm.ga_a.id, dm.ga_b.id, chuyen.ngay_khoi_hanh)
    assert [c.id for c in ds] == [chuyen.id]
    assert ds[0].tong_ghe == 12 and ds[0].so_cho_trong == 10
    assert ChuyenTauDAO.tim_chuyen_tau(dm.ga_b.id, dm.ga_a.id, chuyen.ngay_khoi_hanh) == []


def test_tim_chuyen_dung_so_truy_van_khong_lap(dm, chuyen, tao_chuyen, hom_nay):
    for d in range(11, 14):
        tao_chuyen(hom_nay + timedelta(days=d))
    with CaptureQueriesContext(connection) as q:
        ChuyenTauDAO.tim_chuyen_tau(dm.ga_a.id, dm.ga_b.id, chuyen.ngay_khoi_hanh)
    assert len(q) == 1


def test_don_het_han_khong_tinh_vao_cho_trong(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    het_han(don)
    assert ChuyenTauDAO.tim_chuyen_tau(dm.ga_a.id, dm.ga_b.id, chuyen.ngay_khoi_hanh)[0].so_cho_trong == 12


# --------------------------------------------------------------------------- Form: kiểm tra dữ liệu (A4)
@pytest.mark.parametrize("sdt", ["123456789", "09123456", "09123456789", "abcdefghij", ""])
def test_form_nguoi_dat_tu_choi_so_dien_thoai_sai(sdt):
    f = ThongTinDatVeForm({"ho_ten": "A B", "so_dien_thoai": sdt, "email": ""})
    assert not f.is_valid() and "so_dien_thoai" in f.errors


def test_form_nguoi_dat_chap_nhan_sdt_hop_le_va_chuan_hoa():
    f = ThongTinDatVeForm({"ho_ten": "  Nguyễn   Văn A ", "so_dien_thoai": "0912 345 678", "email": "",
                           "ma_khuyen_mai": " sv80k "})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["so_dien_thoai"] == "0912345678"
    assert f.cleaned_data["ho_ten"] == "Nguyễn Văn A" and f.cleaned_data["ma_khuyen_mai"] == "SV80K"


def test_form_nguoi_dat_email_va_ho_ten():
    assert not ThongTinDatVeForm({"ho_ten": "A", "so_dien_thoai": "0912345678", "email": "khong-hop-le"}).is_valid()
    assert ThongTinDatVeForm({"ho_ten": "A", "so_dien_thoai": "0912345678", "email": ""}).is_valid()   # email tùy chọn
    f = ThongTinDatVeForm({"ho_ten": "   ", "so_dien_thoai": "0912345678"})
    assert not f.is_valid() and "ho_ten" in f.errors


@pytest.mark.parametrize("giay_to", ["12345", "123 456 789", "abc-123456", "A" * 21, ""])
def test_form_hanh_khach_tu_choi_so_giay_to_sai(giay_to):
    f = HanhKhachForm({"ghe_id": 1, "ho_ten": "A", "doi_tuong": "NGUOI_LON", "so_giay_to": giay_to})
    assert not f.is_valid() and "so_giay_to" in f.errors


def test_form_hanh_khach_doi_tuong_phai_thuoc_danh_sach_va_ho_ten_bat_buoc():
    assert not HanhKhachForm({"ghe_id": 1, "ho_ten": "A", "doi_tuong": "KHAC", "so_giay_to": "123456"}).is_valid()
    assert not HanhKhachForm({"ghe_id": 1, "ho_ten": " ", "doi_tuong": "TRE_EM", "so_giay_to": "123456"}).is_valid()
    assert HanhKhachForm({"ghe_id": 1, "ho_ten": "A", "doi_tuong": "TRE_EM", "so_giay_to": "ab123456"}).is_valid()


# --------------------------------------------------------------------------- Luồng HTTP
def du_lieu_giu_cho(ghe_list, nguoi_dat, ma="", **ghi_de_hk):
    d = {"hk-TOTAL_FORMS": len(ghe_list), "hk-INITIAL_FORMS": len(ghe_list), "hk-MIN_NUM_FORMS": 0,
         "hk-MAX_NUM_FORMS": 1000, "ho_ten": nguoi_dat["ho_ten"], "so_dien_thoai": nguoi_dat["so_dien_thoai"],
         "email": nguoi_dat["email"], "ma_khuyen_mai": ma}
    for i, g in enumerate(ghe_list):
        d.update({f"hk-{i}-ghe_id": g.id, f"hk-{i}-ho_ten": f"Hành khách {i + 1}", f"hk-{i}-doi_tuong": "NGUOI_LON",
                  f"hk-{i}-so_giay_to": f"01234567{i}"})
    for k, v in ghi_de_hk.items():
        d[k] = v
    return d


def test_http_tim_chuyen_va_chon_cho(client, dm, chuyen):
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id,
                                           "ngay_di": chuyen.ngay_khoi_hanh.isoformat(), "so_hanh_khach": 2})
    assert r.status_code == 200 and [c.id for c in r.context["ds_chuyen"]] == [chuyen.id]
    assert r.context["ds_chuyen"][0].gia_thap_nhat == 450_000
    r = client.get(reverse("chon_cho", args=[chuyen.id]), {"toa": dm.toa2.id})
    assert r.status_code == 200 and r.context["toa_chon"] == dm.toa2.id
    html = r.content.decode()
    assert 'name="ghe"' in html and "seat-trong" in html and "450.000 đ" in html and "750.000 đ" in html


def test_http_trang_tim_chuyen_khi_chua_nhap_gi(client, db):
    assert client.get(reverse("tim_chuyen")).status_code == 200
    assert client.get("/").status_code == 302


def test_a1_khong_co_chuyen_goi_y_ngay_lan_can(client, dm, tao_chuyen, gia_day_du, hom_nay):
    co_chuyen = hom_nay + timedelta(days=9)
    tao_chuyen(co_chuyen)
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id,
                                           "ngay_di": (hom_nay + timedelta(days=7)).isoformat(), "so_hanh_khach": 1})
    assert r.status_code == 200 and r.context["ds_chuyen"] == []
    goi_y = r.context["goi_y"]
    assert [g["ngay"] for g in goi_y] == [co_chuyen]
    html = r.content.decode()
    assert "Không có chuyến phù hợp" in html and goi_y[0]["url"] in html.replace("&amp;", "&")


def test_a1_ngay_di_qua_khu_hoac_ga_trung_bi_chan(client, dm, hom_nay):
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_a.id,
                                           "ngay_di": (hom_nay - timedelta(days=1)).isoformat(), "so_hanh_khach": 1})
    assert r.status_code == 200 and {"ga_den", "ngay_di"} <= set(r.context["form"].errors)


def test_a2_chuyen_het_cho_thong_bao_va_ve_trang_tim(client, dm, chuyen, nguoi_dat):
    tat_ca = dm.ghe1 + dm.ghe2
    for i in range(0, len(tat_ca), 6):
        DatVeService.giu_cho(chuyen.id, [cho(g, so_giay_to=f"12345678{j}") for j, g in enumerate(tat_ca[i:i + 6])],
                             {**nguoi_dat, "so_dien_thoai": f"09000000{i:02d}"}, None)
    r = client.get(reverse("chon_cho", args=[chuyen.id]), follow=True)
    assert r.redirect_chain and "hết chỗ" in r.content.decode()


def test_a2_chuyen_ngung_ban_khong_vao_duoc_so_do(client, dm, tao_chuyen, hom_nay, gia_day_du):
    c = tao_chuyen(hom_nay + timedelta(days=4), ChuyenTau.TrangThai.NGUNG_BAN)
    r = client.get(reverse("chon_cho", args=[c.id]), follow=True)
    assert r.redirect_chain and "ngừng bán" in r.content.decode()


def test_a3_server_kiem_tra_lai_so_cho_toi_da(client, dm, chuyen, settings):
    settings.MAX_CHO_MOI_DON = 2
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [g.id for g in dm.ghe1[:3]]}, follow=True)
    assert r.redirect_chain and "tối đa 2 chỗ" in r.content.decode()
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [g.id for g in dm.ghe1[:2]]})
    assert r.status_code == 200 and len(r.context["formset"].forms) == 2


def test_thong_tin_tu_choi_ghe_la_hoac_rong_hoac_da_giu(client, dm, chuyen, nguoi_dat):
    for tham_so in ({}, {"ghe": ["abc"]}, {"ghe": [10 ** 9]}):
        r = client.get(reverse("thong_tin", args=[chuyen.id]), tham_so)
        assert r.status_code == 302
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [dm.ghe1[0].id]}, follow=True)
    assert r.redirect_chain and "vừa được người khác giữ" in r.content.decode()


def test_giu_cho_qua_http_thanh_cong_va_xem_ket_qua(client, dm, chuyen, nguoi_dat, tao_km):
    tao_km(ma_khuyen_mai="DATSOM10")
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [dm.ghe1[0].id, dm.ghe1[1].id]})
    assert r.status_code == 200 and r.context["tam_tinh"] == 900_000
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat))
    don = DonDatCho.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("ket_qua", args=[don.ma_dat_cho])
    assert don.tong_tien == 810_000 and client.session["don_cua_toi"] == [don.ma_dat_cho]
    r = client.get(r["Location"])
    html = r.content.decode()
    assert r.status_code == 200 and don.ma_dat_cho in html and 'id="dem-nguoc"' in html and "810.000 đ" in html
    assert 0 < r.context["con_lai_giay"] <= settings.GIU_CHO_PHUT * 60


def test_ket_qua_chi_xem_duoc_khi_ma_nam_trong_session(client, dm, chuyen, nguoi_dat, client_khac=None):
    from django.test import Client
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    assert client.get(reverse("ket_qua", args=[don.ma_dat_cho])).status_code == 200
    nguoi_la = Client()
    assert nguoi_la.get(reverse("ket_qua", args=[don.ma_dat_cho])).status_code == 403
    assert nguoi_la.post(reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho])).status_code == 403
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DANG_GIU


def test_a4_loi_formset_gan_dung_truong_va_giu_du_lieu(client, dm, chuyen, nguoi_dat):
    du_lieu = du_lieu_giu_cho(dm.ghe1[:2], {**nguoi_dat, "so_dien_thoai": "12345"},
                              **{"hk-1-so_giay_to": "12", "hk-0-ho_ten": "Họ tên giữ lại"})
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu)
    assert r.status_code == 200
    assert "so_dien_thoai" in r.context["form"].errors
    assert "so_giay_to" in r.context["formset"].forms[1].errors and not r.context["formset"].forms[0].errors
    html = r.content.decode()
    assert "Họ tên giữ lại" in html and 'value="12345"' in html and "is-invalid" in html
    assert DonDatCho.objects.count() == 0


def test_a4_hanh_khach_trung_ghe_hoac_thieu_form(client, dm, chuyen, nguoi_dat):
    d = du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat, **{"hk-1-ghe_id": dm.ghe1[0].id})
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 200 and r.context["formset"].non_form_errors()
    d = du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat, **{"hk-TOTAL_FORMS": 0})
    assert client.post(reverse("giu_cho", args=[chuyen.id]), d).status_code == 200
    assert client.post(reverse("giu_cho", args=[chuyen.id]), {}).status_code == 200
    assert DonDatCho.objects.count() == 0


def test_post_ghe_la_khong_bao_gio_tra_500(client, dm, chuyen, nguoi_dat):
    from danhmuc.models import GheNgoi, Tau, ToaXe
    toa = ToaXe.objects.create(tau=Tau.objects.create(ma_tau="T09", ten_tau="Tàu lạ"), so_toa=1, loai_cho=dm.nm)
    ghe_la = GheNgoi.objects.create(toa_xe=toa, so_ghe="1")
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho([ghe_la], nguoi_dat))
    assert r.status_code == 302 and r["Location"].startswith(reverse("chon_cho", args=[chuyen.id]))
    r = client.post(reverse("giu_cho", args=[10 ** 9]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    assert r.status_code == 404
    assert DonDatCho.objects.count() == 0


def test_post_vuot_so_cho_toi_da_khong_500(client, dm, chuyen, nguoi_dat, settings):
    settings.MAX_CHO_MOI_DON = 2
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:3], nguoi_dat))
    assert r.status_code == 200 and r.context["formset"].non_form_errors()


def test_a5_ma_khuyen_mai_sai_loi_o_o_ma_hien_gia_khong_ma_va_tiep_tuc_khong_dung_ma(client, dm, chuyen, nguoi_dat, tao_km):
    tao_km(ma_khuyen_mai="TUDONG10")                                    # 10% tự động = 45.000 / vé
    d = du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat, ma="KHONGCO")
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 200 and "ma_khuyen_mai" in r.context["form"].errors
    assert r.context["tong_khong_ma"] == 2 * 405_000 and len(r.context["bang_gia_khong_ma"]) == 2
    html = r.content.decode()
    assert "Tiếp tục không dùng mã" in html and 'value="KHONGCO"' in html and "810.000 đ" in html
    assert DonDatCho.objects.count() == 0
    d["bo_ma"] = "1"                                                     # bấm nút "Tiếp tục không dùng mã"
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 302
    assert DonDatCho.objects.get().tong_tien == 810_000


def test_a5_ma_hop_le_nhung_khong_ap_dung_cho_ai_thi_canh_bao_khong_loi(client, dm, chuyen, nguoi_dat, tao_km):
    tao_km(ma_khuyen_mai="CHISV", doi_tuong_ap_dung="SINH_VIEN", bat_buoc_nhap_ma=True)
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat, ma="CHISV"),
                    follow=True)
    assert "không áp dụng được cho hành khách nào" in r.content.decode()
    assert DonDatCho.objects.get().tong_tien == 450_000


def test_a5_khuyen_mai_het_luot_hien_loi_o_o_ma(client, dm, chuyen, nguoi_dat, tao_km, monkeypatch):
    from giave.dao import KhuyenMaiDAO
    tao_km(ma_khuyen_mai="CON1", so_luot_toi_da=2, so_luot_da_dung=1, bat_buoc_nhap_ma=True)
    # lượt cuối bị người khác lấy mất đúng lúc ghi (tranh chấp)
    monkeypatch.setattr(KhuyenMaiDAO, "tang_luot_dung", staticmethod(lambda id, so_luot: False))
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat, ma="CON1"))
    assert r.status_code == 200 and "ma_khuyen_mai" in r.context["form"].errors
    assert DonDatCho.objects.count() == 0


def test_a6_xung_dot_ve_so_do_cua_toa_bao_so_ghe_mat_va_giu_thong_tin(client, dm, chuyen, nguoi_dat):
    # Người khác giữ ghế 2 của toa 2 trước
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe2[1])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    d = du_lieu_giu_cho([dm.ghe1[0], dm.ghe2[1]], nguoi_dat, ma="")
    d["hk-0-ho_ten"] = "Người cần điền lại"
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d, follow=True)
    assert r.redirect_chain[-1][0] == reverse("chon_cho", args=[chuyen.id]) + f"?toa={dm.toa2.id}"
    html = r.content.decode()
    assert "1 chỗ vừa được người khác giữ" in html and "ghế 2 (toa 2)" in html
    assert r.context["toa_chon"] == dm.toa2.id
    assert DonDatCho.objects.count() == 1                                 # chỉ đơn của người kia; đơn này hoàn tác
    tam = client.session["thong_tin_tam"]
    assert tam["nguoi_dat"]["so_dien_thoai"] == "0912345678" and tam["hanh_khach"][0]["ho_ten"] == "Người cần điền lại"
    # chọn lại ghế khác: thông tin hành khách được điền sẵn
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [dm.ghe2[2].id, dm.ghe1[0].id]})
    html = r.content.decode()
    assert "Người cần điền lại" in html and 'value="0912345678"' in html
    assert "thong_tin_tam" not in client.session                           # chỉ điền lại một lần


def test_a7_trang_ket_qua_don_het_han_chuyen_het_han_ve_huy_hoan_luot(client, dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="GIAM10", so_luot_toi_da=5)
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1
    het_han(don)
    r = client.get(reverse("ket_qua", args=[don.ma_dat_cho]))
    assert r.status_code == 200 and r.context["don"].trang_thai == DonDatCho.TrangThai.HET_HAN
    assert 'id="dem-nguoc"' not in r.content.decode()
    assert don.ds_ve.get().trang_thai == Ve.TrangThai.DA_HUY
    km.refresh_from_db()
    assert km.so_luot_da_dung == 0
    assert GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)[0]["trang_thai"] == "TRONG"


def test_a8_huy_truoc_khi_giu_cho_khong_tao_don(client, dm, chuyen):
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [dm.ghe1[0].id]})
    assert reverse("tim_chuyen") in r.content.decode()                     # nút "Hủy đặt vé"
    client.get(reverse("tim_chuyen"))
    assert DonDatCho.objects.count() == 0 and Ve.objects.count() == 0


def test_thanh_toan_gia_lap_qua_http_chi_chap_nhan_post(client, dm, chuyen, nguoi_dat):
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    url = reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho])
    assert client.get(url).status_code == 405
    r = client.post(url, follow=True)
    assert "Thanh toán (giả lập) thành công" in r.content.decode()
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DA_THANH_TOAN
    # sơ đồ: ghế chuyển sang "đã bán"
    assert GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)[0]["trang_thai"] == "DA_BAN"
    r = client.post(url, follow=True)                                      # thanh toán lại -> báo lỗi, không đổi
    assert "không còn ở trạng thái đang giữ chỗ" in r.content.decode()


def test_thanh_toan_don_het_han_qua_http_bi_tu_choi_va_giai_phong(client, dm, chuyen, nguoi_dat):
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    het_han(don)
    r = client.post(reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho]), follow=True)
    assert "hết thời gian giữ chỗ" in r.content.decode()
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.HET_HAN


def test_so_do_cho_http_hien_ghe_dang_giu_khong_chon_duoc(client, dm, chuyen, nguoi_dat):
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    r = client.get(reverse("chon_cho", args=[chuyen.id]))
    html = r.content.decode()
    assert "seat-dang_giu" in html
    assert f'value="{dm.ghe1[0].id}"' in html
    import re
    o_ghe = re.search(r'<input type="checkbox" name="ghe" value="%d"[^>]*>' % dm.ghe1[0].id, html).group(0)
    assert "disabled" in o_ghe
