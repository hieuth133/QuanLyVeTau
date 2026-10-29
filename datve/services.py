"""Nghiệp vụ UC02: tính giá vé và giữ chỗ."""
import logging
import secrets
from collections import Counter
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from danhmuc.dao import ChuyenTauDAO, GheNgoiDAO
from danhmuc.models import ChuyenTau, GheNgoi
from danhmuc.thoi_gian import thoi_diem_ngung_ban
from giave.dao import KhuyenMaiDAO, QuyTacGiaDAO
from giave.models import KhuyenMai

from .dao import DonDatChoDAO, KhachHangDAO
from .exceptions import (ChoDaBiGiu, ChuyenKhongMoBan, DonKhongThanhToanDuoc, KhongCoGia, KhuyenMaiHetLuot,
                         MaKhuyenMaiKhongHopLe)
from .models import DonDatCho, Ve

logger = logging.getLogger(__name__)

NGHIN = Decimal(1000)
BANG_CHU_MA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bỏ các ký tự dễ nhầm 0, O, 1, I


class TinhGiaService:
    @staticmethod
    def tinh_gia_ve(chuyen: ChuyenTau, ghe: GheNgoi, doi_tuong: str, ma_km: str | None,
                    hom_nay: date | None = None, luot_tam: dict[int, int] | None = None) -> Ve:
        """Tính giá một vé (chưa lưu): giá cơ sở theo tuyến/loại chỗ/ngày đi, rồi áp khuyến mãi có lợi nhất.

        luot_tam: số lượt đã gán tạm cho từng khuyến mãi (theo id) bởi các vé trước trong cùng đơn,
        để khuyến mãi còn ít lượt không bị gán cho nhiều vé hơn số lượt còn lại."""
        luot_tam = luot_tam or {}
        hom_nay = hom_nay or timezone.localdate()
        tuyen_id = chuyen.lich_trinh.tuyen_duong_id
        loai_cho_id = ghe.toa_xe.loai_cho_id
        qt = QuyTacGiaDAO.tim_gia_ap_dung(tuyen_id, loai_cho_id, chuyen.ngay_khoi_hanh)
        if qt is None:
            raise KhongCoGia(chuyen.id, loai_cho_id)

        # Gộp khuyến mãi tự động và khuyến mãi theo mã, loại trùng theo id
        ung_vien = {km.id: km for km in KhuyenMaiDAO.tim_khuyen_mai_hieu_luc(tuyen_id, loai_cho_id, hom_nay)}
        ma_km = (ma_km or "").strip().upper()
        if ma_km:
            km_ma = KhuyenMaiDAO.tim_theo_ma(ma_km)
            if km_ma is None or not TinhGiaService._km_con_hieu_luc(km_ma, tuyen_id, loai_cho_id, hom_nay):
                raise MaKhuyenMaiKhongHopLe(ma_km)
            ung_vien[km_ma.id] = km_ma

        tot_nhat, giam_max = None, Decimal(0)
        for km in ung_vien.values():
            if not TinhGiaService._du_dieu_kien(km, doi_tuong, chuyen.ngay_khoi_hanh, hom_nay, luot_tam.get(km.id, 0)):
                continue
            giam = TinhGiaService._so_tien_giam(km, qt.gia_co_so)
            if giam > giam_max:
                tot_nhat, giam_max = km, giam

        return Ve(chuyen_tau=chuyen, ghe_ngoi=ghe, doi_tuong=doi_tuong,
                  gia_co_so=qt.gia_co_so, so_tien_giam=giam_max,
                  gia_ve=qt.gia_co_so - giam_max, quy_tac_gia=qt, khuyen_mai=tot_nhat)

    @staticmethod
    def _km_con_hieu_luc(km: KhuyenMai, tuyen_id: int, loai_cho_id: int, hom_nay: date) -> bool:
        """Như tim_khuyen_mai_hieu_luc nhưng không đòi bat_buoc_nhap_ma = False; thêm kiểm tra còn lượt."""
        if km.trang_thai == KhuyenMai.TrangThai.DA_KET_THUC:
            return False
        if not (km.ngay_bat_dau <= hom_nay <= km.ngay_ket_thuc):
            return False
        if km.tuyen_duong_id is not None and km.tuyen_duong_id != tuyen_id:
            return False
        if km.loai_cho_id is not None and km.loai_cho_id != loai_cho_id:
            return False
        if km.so_luot_toi_da is not None and km.so_luot_da_dung >= km.so_luot_toi_da:
            return False
        return True

    @staticmethod
    def _du_dieu_kien(km: KhuyenMai, doi_tuong: str, ngay_di: date, hom_nay: date, luot_tam: int = 0) -> bool:
        if km.doi_tuong_ap_dung and km.doi_tuong_ap_dung != doi_tuong:
            return False
        if (ngay_di - hom_nay).days < km.so_ngay_dat_truoc:
            return False
        if km.so_luot_toi_da is not None and km.so_luot_da_dung + luot_tam >= km.so_luot_toi_da:
            return False
        return True

    @staticmethod
    def _so_tien_giam(km: KhuyenMai, gia_co_so: Decimal) -> Decimal:
        if km.hinh_thuc_giam == KhuyenMai.HinhThucGiam.PHAN_TRAM:
            giam = gia_co_so * km.gia_tri_giam / 100
        else:
            giam = km.gia_tri_giam
        if km.muc_giam_toi_da is not None:
            giam = min(giam, km.muc_giam_toi_da)
        giam = min(giam, gia_co_so)
        return (giam / NGHIN).to_integral_value(rounding=ROUND_DOWN) * NGHIN  # làm tròn xuống đến nghìn đồng


