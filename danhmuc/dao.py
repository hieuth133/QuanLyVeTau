"""DAO đọc danh mục: ga, tuyến, loại chỗ, chuyến tàu, ghế."""
from datetime import date, datetime

from django.db.models import Count, Q
from django.utils import timezone

from datve.models import Ve
from giave.dao import QuyTacGiaDAO

from .models import ChuyenTau, GaTau, GheNgoi, LoaiCho, ToaXe, TuyenDuong


def ve_chiem_cho_q(thoi_diem: datetime, tien_to: str = "") -> Q:
    """Điều kiện (trên Ve) cho vé đang chiếm chỗ: đã thanh toán, hoặc đang giữ mà đơn chưa quá hạn."""
    return Q(**{f"{tien_to}trang_thai": Ve.TrangThai.DA_THANH_TOAN}) | Q(**{
        f"{tien_to}trang_thai": Ve.TrangThai.DANG_GIU,
        f"{tien_to}don_dat_cho__thoi_diem_het_han__gt": thoi_diem,
    })


class GaTauDAO:
    @staticmethod
    def lay_danh_sach_ga() -> list[GaTau]:
        return list(GaTau.objects.order_by("ten_ga"))


class TuyenDuongDAO:
    @staticmethod
    def lay_danh_sach() -> list[TuyenDuong]:
        return list(TuyenDuong.objects.select_related("ga_di", "ga_den").order_by("ma_tuyen"))

    @staticmethod
    def lay_theo_id(id: int) -> TuyenDuong:
        return TuyenDuong.objects.get(pk=id)


class LoaiChoDAO:
    @staticmethod
    def lay_danh_sach() -> list[LoaiCho]:
        return list(LoaiCho.objects.order_by("ma_loai"))

    @staticmethod
    def lay_theo_id(id: int) -> LoaiCho:
        return LoaiCho.objects.get(pk=id)


class ChuyenTauDAO:
    @staticmethod
    def _co_ban():
        return ChuyenTau.objects.select_related(
            "lich_trinh__tau", "lich_trinh__tuyen_duong__ga_di", "lich_trinh__tuyen_duong__ga_den")

    @staticmethod
    def tim_chuyen_tau(ga_di_id: int, ga_den_id: int, ngay_di: date) -> list[ChuyenTau]:
        """Chuyến MO_BAN theo ga đi/đến/ngày, còn cách giờ chạy hơn NGUNG_BAN_TRUOC_PHUT.

        Mỗi chuyến có thêm `tong_ghe` và `so_cho_trong` (tính bằng annotate, không truy vấn lặp)."""
        now = timezone.now()
        qs = (ChuyenTauDAO._co_ban()
              .filter(trang_thai=ChuyenTau.TrangThai.MO_BAN,
                      lich_trinh__tuyen_duong__ga_di_id=ga_di_id,
                      lich_trinh__tuyen_duong__ga_den_id=ga_den_id,
                      ngay_khoi_hanh=ngay_di)
              .annotate(
                  tong_ghe=Count("lich_trinh__tau__ds_toa__ds_ghe", distinct=True),
                  so_ve_chiem=Count("ve", filter=ve_chiem_cho_q(now, "ve__"), distinct=True))
              .order_by("lich_trinh__gio_khoi_hanh", "id"))
        ket_qua = []
        for c in qs:
            if now >= c.thoi_diem_ngung_ban:
                continue
            c.so_cho_trong = max(c.tong_ghe - c.so_ve_chiem, 0)
            ket_qua.append(c)
        return ket_qua

    @staticmethod
    def lay_theo_id(id: int) -> ChuyenTau:
        """Ném ChuyenTau.DoesNotExist nếu không có."""
        return ChuyenTauDAO._co_ban().get(pk=id)

    @staticmethod
    def gia_thap_nhat(chuyen: ChuyenTau):
        """Giá cơ sở thấp nhất trong các loại chỗ của đoàn tàu (None nếu chưa có giá nào)."""
        loai_ids = set(ToaXe.objects.filter(tau_id=chuyen.lich_trinh.tau_id).values_list("loai_cho_id", flat=True))
        gia = []
        for loai_id in loai_ids:
            qt = QuyTacGiaDAO.tim_gia_ap_dung(chuyen.lich_trinh.tuyen_duong_id, loai_id, chuyen.ngay_khoi_hanh)
            if qt:
                gia.append(qt.gia_co_so)
        return min(gia) if gia else None

    @staticmethod
    def danh_sach_mo_ban_tu(hom_nay: date) -> list[ChuyenTau]:
        return list(ChuyenTauDAO._co_ban()
                    .filter(trang_thai=ChuyenTau.TrangThai.MO_BAN, ngay_khoi_hanh__gte=hom_nay)
                    .order_by("ngay_khoi_hanh", "lich_trinh__gio_khoi_hanh", "id"))


def _khoa_so_ghe(so_ghe: str):
    return (0, int(so_ghe), "") if so_ghe.isdigit() else (1, 0, so_ghe)


