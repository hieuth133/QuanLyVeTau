"""UC14 nhánh A: quy tắc giá – form (E1), DAO, ràng buộc EXCLUDE (E2), sửa quy tắc đã dùng (E4), phân quyền."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse

from datve.models import Ve
from datve.services import DatVeService
from giave.dao import QuyTacGiaDAO
from giave.forms import QuyTacGiaForm
from giave.models import NhatKyThayDoi, QuyTacGia
from tien_ich import cho

pytestmark = pytest.mark.django_db

LT = QuyTacGia.LoaiThoiDiem
TT = QuyTacGia.TrangThai
D = date(2030, 5, 1)


def du_lieu(dm, hom_nay, **ghi_de):
    d = {"tuyen_duong": dm.tuyen.id, "loai_cho": dm.nm.id, "gia_co_so": "500000", "loai_thoi_diem": "CUOI_TUAN",
         "ngay_bat_dau": (hom_nay + timedelta(days=1)).isoformat(), "ngay_ket_thuc": "", "ghi_chu": "thử"}
    d.update(ghi_de)
    return d


@pytest.fixture
def client_ql(client, quan_ly):
    client.force_login(quan_ly)
    return client


@pytest.fixture
def da_dung(dm, chuyen, gia_day_du, nguoi_dat):
    """Đặt một vé để gia_day_du.nm trở thành quy tắc 'đã được dùng'."""
    don = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[0])], nguoi_dat, None)
    return don


# --------------------------------------------------------------------------- Form (E1)
def test_form_tu_choi_gia_khong_duong(dm, hom_nay):
    for gia in ("0", "-100"):
        form = QuyTacGiaForm(du_lieu(dm, hom_nay, gia_co_so=gia))
        assert not form.is_valid()
        assert "gia_co_so" in form.errors


def test_form_tu_choi_ngay_ket_thuc_truoc_ngay_bat_dau(dm, hom_nay):
    form = QuyTacGiaForm(du_lieu(dm, hom_nay, ngay_bat_dau=(hom_nay + timedelta(days=5)).isoformat(),
                                 ngay_ket_thuc=(hom_nay + timedelta(days=2)).isoformat()))
    assert not form.is_valid()
    assert "ngay_ket_thuc" in form.errors


def test_form_tu_choi_ngay_bat_dau_qua_khu_khi_tao_moi(dm, hom_nay):
    form = QuyTacGiaForm(du_lieu(dm, hom_nay, ngay_bat_dau=(hom_nay - timedelta(days=1)).isoformat()))
    assert not form.is_valid()
    assert "ngay_bat_dau" in form.errors


def test_form_cho_phep_ngay_bat_dau_qua_khu_khi_sua(dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, hom_nay - timedelta(days=30))
    form = QuyTacGiaForm(du_lieu(dm, hom_nay, ngay_bat_dau=(hom_nay - timedelta(days=30)).isoformat()), instance=qt)
    assert form.is_valid(), form.errors


def test_form_bat_buoc_cac_truong(dm, hom_nay):
    form = QuyTacGiaForm({})
    assert not form.is_valid()
    for truong in ("tuyen_duong", "loai_cho", "gia_co_so", "loai_thoi_diem", "ngay_bat_dau"):
        assert truong in form.errors


def test_form_hop_le(dm, hom_nay):
    assert QuyTacGiaForm(du_lieu(dm, hom_nay)).is_valid()


# --------------------------------------------------------------------------- DAO: tim_quy_tac_trung (E2)
def _moi(dm, quan_ly, bat_dau, ket_thuc=None, loai_td=LT.CUOI_TUAN, loai_cho=None, pk=None):
    return QuyTacGia(pk=pk, tuyen_duong=dm.tuyen, loai_cho=loai_cho or dm.nm, gia_co_so=Decimal(1000),
                     loai_thoi_diem=loai_td, ngay_bat_dau=bat_dau, ngay_ket_thuc=ket_thuc, nguoi_tao=quan_ly)


def test_tim_trung_phat_hien_giao_nhau(dm, quan_ly, tao_quy_tac):
    co_san = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, D, D + timedelta(days=30))
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D + timedelta(days=10), D + timedelta(days=40))) == [co_san]
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D - timedelta(days=5), D + timedelta(days=1))) == [co_san]
    # ngày chạm nhau (khoảng đóng) cũng là trùng
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D + timedelta(days=30), D + timedelta(days=35))) == [co_san]


def test_tim_trung_khong_bao_khi_lien_ke_khong_giao(dm, quan_ly, tao_quy_tac):
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, D, D + timedelta(days=30))
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D + timedelta(days=31), D + timedelta(days=60))) == []
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D - timedelta(days=10), D - timedelta(days=1))) == []


def test_tim_trung_khi_mot_ben_khong_co_ngay_ket_thuc(dm, quan_ly, tao_quy_tac):
    mo = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, D)                  # không có ngày kết thúc
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D + timedelta(days=365), D + timedelta(days=400))) == [mo]
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D - timedelta(days=100))) == [mo]   # cả hai đều vô hạn
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D - timedelta(days=100), D - timedelta(days=1))) == []
    dong = tao_quy_tac(dm.nm, LT.NGAY_THUONG, 1000, D, D + timedelta(days=5))
    assert QuyTacGiaDAO.tim_quy_tac_trung(
        _moi(dm, quan_ly, D + timedelta(days=100), loai_td=LT.NGAY_THUONG)) == []
    assert dong


def test_tim_trung_bo_qua_khac_loai_khac_trang_thai_va_chinh_no(dm, quan_ly, tao_quy_tac):
    co_san = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, D)
    tao_quy_tac(dm.k4, LT.CUOI_TUAN, 800_000, D)
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 450_000, D)
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 1, D, trang_thai=TT.NGUNG_AP_DUNG)
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D)) == [co_san]
    assert QuyTacGiaDAO.tim_quy_tac_trung(_moi(dm, quan_ly, D, pk=co_san.pk)) == []        # loại trừ chính nó (E4)


def test_rang_buoc_exclude_nem_integrity_error_khi_chen_truc_tiep(dm, quan_ly, tao_quy_tac):
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, D, D + timedelta(days=30))
    with pytest.raises(IntegrityError, match="ex_quy_tac_khong_trung"):
        with transaction.atomic():
            tao_quy_tac(dm.nm, LT.CUOI_TUAN, 600_000, D + timedelta(days=10))


def test_rang_buoc_exclude_cho_phep_khi_quy_tac_cu_da_ngung(dm, tao_quy_tac):
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, D, trang_thai=TT.NGUNG_AP_DUNG)
    tao_quy_tac(dm.nm, LT.CUOI_TUAN, 600_000, D)       # không lỗi


# --------------------------------------------------------------------------- DAO: ket_thuc, da_duoc_su_dung
def test_ket_thuc_dat_ngay_va_trang_thai(dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, bat_dau=hom_nay - timedelta(days=10))
    assert QuyTacGiaDAO.ket_thuc(qt.id, hom_nay) is True
    qt.refresh_from_db()
    assert qt.trang_thai == TT.NGUNG_AP_DUNG and qt.ngay_ket_thuc == hom_nay


def test_ket_thuc_quy_tac_bat_dau_o_tuong_lai_khong_vi_pham_rang_buoc(dm, tao_quy_tac, hom_nay):
    tuong_lai = hom_nay + timedelta(days=20)
    qt = tao_quy_tac(dm.nm, bat_dau=tuong_lai)
    assert QuyTacGiaDAO.ket_thuc(qt.id, hom_nay) is True       # nếu đặt = hom_nay sẽ vi phạm ck_qtg_khoang_ngay
    qt.refresh_from_db()
    assert qt.ngay_ket_thuc == tuong_lai and qt.trang_thai == TT.NGUNG_AP_DUNG


def test_ket_thuc_giu_ngay_ket_thuc_som_hon(dm, tao_quy_tac, hom_nay):
    som = hom_nay + timedelta(days=3)
    qt = tao_quy_tac(dm.nm, bat_dau=hom_nay - timedelta(days=10), ket_thuc=som)
    QuyTacGiaDAO.ket_thuc(qt.id, hom_nay + timedelta(days=100))
    qt.refresh_from_db()
    assert qt.ngay_ket_thuc == som


def test_ket_thuc_khong_lam_lai_quy_tac_da_ngung(dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, bat_dau=hom_nay - timedelta(days=10), trang_thai=TT.NGUNG_AP_DUNG,
                     ket_thuc=hom_nay - timedelta(days=5))
    assert QuyTacGiaDAO.ket_thuc(qt.id, hom_nay) is False
    qt.refresh_from_db()
    assert qt.ngay_ket_thuc == hom_nay - timedelta(days=5)
    assert QuyTacGiaDAO.ket_thuc(10 ** 9, hom_nay) is False


def test_da_duoc_su_dung_va_khong_xoa_duoc_quy_tac_da_dung(da_dung, gia_day_du):
    assert QuyTacGiaDAO.da_duoc_su_dung(gia_day_du.nm.id) is True
    assert QuyTacGiaDAO.da_duoc_su_dung(gia_day_du.k4.id) is False
    with pytest.raises(ProtectedError):
        gia_day_du.nm.delete()
    gia_day_du.k4.delete()      # quy tắc chưa dùng thì xóa được (qua Admin)


def test_tim_quy_tac_gia_loc(dm, tao_quy_tac, hom_nay):
    a = tao_quy_tac(dm.nm, LT.NGAY_THUONG)
    b = tao_quy_tac(dm.k4, LT.NGAY_THUONG, 750_000)
    c = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, trang_thai=TT.NGUNG_AP_DUNG)
    assert {q.id for q in QuyTacGiaDAO.tim_quy_tac_gia(None, None, None)} == {a.id, b.id, c.id}
    assert {q.id for q in QuyTacGiaDAO.tim_quy_tac_gia(dm.tuyen.id, dm.k4.id, None)} == {b.id}
    assert {q.id for q in QuyTacGiaDAO.tim_quy_tac_gia(None, None, TT.NGUNG_AP_DUNG)} == {c.id}
    assert QuyTacGiaDAO.tim_quy_tac_gia(dm.tuyen2.id, None, None) == []


# --------------------------------------------------------------------------- Phân quyền
URL_QUAN_LY = ["quan_ly_gia_ve", "quy_tac_them", "khuyen_mai_them"]


@pytest.mark.parametrize("ten", URL_QUAN_LY)
def test_nhan_vien_nhan_403_than_thien(client, nhan_vien, ten):
    client.force_login(nhan_vien)
    r = client.get(reverse(ten))
    assert r.status_code == 403
    assert "Bạn không có quyền truy cập" in r.content.decode()      # template 403.html


def test_nhan_vien_khong_the_post_sua_ngung(client, nhan_vien, gia_day_du):
    client.force_login(nhan_vien)
    assert client.post(reverse("quy_tac_ngung", args=[gia_day_du.nm.id])).status_code == 403
    assert client.get(reverse("quy_tac_sua", args=[gia_day_du.nm.id])).status_code == 403
    gia_day_du.nm.refresh_from_db()
    assert gia_day_du.nm.trang_thai == TT.DANG_AP_DUNG


@pytest.mark.parametrize("ten", URL_QUAN_LY)
def test_chua_dang_nhap_chuyen_toi_dang_nhap(client, ten):
    r = client.get(reverse(ten))
    assert r.status_code == 302 and r["Location"].startswith("/accounts/login/")


def test_superuser_duoc_phep(client, db):
    from taikhoan.models import ThanhVien
    admin = ThanhVien.objects.create_superuser("root", "", "x", ho_ten="Root")
    client.force_login(admin)
    assert client.get(reverse("quan_ly_gia_ve")).status_code == 200


# --------------------------------------------------------------------------- View: danh sách, E1, E2, thêm, sửa
def test_danh_sach_hai_the_va_bo_loc(client_ql, dm, tao_quy_tac):
    tao_quy_tac(dm.nm, LT.NGAY_THUONG, 450_000)
    tao_quy_tac(dm.k4, LT.NGAY_THUONG, 750_000)
    r = client_ql.get(reverse("quan_ly_gia_ve"), {"the": "gia-ve", "loai_cho": dm.k4.id})
    assert r.status_code == 200
    assert [q.loai_cho_id for q in r.context["ds_quy_tac"]] == [dm.k4.id]
    assert "750.000 đ" in r.content.decode()
    r = client_ql.get(reverse("quan_ly_gia_ve"), {"the": "khuyen-mai"})
    assert r.status_code == 200 and "ds_khuyen_mai" in r.context


def test_e1_gia_am_loi_gan_dung_truong_va_giu_du_lieu(client_ql, dm, hom_nay):
    r = client_ql.post(reverse("quy_tac_them"), du_lieu(dm, hom_nay, gia_co_so="-500", ghi_chu="giữ lại ghi chú"))
    assert r.status_code == 200
    assert "gia_co_so" in r.context["form"].errors
    html = r.content.decode()
    assert 'value="-500"' in html and "giữ lại ghi chú" in html          # dữ liệu nhập được giữ nguyên
    assert 'is-invalid' in html
    assert QuyTacGia.objects.count() == 0


def test_e1_ngay_ket_thuc_truoc_ngay_bat_dau(client_ql, dm, hom_nay):
    r = client_ql.post(reverse("quy_tac_them"), du_lieu(
        dm, hom_nay, ngay_bat_dau=(hom_nay + timedelta(days=9)).isoformat(),
        ngay_ket_thuc=(hom_nay + timedelta(days=3)).isoformat()))
    assert r.status_code == 200 and "ngay_ket_thuc" in r.context["form"].errors


def test_e1_thieu_truong_bat_buoc(client_ql, dm):
    r = client_ql.post(reverse("quy_tac_them"), {})
    assert r.status_code == 200 and "tuyen_duong" in r.context["form"].errors


def test_e2_hien_thi_danh_sach_quy_tac_bi_trung(client_ql, dm, tao_quy_tac, hom_nay):
    co_san = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, hom_nay)          # không ngày kết thúc
    r = client_ql.post(reverse("quy_tac_them"), du_lieu(
        dm, hom_nay, ngay_bat_dau=(hom_nay + timedelta(days=20)).isoformat()))
    assert r.status_code == 200
    assert r.context["trung"] == [co_san]
    assert "Quy tắc bị trùng thời gian áp dụng" in r.content.decode()
    assert QuyTacGia.objects.count() == 1 and NhatKyThayDoi.objects.count() == 0


def test_them_thanh_cong_ghi_nhat_ky(client_ql, dm, quan_ly, hom_nay):
    r = client_ql.post(reverse("quy_tac_them"), du_lieu(dm, hom_nay), follow=True)
    assert r.redirect_chain[-1][0].startswith(reverse("quan_ly_gia_ve"))
    assert "Lưu thành công" in r.content.decode()
    qt = QuyTacGia.objects.get()
    assert qt.nguoi_tao == quan_ly and qt.gia_co_so == 500_000
    nk = NhatKyThayDoi.objects.get()
    assert nk.hanh_dong == "THEM" and nk.doi_tuong_id == qt.id and nk.nguoi_thuc_hien == quan_ly
    assert nk.gia_tri_cu is None and nk.gia_tri_moi["gia_co_so"] == "500000"


def test_sua_quy_tac_chua_dung_cap_nhat_tai_cho(client_ql, dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, hom_nay + timedelta(days=1))
    r = client_ql.post(reverse("quy_tac_sua", args=[qt.id]), du_lieu(dm, hom_nay, gia_co_so="520000"))
    assert r.status_code == 302
    qt.refresh_from_db()
    assert qt.gia_co_so == 520_000 and QuyTacGia.objects.count() == 1
    nk = NhatKyThayDoi.objects.get()
    assert nk.hanh_dong == "SUA" and nk.gia_tri_cu["gia_co_so"] == "500000" and nk.gia_tri_moi["gia_co_so"] == "520000"


def test_sua_khong_bao_trung_voi_chinh_no(client_ql, dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, hom_nay + timedelta(days=1))
    r = client_ql.post(reverse("quy_tac_sua", args=[qt.id]), du_lieu(dm, hom_nay, ghi_chu="đổi ghi chú"))
    assert r.status_code == 302


def test_sua_quy_tac_khong_ton_tai_404(client_ql):
    assert client_ql.get(reverse("quy_tac_sua", args=[999999])).status_code == 404


# --------------------------------------------------------------------------- E4: sửa quy tắc đã dùng
def test_e4_sua_quy_tac_da_dung_ket_thuc_cu_va_tao_ban_moi(client_ql, dm, da_dung, gia_day_du, quan_ly, hom_nay):
    cu = gia_day_du.nm
    ve = Ve.objects.get()
    assert ve.quy_tac_gia_id == cu.id and ve.gia_co_so == 450_000
    r = client_ql.get(reverse("quy_tac_sua", args=[cu.id]))
    assert r.status_code == 200 and r.context["da_dung"] is True
    r = client_ql.post(reverse("quy_tac_sua", args=[cu.id]), du_lieu(
        dm, hom_nay, gia_co_so="480000", loai_thoi_diem="NGAY_THUONG", ngay_bat_dau=cu.ngay_bat_dau.isoformat()))
    assert r.status_code == 302, getattr(r, "context", None) and r.context["form"].errors
    cu.refresh_from_db()
    assert cu.trang_thai == TT.NGUNG_AP_DUNG and cu.ngay_ket_thuc == hom_nay and cu.gia_co_so == 450_000
    moi = QuyTacGia.objects.exclude(pk=cu.pk).get(loai_cho=dm.nm)
    assert moi.trang_thai == TT.DANG_AP_DUNG and moi.gia_co_so == 480_000
    assert moi.ngay_bat_dau == hom_nay and moi.ngay_ket_thuc is None and moi.nguoi_tao == quan_ly
    # QT05: vé đã giữ giữ nguyên giá và quy tắc cũ
    ve.refresh_from_db()
    assert ve.quy_tac_gia_id == cu.id and ve.gia_co_so == 450_000 and ve.gia_ve == 450_000
    # nhật ký: NGUNG_AP_DUNG (quy tắc cũ) rồi THEM (phiên bản mới)
    nk = {n.hanh_dong: n for n in NhatKyThayDoi.objects.all()}
    assert set(nk) == {"NGUNG_AP_DUNG", "THEM"}
    assert nk["NGUNG_AP_DUNG"].doi_tuong_id == cu.id and nk["NGUNG_AP_DUNG"].gia_tri_cu["gia_co_so"] == "450000"
    assert nk["THEM"].doi_tuong_id == moi.id and nk["THEM"].gia_tri_moi["gia_co_so"] == "480000"


def test_e4_ban_moi_ap_dung_gia_moi_cho_dat_cho_sau(client_ql, dm, da_dung, gia_day_du, chuyen, nguoi_dat, hom_nay):
    client_ql.post(reverse("quy_tac_sua", args=[gia_day_du.nm.id]), du_lieu(
        dm, hom_nay, gia_co_so="480000", loai_thoi_diem="NGAY_THUONG", ngay_bat_dau="2020-01-01"))
    don2 = DatVeService.giu_cho(chuyen.id, [cho(dm.ghe1[1], so_giay_to="987654321")],
                                {**nguoi_dat, "so_dien_thoai": "0987654321"}, None)
    assert don2.tong_tien == 480_000
    assert Ve.objects.get(ghe_ngoi=dm.ghe1[0]).gia_ve == 450_000


def test_e4_ngay_ket_thuc_truoc_ngay_bat_dau_moi_bao_loi_e1(client_ql, dm, da_dung, gia_day_du, hom_nay):
    r = client_ql.post(reverse("quy_tac_sua", args=[gia_day_du.nm.id]), du_lieu(
        dm, hom_nay, loai_thoi_diem="NGAY_THUONG", ngay_bat_dau="2020-01-01",
        ngay_ket_thuc=(hom_nay - timedelta(days=5)).isoformat()))
    assert r.status_code == 200
    assert "ngay_ket_thuc" in r.context["form"].errors
    gia_day_du.nm.refresh_from_db()
    assert gia_day_du.nm.trang_thai == TT.DANG_AP_DUNG                  # không đổi gì
    assert QuyTacGia.objects.count() == 2 and NhatKyThayDoi.objects.count() == 0


def test_e4_ban_moi_bat_dau_tu_ngay_form_neu_o_tuong_lai(client_ql, dm, da_dung, gia_day_du, hom_nay):
    tuong_lai = hom_nay + timedelta(days=15)
    r = client_ql.post(reverse("quy_tac_sua", args=[gia_day_du.nm.id]), du_lieu(
        dm, hom_nay, loai_thoi_diem="NGAY_THUONG", ngay_bat_dau=tuong_lai.isoformat()))
    assert r.status_code == 302
    moi = QuyTacGia.objects.filter(loai_cho=dm.nm, trang_thai=TT.DANG_AP_DUNG).get()
    assert moi.ngay_bat_dau == tuong_lai


def test_e4_van_bao_trung_voi_quy_tac_khac(client_ql, dm, da_dung, gia_day_du, tao_quy_tac, hom_nay):
    khac = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, hom_nay)
    r = client_ql.post(reverse("quy_tac_sua", args=[gia_day_du.nm.id]), du_lieu(
        dm, hom_nay, loai_thoi_diem="CUOI_TUAN", ngay_bat_dau="2020-01-01"))
    assert r.status_code == 200 and r.context["trung"] == [khac]
    gia_day_du.nm.refresh_from_db()
    assert gia_day_du.nm.trang_thai == TT.DANG_AP_DUNG


# --------------------------------------------------------------------------- IntegrityError của EXCLUDE -> như E2
def test_integrity_error_exclude_hien_thi_nhu_e2(client_ql, dm, tao_quy_tac, hom_nay, monkeypatch):
    co_san = tao_quy_tac(dm.nm, LT.CUOI_TUAN, 500_000, hom_nay)
    that = QuyTacGiaDAO.tim_quy_tac_trung
    goi = {"n": 0}

    def gia_lap(qt):
        goi["n"] += 1
        return [] if goi["n"] == 1 else that(qt)         # lần đầu bỏ lọt (mô phỏng đua), lần sau trả đúng

    monkeypatch.setattr(QuyTacGiaDAO, "tim_quy_tac_trung", staticmethod(gia_lap))
    r = client_ql.post(reverse("quy_tac_them"), du_lieu(
        dm, hom_nay, ngay_bat_dau=(hom_nay + timedelta(days=5)).isoformat()))
    assert r.status_code == 200
    assert r.context["trung"] == [co_san]
    assert QuyTacGia.objects.count() == 1 and NhatKyThayDoi.objects.count() == 0


# --------------------------------------------------------------------------- E3 / E5
def test_e3_ngung_ap_dung_co_trang_xac_nhan_roi_moi_thuc_hien(client_ql, dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, bat_dau=hom_nay - timedelta(days=3))
    r = client_ql.get(reverse("quy_tac_ngung", args=[qt.id]))
    assert r.status_code == 200 and "Xác nhận ngừng áp dụng" in r.content.decode()
    qt.refresh_from_db()
    assert qt.trang_thai == TT.DANG_AP_DUNG                              # GET không làm thay đổi gì
    r = client_ql.post(reverse("quy_tac_ngung", args=[qt.id]))
    assert r.status_code == 302
    qt.refresh_from_db()
    assert qt.trang_thai == TT.NGUNG_AP_DUNG and qt.ngay_ket_thuc == hom_nay
    assert NhatKyThayDoi.objects.get().hanh_dong == "NGUNG_AP_DUNG"


def test_e3_ngung_quy_tac_tuong_lai_khong_loi_rang_buoc(client_ql, dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, bat_dau=hom_nay + timedelta(days=30))
    assert client_ql.post(reverse("quy_tac_ngung", args=[qt.id])).status_code == 302
    qt.refresh_from_db()
    assert qt.trang_thai == TT.NGUNG_AP_DUNG and qt.ngay_ket_thuc == qt.ngay_bat_dau


def test_khong_sua_hoac_ngung_lai_quy_tac_da_ngung(client_ql, dm, tao_quy_tac, hom_nay):
    qt = tao_quy_tac(dm.nm, bat_dau=hom_nay - timedelta(days=9), ket_thuc=hom_nay - timedelta(days=1),
                     trang_thai=TT.NGUNG_AP_DUNG)
    for ten in ("quy_tac_sua", "quy_tac_ngung"):
        r = client_ql.get(reverse(ten, args=[qt.id]), follow=True)
        assert r.redirect_chain and "ngừng áp dụng" in r.content.decode()
    r = client_ql.post(reverse("quy_tac_sua", args=[qt.id]), du_lieu(dm, hom_nay, gia_co_so="1"))
    assert r.status_code == 302
    r = client_ql.post(reverse("quy_tac_ngung", args=[qt.id]))
    assert r.status_code == 302
    qt.refresh_from_db()
    assert qt.gia_co_so == 450_000 and NhatKyThayDoi.objects.count() == 0


def test_e5_nut_huy_la_lien_ket_ve_danh_sach_va_khong_luu(client_ql, dm):
    r = client_ql.get(reverse("quy_tac_them"))
    html = r.content.decode()
    assert f'href="{reverse("quan_ly_gia_ve")}?the=gia-ve"' in html and ">Hủy<" in html
    assert QuyTacGia.objects.count() == 0 and NhatKyThayDoi.objects.count() == 0
