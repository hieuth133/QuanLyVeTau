"""UC14 nhánh B: khuyến mãi – form, DAO, lượt sử dụng, kết thúc, trạng thái suy ra từ ngày."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from datve.models import Ve
from datve.services import DatVeService
from giave.dao import KhuyenMaiDAO
from giave.forms import KhuyenMaiForm
from giave.models import KhuyenMai, NhatKyThayDoi
from tien_ich import cho

pytestmark = pytest.mark.django_db

TT = KhuyenMai.TrangThai


def du_lieu(hom_nay, **ghi_de):
    d = {"ma_khuyen_mai": "he2026", "ten": "Khuyến mãi hè", "hinh_thuc_giam": "PHAN_TRAM", "gia_tri_giam": "20",
         "muc_giam_toi_da": "150000", "ngay_bat_dau": hom_nay.isoformat(),
         "ngay_ket_thuc": (hom_nay + timedelta(days=30)).isoformat(), "tuyen_duong": "", "loai_cho": "",
         "doi_tuong_ap_dung": "", "so_ngay_dat_truoc": "0", "so_luot_toi_da": "", "bat_buoc_nhap_ma": "on"}
    d.update(ghi_de)
    return d


@pytest.fixture
def client_ql(client, quan_ly):
    client.force_login(quan_ly)
    return client


# --------------------------------------------------------------------------- Form (E1)
def test_form_hop_le_chuan_hoa_ma(hom_nay):
    form = KhuyenMaiForm(du_lieu(hom_nay, ma_khuyen_mai=" he 2026 "))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["ma_khuyen_mai"] == "HE2026"


def test_form_tu_choi_ma_trung_khong_phan_biet_hoa_thuong(hom_nay, tao_km):
    tao_km(ma_khuyen_mai="HE2026")
    form = KhuyenMaiForm(du_lieu(hom_nay, ma_khuyen_mai="he2026"))
    assert not form.is_valid() and "ma_khuyen_mai" in form.errors


def test_form_sua_khong_bao_trung_voi_chinh_no(hom_nay, tao_km):
    km = tao_km(ma_khuyen_mai="HE2026")
    form = KhuyenMaiForm(du_lieu(hom_nay, ma_khuyen_mai="HE2026"), instance=km)
    assert form.is_valid(), form.errors


@pytest.mark.parametrize("gia_tri", ["100.01", "150", "1000"])
def test_form_tu_choi_phan_tram_lon_hon_100(hom_nay, gia_tri):
    form = KhuyenMaiForm(du_lieu(hom_nay, gia_tri_giam=gia_tri))
    assert not form.is_valid() and "gia_tri_giam" in form.errors


def test_form_chap_nhan_phan_tram_100(hom_nay):
    assert KhuyenMaiForm(du_lieu(hom_nay, gia_tri_giam="100")).is_valid()


def test_form_so_tien_khong_gioi_han_100(hom_nay):
    assert KhuyenMaiForm(du_lieu(hom_nay, hinh_thuc_giam="SO_TIEN", gia_tri_giam="80000")).is_valid()


@pytest.mark.parametrize("gia_tri", ["0", "-5"])
def test_form_tu_choi_gia_tri_giam_khong_duong(hom_nay, gia_tri):
    form = KhuyenMaiForm(du_lieu(hom_nay, gia_tri_giam=gia_tri))
    assert not form.is_valid() and "gia_tri_giam" in form.errors


def test_form_tu_choi_ngay_ket_thuc_truoc_ngay_bat_dau(hom_nay):
    form = KhuyenMaiForm(du_lieu(hom_nay, ngay_ket_thuc=(hom_nay - timedelta(days=2)).isoformat()))
    assert not form.is_valid() and "ngay_ket_thuc" in form.errors


def test_form_tu_choi_doi_tuong_ngoai_danh_sach(hom_nay):
    form = KhuyenMaiForm(du_lieu(hom_nay, doi_tuong_ap_dung="SIEU_NHAN"))
    assert not form.is_valid() and "doi_tuong_ap_dung" in form.errors


def test_form_tu_choi_luot_toi_da_nho_hon_da_dung(hom_nay, tao_km):
    km = tao_km(ma_khuyen_mai="HE2026", so_luot_toi_da=10, so_luot_da_dung=6)
    form = KhuyenMaiForm(du_lieu(hom_nay, so_luot_toi_da="5"), instance=km)
    assert not form.is_valid() and "so_luot_toi_da" in form.errors


def test_form_thieu_truong_bat_buoc(hom_nay):
    form = KhuyenMaiForm({})
    assert not form.is_valid()
    for truong in ("ma_khuyen_mai", "ten", "hinh_thuc_giam", "gia_tri_giam", "ngay_bat_dau", "ngay_ket_thuc"):
        assert truong in form.errors


# --------------------------------------------------------------------------- DAO
def test_ton_tai_ma(tao_km):
    km = tao_km(ma_khuyen_mai="ABC")
    assert KhuyenMaiDAO.ton_tai_ma("abc") is True
    assert KhuyenMaiDAO.ton_tai_ma("ABC", bo_qua_id=km.id) is False
    assert KhuyenMaiDAO.ton_tai_ma("XYZ") is False


def test_tang_luot_dung_tra_false_khi_vuot_toi_da(tao_km):
    km = tao_km(so_luot_toi_da=3, so_luot_da_dung=0)
    assert KhuyenMaiDAO.tang_luot_dung(km.id, 2) is True
    assert KhuyenMaiDAO.tang_luot_dung(km.id, 1) is True          # đúng bằng mức tối đa
    assert KhuyenMaiDAO.tang_luot_dung(km.id, 1) is False         # vượt
    km.refresh_from_db()
    assert km.so_luot_da_dung == 3


def test_tang_luot_dung_khong_vuot_khi_xin_nhieu_hon_con_lai(tao_km):
    km = tao_km(so_luot_toi_da=3, so_luot_da_dung=2)
    assert KhuyenMaiDAO.tang_luot_dung(km.id, 2) is False
    km.refresh_from_db()
    assert km.so_luot_da_dung == 2


def test_tang_luot_dung_khong_gioi_han(tao_km):
    km = tao_km(so_luot_toi_da=None)
    assert KhuyenMaiDAO.tang_luot_dung(km.id, 50) is True
    km.refresh_from_db()
    assert km.so_luot_da_dung == 50


def test_hoan_luot_dung_khong_xuong_duoi_khong(tao_km):
    km = tao_km(so_luot_toi_da=5, so_luot_da_dung=2)
    KhuyenMaiDAO.hoan_luot_dung(km.id, 1)
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1
    KhuyenMaiDAO.hoan_luot_dung(km.id, 10)
    km.refresh_from_db()
    assert km.so_luot_da_dung == 0


def test_ket_thuc_khuyen_mai(tao_km, hom_nay):
    km = tao_km(ngay_bat_dau=hom_nay - timedelta(days=5), ngay_ket_thuc=hom_nay + timedelta(days=20))
    assert KhuyenMaiDAO.ket_thuc(km.id, hom_nay) is True
    km.refresh_from_db()
    assert km.trang_thai == TT.DA_KET_THUC and km.ngay_ket_thuc == hom_nay
    assert KhuyenMaiDAO.ket_thuc(km.id, hom_nay) is False       # đã kết thúc rồi


def test_ket_thuc_khuyen_mai_chua_bat_dau_khong_vi_pham_rang_buoc(tao_km, hom_nay):
    bd = hom_nay + timedelta(days=10)
    km = tao_km(ngay_bat_dau=bd, ngay_ket_thuc=bd + timedelta(days=10))
    assert KhuyenMaiDAO.ket_thuc(km.id, hom_nay) is True
    km.refresh_from_db()
    assert km.ngay_ket_thuc == bd


def test_loc_khuyen_mai_theo_trang_thai_suy_ra_tu_ngay(tao_km, hom_nay):
    sap = tao_km(ngay_bat_dau=hom_nay + timedelta(days=3), ngay_ket_thuc=hom_nay + timedelta(days=9))
    dang = tao_km(ngay_bat_dau=hom_nay - timedelta(days=3), ngay_ket_thuc=hom_nay + timedelta(days=9))
    het_ngay = tao_km(ngay_bat_dau=hom_nay - timedelta(days=9), ngay_ket_thuc=hom_nay - timedelta(days=1))
    chu_dong = tao_km(ngay_bat_dau=hom_nay - timedelta(days=9), ngay_ket_thuc=hom_nay + timedelta(days=9),
                      trang_thai=TT.DA_KET_THUC)
    ids = lambda ds: {k.id for k in ds}  # noqa: E731
    assert ids(KhuyenMaiDAO.tim_khuyen_mai(TT.SAP_AP_DUNG)) == {sap.id}
    assert ids(KhuyenMaiDAO.tim_khuyen_mai(TT.DANG_AP_DUNG)) == {dang.id}
    assert ids(KhuyenMaiDAO.tim_khuyen_mai(TT.DA_KET_THUC)) == {het_ngay.id, chu_dong.id}
    assert ids(KhuyenMaiDAO.tim_khuyen_mai(None)) == {sap.id, dang.id, het_ngay.id, chu_dong.id}
    assert sap.trang_thai_hien_thi() == TT.SAP_AP_DUNG and dang.trang_thai_hien_thi() == TT.DANG_AP_DUNG
    assert chu_dong.trang_thai_hien_thi() == TT.DA_KET_THUC


def test_tim_khuyen_mai_hieu_luc_loc_phan_pham_vi_va_ma(dm, tao_km, hom_nay):
    chung = tao_km()
    rieng_tuyen2 = tao_km(tuyen_duong=dm.tuyen2)
    rieng_k4 = tao_km(loai_cho=dm.k4)
    chi_ma = tao_km(bat_buoc_nhap_ma=True)
    da_ket_thuc = tao_km(trang_thai=TT.DA_KET_THUC)
    ket_qua = KhuyenMaiDAO.tim_khuyen_mai_hieu_luc(dm.tuyen.id, dm.nm.id, hom_nay)
    assert {k.id for k in ket_qua} == {chung.id}
    assert rieng_tuyen2.id not in {k.id for k in ket_qua} and chi_ma.id not in {k.id for k in ket_qua}
    assert da_ket_thuc.id not in {k.id for k in ket_qua} and rieng_k4.id not in {k.id for k in ket_qua}


# --------------------------------------------------------------------------- QT05: kết thúc không đổi giá vé đã giữ
def test_ket_thuc_khuyen_mai_khong_doi_gia_ve_da_giu(dm, chuyen, nguoi_dat, tao_km, hom_nay):
    km = tao_km(ma_khuyen_mai="GIAM10", gia_tri_giam=Decimal(10))
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    ve = Ve.objects.get(don_dat_cho=don)
    assert ve.khuyen_mai == km and ve.so_tien_giam == 45_000 and ve.gia_ve == 405_000
    KhuyenMaiDAO.ket_thuc(km.id, hom_nay)
    ve.refresh_from_db()
    assert ve.so_tien_giam == 45_000 and ve.gia_ve == 405_000 and ve.khuyen_mai_id == km.id
    # đơn mới không còn được giảm
    don2 = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[1], so_giay_to="987654321")],
                                {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    assert don2.tong_tien == 450_000


# --------------------------------------------------------------------------- View
def test_view_them_khuyen_mai_thanh_cong_ghi_nhat_ky(client_ql, hom_nay, quan_ly):
    r = client_ql.post(reverse("khuyen_mai_them"), du_lieu(hom_nay), follow=True)
    assert "Lưu thành công" in r.content.decode()
    km = KhuyenMai.objects.get()
    assert km.ma_khuyen_mai == "HE2026" and km.bat_buoc_nhap_ma is True and km.muc_giam_toi_da == 150_000
    nk = NhatKyThayDoi.objects.get()
    assert nk.hanh_dong == "THEM" and nk.loai_doi_tuong == "KhuyenMai" and nk.nguoi_thuc_hien == quan_ly


def test_view_e1_giu_du_lieu_va_gan_loi_dung_truong(client_ql, hom_nay):
    r = client_ql.post(reverse("khuyen_mai_them"), du_lieu(hom_nay, gia_tri_giam="150", ten="Tên cần giữ lại"))
    assert r.status_code == 200
    assert "gia_tri_giam" in r.context["form"].errors
    html = r.content.decode()
    assert "Tên cần giữ lại" in html and 'value="150"' in html
    assert KhuyenMai.objects.count() == 0


def test_view_sua_khuyen_mai_ghi_cu_moi(client_ql, tao_km, hom_nay):
    km = tao_km(ma_khuyen_mai="HE2026", gia_tri_giam=Decimal(10))
    r = client_ql.post(reverse("khuyen_mai_sua", args=[km.id]), du_lieu(hom_nay, gia_tri_giam="25"))
    assert r.status_code == 302
    km.refresh_from_db()
    assert km.gia_tri_giam == 25
    nk = NhatKyThayDoi.objects.get()
    assert nk.hanh_dong == "SUA" and nk.gia_tri_cu["gia_tri_giam"] == "10.00" and nk.gia_tri_moi["gia_tri_giam"] == "25"


def test_view_ket_thuc_co_trang_xac_nhan(client_ql, tao_km, hom_nay):
    km = tao_km()
    r = client_ql.get(reverse("khuyen_mai_ket_thuc", args=[km.id]))
    assert r.status_code == 200 and "Xác nhận kết thúc" in r.content.decode()
    km.refresh_from_db()
    assert km.trang_thai != TT.DA_KET_THUC
    assert client_ql.post(reverse("khuyen_mai_ket_thuc", args=[km.id])).status_code == 302
    km.refresh_from_db()
    assert km.trang_thai == TT.DA_KET_THUC
    assert NhatKyThayDoi.objects.get().hanh_dong == "KET_THUC"


def test_view_khong_sua_hoac_ket_thuc_lai_khuyen_mai_da_ket_thuc(client_ql, tao_km):
    km = tao_km(trang_thai=TT.DA_KET_THUC)
    for ten in ("khuyen_mai_sua", "khuyen_mai_ket_thuc"):
        r = client_ql.get(reverse(ten, args=[km.id]), follow=True)
        assert r.redirect_chain and "đã kết thúc" in r.content.decode()
    assert client_ql.post(reverse("khuyen_mai_ket_thuc", args=[km.id])).status_code == 302
    assert NhatKyThayDoi.objects.count() == 0


def test_the_khuyen_mai_loc_theo_trang_thai(client_ql, tao_km, hom_nay):
    sap = tao_km(ma_khuyen_mai="SAP", ngay_bat_dau=hom_nay + timedelta(days=3), ngay_ket_thuc=hom_nay + timedelta(days=9))
    dang = tao_km(ma_khuyen_mai="DANG")
    xong = tao_km(ma_khuyen_mai="XONG", ngay_bat_dau=hom_nay - timedelta(days=9), ngay_ket_thuc=hom_nay - timedelta(days=1))
    for trang_thai, mong_doi in (("SAP_AP_DUNG", sap), ("DANG_AP_DUNG", dang), ("DA_KET_THUC", xong)):
        r = client_ql.get(reverse("quan_ly_gia_ve"), {"the": "khuyen-mai", "trang_thai": trang_thai})
        assert [k.id for k in r.context["ds_khuyen_mai"]] == [mong_doi.id]


def test_nhan_vien_khong_ket_thuc_duoc_khuyen_mai(client, nhan_vien, tao_km):
    km = tao_km()
    client.force_login(nhan_vien)
    assert client.post(reverse("khuyen_mai_ket_thuc", args=[km.id])).status_code == 403
    km.refresh_from_db()
    assert km.trang_thai != TT.DA_KET_THUC
