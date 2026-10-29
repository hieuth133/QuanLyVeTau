"""DAO của UC14: nơi duy nhất truy vấn CSDL cho quy tắc giá, khuyến mãi và nhật ký."""
from datetime import date

from django.db.models import Exists, F, OuterRef, Q, Value
from django.db.models.functions import Greatest
from django.forms.models import model_to_dict
from django.utils import timezone

from datve.models import Ve

from .models import KhuyenMai, NhatKyThayDoi, QuyTacGia


class QuyTacGiaDAO:
    @staticmethod
    def tim_quy_tac_gia(tuyen_id: int | None = None, loai_cho_id: int | None = None,
                        trang_thai: str | None = None) -> list[QuyTacGia]:
        qs = QuyTacGia.objects.select_related("tuyen_duong", "loai_cho", "nguoi_tao").annotate(
            da_dung=Exists(Ve.objects.filter(quy_tac_gia_id=OuterRef("pk")))
        )
        if tuyen_id:
            qs = qs.filter(tuyen_duong_id=tuyen_id)
        if loai_cho_id:
            qs = qs.filter(loai_cho_id=loai_cho_id)
        if trang_thai:
            qs = qs.filter(trang_thai=trang_thai)
        return list(qs.order_by("tuyen_duong__ma_tuyen", "loai_cho__ma_loai", "loai_thoi_diem", "-ngay_bat_dau", "-id"))

    @staticmethod
    def lay_theo_id(id: int) -> QuyTacGia:
        return QuyTacGia.objects.select_related("tuyen_duong", "loai_cho").get(pk=id)

    @staticmethod
    def tim_quy_tac_trung(qt: QuyTacGia) -> list[QuyTacGia]:
        """Quy tắc DANG_AP_DUNG khác `qt`, cùng tuyến/loại chỗ/loại thời điểm, có khoảng ngày giao nhau."""
        qs = QuyTacGia.objects.filter(
            trang_thai=QuyTacGia.TrangThai.DANG_AP_DUNG,
            tuyen_duong_id=qt.tuyen_duong_id,
            loai_cho_id=qt.loai_cho_id,
            loai_thoi_diem=qt.loai_thoi_diem,
        ).filter(Q(ngay_ket_thuc__isnull=True) | Q(ngay_ket_thuc__gte=qt.ngay_bat_dau))
        if qt.ngay_ket_thuc is not None:
            qs = qs.filter(ngay_bat_dau__lte=qt.ngay_ket_thuc)
        if qt.pk:
            qs = qs.exclude(pk=qt.pk)
        return list(qs.select_related("tuyen_duong", "loai_cho").order_by("ngay_bat_dau", "id"))

    @staticmethod
    def da_duoc_su_dung(id: int) -> bool:
        return Ve.objects.filter(quy_tac_gia_id=id).exists()

    @staticmethod
    def luu(qt: QuyTacGia) -> QuyTacGia:
        qt.save()
        return qt

    @staticmethod
    def ket_thuc(id: int, ngay: date) -> bool:
        """Chuyển sang NGUNG_AP_DUNG và đặt ngày kết thúc.

        ngay_ket_thuc = max(ngay, ngay_bat_dau) để không vi phạm ck_qtg_khoang_ngay khi quy tắc
        bắt đầu ở tương lai; nếu ngày kết thúc hiện có đã sớm hơn thì giữ nguyên."""
        try:
            qt = QuyTacGia.objects.get(pk=id)
        except QuyTacGia.DoesNotExist:
            return False
        if qt.trang_thai == QuyTacGia.TrangThai.NGUNG_AP_DUNG:
            return False
        ngay_kt = ngay
        if qt.ngay_ket_thuc is not None and qt.ngay_ket_thuc < ngay_kt:
            ngay_kt = qt.ngay_ket_thuc
        ngay_kt = max(ngay_kt, qt.ngay_bat_dau)
        QuyTacGia.objects.filter(pk=id).update(
            trang_thai=QuyTacGia.TrangThai.NGUNG_AP_DUNG, ngay_ket_thuc=ngay_kt)
        return True

    @staticmethod
    def tim_gia_ap_dung(tuyen_id: int, loai_cho_id: int, ngay_di: date) -> QuyTacGia | None:
        """Chọn quy tắc theo thứ tự ưu tiên: LE_TET, rồi CUOI_TUAN (thứ Bảy/Chủ nhật), rồi NGAY_THUONG."""
        qs = QuyTacGia.objects.filter(
            tuyen_duong_id=tuyen_id, loai_cho_id=loai_cho_id,
            trang_thai=QuyTacGia.TrangThai.DANG_AP_DUNG, ngay_bat_dau__lte=ngay_di,
        ).filter(Q(ngay_ket_thuc__isnull=True) | Q(ngay_ket_thuc__gte=ngay_di)).order_by("ngay_bat_dau", "id")
        theo_loai = {q.loai_thoi_diem: q for q in qs}
        thu_tu = [QuyTacGia.LoaiThoiDiem.LE_TET]
        if ngay_di.weekday() >= 5:
            thu_tu.append(QuyTacGia.LoaiThoiDiem.CUOI_TUAN)
        thu_tu.append(QuyTacGia.LoaiThoiDiem.NGAY_THUONG)
        for loai in thu_tu:
            if loai in theo_loai:
                return theo_loai[loai]
        return None


