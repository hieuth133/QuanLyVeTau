"""Đặt đồng thời: nhiều luồng cùng giữ một chỗ, chỉ một luồng thành công (QT01, UC02 bước 10)."""
import threading
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connections

from datve.exceptions import ChoDaBiGiu
from datve.models import DonDatCho, Ve
from datve.services import DatVeService
from tien_ich import cho

pytestmark = pytest.mark.django_db(transaction=True)

SO_LUONG = 5


def _chay_dong_thoi(chuyen_id, ds_cho_theo_luong, nguoi_dat_theo_luong):
    """Chạy len(ds_cho_theo_luong) luồng xuất phát cùng lúc; trả về danh sách (loại, giá trị)."""
    n = len(ds_cho_theo_luong)
    barrier = threading.Barrier(n)
    ket_qua = [None] * n

    def chay(i):
        try:
            connections["default"].ensure_connection()
            barrier.wait(timeout=30)
            try:
                ket_qua[i] = ("OK", DatVeService.giu_cho(chuyen_id, ds_cho_theo_luong[i], nguoi_dat_theo_luong[i], None))
            except ChoDaBiGiu as e:
                ket_qua[i] = ("CHO_DA_BI_GIU", e)
            except Exception as e:  # noqa: BLE001 - ghi lại để assert thất bại có thông tin
                ket_qua[i] = ("LOI", e)
        finally:
            connections.close_all()

    luong = [threading.Thread(target=chay, args=(i,)) for i in range(n)]
    for t in luong:
        t.start()
    for t in luong:
        t.join(timeout=60)
    return ket_qua


def test_nam_luong_cung_giu_mot_ghe_chi_mot_thanh_cong(dm, chuyen):
    ghe = dm.ghe1[0]
    ket_qua = _chay_dong_thoi(
        chuyen.id,
        [[cho(ghe, ho_ten=f"Khách {i}", so_giay_to=f"01234567{i}")] for i in range(SO_LUONG)],
        [{"ho_ten": f"Khách {i}", "so_dien_thoai": f"09000000{i:02d}", "email": ""} for i in range(SO_LUONG)])
    loi = [r for r in ket_qua if r[0] == "LOI"]
    assert not loi, loi
    assert sum(1 for r in ket_qua if r[0] == "OK") == 1
    assert sum(1 for r in ket_qua if r[0] == "CHO_DA_BI_GIU") == SO_LUONG - 1
    # trong tblVe chỉ có 1 vé còn hiệu lực cho ghế đó, và đúng 1 đơn được tạo
    assert Ve.objects.filter(chuyen_tau=chuyen, ghe_ngoi=ghe, trang_thai__in=Ve.CON_HIEU_LUC).count() == 1
    assert Ve.objects.count() == 1 and DonDatCho.objects.count() == 1


def test_hai_luong_chon_cac_ghe_giao_nhau_khong_deadlock_va_khong_ban_trung(dm, chuyen):
    """Luồng A chọn {1,2,3}, luồng B chọn {3,2,1} (thứ tự ngược): khóa theo id nên không deadlock."""
    a, b, c = dm.ghe1[:3]
    ket_qua = _chay_dong_thoi(
        chuyen.id,
        [[cho(a), cho(b, so_giay_to="123456781"), cho(c, so_giay_to="123456782")],
         [cho(c), cho(b, so_giay_to="123456781"), cho(a, so_giay_to="123456782")]],
        [{"ho_ten": "A", "so_dien_thoai": "0911111111", "email": ""},
         {"ho_ten": "B", "so_dien_thoai": "0922222222", "email": ""}])
    loai = sorted(r[0] for r in ket_qua)
    assert loai == ["CHO_DA_BI_GIU", "OK"], ket_qua
    assert Ve.objects.filter(trang_thai__in=Ve.CON_HIEU_LUC).count() == 3


def test_nhieu_luong_cung_so_dien_thoai_khong_loi_khach_hang_trung(dm, chuyen):
    ket_qua = _chay_dong_thoi(
        chuyen.id,
        [[cho(dm.ghe1[i], so_giay_to=f"01234567{i}")] for i in range(4)],
        [{"ho_ten": "Cùng một người", "so_dien_thoai": "0912345678", "email": ""}] * 4)
    assert [r[0] for r in ket_qua] == ["OK"] * 4, ket_qua
    from datve.models import KhachHang
    assert KhachHang.objects.count() == 1 and Ve.objects.count() == 4


def test_lenh_thu_dong_thoi_in_ket_qua(dm, chuyen):
    out = StringIO()
    call_command("thu_dong_thoi", "--so-luong", str(SO_LUONG), "--chuyen", str(chuyen.id),
                 "--ghe", str(dm.ghe1[2].id), stdout=out)
    noi_dung = out.getvalue()
    assert f"{1} thành công, {SO_LUONG - 1} ChoDaBiGiu" in noi_dung
    assert Ve.objects.filter(ghe_ngoi=dm.ghe1[2], trang_thai__in=Ve.CON_HIEU_LUC).count() == 1


def test_lenh_thu_dong_thoi_tu_chon_chuyen_va_ghe(dm, chuyen):
    out = StringIO()
    call_command("thu_dong_thoi", "--so-luong", "3", stdout=out)
    assert "1 thành công, 2 ChoDaBiGiu" in out.getvalue()
    assert Ve.objects.count() == 1