class GheNgoiDAO:
    @staticmethod
    def lay_ds_toa(chuyen_id: int) -> list[ToaXe]:
        """Các toa của đoàn tàu, mỗi toa có thêm tong_ghe, so_cho_trong, gia_co_so (None nếu chưa có giá)."""
        chuyen = ChuyenTauDAO.lay_theo_id(chuyen_id)
        now = timezone.now()
        ds_toa = list(ToaXe.objects.filter(tau_id=chuyen.lich_trinh.tau_id)
                      .select_related("loai_cho").annotate(tong_ghe=Count("ds_ghe")).order_by("so_toa"))
        da_chiem = dict(
            Ve.objects.filter(chuyen_tau_id=chuyen_id).filter(ve_chiem_cho_q(now))
            .values("ghe_ngoi__toa_xe_id").annotate(n=Count("id")).values_list("ghe_ngoi__toa_xe_id", "n"))
        tuyen_id = chuyen.lich_trinh.tuyen_duong_id
        gia_theo_loai: dict[int, object] = {}
        for toa in ds_toa:
            toa.so_cho_trong = max(toa.tong_ghe - da_chiem.get(toa.id, 0), 0)
            if toa.loai_cho_id not in gia_theo_loai:
                qt = QuyTacGiaDAO.tim_gia_ap_dung(tuyen_id, toa.loai_cho_id, chuyen.ngay_khoi_hanh)
                gia_theo_loai[toa.loai_cho_id] = qt.gia_co_so if qt else None
            toa.gia_co_so = gia_theo_loai[toa.loai_cho_id]
        return ds_toa

    @staticmethod
    def lay_so_do_cho(chuyen_id: int, toa_id: int) -> list[dict]:
        """Mỗi ghế của toa một dict {ghe_id, so_ghe, trang_thai, gia}.

        trang_thai: TRONG | DANG_GIU | DA_BAN. Vé DANG_GIU của đơn đã quá hạn được coi là TRONG.
        gia là None nếu toa chưa có giá (ghế bị vô hiệu hóa trên giao diện)."""
        chuyen = ChuyenTauDAO.lay_theo_id(chuyen_id)
        toa = ToaXe.objects.get(pk=toa_id, tau_id=chuyen.lich_trinh.tau_id)
        qt = QuyTacGiaDAO.tim_gia_ap_dung(chuyen.lich_trinh.tuyen_duong_id, toa.loai_cho_id, chuyen.ngay_khoi_hanh)
        gia = qt.gia_co_so if qt else None
        chiem = dict(
            Ve.objects.filter(chuyen_tau_id=chuyen_id, ghe_ngoi__toa_xe_id=toa_id)
            .filter(ve_chiem_cho_q(timezone.now())).values_list("ghe_ngoi_id", "trang_thai"))
        ket_qua = []
        for g in sorted(GheNgoi.objects.filter(toa_xe_id=toa_id), key=lambda g: _khoa_so_ghe(g.so_ghe)):
            tt_ve = chiem.get(g.id)
            if tt_ve == Ve.TrangThai.DA_THANH_TOAN:
                trang_thai = "DA_BAN"
            elif tt_ve == Ve.TrangThai.DANG_GIU:
                trang_thai = "DANG_GIU"
            else:
                trang_thai = "TRONG"
            ket_qua.append({"ghe_id": g.id, "so_ghe": g.so_ghe, "trang_thai": trang_thai, "gia": gia})
        return ket_qua

    @staticmethod
    def lay_theo_ids(chuyen_id: int, ds_ghe_id: list[int]) -> list[GheNgoi]:
        """Các ghế thuộc đoàn tàu của chuyến (bỏ qua id lạ), sắp theo toa rồi số ghế."""
        chuyen = ChuyenTauDAO.lay_theo_id(chuyen_id)
        ghe = GheNgoi.objects.select_related("toa_xe__loai_cho").filter(
            id__in=ds_ghe_id, toa_xe__tau_id=chuyen.lich_trinh.tau_id)
        return sorted(ghe, key=lambda g: (g.toa_xe.so_toa, _khoa_so_ghe(g.so_ghe)))

    @staticmethod
    def lay_ghe_dang_chiem(chuyen_id: int, ds_ghe_id: list[int]) -> list[int]:
        """Ghế (trong danh sách) đang có vé chiếm chỗ, không tính vé của đơn đã quá hạn."""
        return list(Ve.objects.filter(chuyen_tau_id=chuyen_id, ghe_ngoi_id__in=ds_ghe_id)
                    .filter(ve_chiem_cho_q(timezone.now())).values_list("ghe_ngoi_id", flat=True))

    @staticmethod
    def khoa_va_kiem_tra(chuyen_id: int, ds_ghe_id: list[int]) -> list[int]:
        """Khóa hàng các ghế (SELECT ... FOR UPDATE, theo thứ tự id để tránh deadlock) và trả về
        danh sách ghế đã có vé còn hiệu lực. Phải gọi bên trong transaction.atomic()."""
        chuyen = ChuyenTau.objects.select_related("lich_trinh").get(id=chuyen_id)
        # of=("self",): chỉ khóa dòng ghế, không khóa dòng toa xe (join) để ghế khác nhau cùng toa không chờ nhau
        ghe = list(GheNgoi.objects.select_for_update(of=("self",))
                   .filter(id__in=ds_ghe_id, toa_xe__tau_id=chuyen.lich_trinh.tau_id)
                   .order_by("id"))
        if len(ghe) != len(set(ds_ghe_id)):
            raise ValueError("Ghế không thuộc đoàn tàu của chuyến")
        return list(Ve.objects.filter(chuyen_tau_id=chuyen_id, ghe_ngoi_id__in=ds_ghe_id,
                                      trang_thai__in=Ve.CON_HIEU_LUC)
                    .values_list("ghe_ngoi_id", flat=True))
