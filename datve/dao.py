"""DAO của UC02: khách hàng và đơn đặt chỗ."""
from collections import Counter
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from giave.dao import KhuyenMaiDAO

from .models import DonDatCho, KhachHang, Ve


class KhachHangDAO:
    @staticmethod
    def tim_hoac_tao(ho_ten: str, so_dien_thoai: str, email: str = "") -> KhachHang:
        """Tìm khách theo số điện thoại (tạo nếu chưa có) và cập nhật họ tên, email."""
        email = email or ""
        kh, tao_moi = KhachHang.objects.get_or_create(
            so_dien_thoai=so_dien_thoai, defaults={"ho_ten": ho_ten, "email": email})
        if not tao_moi and (kh.ho_ten != ho_ten or kh.email != email):
            kh.ho_ten, kh.email = ho_ten, email
            kh.save(update_fields=["ho_ten", "email"])
        return kh


class DonDatChoDAO:
    @staticmethod
    def tao_don(don: DonDatCho, ds_ve: list[Ve]) -> DonDatCho:
        don.save()
        for ve in ds_ve:
            ve.don_dat_cho = don
            ve.save()
        return don

    @staticmethod
    def lay_theo_ma(ma: str) -> DonDatCho:
        """Ném DonDatCho.DoesNotExist nếu không có."""
        return DonDatCho.objects.select_related("khach_hang").get(ma_dat_cho=ma)

    @staticmethod
    def lay_ds_ve(don: DonDatCho) -> list[Ve]:
        return list(don.ds_ve.select_related(
            "ghe_ngoi__toa_xe__loai_cho", "khuyen_mai", "chuyen_tau__lich_trinh__tuyen_duong__ga_di",
            "chuyen_tau__lich_trinh__tuyen_duong__ga_den", "chuyen_tau__lich_trinh__tau",
        ).order_by("ghe_ngoi__toa_xe__so_toa", "ghe_ngoi_id"))

    @staticmethod
    def tim_don_het_han(thoi_diem: datetime, chuyen_id: int | None = None) -> list[DonDatCho]:
        qs = DonDatCho.objects.filter(trang_thai=DonDatCho.TrangThai.DANG_GIU, thoi_diem_het_han__lte=thoi_diem)
        if chuyen_id is not None:
            qs = qs.filter(ds_ve__chuyen_tau_id=chuyen_id).distinct()
        return list(qs.order_by("id"))

    @staticmethod
    def giai_phong(don: DonDatCho) -> bool:
        """Khóa dòng đơn, kiểm tra lại còn DANG_GIU và đã quá hạn; đơn -> HET_HAN, vé -> DA_HUY,
        hoàn lượt khuyến mãi. Trả về True nếu đã giải phóng."""
        with transaction.atomic():
            d = DonDatCho.objects.select_for_update().get(pk=don.pk)
            if d.trang_thai != DonDatCho.TrangThai.DANG_GIU or d.thoi_diem_het_han > timezone.now():
                return False
            ve_dang_giu = list(d.ds_ve.filter(trang_thai=Ve.TrangThai.DANG_GIU))
            dem_km = Counter(v.khuyen_mai_id for v in ve_dang_giu if v.khuyen_mai_id)
            d.ds_ve.filter(trang_thai=Ve.TrangThai.DANG_GIU).update(trang_thai=Ve.TrangThai.DA_HUY)
            d.trang_thai = DonDatCho.TrangThai.HET_HAN
            d.save(update_fields=["trang_thai"])
            for km_id, so_luot in dem_km.items():
                KhuyenMaiDAO.hoan_luot_dung(km_id, so_luot)
        don.trang_thai = DonDatCho.TrangThai.HET_HAN
        return True
