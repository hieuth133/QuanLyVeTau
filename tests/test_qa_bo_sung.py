"""Kiểm thử bổ sung của QA độc lập: các ca biên chưa được phủ bởi bộ test gốc.

Các ca từng là `xfail(strict=True)` (bằng chứng lỗi) đã được sửa mã và chạy như test thường."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from danhmuc.dao import ChuyenTauDAO, GheNgoiDAO
from danhmuc.models import ChuyenTau, GaTau, GheNgoi, LichTrinh, Tau, ToaXe, TuyenDuong
from datve.dao import DonDatChoDAO
from datve.exceptions import (ChoDaBiGiu, ChuyenKhongMoBan, DonKhongThanhToanDuoc, KhongCoGia, KhuyenMaiHetLuot,
                              MaKhuyenMaiKhongHopLe)
from datve.models import DonDatCho, Ve
from datve.services import DatVeService, TinhGiaService
from datve.tasks import GiaiPhongChoTask
from giave.dao import KhuyenMaiDAO, QuyTacGiaDAO
from giave.forms import KhuyenMaiForm
from giave.models import KhuyenMai, NhatKyThayDoi, QuyTacGia
from tien_ich import cho, thoi_diem_khoi_hanh_sau

pytestmark = pytest.mark.django_db

LT = QuyTacGia.LoaiThoiDiem
TTQ = QuyTacGia.TrangThai


# --------------------------------------------------------------------------- tiện ích
def het_han(don, phut=5):
    DonDatCho.objects.filter(pk=don.pk).update(thoi_diem_het_han=timezone.now() - timedelta(minutes=phut))


def du_lieu_giu_cho(ghe_list, nguoi_dat, ma="", **ghi_de):
    d = {"hk-TOTAL_FORMS": len(ghe_list), "hk-INITIAL_FORMS": len(ghe_list), "hk-MIN_NUM_FORMS": 0,
         "hk-MAX_NUM_FORMS": 1000, "ho_ten": nguoi_dat["ho_ten"], "so_dien_thoai": nguoi_dat["so_dien_thoai"],
         "email": nguoi_dat["email"], "ma_khuyen_mai": ma}
    for i, g in enumerate(ghe_list):
        gid = g.id if hasattr(g, "id") else g
        d.update({f"hk-{i}-ghe_id": gid, f"hk-{i}-ho_ten": f"Hành khách {i + 1}", f"hk-{i}-doi_tuong": "NGUOI_LON",
                  f"hk-{i}-so_giay_to": f"01234567{i}"})
    d.update(ghi_de)
    return d


def du_lieu_qt(dm, hom_nay, **ghi_de):
    d = {"tuyen_duong": dm.tuyen.id, "loai_cho": dm.nm.id, "gia_co_so": "500000", "loai_thoi_diem": "CUOI_TUAN",
         "ngay_bat_dau": (hom_nay + timedelta(days=1)).isoformat(), "ngay_ket_thuc": "", "ghi_chu": "thử"}
    d.update(ghi_de)
    return d


def du_lieu_km(hom_nay, **ghi_de):
    d = {"ma_khuyen_mai": "qa2026", "ten": "KM QA", "hinh_thuc_giam": "PHAN_TRAM", "gia_tri_giam": "20",
         "muc_giam_toi_da": "", "ngay_bat_dau": hom_nay.isoformat(),
         "ngay_ket_thuc": (hom_nay + timedelta(days=30)).isoformat(), "tuyen_duong": "", "loai_cho": "",
         "doi_tuong_ap_dung": "", "so_ngay_dat_truoc": "0", "so_luot_toi_da": "", "bat_buoc_nhap_ma": "on"}
    d.update(ghi_de)
    return d


@pytest.fixture
def client_ql(client, quan_ly):
    client.force_login(quan_ly)
    return client


@pytest.fixture
def tau_khac(dm):
    """Một tàu khác (cùng loại chỗ) – ghế của nó không được bán cho chuyến của tàu T01."""
    tau = Tau.objects.create(ma_tau="T02", ten_tau="Tàu 02")
    toa = ToaXe.objects.create(tau=tau, so_toa=1, loai_cho=dm.nm)
    return GheNgoi.objects.create(toa_xe=toa, so_ghe="1")


def sv80k(tao_km, **kw):
    du = dict(ma_khuyen_mai="SV80K", hinh_thuc_giam="SO_TIEN", gia_tri_giam=Decimal(80_000),
              doi_tuong_ap_dung="SINH_VIEN", bat_buoc_nhap_ma=True, so_luot_toi_da=100)
    du.update(kw)
    return tao_km(**du)


# =========================================================================== 1. Ranh giới khoảng giá
def test_khoang_gia_ngay_bat_dau_va_ket_thuc_dung_bang_ngay_di(dm, tao_quy_tac, tao_chuyen, hom_nay):
    ngay = hom_nay + timedelta(days=20)
    tao_quy_tac(dm.nm, LT.LE_TET, 999_000, bat_dau=ngay, ket_thuc=ngay)          # hiệu lực đúng 1 ngày
    tid, lid = dm.tuyen.id, dm.nm.id
    assert QuyTacGiaDAO.tim_gia_ap_dung(tid, lid, ngay).gia_co_so == 999_000
    assert QuyTacGiaDAO.tim_gia_ap_dung(tid, lid, ngay - timedelta(days=1)) is None
    assert QuyTacGiaDAO.tim_gia_ap_dung(tid, lid, ngay + timedelta(days=1)) is None
    c = tao_chuyen(ngay)
    assert TinhGiaService.tinh_gia_ve(c, dm.ghe1[0], "NGUOI_LON", None).gia_ve == 999_000
    c2 = tao_chuyen(ngay + timedelta(days=1))
    with pytest.raises(KhongCoGia):
        TinhGiaService.tinh_gia_ve(c2, dm.ghe1[0], "NGUOI_LON", None)


def test_hai_khoang_gia_chung_dung_mot_ngay_la_trung(dm, tao_quy_tac):
    d = date(2031, 3, 10)
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, bat_dau=d, ket_thuc=d + timedelta(days=10))

    def moi(bd, kt):
        return QuyTacGia(tuyen_duong=dm.tuyen, loai_cho=dm.nm, loai_thoi_diem=LT.CUOI_TUAN, gia_co_so=1,
                         ngay_bat_dau=bd, ngay_ket_thuc=kt)

    assert QuyTacGiaDAO.tim_quy_tac_trung(moi(d + timedelta(days=10), d + timedelta(days=12)))   # chạm ngày cuối
    assert QuyTacGiaDAO.tim_quy_tac_trung(moi(d - timedelta(days=3), d))                          # chạm ngày đầu
    assert not QuyTacGiaDAO.tim_quy_tac_trung(moi(d + timedelta(days=11), None))
    assert not QuyTacGiaDAO.tim_quy_tac_trung(moi(d - timedelta(days=3), d - timedelta(days=1)))


def test_exclude_chan_khoang_chung_dung_mot_ngay_va_cho_phep_lien_ke(dm, tao_quy_tac):
    d = date(2031, 3, 10)
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, bat_dau=d, ket_thuc=d + timedelta(days=10))
    with pytest.raises(IntegrityError), transaction.atomic():
        tao_quy_tac(dm.nm, LT.CUOI_TUAN, 1, bat_dau=d + timedelta(days=10), ket_thuc=None)
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 1, bat_dau=d + timedelta(days=11), ket_thuc=None)


def test_http_them_quy_tac_bat_dau_dung_bang_ngay_ket_thuc_quy_tac_khac_bao_e2(client_ql, dm, tao_quy_tac, hom_nay):
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, bat_dau=hom_nay + timedelta(days=1), ket_thuc=hom_nay + timedelta(days=9))
    r = client_ql.post(reverse("quy_tac_them"), du_lieu_qt(dm, hom_nay, ngay_bat_dau=(hom_nay + timedelta(days=9)).isoformat()))
    assert r.status_code == 200 and len(r.context["trung"]) == 1
    r = client_ql.post(reverse("quy_tac_them"), du_lieu_qt(dm, hom_nay, ngay_bat_dau=(hom_nay + timedelta(days=10)).isoformat()))
    assert r.status_code == 302


def test_khuyen_mai_bien_ngay_hieu_luc_bao_gom_ca_hai_dau(dm, chuyen, nguoi_dat, tao_km, hom_nay):
    km = tao_km(ma_khuyen_mai="HOMNAY", bat_buoc_nhap_ma=True, ngay_bat_dau=hom_nay, ngay_ket_thuc=hom_nay)
    ve = TinhGiaService.tinh_gia_ve(chuyen, dm.ghe1[0], "NGUOI_LON", "homnay")
    assert ve.khuyen_mai == km and ve.so_tien_giam == 45_000
    # Ngày mai: chương trình đã kết thúc; hôm qua: chưa tới ngày
    with pytest.raises(MaKhuyenMaiKhongHopLe):
        TinhGiaService.tinh_gia_ve(chuyen, dm.ghe1[0], "NGUOI_LON", "HOMNAY", hom_nay=hom_nay + timedelta(days=1))
    with pytest.raises(MaKhuyenMaiKhongHopLe):
        TinhGiaService.tinh_gia_ve(chuyen, dm.ghe1[0], "NGUOI_LON", "HOMNAY", hom_nay=hom_nay - timedelta(days=1))


def test_so_ngay_dat_truoc_dung_bang_nguong_van_duoc_ap_dung(dm, tao_km, tao_chuyen, gia_day_du, hom_nay):
    tao_km(ma_khuyen_mai="SOM7", so_ngay_dat_truoc=7)
    c7, c6 = tao_chuyen(hom_nay + timedelta(days=7)), tao_chuyen(hom_nay + timedelta(days=6))
    assert TinhGiaService.tinh_gia_ve(c7, dm.ghe1[0], "NGUOI_LON", None).so_tien_giam == 45_000
    assert TinhGiaService.tinh_gia_ve(c6, dm.ghe1[0], "NGUOI_LON", None).so_tien_giam == 0


# =========================================================================== 2. Khuyến mãi lớn hơn giá vé
def test_km_so_tien_lon_hon_gia_ve_cho_gia_0_khong_am(dm, chuyen, nguoi_dat, tao_km):
    tao_km(ma_khuyen_mai="TOLON", hinh_thuc_giam="SO_TIEN", gia_tri_giam=Decimal(5_000_000), bat_buoc_nhap_ma=False)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    ve = don.ds_ve.get()
    assert (ve.gia_co_so, ve.so_tien_giam, ve.gia_ve) == (450_000, 450_000, 0)
    assert don.tong_tien == 0


def test_km_100_phan_tram_cho_gia_0_va_hien_thi_dung_o_trang_ket_qua(client, dm, chuyen, nguoi_dat, tao_km):
    tao_km(ma_khuyen_mai="FREE", gia_tri_giam=Decimal(100), bat_buoc_nhap_ma=False)
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    assert r.status_code == 302
    r = client.get(r["Location"])
    assert r.status_code == 200 and "0 đ" in r.content.decode()
    assert DonDatCho.objects.get().tong_tien == 0


def test_km_so_tien_lam_tron_xuong_nghin_voi_gia_le(dm, chuyen, tao_km):
    tao_km(ma_khuyen_mai="LE", hinh_thuc_giam="SO_TIEN", gia_tri_giam=Decimal("79999.99"), bat_buoc_nhap_ma=False)
    ve = TinhGiaService.tinh_gia_ve(chuyen, dm.ghe1[0], "NGUOI_LON", None)
    assert ve.so_tien_giam == 79_000 and ve.gia_ve == 371_000


# =========================================================================== 3. Khuyến mãi hết lượt giữa chừng
def test_km_ma_het_luot_giua_chung_http_khong_tao_don_va_cho_di_tiep_khong_dung_ma(client, dm, chuyen, nguoi_dat, tao_km,
                                                                                    monkeypatch):
    km = sv80k(tao_km, so_luot_toi_da=3, so_luot_da_dung=2)
    # lượt cuối bị người khác lấy mất đúng lúc ghi (tranh chấp đồng thời)
    monkeypatch.setattr(KhuyenMaiDAO, "tang_luot_dung", staticmethod(lambda id, so_luot: False))
    ghe = dm.ghe1[:2]
    d = du_lieu_giu_cho(ghe, nguoi_dat, ma="sv80k", **{"hk-0-doi_tuong": "SINH_VIEN", "hk-1-doi_tuong": "SINH_VIEN"})
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 200 and "ma_khuyen_mai" in r.context["form"].errors
    assert DonDatCho.objects.count() == 0 and Ve.objects.count() == 0
    km.refresh_from_db()
    assert km.so_luot_da_dung == 2
    d["bo_ma"] = "1"                                                     # nút "Tiếp tục không dùng mã"
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 302 and DonDatCho.objects.get().tong_tien == 900_000


def test_km_tu_dong_con_1_luot_don_2_ve_van_dat_duoc(client, dm, chuyen, nguoi_dat, tao_km):
    tao_km(ma_khuyen_mai="AUTO1", so_luot_toi_da=1, so_luot_da_dung=0, bat_buoc_nhap_ma=False)
    d = du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat)
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    if r.status_code != 302:                                             # thử đường thoát duy nhất mà giao diện cho
        d["bo_ma"] = "1"
        r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 302 and DonDatCho.objects.count() == 1


def test_km_het_luot_service_giam_du_so_luot_con_lai_va_tranh_chap_hoan_tac(dm, chuyen, nguoi_dat, tao_km, monkeypatch):
    km = tao_km(ma_khuyen_mai="AUTO1", so_luot_toi_da=1, so_luot_da_dung=0, bat_buoc_nhap_ma=False)
    # tranh chấp đồng thời (tang_luot_dung thất bại) -> KhuyenMaiHetLuot, hoàn tác toàn bộ
    with monkeypatch.context() as m:
        m.setattr(KhuyenMaiDAO, "tang_luot_dung", staticmethod(lambda id, so_luot: False))
        with pytest.raises(KhuyenMaiHetLuot):
            DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, None)
    km.refresh_from_db()
    assert km.so_luot_da_dung == 0 and DonDatCho.objects.count() == 0 and Ve.objects.count() == 0
    # không tranh chấp: 2 vé, 1 lượt -> đúng 1 vé được giảm
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, None)
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1 and sorted(v.so_tien_giam for v in don.ds_ve.all()) == [0, 45_000]
    # hết lượt thật: vé tiếp theo không còn được giảm và đặt bình thường
    don2 = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[2], so_giay_to="987654322")], nguoi_dat, None)
    assert don2.tong_tien == 450_000


# =========================================================================== 4. Mã khuyến mãi: chữ thường, khoảng trắng
@pytest.mark.parametrize("ma", ["sv80k", "  SV80K  ", " sv80k\t", "Sv80K"])
def test_ma_km_service_chuan_hoa_chu_thuong_va_khoang_trang(dm, chuyen, nguoi_dat, tao_km, ma):
    km = sv80k(tao_km)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0], doi_tuong="SINH_VIEN")], nguoi_dat, ma)
    assert don.tong_tien == 370_000
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1


@pytest.mark.parametrize("ma", ["sv80k", " sv 80k ", "SV80K "])
def test_ma_km_http_chuan_hoa(client, dm, chuyen, nguoi_dat, tao_km, ma):
    sv80k(tao_km)
    d = du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat, ma=ma, **{"hk-0-doi_tuong": "SINH_VIEN"})
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 302, r.content.decode()[:300]
    assert DonDatCho.objects.get().tong_tien == 370_000


def test_ma_km_chi_khoang_trang_coi_nhu_khong_nhap(dm, chuyen, nguoi_dat, tao_km):
    sv80k(tao_km)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, "   ")
    assert don.tong_tien == 450_000


def test_ma_km_hop_le_nhung_sai_doi_tuong_khong_loi_va_khong_tang_luot(dm, chuyen, nguoi_dat, tao_km):
    km = sv80k(tao_km)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, "SV80K")          # người lớn
    km.refresh_from_db()
    assert don.tong_tien == 450_000 and km.so_luot_da_dung == 0


@pytest.mark.parametrize("bd,kt", [(-10, -1), (1, 10)])        # đã kết thúc hôm qua / bắt đầu từ ngày mai
def test_ma_km_da_ket_thuc_hoac_chua_toi_ngay_bao_loi_http(client, dm, chuyen, nguoi_dat, tao_km, hom_nay, bd, kt):
    sv80k(tao_km, ngay_bat_dau=hom_nay + timedelta(days=bd), ngay_ket_thuc=hom_nay + timedelta(days=kt))
    d = du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat, ma="SV80K", **{"hk-0-doi_tuong": "SINH_VIEN"})
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 200 and "ma_khuyen_mai" in r.context["form"].errors
    assert DonDatCho.objects.count() == 0
    assert "Tiếp tục không dùng mã" in r.content.decode()


def test_ma_km_do_quan_ly_ket_thuc_chu_dong_bao_loi_ngay_ca_khi_con_han(dm, chuyen, nguoi_dat, tao_km):
    km = sv80k(tao_km)
    KhuyenMaiDAO.ket_thuc(km.id, timezone.localdate())
    with pytest.raises(MaKhuyenMaiKhongHopLe):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0], doi_tuong="SINH_VIEN")], nguoi_dat, "SV80K")


# =========================================================================== 5. Ghế bất thường
def test_ghe_cua_tau_khac_http_post_khong_500_va_khong_tao_don(client, dm, chuyen, nguoi_dat, tau_khac):
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho([tau_khac], nguoi_dat))
    assert r.status_code in (200, 302)
    assert DonDatCho.objects.count() == 0 and Ve.objects.count() == 0
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [tau_khac.id]})
    assert r.status_code == 302


def test_ghe_cua_tau_khac_lan_voi_ghe_hop_le_service_tu_choi_ca_don(dm, chuyen, nguoi_dat, tau_khac):
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(tau_khac, so_giay_to="987654321")], nguoi_dat, None)
    assert Ve.objects.count() == 0 and not GheNgoi.objects.get(pk=dm.ghe1[0].pk).ve_set.exists()


def test_ghe_trung_trong_mot_yeu_cau_http_va_service(client, dm, chuyen, nguoi_dat):
    d = du_lieu_giu_cho([dm.ghe1[0], dm.ghe1[0]], nguoi_dat)
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 200 and DonDatCho.objects.count() == 0
    with pytest.raises(ValueError):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[0], so_giay_to="987654321")], nguoi_dat, None)
    assert Ve.objects.count() == 0
    # GET: tham số ghe trùng được gộp lại thành một
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [dm.ghe1[0].id, dm.ghe1[0].id]})
    assert r.status_code == 200 and len(r.context["formset"].forms) == 1


@pytest.mark.parametrize("n,ok", [(0, False), (1, True), (6, True), (7, False)])
def test_so_ghe_0_va_7_service(dm, chuyen, nguoi_dat, n, ok):
    ghe = (dm.ghe1 + dm.ghe2)[:n]
    ds = [cho(g, so_giay_to=f"98765432{i}") for i, g in enumerate(ghe)]
    if ok:
        assert DatVeService.giu_cho(chuyen.id, ds, nguoi_dat, None).ds_ve.count() == n
    else:
        with pytest.raises(ValueError):
            DatVeService.giu_cho(chuyen.id, ds, nguoi_dat, None)
        assert DonDatCho.objects.count() == 0


@pytest.mark.parametrize("n,ma_http", [(0, 200), (7, 200), (6, 302)])
def test_so_ghe_0_va_7_http(client, dm, chuyen, nguoi_dat, n, ma_http):
    ghe = (dm.ghe1 + dm.ghe2)[:n]
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(ghe, nguoi_dat))
    assert r.status_code == ma_http
    assert DonDatCho.objects.count() == (1 if ma_http == 302 else 0)
    if ma_http == 200:
        assert "từ 1 đến" in r.content.decode()


def test_get_thong_tin_0_ghe_va_7_ghe_chuyen_huong(client, dm, chuyen):
    assert client.get(reverse("thong_tin", args=[chuyen.id])).status_code == 302
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [g.id for g in (dm.ghe1 + dm.ghe2)[:7]]})
    assert r.status_code == 302
    r = client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [g.id for g in (dm.ghe1 + dm.ghe2)[:6]]})
    assert r.status_code == 200


@pytest.mark.parametrize("tham_so", [
    {"ghe": ["abc"]}, {"ghe": ["1.5"]}, {"ghe": [""]}, {"ghe": ["-1"]}, {"ghe": ["0"]},
    {"ghe": ["99999999999"]}, {"ghe": ["9" * 30]}, {"ghe": ["1e3"]}, {"ghe": ["١٢"]}, {"ghe": ["%00"]},
    {"ghe": ["abc", "999999", "xyz"]}, {"ghe": ["\u0000"]},
])
def test_get_thong_tin_tham_so_ghe_rac_khong_500(client, chuyen, tham_so):
    r = client.get(reverse("thong_tin", args=[chuyen.id]), tham_so)
    assert r.status_code in (200, 302)


@pytest.mark.parametrize("ghe_id", ["abc", "", "-5", "0", "99999999999", "9" * 30, "1.5"])
def test_post_giu_cho_ghe_id_rac_khong_500_va_khong_tao_don(client, chuyen, nguoi_dat, ghe_id):
    d = du_lieu_giu_cho([1], nguoi_dat)
    d["hk-0-ghe_id"] = ghe_id
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code in (200, 302)
    assert DonDatCho.objects.count() == 0


@pytest.mark.parametrize("sua", [
    {"hk-TOTAL_FORMS": "abc"}, {"hk-TOTAL_FORMS": "-1"}, {"hk-TOTAL_FORMS": "99999999999999"},
    {"hk-TOTAL_FORMS": "5000"}, {"hk-INITIAL_FORMS": "xyz"}, {"hk-MAX_NUM_FORMS": "-3"},
])
def test_post_giu_cho_management_form_hong_khong_500(client, dm, chuyen, nguoi_dat, sua):
    d = du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat)
    d.update(sua)
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code in (200, 302)


def test_post_giu_cho_thieu_management_form_khong_500(client, dm, chuyen, nguoi_dat):
    r = client.post(reverse("giu_cho", args=[chuyen.id]),
                    {"ho_ten": "A B", "so_dien_thoai": "0912345678", "email": "", "ma_khuyen_mai": ""})
    assert r.status_code in (200, 302) and DonDatCho.objects.count() == 0


@pytest.mark.parametrize("truong,gia_tri", [
    ("ho_ten", "x" * 101), ("so_dien_thoai", "9" * 300), ("email", "khong-phai-email"), ("email", "a" * 300 + "@x.vn"),
    ("ma_khuyen_mai", "A" * 500), ("ho_ten", "\u0000"), ("ho_ten", "   "),
])
def test_post_giu_cho_truong_nguoi_dat_rac_khong_500(client, dm, chuyen, nguoi_dat, truong, gia_tri):
    d = du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat)
    d[truong] = gia_tri
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code in (200, 302)
    if r.status_code == 200:
        assert DonDatCho.objects.count() == 0


@pytest.mark.parametrize("truong,gia_tri", [
    ("doi_tuong", "QUAI_VAT"), ("doi_tuong", ""), ("so_giay_to", "ab cd ef"), ("so_giay_to", "\u0000" * 8),
    ("so_giay_to", "Đ" * 8), ("ho_ten", "y" * 500),
])
def test_post_giu_cho_truong_hanh_khach_rac_khong_500(client, dm, chuyen, nguoi_dat, truong, gia_tri):
    d = du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat)
    d[f"hk-0-{truong}"] = gia_tri
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code in (200, 302)
    if r.status_code == 200:
        assert DonDatCho.objects.count() == 0


def test_post_giu_cho_ghe_da_ban_http_la_a6_khong_500(client, dm, chuyen, nguoi_dat):
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:2], nguoi_dat))
    assert r.status_code == 302 and DonDatCho.objects.count() == 1       # không tạo thêm đơn nào (hoàn tác cả đơn)


# =========================================================================== 6. Ngừng bán trước giờ tàu chạy
@pytest.fixture
def chuyen_sap_chay(dm, tao_chuyen, gia_day_du):
    """Fabrique tạo chuyến khởi hành sau `phut` phút (cùng tàu, lịch trình riêng để không trùng chuyến)."""
    def _tao(phut: int) -> ChuyenTau:
        ngay, gio = thoi_diem_khoi_hanh_sau(phut)
        lich = LichTrinh.objects.create(tuyen_duong=dm.tuyen, tau=dm.tau, gio_khoi_hanh=gio, thoi_gian_chay=600)
        return ChuyenTau.objects.create(lich_trinh=lich, ngay_khoi_hanh=ngay)
    return _tao


def test_chuyen_trong_vong_ngung_ban_khong_hien_o_tim_kiem_nhung_ben_ngoai_thi_hien(client, dm, chuyen_sap_chay):
    gan = chuyen_sap_chay(settings.NGUNG_BAN_TRUOC_PHUT - 10)
    xa = chuyen_sap_chay(settings.NGUNG_BAN_TRUOC_PHUT + 10)
    tim = ChuyenTauDAO.tim_chuyen_tau(dm.ga_a.id, dm.ga_b.id, gan.ngay_khoi_hanh)
    ids = {c.id for c in tim}
    assert xa.id in ids and gan.id not in ids
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id,
                                           "ngay_di": xa.ngay_khoi_hanh.isoformat(), "so_hanh_khach": 1})
    assert r.status_code == 200 and xa.id in {c.id for c in r.context["ds_chuyen"]}
    assert gan.id not in {c.id for c in r.context["ds_chuyen"]}


def test_chuyen_trong_vong_ngung_ban_khong_giu_cho_duoc_ca_service_lan_http(client, dm, chuyen_sap_chay, nguoi_dat):
    gan = chuyen_sap_chay(settings.NGUNG_BAN_TRUOC_PHUT - 10)
    with pytest.raises(ChuyenKhongMoBan):
        DatVeService.giu_cho(gan.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    r = client.post(reverse("giu_cho", args=[gan.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    assert r.status_code == 302 and DonDatCho.objects.count() == 0
    assert client.get(reverse("chon_cho", args=[gan.id])).status_code == 302
    assert client.get(reverse("thong_tin", args=[gan.id]), {"ghe": [dm.ghe1[0].id]}).status_code == 302


def test_chuyen_da_qua_gio_chay_khong_ban_duoc(dm, chuyen_sap_chay, nguoi_dat):
    qua = chuyen_sap_chay(-30)
    with pytest.raises(ChuyenKhongMoBan):
        DatVeService.giu_cho(qua.id, [cho(dm.ghe1[0])], nguoi_dat, None)


def test_thoi_diem_het_han_bi_chan_boi_gio_ngung_ban_dung_bang(dm, chuyen_sap_chay, nguoi_dat):
    sap = chuyen_sap_chay(settings.NGUNG_BAN_TRUOC_PHUT + 3)          # còn ~3 phút trước giờ ngừng bán, giữ chỗ 15 phút
    don = DatVeService.giu_cho(sap.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    assert don.thoi_diem_het_han == sap.thoi_diem_ngung_ban
    assert don.thoi_diem_het_han < timezone.now() + timedelta(minutes=settings.GIU_CHO_PHUT)
    # Hết hạn rồi: ghế hiện trống nhưng chuyến đã đóng nên không đặt lại được
    het_han(don)
    assert GheNgoiDAO.lay_so_do_cho(sap.id, dm.toa1.id)[0]["trang_thai"] == "TRONG"


def test_thoi_diem_het_han_la_gia_tri_nho_hon_khi_chuyen_xa(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    du_kien = timezone.now() + timedelta(minutes=settings.GIU_CHO_PHUT)
    assert abs((don.thoi_diem_het_han - du_kien).total_seconds()) < 5


# =========================================================================== 7. Thanh toán giả lập
def test_thanh_toan_don_het_han_bi_tu_choi_service_va_http(client, dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="AUTO", bat_buoc_nhap_ma=False, so_luot_toi_da=5)
    r = client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1
    het_han(don)
    with pytest.raises(DonKhongThanhToanDuoc):
        DatVeService.thanh_toan_gia_lap(don.ma_dat_cho)
    r = client.post(reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho]), follow=True)
    assert r.status_code == 200 and "hết thời gian giữ chỗ" in r.content.decode()
    don.refresh_from_db()
    km.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.HET_HAN
    assert list(don.ds_ve.values_list("trang_thai", flat=True)) == [Ve.TrangThai.DA_HUY]
    assert km.so_luot_da_dung == 0
    # trang kết quả sau đó hiển thị hết hạn và ghế trống lại
    assert GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)[0]["trang_thai"] == "TRONG"


def test_thanh_toan_hai_lan_lan_hai_bi_tu_choi_va_khong_doi_gi(client, dm, chuyen, nguoi_dat):
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    url = reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho])
    assert client.post(url).status_code == 302
    r = client.post(url, follow=True)
    assert "không còn ở trạng thái đang giữ chỗ" in r.content.decode()
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DA_THANH_TOAN
    assert Ve.objects.get().trang_thai == Ve.TrangThai.DA_THANH_TOAN


def test_don_da_thanh_toan_qua_han_van_la_da_ban_va_khong_bi_giai_phong(client, dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="AUTO", bat_buoc_nhap_ma=False, so_luot_toi_da=5)
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    client.post(reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho]))
    het_han(don, 60)
    assert GiaiPhongChoTask.chay() == 0
    r = client.get(reverse("ket_qua", args=[don.ma_dat_cho]))
    assert r.status_code == 200
    don.refresh_from_db()
    km.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DA_THANH_TOAN and km.so_luot_da_dung == 1
    assert GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)[0]["trang_thai"] == "DA_BAN"
    with pytest.raises(ChoDaBiGiu):
        DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)


def test_thanh_toan_ma_khong_ton_tai_trong_session_la_404_khong_500(client, chuyen):
    s = client.session
    s["don_cua_toi"] = ["ZZZZZZZZ"]
    s.save()
    assert client.get(reverse("ket_qua", args=["ZZZZZZZZ"])).status_code == 404
    assert client.post(reverse("thanh_toan_gia_lap", args=["ZZZZZZZZ"])).status_code == 404


def test_luong_uc02_day_du_co_thanh_toan_qua_http(client, dm, chuyen, nguoi_dat, tao_km):
    tao_km(ma_khuyen_mai="DATSOM10", so_ngay_dat_truoc=7, muc_giam_toi_da=Decimal(100_000), bat_buoc_nhap_ma=False)
    sv80k(tao_km)
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id,
                                           "ngay_di": chuyen.ngay_khoi_hanh.isoformat(), "so_hanh_khach": 2})
    assert r.status_code == 200 and "450.000 đ" in r.content.decode()
    assert client.get(reverse("chon_cho", args=[chuyen.id])).status_code == 200
    ghe = dm.ghe1[:2]
    assert client.get(reverse("thong_tin", args=[chuyen.id]), {"ghe": [g.id for g in ghe]}).status_code == 200
    d = du_lieu_giu_cho(ghe, nguoi_dat, ma="SV80K", **{"hk-1-doi_tuong": "SINH_VIEN"})
    r = client.post(reverse("giu_cho", args=[chuyen.id]), d)
    assert r.status_code == 302
    don = DonDatCho.objects.get()
    ve = {v.ghe_ngoi_id: v for v in don.ds_ve.all()}
    assert ve[ghe[0].id].so_tien_giam == 45_000 and ve[ghe[1].id].so_tien_giam == 80_000
    assert don.tong_tien == (450_000 - 45_000) + (450_000 - 80_000)
    assert client.post(reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho])).status_code == 302
    html = client.get(reverse("ket_qua", args=[don.ma_dat_cho])).content.decode()
    assert "Đã thanh toán" in html and "775.000 đ" in html
    trang_thai = {g["ghe_id"]: g["trang_thai"] for g in GheNgoiDAO.lay_so_do_cho(chuyen.id, dm.toa1.id)}
    assert trang_thai[ghe[0].id] == trang_thai[ghe[1].id] == "DA_BAN"


# =========================================================================== 8. Xem đơn của người khác
def test_xem_don_nguoi_khac_bi_chan_ke_ca_khi_dang_nhap_quan_ly(client, dm, chuyen, nguoi_dat, quan_ly):
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    khac = Client()
    khac.force_login(quan_ly)
    assert khac.get(reverse("ket_qua", args=[don.ma_dat_cho])).status_code == 403
    assert khac.post(reverse("thanh_toan_gia_lap", args=[don.ma_dat_cho])).status_code == 403
    khac.session["don_cua_toi"] = []
    # mã đơn viết thường không nằm trong session -> 403, không lộ thông tin
    assert client.get(reverse("ket_qua", args=[don.ma_dat_cho.lower()])).status_code == 403
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DANG_GIU


def test_trang_ket_qua_cua_nguoi_khac_khong_lo_ten_hanh_khach(client, dm, chuyen, nguoi_dat):
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    r = Client().get(reverse("ket_qua", args=[don.ma_dat_cho]))
    assert r.status_code == 403
    assert "Hành khách 1" not in r.content.decode() and nguoi_dat["so_dien_thoai"] not in r.content.decode()


# =========================================================================== 9. Phân quyền trang quản lý
URL_QL = [
    ("quan_ly_gia_ve", []), ("quy_tac_them", []), ("khuyen_mai_them", []),
    ("quy_tac_sua", [1]), ("quy_tac_ngung", [1]), ("khuyen_mai_sua", [1]), ("khuyen_mai_ket_thuc", [1]),
]


@pytest.mark.parametrize("ten,args", URL_QL)
def test_chua_dang_nhap_get_va_post_deu_chuyen_toi_login(client, ten, args):
    url = reverse(ten, args=args)
    for phuong_thuc in (client.get, client.post):
        r = phuong_thuc(url)
        assert r.status_code == 302 and r["Location"].startswith("/accounts/login/?next=")


def test_trang_dang_nhap_hien_thi_va_dang_nhap_xong_ve_dung_next(client, quan_ly):
    r = client.get("/accounts/login/", {"next": reverse("quan_ly_gia_ve")})
    assert r.status_code == 200 and "Đăng nhập" in r.content.decode()
    r = client.post("/accounts/login/?next=" + reverse("quan_ly_gia_ve"),
                    {"username": "quanly_test", "password": "Matkhau@123", "next": reverse("quan_ly_gia_ve")})
    assert r.status_code == 302 and r["Location"] == reverse("quan_ly_gia_ve")
    # next trỏ ra ngoài miền không được chấp nhận
    client.logout()
    r = client.post("/accounts/login/", {"username": "quanly_test", "password": "Matkhau@123",
                                         "next": "https://evil.example.com/"})
    assert r.status_code == 302 and "evil.example.com" not in r["Location"]


def test_nhan_vien_post_truc_tiep_them_quy_tac_va_khuyen_mai_bi_403_khong_ghi_gi(client, nhan_vien, dm, hom_nay):
    client.force_login(nhan_vien)
    r = client.post(reverse("quy_tac_them"), du_lieu_qt(dm, hom_nay))
    assert r.status_code == 403
    r = client.post(reverse("khuyen_mai_them"), du_lieu_km(hom_nay))
    assert r.status_code == 403
    assert QuyTacGia.objects.count() == 0 and KhuyenMai.objects.count() == 0 and NhatKyThayDoi.objects.count() == 0


def test_nhan_vien_post_ngung_ket_thuc_sua_bi_403_khong_doi_trang_thai(client, nhan_vien, gia_day_du, tao_km, hom_nay):
    km = tao_km(ma_khuyen_mai="KMX")
    client.force_login(nhan_vien)
    assert client.post(reverse("quy_tac_ngung", args=[gia_day_du.nm.id])).status_code == 403
    assert client.post(reverse("quy_tac_sua", args=[gia_day_du.nm.id]), {"gia_co_so": "1"}).status_code == 403
    assert client.post(reverse("khuyen_mai_ket_thuc", args=[km.id])).status_code == 403
    assert client.post(reverse("khuyen_mai_sua", args=[km.id]), du_lieu_km(hom_nay, ma_khuyen_mai="KMX")).status_code == 403
    gia_day_du.nm.refresh_from_db()
    km.refresh_from_db()
    assert gia_day_du.nm.trang_thai == TTQ.DANG_AP_DUNG and km.trang_thai == KhuyenMai.TrangThai.DANG_AP_DUNG
    assert NhatKyThayDoi.objects.count() == 0


def test_post_can_csrf_khi_dung_client_co_kiem_tra(quan_ly, dm, hom_nay):
    c = Client(enforce_csrf_checks=True)
    c.force_login(quan_ly)
    assert c.post(reverse("quy_tac_them"), du_lieu_qt(dm, hom_nay)).status_code == 403
    assert QuyTacGia.objects.count() == 0


def test_dang_xuat_bang_get_khong_duoc_chap_nhan(client, quan_ly):
    client.force_login(quan_ly)
    assert client.get("/accounts/logout/").status_code == 405
    assert client.get(reverse("quan_ly_gia_ve")).status_code == 200
    assert client.post("/accounts/logout/").status_code == 302
    assert client.get(reverse("quan_ly_gia_ve")).status_code == 302


# =========================================================================== 10. Khuyến mãi: form/HTTP
def test_http_sua_km_giu_nguyen_ma_cua_chinh_no_khong_bao_trung(client_ql, tao_km, hom_nay):
    km = tao_km(ma_khuyen_mai="GIUMA", gia_tri_giam=Decimal(10))
    r = client_ql.post(reverse("khuyen_mai_sua", args=[km.id]),
                       du_lieu_km(hom_nay, ma_khuyen_mai="giuma", gia_tri_giam="15", bat_buoc_nhap_ma=""))
    assert r.status_code == 302, getattr(r, "context", None) and r.context["form"].errors
    km.refresh_from_db()
    assert km.ma_khuyen_mai == "GIUMA" and km.gia_tri_giam == 15


def test_http_sua_km_doi_sang_ma_cua_km_khac_khac_hoa_thuong_bi_bao_trung(client_ql, tao_km, hom_nay):
    tao_km(ma_khuyen_mai="DATSOM10")
    km = tao_km(ma_khuyen_mai="KHAC")
    r = client_ql.post(reverse("khuyen_mai_sua", args=[km.id]), du_lieu_km(hom_nay, ma_khuyen_mai="datsom10"))
    assert r.status_code == 200 and "ma_khuyen_mai" in r.context["form"].errors
    km.refresh_from_db()
    assert km.ma_khuyen_mai == "KHAC"


def test_http_them_km_ma_viet_thuong_co_khoang_trang_duoc_chuan_hoa_in_hoa(client_ql, hom_nay):
    r = client_ql.post(reverse("khuyen_mai_them"), du_lieu_km(hom_nay, ma_khuyen_mai="  he 2026 "))
    assert r.status_code == 302
    assert KhuyenMai.objects.get().ma_khuyen_mai == "HE2026"


@pytest.mark.parametrize("gt,ok", [("100", True), ("100.00", True), ("100.01", False), ("100.5", False),
                                   ("99.99", True), ("0", False), ("0.00", False), ("-1", False),
                                   ("abc", False), ("NaN", False), ("Infinity", False), ("1e400", False),
                                   ("1,5", False), ("", False)])
def test_http_km_phan_tram_bien_100(client_ql, hom_nay, gt, ok):
    r = client_ql.post(reverse("khuyen_mai_them"), du_lieu_km(hom_nay, gia_tri_giam=gt))
    assert r.status_code == (302 if ok else 200)
    assert KhuyenMai.objects.count() == (1 if ok else 0)
    if not ok:
        assert "gia_tri_giam" in r.context["form"].errors


def test_http_km_so_tien_cho_phep_lon_hon_100(client_ql, hom_nay):
    r = client_ql.post(reverse("khuyen_mai_them"), du_lieu_km(hom_nay, hinh_thuc_giam="SO_TIEN", gia_tri_giam="250000"))
    assert r.status_code == 302


def test_form_km_loi_e1_dong_thoi_nhieu_truong_khong_500(client_ql, hom_nay):
    r = client_ql.post(reverse("khuyen_mai_them"), du_lieu_km(
        hom_nay, ma_khuyen_mai="", ten="", hinh_thuc_giam="SAI", gia_tri_giam="x", muc_giam_toi_da="-5",
        ngay_bat_dau="2026-13-45", ngay_ket_thuc="", so_ngay_dat_truoc="-1", so_luot_toi_da="0",
        doi_tuong_ap_dung="QUAI_VAT", tuyen_duong="99999", loai_cho="abc"))
    assert r.status_code == 200 and not KhuyenMai.objects.exists()
    loi = r.context["form"].errors
    for truong in ("ma_khuyen_mai", "ten", "hinh_thuc_giam", "gia_tri_giam", "ngay_bat_dau", "ngay_ket_thuc"):
        assert truong in loi


@pytest.mark.parametrize("gia", ["450000.5", "1e400", "NaN", "abc", "99999999999999", "0", "-1", "", " "])
def test_http_quy_tac_gia_so_rac_khong_500(client_ql, dm, hom_nay, gia):
    r = client_ql.post(reverse("quy_tac_them"), du_lieu_qt(dm, hom_nay, gia_co_so=gia))
    assert r.status_code == 200 and QuyTacGia.objects.count() == 0
    assert "gia_co_so" in r.context["form"].errors


def test_http_quy_tac_gia_tuyen_va_loai_cho_khong_ton_tai_khong_500(client_ql, dm, hom_nay):
    r = client_ql.post(reverse("quy_tac_them"), du_lieu_qt(dm, hom_nay, tuyen_duong="99999", loai_cho="abc"))
    assert r.status_code == 200 and QuyTacGia.objects.count() == 0


def test_http_quy_tac_gia_ngay_ket_thuc_cuc_dai_9999_khong_500(client_ql, dm, hom_nay):
    client_ql.raise_request_exception = False
    r = client_ql.post(reverse("quy_tac_them"), du_lieu_qt(dm, hom_nay, ngay_ket_thuc="9999-12-31"))
    assert r.status_code in (200, 302)


# =========================================================================== 11. 404 cho id không tồn tại
@pytest.mark.parametrize("ten", ["quy_tac_sua", "quy_tac_ngung", "khuyen_mai_sua", "khuyen_mai_ket_thuc"])
@pytest.mark.parametrize("id_", [987654, 2 ** 31, 10 ** 25])
def test_quan_ly_id_khong_ton_tai_get_va_post_la_404(client_ql, ten, id_):
    url = reverse(ten, args=[id_])
    assert client_ql.get(url).status_code == 404
    assert client_ql.post(url).status_code == 404


@pytest.mark.parametrize("ten", ["chon_cho", "thong_tin", "giu_cho"])
@pytest.mark.parametrize("id_", [987654, 2 ** 31, 10 ** 25])
def test_dat_ve_chuyen_khong_ton_tai_la_404(client, ten, id_, nguoi_dat):
    url = reverse(ten, args=[id_])
    if ten == "giu_cho":
        assert client.post(url, {"hk-TOTAL_FORMS": 0, "hk-INITIAL_FORMS": 0}).status_code == 404
    else:
        assert client.get(url, {"ghe": [1]}).status_code == 404


def test_404_la_trang_tieng_viet_than_thien(client_ql):
    r = client_ql.get(reverse("quy_tac_sua", args=[987654]))
    assert r.status_code == 404 and "Không tìm thấy" in r.content.decode()


def test_url_khong_ton_tai_la_404(client):
    assert client.get("/khong-co-trang-nay/").status_code == 404
    assert client.get("/dat-ve/chuyen/abc/").status_code == 404
    assert client.get("/dat-ve/don/").status_code == 404


# =========================================================================== 12. Tham số tìm kiếm rác
@pytest.mark.parametrize("sua", [
    {"ngay_di": "31/12/2026"}, {"ngay_di": "2026-02-30"}, {"ngay_di": "abc"}, {"ngay_di": ""}, {"ngay_di": "0000-00-00"},
    {"ngay_di": "2026-1-1"}, {"ngay_di": "0001-01-01"}, {"ngay_di": "99999-01-01"},
    {"ga_di": "999999"}, {"ga_den": "999999"}, {"ga_di": "abc"}, {"ga_den": ""}, {"ga_di": "9" * 30}, {"ga_di": "-1"},
    {"so_hanh_khach": "abc"}, {"so_hanh_khach": "0"}, {"so_hanh_khach": "-1"}, {"so_hanh_khach": "7"},
    {"so_hanh_khach": "1.5"}, {"so_hanh_khach": "9" * 30}, {"so_hanh_khach": ""},
])
def test_tim_chuyen_tham_so_rac_khong_500(client, dm, chuyen, sua):
    tham_so = {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id, "ngay_di": chuyen.ngay_khoi_hanh.isoformat(), "so_hanh_khach": 1}
    tham_so.update(sua)
    r = client.get(reverse("tim_chuyen"), tham_so)
    assert r.status_code == 200
    assert not r.context["ds_chuyen"]                       # tham số sai thì không được trả chuyến nào


def test_tim_chuyen_ga_di_bang_ga_den_bao_loi_o_dung_truong(client, dm, chuyen):
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_a.id,
                                           "ngay_di": chuyen.ngay_khoi_hanh.isoformat(), "so_hanh_khach": 1})
    assert r.status_code == 200 and "ga_den" in r.context["form"].errors and not r.context["ds_chuyen"]


def test_tim_chuyen_ngay_trong_qua_khu_bi_chan(client, dm, hom_nay):
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id,
                                           "ngay_di": (hom_nay - timedelta(days=1)).isoformat(), "so_hanh_khach": 1})
    assert "ngay_di" in r.context["form"].errors


def test_tim_chuyen_chieu_nguoc_khong_co_chuyen_va_goi_y_ngay_lan_can_dung(client, dm, chuyen):
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_b.id, "ga_den": dm.ga_a.id,
                                           "ngay_di": chuyen.ngay_khoi_hanh.isoformat(), "so_hanh_khach": 1})
    assert r.status_code == 200 and r.context["ds_chuyen"] == [] and r.context["goi_y"] == []


def test_tim_chuyen_ngay_khong_co_chuyen_goi_y_ngay_lan_can(client, dm, chuyen, hom_nay):
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id,
                                           "ngay_di": (chuyen.ngay_khoi_hanh + timedelta(days=3)).isoformat(),
                                           "so_hanh_khach": 1})
    assert r.status_code == 200 and [g["ngay"] for g in r.context["goi_y"]] == [chuyen.ngay_khoi_hanh]


def test_tim_chuyen_ngay_9999_12_31_khong_500(client, dm, chuyen):
    r = client.get(reverse("tim_chuyen"), {"ga_di": dm.ga_a.id, "ga_den": dm.ga_b.id,
                                           "ngay_di": "9999-12-31", "so_hanh_khach": 1})
    assert r.status_code == 200


@pytest.mark.parametrize("tham_so", [
    {"toa": "abc"}, {"toa": "99999999999999999999"}, {"toa": "-1"}, {"toa": ""}, {"toa": "1.5"},
    {"so_hanh_khach": "abc"}, {"so_hanh_khach": "9" * 30}, {"so_hanh_khach": "-4"},
])
def test_chon_cho_tham_so_rac_khong_500(client, dm, chuyen, tham_so):
    r = client.get(reverse("chon_cho", args=[chuyen.id]), tham_so)
    assert r.status_code == 200
    assert r.context["toa_chon"] in {dm.toa1.id, dm.toa2.id}


def test_chon_cho_toa_cua_tau_khac_bi_bo_qua(client, dm, chuyen, tau_khac):
    r = client.get(reverse("chon_cho", args=[chuyen.id]), {"toa": tau_khac.toa_xe_id})
    assert r.status_code == 200 and r.context["toa_chon"] in {dm.toa1.id, dm.toa2.id}


def test_chon_cho_chuyen_het_cho_va_chuyen_ngung_ban_chuyen_huong(client, dm, chuyen, nguoi_dat, tao_chuyen, hom_nay):
    ngung = tao_chuyen(hom_nay + timedelta(days=11), trang_thai=ChuyenTau.TrangThai.NGUNG_BAN)
    assert client.get(reverse("chon_cho", args=[ngung.id])).status_code == 302
    ds = [cho(g, so_giay_to=f"98765432{i}") for i, g in enumerate(dm.ghe1[:6])]
    DatVeService.giu_cho(chuyen.id, ds, nguoi_dat, None)
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[6]), cho(dm.ghe1[7], so_giay_to="98765432A")], nguoi_dat, None)
    DatVeService.giu_cho(chuyen.id, [cho(g, so_giay_to=f"9876543{i}") for i, g in enumerate(dm.ghe2)], nguoi_dat, None)
    r = client.get(reverse("chon_cho", args=[chuyen.id]), follow=True)
    assert "hết chỗ" in r.content.decode()


# =========================================================================== 13. Giải phóng chạy hai lần
def test_giai_phong_chay_hai_lan_khong_hoan_luot_km_hai_lan(client, dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="AUTO", bat_buoc_nhap_ma=False, so_luot_toi_da=10)
    # Đơn A (sẽ hết hạn) dùng 2 lượt, đơn B (còn hạn) dùng 1 lượt
    don_a = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0]), cho(dm.ghe1[1], so_giay_to="987654321")], nguoi_dat, None)
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[2], so_giay_to="987654322")],
                         {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    km.refresh_from_db()
    assert km.so_luot_da_dung == 3
    het_han(don_a)
    assert GiaiPhongChoTask.chay() == 1
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1
    assert GiaiPhongChoTask.chay() == 0                        # lần hai: không còn gì để giải phóng
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1


def test_giai_phong_cung_mot_doi_tuong_cu_hai_lan_chi_hoan_mot_lan(dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="AUTO", bat_buoc_nhap_ma=False, so_luot_toi_da=10)
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    het_han(don)
    cu = DonDatCho.objects.get(pk=don.pk)                       # hai "bản chụp" cũ của cùng một đơn (như hai tiến trình)
    cu2 = DonDatCho.objects.get(pk=don.pk)
    assert DonDatChoDAO.giai_phong(cu) is True
    assert DonDatChoDAO.giai_phong(cu2) is False
    km.refresh_from_db()
    assert km.so_luot_da_dung == 0
    assert Ve.objects.get().trang_thai == Ve.TrangThai.DA_HUY


def test_xem_trang_ket_qua_don_het_han_nhieu_lan_chi_hoan_mot_lan(client, dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="AUTO", bat_buoc_nhap_ma=False, so_luot_toi_da=10)
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[3], so_giay_to="987654329")], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    don = DonDatCho.objects.get(ma_dat_cho__in=client.session["don_cua_toi"])
    het_han(don)
    for _ in range(3):
        r = client.get(reverse("ket_qua", args=[don.ma_dat_cho]))
        assert r.status_code == 200 and "Hết hạn" in r.content.decode()
    km.refresh_from_db()
    assert km.so_luot_da_dung == 1                             # chỉ còn đơn kia


def test_giai_phong_chua_den_han_hoac_dang_o_ranh_gioi_khong_dong_vao(dm, chuyen, nguoi_dat):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    assert GiaiPhongChoTask.chay() == 0
    DonDatCho.objects.filter(pk=don.pk).update(thoi_diem_het_han=timezone.now() + timedelta(seconds=30))
    assert GiaiPhongChoTask.chay() == 0
    don.refresh_from_db()
    assert don.trang_thai == DonDatCho.TrangThai.DANG_GIU


def test_don_het_han_dat_lai_cung_ghe_duoc_va_hoan_luot_dung_don_cu(dm, chuyen, nguoi_dat, tao_km):
    km = tao_km(ma_khuyen_mai="AUTO", bat_buoc_nhap_ma=False, so_luot_toi_da=10)
    cu = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    het_han(cu)
    moi = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    cu.refresh_from_db()
    km.refresh_from_db()
    assert cu.trang_thai == DonDatCho.TrangThai.HET_HAN and moi.trang_thai == DonDatCho.TrangThai.DANG_GIU
    assert km.so_luot_da_dung == 1                              # hoàn 1 (đơn cũ) rồi dùng 1 (đơn mới)


# =========================================================================== 14. Sơ đồ chỗ / khách hàng / nhật ký
def test_khach_hang_cung_sdt_khac_ten_cap_nhat_ten_khong_tao_trung(dm, chuyen, nguoi_dat):
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[1], so_giay_to="987654321")], {**nguoi_dat, "ho_ten": "Người Khác"}, None)
    from datve.models import KhachHang
    assert KhachHang.objects.count() == 1


def test_e4_sua_quy_tac_da_dung_ve_cu_giu_gia_ve_moi_theo_gia_moi_va_ghi_hai_nhat_ky(client_ql, dm, chuyen, nguoi_dat, gia_day_du, hom_nay):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    cu = gia_day_du.nm
    r = client_ql.post(reverse("quy_tac_sua", args=[cu.id]), {
        "tuyen_duong": dm.tuyen.id, "loai_cho": dm.nm.id, "gia_co_so": "480000", "loai_thoi_diem": "NGAY_THUONG",
        "ngay_bat_dau": cu.ngay_bat_dau.isoformat(), "ngay_ket_thuc": "", "ghi_chu": "tăng giá"})
    assert r.status_code == 302
    cu.refresh_from_db()
    assert cu.trang_thai == TTQ.NGUNG_AP_DUNG and cu.ngay_ket_thuc == hom_nay
    moi = QuyTacGia.objects.get(trang_thai=TTQ.DANG_AP_DUNG, loai_cho=dm.nm)
    assert moi.gia_co_so == 480_000 and moi.ngay_bat_dau == hom_nay
    assert Ve.objects.get().gia_ve == 450_000 and Ve.objects.get().quy_tac_gia_id == cu.id
    don2 = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[1], so_giay_to="987654321")], {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    assert don2.tong_tien == 480_000 and don.tong_tien == 450_000
    hd = list(NhatKyThayDoi.objects.order_by("id").values_list("hanh_dong", flat=True))
    assert hd == ["NGUNG_AP_DUNG", "THEM"]


def test_nhat_ky_ghi_nguoi_thuc_hien_va_json_gia_tri_cu_moi(client_ql, quan_ly, tao_km, hom_nay):
    km = tao_km(ma_khuyen_mai="NK1", gia_tri_giam=Decimal(10))
    client_ql.post(reverse("khuyen_mai_sua", args=[km.id]), du_lieu_km(hom_nay, ma_khuyen_mai="NK1", gia_tri_giam="12"))
    nk = NhatKyThayDoi.objects.get()
    assert nk.nguoi_thuc_hien == quan_ly and nk.hanh_dong == "SUA"
    assert Decimal(str(nk.gia_tri_cu["gia_tri_giam"])) == 10 and Decimal(str(nk.gia_tri_moi["gia_tri_giam"])) == 12


# =========================================================================== 15. Django Admin / đăng xuất / thông báo A7 (lỗi đã tái hiện)
@pytest.fixture
def client_admin(client, db):
    from taikhoan.models import ThanhVien
    root = ThanhVien.objects.create_superuser("root_qa", "", "x", ho_ten="Root QA")
    client.force_login(root)
    client.raise_request_exception = False
    return client


def test_admin_them_quy_tac_trung_thoi_gian_khong_500(client_admin, dm, tao_quy_tac, quan_ly, hom_nay):
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 450_000, bat_dau=hom_nay)
    r = client_admin.post(reverse("admin:giave_quytacgia_add"), {
        "tuyen_duong": dm.tuyen.id, "loai_cho": dm.nm.id, "gia_co_so": "123000", "loai_thoi_diem": "NGAY_THUONG",
        "ngay_bat_dau": (hom_nay + timedelta(days=5)).isoformat(), "ngay_ket_thuc": "",
        "trang_thai": "DANG_AP_DUNG", "ghi_chu": "", "nguoi_tao": quan_ly.id})
    assert r.status_code == 200          # biểu mẫu hiện lỗi, không phải 500
    assert QuyTacGia.objects.count() == 1


def test_admin_sua_khuyen_mai_phai_ghi_nhat_ky(client_admin, tao_km):
    km = tao_km(ma_khuyen_mai="ADM1", gia_tri_giam=Decimal(10))
    r = client_admin.post(reverse("admin:giave_khuyenmai_change", args=[km.id]), {
        "ma_khuyen_mai": "ADM1", "ten": "đổi tên qua admin", "hinh_thuc_giam": "PHAN_TRAM", "gia_tri_giam": "50",
        "muc_giam_toi_da": "", "ngay_bat_dau": km.ngay_bat_dau.isoformat(), "ngay_ket_thuc": km.ngay_ket_thuc.isoformat(),
        "tuyen_duong": "", "loai_cho": "", "doi_tuong_ap_dung": "", "so_ngay_dat_truoc": "0", "so_luot_toi_da": "",
        "so_luot_da_dung": "0", "bat_buoc_nhap_ma": "", "trang_thai": "DANG_AP_DUNG"})
    assert r.status_code == 302
    km.refresh_from_db()
    assert km.gia_tri_giam == 50                      # đã sửa được (xác nhận admin hoạt động)
    assert NhatKyThayDoi.objects.count() >= 1


def test_dang_xuat_khong_lam_mat_quyen_xem_don_dang_giu(client, quan_ly, dm, chuyen, nguoi_dat):
    client.force_login(quan_ly)
    client.post(reverse("giu_cho", args=[chuyen.id]), du_lieu_giu_cho(dm.ghe1[:1], nguoi_dat))
    don = DonDatCho.objects.get()
    assert client.get(reverse("ket_qua", args=[don.ma_dat_cho])).status_code == 200
    client.post("/accounts/logout/")
    assert client.get(reverse("ket_qua", args=[don.ma_dat_cho])).status_code == 200


def test_giai_phong_het_han_gui_thong_bao_cho_khach(dm, chuyen, nguoi_dat, mailoutbox,
                                                    django_capture_on_commit_callbacks):
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    # email xác nhận giữ chỗ gửi sau on_commit (không tự chạy trong test) -> làm trống hộp thư để so sánh
    mailoutbox.clear()
    het_han(don)
    with django_capture_on_commit_callbacks(execute=True):          # thông báo hết hạn gửi sau on_commit
        assert GiaiPhongChoTask.chay() == 1
    assert len(mailoutbox) == 1 and nguoi_dat["email"] in mailoutbox[0].to
