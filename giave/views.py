"""View của UC14 – Quản lý giá vé và khuyến mãi (chỉ vai trò Quản lý)."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from danhmuc.dao import LoaiChoDAO, TuyenDuongDAO
from taikhoan.mixins import VaiTroRequiredMixin
from taikhoan.models import ThanhVien

from .dao import KhuyenMaiDAO, NhatKyDAO, QuyTacGiaDAO
from .forms import KhuyenMaiForm, QuyTacGiaForm
from .models import KhuyenMai, NhatKyThayDoi, QuyTacGia

HD = NhatKyThayDoi.HanhDong


def _int_hoac_none(gia_tri):
    try:
        return int(gia_tri) if gia_tri not in (None, "") else None
    except (TypeError, ValueError):
        return None


def url_danh_sach(the: str = "gia-ve") -> str:
    return reverse("quan_ly_gia_ve") + f"?the={the}"


class QuanLyBaseView(LoginRequiredMixin, VaiTroRequiredMixin, View):
    vai_tro_cho_phep = [ThanhVien.VaiTro.QUAN_LY]


class QuanLyGiaVeView(QuanLyBaseView):
    """Bước 1-2, A3-A4, B3-B4: giao diện hai thẻ Giá vé / Khuyến mãi kèm bộ lọc."""

    template_name = "quan_ly/gd_quan_ly_gia_ve.html"

    def get(self, request):
        the = request.GET.get("the", "gia-ve")
        if the not in ("gia-ve", "khuyen-mai"):
            the = "gia-ve"
        tuyen_id = _int_hoac_none(request.GET.get("tuyen"))
        loai_cho_id = _int_hoac_none(request.GET.get("loai_cho"))
        trang_thai = request.GET.get("trang_thai") or None
        ctx = {
            "the": the,
            "ds_tuyen": TuyenDuongDAO.lay_danh_sach(),
            "ds_loai_cho": LoaiChoDAO.lay_danh_sach(),
            "loc_tuyen": tuyen_id,
            "loc_loai_cho": loai_cho_id,
            "loc_trang_thai": trang_thai or "",
        }
        if the == "gia-ve":
            if trang_thai not in QuyTacGia.TrangThai.values:
                trang_thai = None
                ctx["loc_trang_thai"] = ""
            ctx["ds_quy_tac"] = QuyTacGiaDAO.tim_quy_tac_gia(tuyen_id, loai_cho_id, trang_thai)
            ctx["ds_trang_thai"] = QuyTacGia.TrangThai.choices
        else:
            if trang_thai not in KhuyenMai.TrangThai.values:
                trang_thai = None
                ctx["loc_trang_thai"] = ""
            ctx["ds_khuyen_mai"] = KhuyenMaiDAO.tim_khuyen_mai(trang_thai)
            ctx["ds_trang_thai"] = KhuyenMai.TrangThai.choices
            ctx["hom_nay"] = timezone.localdate()
        return render(request, self.template_name, ctx)


class QuyTacGiaView(QuanLyBaseView):
    """Thêm / sửa quy tắc giá (A5-A9, E1, E2, E4)."""

    template_name = "quan_ly/gd_quy_tac_gia.html"

    def _lay(self, id):
        if id is None:
            return None
        try:
            return QuyTacGiaDAO.lay_theo_id(id)
        except QuyTacGia.DoesNotExist:
            raise Http404("Không tìm thấy quy tắc giá")

    def _ve_trang(self, request, form, goc, da_dung, trung=None, status=200):
        return render(request, self.template_name, {
            "form": form, "qt": goc, "da_dung": da_dung, "trung": trung or [],
            "url_huy": url_danh_sach("gia-ve"),
        }, status=status)

    def get(self, request, id=None):
        goc = self._lay(id)
        if goc and goc.trang_thai == QuyTacGia.TrangThai.NGUNG_AP_DUNG:
            messages.error(request, "Quy tắc đã ngừng áp dụng nên không thể sửa. Hãy thêm quy tắc mới.")
            return redirect(url_danh_sach("gia-ve"))
        da_dung = bool(goc and QuyTacGiaDAO.da_duoc_su_dung(goc.id))
        return self._ve_trang(request, QuyTacGiaForm(instance=goc), goc, da_dung)

    def post(self, request, id=None):
        goc = self._lay(id)
        if goc and goc.trang_thai == QuyTacGia.TrangThai.NGUNG_AP_DUNG:
            messages.error(request, "Quy tắc đã ngừng áp dụng nên không thể sửa. Hãy thêm quy tắc mới.")
            return redirect(url_danh_sach("gia-ve"))
        hom_nay = timezone.localdate()
        goc_id = goc.id if goc else None
        da_dung = bool(goc and QuyTacGiaDAO.da_duoc_su_dung(goc_id))
        gia_tri_cu = NhatKyDAO.chup(goc) if goc else None

        form = QuyTacGiaForm(request.POST, instance=goc, hom_nay=hom_nay)
        # Bước 1: kiểm tra hợp lệ (E1)
        if not form.is_valid():
            return self._ve_trang(request, form, goc, da_dung)

        # Bước 2: dựng đối tượng từ form (chưa lưu)
        qt = form.save(commit=False)
        if goc is None:
            qt.nguoi_tao = request.user
        if da_dung:
            # E4: phiên bản mới có hiệu lực từ thời điểm lưu
            qt.ngay_bat_dau = max(hom_nay, qt.ngay_bat_dau)
            if qt.ngay_ket_thuc and qt.ngay_ket_thuc < qt.ngay_bat_dau:
                form.add_error("ngay_ket_thuc",
                               f"Quy tắc mới có hiệu lực từ {qt.ngay_bat_dau:%d/%m/%Y} nên ngày kết thúc "
                               "không được trước ngày đó.")
                return self._ve_trang(request, form, goc, da_dung)

        # Bước 3: kiểm tra trùng thời gian áp dụng (E2) – loại trừ chính quy tắc đang sửa
        trung = QuyTacGiaDAO.tim_quy_tac_trung(qt)
        if trung:
            form.add_error(None, "Thời gian áp dụng bị trùng với quy tắc đang áp dụng khác. "
                                 "Hãy điều chỉnh khoảng thời gian hoặc hủy thao tác.")
            return self._ve_trang(request, form, goc, da_dung, trung)

        # Bước 4-5: lưu + ghi nhật ký trong một giao dịch
        try:
            with transaction.atomic():
                if goc is None:
                    QuyTacGiaDAO.luu(qt)
                    NhatKyDAO.ghi(HD.THEM, "QuyTacGia", qt.pk, None, NhatKyDAO.chup(qt), request.user)
                elif not da_dung:
                    QuyTacGiaDAO.luu(qt)
                    NhatKyDAO.ghi(HD.SUA, "QuyTacGia", qt.pk, gia_tri_cu, NhatKyDAO.chup(qt), request.user)
                else:
                    QuyTacGiaDAO.ket_thuc(goc_id, hom_nay)
                    NhatKyDAO.ghi(HD.NGUNG_AP_DUNG, "QuyTacGia", goc_id, gia_tri_cu,
                                  NhatKyDAO.chup(QuyTacGiaDAO.lay_theo_id(goc_id)), request.user)
                    qt.pk = None
                    qt.id = None
                    qt._state.adding = True
                    qt.trang_thai = QuyTacGia.TrangThai.DANG_AP_DUNG
                    qt.nguoi_tao = request.user
                    QuyTacGiaDAO.luu(qt)
                    NhatKyDAO.ghi(HD.THEM, "QuyTacGia", qt.pk, None, NhatKyDAO.chup(qt), request.user)
        except IntegrityError as e:
            if "ex_quy_tac_khong_trung" not in str(e):
                raise
            qt.pk = qt.id = goc_id
            qt._state.adding = goc_id is None
            form.add_error(None, "Thời gian áp dụng bị trùng với quy tắc đang áp dụng khác "
                                 "(vừa được thêm bởi người khác). Hãy điều chỉnh khoảng thời gian.")
            return self._ve_trang(request, form, goc, da_dung, QuyTacGiaDAO.tim_quy_tac_trung(qt))

        if da_dung:
            messages.success(request, "Lưu thành công. Quy tắc cũ đã được kết thúc và tạo phiên bản mới "
                                      "(các vé đã giữ/đã bán giữ nguyên giá).")
        else:
            messages.success(request, "Lưu thành công")
        return redirect(url_danh_sach("gia-ve"))


class NgungApDungView(QuanLyBaseView):
    """E3: ngừng áp dụng quy tắc giá (GET: trang xác nhận, POST: thực hiện)."""

    template_name = "quan_ly/gd_xac_nhan.html"

    def _lay(self, request, id):
        try:
            qt = QuyTacGiaDAO.lay_theo_id(id)
        except QuyTacGia.DoesNotExist:
            raise Http404("Không tìm thấy quy tắc giá")
        if qt.trang_thai == QuyTacGia.TrangThai.NGUNG_AP_DUNG:
            messages.error(request, "Quy tắc này đã ngừng áp dụng trước đó.")
            return None
        return qt

    def get(self, request, id):
        qt = self._lay(request, id)
        if qt is None:
            return redirect(url_danh_sach("gia-ve"))
        return render(request, self.template_name, {
            "tieu_de": "Ngừng áp dụng quy tắc giá",
            "dong": [
                ("Tuyến", qt.tuyen_duong), ("Loại chỗ", qt.loai_cho),
                ("Loại thời điểm", qt.get_loai_thoi_diem_display()), ("Giá cơ sở", qt.gia_co_so),
                ("Hiệu lực từ", qt.ngay_bat_dau), ("Đến", qt.ngay_ket_thuc or "Không giới hạn"),
            ],
            "la_gia": True,
            "da_dung": QuyTacGiaDAO.da_duoc_su_dung(qt.id),
            "thong_diep": "Quy tắc sẽ chuyển sang trạng thái “Ngừng áp dụng” và ngày kết thúc được đặt là hôm nay. "
                          "Quy tắc không bị xóa; các vé đã giữ hoặc đã bán không bị ảnh hưởng.",
            "nut": "Xác nhận ngừng áp dụng",
            "url_huy": url_danh_sach("gia-ve"),
        })

    def post(self, request, id):
        qt = self._lay(request, id)
        if qt is None:
            return redirect(url_danh_sach("gia-ve"))
        cu = NhatKyDAO.chup(qt)
        with transaction.atomic():
            da_ngung = QuyTacGiaDAO.ket_thuc(qt.id, timezone.localdate())
            if da_ngung:
                NhatKyDAO.ghi(HD.NGUNG_AP_DUNG, "QuyTacGia", qt.id, cu,
                              NhatKyDAO.chup(QuyTacGiaDAO.lay_theo_id(qt.id)), request.user)
        if da_ngung:
            messages.success(request, "Đã ngừng áp dụng quy tắc giá.")
        else:
            messages.warning(request, "Quy tắc này vừa được ngừng áp dụng bởi người khác; không có thay đổi nào.")
        return redirect(url_danh_sach("gia-ve"))


class KhuyenMaiView(QuanLyBaseView):
    """Thêm / sửa khuyến mãi (B5-B9, E1)."""

    template_name = "quan_ly/gd_khuyen_mai.html"

    def _lay(self, id):
        if id is None:
            return None
        try:
            return KhuyenMaiDAO.lay_theo_id(id)
        except KhuyenMai.DoesNotExist:
            raise Http404("Không tìm thấy khuyến mãi")

    def _ve_trang(self, request, form, km):
        return render(request, self.template_name, {"form": form, "km": km, "url_huy": url_danh_sach("khuyen-mai")})

    def _chan_neu_ket_thuc(self, request, km):
        if km and km.trang_thai_hien_thi() == KhuyenMai.TrangThai.DA_KET_THUC:
            messages.error(request, "Chương trình khuyến mãi đã kết thúc nên không thể sửa. Hãy tạo chương trình mới.")
            return redirect(url_danh_sach("khuyen-mai"))
        return None

    def get(self, request, id=None):
        km = self._lay(id)
        chan = self._chan_neu_ket_thuc(request, km)
        if chan:
            return chan
        return self._ve_trang(request, KhuyenMaiForm(instance=km), km)

    def post(self, request, id=None):
        km_goc = self._lay(id)
        chan = self._chan_neu_ket_thuc(request, km_goc)
        if chan:
            return chan
        gia_tri_cu = NhatKyDAO.chup(km_goc) if km_goc else None
        form = KhuyenMaiForm(request.POST, instance=km_goc)
        if not form.is_valid():
            return self._ve_trang(request, form, km_goc)
        km = form.save(commit=False)
        try:
            with transaction.atomic():
                KhuyenMaiDAO.luu(km)
                NhatKyDAO.ghi(HD.SUA if km_goc else HD.THEM, "KhuyenMai", km.pk, gia_tri_cu,
                              NhatKyDAO.chup(km), request.user)
        except IntegrityError as e:
            if "ma_khuyen_mai" not in str(e):
                raise
            form.add_error("ma_khuyen_mai", "Mã khuyến mãi này đã tồn tại.")
            return self._ve_trang(request, form, km_goc)
        messages.success(request, "Lưu thành công")
        return redirect(url_danh_sach("khuyen-mai"))


class KetThucKhuyenMaiView(QuanLyBaseView):
    """E3: kết thúc chương trình khuyến mãi (GET: trang xác nhận, POST: thực hiện)."""

    template_name = "quan_ly/gd_xac_nhan.html"

    def _lay(self, request, id):
        try:
            km = KhuyenMaiDAO.lay_theo_id(id)
        except KhuyenMai.DoesNotExist:
            raise Http404("Không tìm thấy khuyến mãi")
        if km.trang_thai_hien_thi() == KhuyenMai.TrangThai.DA_KET_THUC:
            messages.error(request, "Chương trình khuyến mãi này đã kết thúc trước đó.")
            return None
        return km

    def get(self, request, id):
        km = self._lay(request, id)
        if km is None:
            return redirect(url_danh_sach("khuyen-mai"))
        return render(request, self.template_name, {
            "tieu_de": "Kết thúc chương trình khuyến mãi",
            "dong": [
                ("Mã", km.ma_khuyen_mai), ("Tên", km.ten), ("Hiệu lực từ", km.ngay_bat_dau),
                ("Đến", km.ngay_ket_thuc), ("Số lượt đã dùng", km.so_luot_da_dung),
            ],
            "thong_diep": "Chương trình sẽ kết thúc ngay và không áp dụng cho các đơn đặt chỗ mới. "
                          "Các vé đã giữ hoặc đã bán giữ nguyên số tiền giảm đã chốt.",
            "nut": "Xác nhận kết thúc",
            "url_huy": url_danh_sach("khuyen-mai"),
        })

    def post(self, request, id):
        km = self._lay(request, id)
        if km is None:
            return redirect(url_danh_sach("khuyen-mai"))
        cu = NhatKyDAO.chup(km)
        with transaction.atomic():
            da_ket_thuc = KhuyenMaiDAO.ket_thuc(km.id, timezone.localdate())
            if da_ket_thuc:
                NhatKyDAO.ghi(HD.KET_THUC, "KhuyenMai", km.id, cu,
                              NhatKyDAO.chup(KhuyenMaiDAO.lay_theo_id(km.id)), request.user)
        if da_ket_thuc:
            messages.success(request, "Đã kết thúc chương trình khuyến mãi.")
        else:
            messages.warning(request, "Chương trình này vừa được kết thúc bởi người khác; không có thay đổi nào.")
        return redirect(url_danh_sach("khuyen-mai"))