class KhuyenMaiDAO:
    @staticmethod
    def lay_theo_id(id: int) -> KhuyenMai:
        return KhuyenMai.objects.select_related("tuyen_duong", "loai_cho").get(pk=id)

    @staticmethod
    def tim_khuyen_mai(trang_thai: str | None = None, hom_nay: date | None = None) -> list[KhuyenMai]:
        """Lọc theo trạng thái suy ra từ ngày (sắp / đang / đã kết thúc)."""
        hom_nay = hom_nay or timezone.localdate()
        KM = KhuyenMai
        qs = KM.objects.select_related("tuyen_duong", "loai_cho")
        chua_ket_thuc = ~Q(trang_thai=KM.TrangThai.DA_KET_THUC)
        if trang_thai == KM.TrangThai.SAP_AP_DUNG:
            qs = qs.filter(chua_ket_thuc, ngay_bat_dau__gt=hom_nay)
        elif trang_thai == KM.TrangThai.DANG_AP_DUNG:
            qs = qs.filter(chua_ket_thuc, ngay_bat_dau__lte=hom_nay, ngay_ket_thuc__gte=hom_nay)
        elif trang_thai == KM.TrangThai.DA_KET_THUC:
            qs = qs.filter(Q(trang_thai=KM.TrangThai.DA_KET_THUC) | Q(ngay_ket_thuc__lt=hom_nay))
        return list(qs.order_by("-ngay_bat_dau", "-id"))

    @staticmethod
    def ton_tai_ma(ma: str, bo_qua_id: int | None = None) -> bool:
        qs = KhuyenMai.objects.filter(ma_khuyen_mai__iexact=ma)
        if bo_qua_id:
            qs = qs.exclude(pk=bo_qua_id)
        return qs.exists()

    @staticmethod
    def luu(km: KhuyenMai) -> KhuyenMai:
        km.save()
        return km

    @staticmethod
    def ket_thuc(id: int, ngay: date) -> bool:
        try:
            km = KhuyenMai.objects.get(pk=id)
        except KhuyenMai.DoesNotExist:
            return False
        if km.trang_thai == KhuyenMai.TrangThai.DA_KET_THUC:
            return False
        ngay_kt = min(km.ngay_ket_thuc, ngay)
        ngay_kt = max(ngay_kt, km.ngay_bat_dau)
        KhuyenMai.objects.filter(pk=id).update(
            trang_thai=KhuyenMai.TrangThai.DA_KET_THUC, ngay_ket_thuc=ngay_kt)
        return True

    @staticmethod
    def tim_khuyen_mai_hieu_luc(tuyen_id: int, loai_cho_id: int, ngay: date) -> list[KhuyenMai]:
        """Khuyến mãi tự động (không bắt buộc nhập mã) đang hiệu lực vào `ngay` (ngày đặt vé)."""
        return list(
            KhuyenMai.objects.exclude(trang_thai=KhuyenMai.TrangThai.DA_KET_THUC)
            .filter(ngay_bat_dau__lte=ngay, ngay_ket_thuc__gte=ngay, bat_buoc_nhap_ma=False)
            .filter(Q(tuyen_duong__isnull=True) | Q(tuyen_duong_id=tuyen_id))
            .filter(Q(loai_cho__isnull=True) | Q(loai_cho_id=loai_cho_id))
            .order_by("id")
        )

    @staticmethod
    def tim_theo_ma(ma: str) -> KhuyenMai | None:
        return KhuyenMai.objects.filter(ma_khuyen_mai__iexact=ma.strip()).first()

    @staticmethod
    def tang_luot_dung(id: int, so_luot: int) -> bool:
        """Cập nhật có điều kiện trong một câu lệnh (an toàn khi đặt đồng thời)."""
        updated = (KhuyenMai.objects
                   .filter(id=id)
                   .filter(Q(so_luot_toi_da__isnull=True) | Q(so_luot_da_dung__lte=F("so_luot_toi_da") - so_luot))
                   .update(so_luot_da_dung=F("so_luot_da_dung") + so_luot))
        return updated == 1

    @staticmethod
    def hoan_luot_dung(id: int, so_luot: int) -> None:
        KhuyenMai.objects.filter(id=id).update(
            so_luot_da_dung=Greatest(F("so_luot_da_dung") - so_luot, Value(0)))


class NhatKyDAO:
    @staticmethod
    def ghi_nhat_ky(nk: NhatKyThayDoi) -> bool:
        nk.save()
        return nk.pk is not None

    @staticmethod
    def chup(obj) -> dict:
        """Ảnh chụp giá trị của đối tượng (model_to_dict + id) để ghi vào nhật ký."""
        d = model_to_dict(obj)
        d["id"] = obj.pk
        return d

    @staticmethod
    def ghi(hanh_dong: str, loai: str, doi_tuong_id: int, gia_tri_cu: dict | None, gia_tri_moi: dict, nguoi) -> bool:
        return NhatKyDAO.ghi_nhat_ky(NhatKyThayDoi(
            hanh_dong=hanh_dong, loai_doi_tuong=loai, doi_tuong_id=doi_tuong_id,
            gia_tri_cu=gia_tri_cu, gia_tri_moi=gia_tri_moi, nguoi_thuc_hien=nguoi))