def sinh_ma_dat_cho() -> str:
    """Mã 8 ký tự từ bảng chữ không có 0, O, 1, I; thử lại khi trùng."""
    while True:
        ma = "".join(secrets.choice(BANG_CHU_MA) for _ in range(8))
        if not DonDatCho.objects.filter(ma_dat_cho=ma).exists():
            return ma


def gui_xac_nhan_giu_cho(ma_dat_cho: str) -> None:
    """Gửi email xác nhận giữ chỗ (console backend khi demo). Lỗi gửi thư không làm hỏng đơn."""
    try:
        don = DonDatChoDAO.lay_theo_ma(ma_dat_cho)
        if not don.khach_hang.email:
            return
        tong = f"{int(don.tong_tien):,}".replace(",", ".")
        han = timezone.localtime(don.thoi_diem_het_han)
        send_mail(
            subject=f"[Bán vé tàu] Xác nhận giữ chỗ {don.ma_dat_cho}",
            message="\n".join([
                f"Xin chào {don.khach_hang.ho_ten},",
                "",
                f"Bạn đã giữ chỗ thành công. Mã đặt chỗ: {don.ma_dat_cho}.",
                f"Tổng tiền: {tong} đ",
                f"Vui lòng thanh toán trước {han:%H:%M:%S %d/%m/%Y}, "
                "sau thời điểm này chỗ sẽ được tự động giải phóng.",
            ]),
            from_email=None,
            recipient_list=[don.khach_hang.email],
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 - thông báo là phụ, không được làm hỏng nghiệp vụ chính
        logger.exception("Không gửi được email xác nhận cho đơn %s", ma_dat_cho)


def gui_thong_bao_het_han(ma_dat_cho: str) -> None:
    """Gửi email báo đơn đã hết hạn giữ chỗ (UC02-A7). Console backend khi demo; lỗi gửi không ảnh hưởng nghiệp vụ."""
    try:
        don = DonDatChoDAO.lay_theo_ma(ma_dat_cho)
        if not don.khach_hang.email:
            return
        send_mail(
            subject=f"[Bán vé tàu] Đơn {don.ma_dat_cho} đã hết hạn giữ chỗ",
            message="\n".join([
                f"Xin chào {don.khach_hang.ho_ten},",
                "",
                f"Đơn đặt chỗ {don.ma_dat_cho} chưa được thanh toán trong thời gian giữ chỗ nên đã hết hạn.",
                "Các chỗ đã được giải phóng. Bạn có thể đặt vé lại trên hệ thống.",
            ]),
            from_email=None,
            recipient_list=[don.khach_hang.email],
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Không gửi được thông báo hết hạn cho đơn %s", ma_dat_cho)


def giai_phong_va_thong_bao(don: DonDatCho) -> bool:
    """Giải phóng một đơn hết hạn (DAO) rồi gửi thông báo cho khách sau khi giao dịch commit.

    Mọi nơi giải phóng đơn (tác vụ nền, bước đầu của giu_cho, các View) đều đi qua hàm này;
    DAO không gửi mail."""
    ma = don.ma_dat_cho
    if DonDatChoDAO.giai_phong(don):
        transaction.on_commit(lambda: gui_thong_bao_het_han(ma))
        return True
    return False


class DatVeService:
    @staticmethod
    def giu_cho(chuyen_id: int, ds_cho: list[dict], nguoi_dat: dict, ma_km: str | None) -> DonDatCho:
        """ds_cho: [{"ghe_id", "ho_ten", "doi_tuong", "so_giay_to"}, ...]
        nguoi_dat: {"ho_ten", "so_dien_thoai", "email"}"""
        if not 1 <= len(ds_cho) <= settings.MAX_CHO_MOI_DON:
            raise ValueError("Số chỗ không hợp lệ")
        ds_ghe_id = [c["ghe_id"] for c in ds_cho]
        if len(set(ds_ghe_id)) != len(ds_ghe_id):
            raise ValueError("Một chỗ không được chọn nhiều lần trong cùng một đơn")
        for c in ds_cho:
            if c.get("doi_tuong") not in Ve.DoiTuong.values:
                raise ValueError("Đối tượng hành khách không hợp lệ")
        try:
            chuyen = ChuyenTauDAO.lay_theo_id(chuyen_id)
        except ChuyenTau.DoesNotExist:
            raise ChuyenKhongMoBan(chuyen_id)
        het_han_ban = thoi_diem_ngung_ban(chuyen)
        if chuyen.trang_thai != ChuyenTau.TrangThai.MO_BAN or timezone.now() >= het_han_ban:
            raise ChuyenKhongMoBan(chuyen_id)

        # Kiểm tra ghế thuộc đoàn tàu của chuyến trước khi tính giá (tránh KeyError / ghế lạ)
        ghe_map = {g.id: g for g in GheNgoi.objects.select_related("toa_xe")
                   .filter(id__in=ds_ghe_id, toa_xe__tau_id=chuyen.lich_trinh.tau_id)}
        if len(ghe_map) != len(ds_ghe_id):
            raise ValueError("Ghế không thuộc đoàn tàu của chuyến")

        # Bước 4-9: tính giá trước khi mở giao dịch (theo Hình 2.16)
        ds_ve = []
        luot_tam: dict[int, int] = {}
        for c in ds_cho:
            ve = TinhGiaService.tinh_gia_ve(chuyen, ghe_map[c["ghe_id"]], c["doi_tuong"], ma_km, luot_tam=luot_tam)
            ve.ho_ten_hanh_khach, ve.so_giay_to = c["ho_ten"], c["so_giay_to"]
            if ve.khuyen_mai_id:
                luot_tam[ve.khuyen_mai_id] = luot_tam.get(ve.khuyen_mai_id, 0) + 1
            ds_ve.append(ve)

        try:
            with transaction.atomic():
                # Giải phóng đơn đã hết hạn của chuyến này để chỉ mục duy nhất không chặn nhầm
                for don_cu in DonDatChoDAO.tim_don_het_han(timezone.now(), chuyen_id):
                    giai_phong_va_thong_bao(don_cu)
                bi_giu = GheNgoiDAO.khoa_va_kiem_tra(chuyen_id, ds_ghe_id)
                if bi_giu:
                    raise ChoDaBiGiu(bi_giu)  # luồng A6
                kh = KhachHangDAO.tim_hoac_tao(
                    nguoi_dat["ho_ten"], nguoi_dat["so_dien_thoai"], nguoi_dat.get("email", ""))
                don = DonDatCho(
                    ma_dat_cho=sinh_ma_dat_cho(), khach_hang=kh,
                    thoi_diem_het_han=min(timezone.now() + timedelta(minutes=settings.GIU_CHO_PHUT), het_han_ban),
                    tong_tien=sum((v.gia_ve for v in ds_ve), Decimal(0)))
                DonDatChoDAO.tao_don(don, ds_ve)
                dem_km = Counter(v.khuyen_mai_id for v in ds_ve if v.khuyen_mai_id)
                for km_id, so_luot in sorted(dem_km.items()):  # thứ tự khóa dòng KM cố định, tránh deadlock
                    if not KhuyenMaiDAO.tang_luot_dung(km_id, so_luot):
                        raise KhuyenMaiHetLuot(km_id)
        except IntegrityError as e:
            # Lưới an toàn: chỉ mục uq_ve_cho_con_hieu_luc chặn trường hợp lọt qua bước khóa
            if "uq_ve_cho_con_hieu_luc" not in str(e):
                raise
            raise ChoDaBiGiu(ds_ghe_id)
        transaction.on_commit(lambda: gui_xac_nhan_giu_cho(don.ma_dat_cho))
        return don

    @staticmethod
    def thanh_toan_gia_lap(ma_dat_cho: str) -> DonDatCho:
        """Thanh toán giả lập (thay cho UC03): chỉ khi đơn còn DANG_GIU và chưa hết hạn."""
        with transaction.atomic():
            try:
                don = DonDatCho.objects.select_for_update().get(ma_dat_cho=ma_dat_cho)
            except DonDatCho.DoesNotExist:
                raise DonKhongThanhToanDuoc("Không tìm thấy đơn đặt chỗ.")
            if don.trang_thai != DonDatCho.TrangThai.DANG_GIU:
                raise DonKhongThanhToanDuoc("Đơn không còn ở trạng thái đang giữ chỗ nên không thể thanh toán.")
            if don.thoi_diem_het_han <= timezone.now():
                raise DonKhongThanhToanDuoc("Đơn đã hết thời gian giữ chỗ.")
            don.ds_ve.filter(trang_thai=Ve.TrangThai.DANG_GIU).update(trang_thai=Ve.TrangThai.DA_THANH_TOAN)
            don.trang_thai = DonDatCho.TrangThai.DA_THANH_TOAN
            don.save(update_fields=["trang_thai"])
        return don
