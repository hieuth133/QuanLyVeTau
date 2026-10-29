"""View của UC02 – Đặt vé (giữ chỗ). Khách hàng không cần đăng nhập."""
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from danhmuc.dao import ChuyenTauDAO, GheNgoiDAO
from danhmuc.models import ChuyenTau
from giave.dao import QuyTacGiaDAO

from .dao import DonDatChoDAO
from .exceptions import (ChoDaBiGiu, ChuyenKhongMoBan, DonKhongThanhToanDuoc, KhongCoGia, KhuyenMaiHetLuot,
                         LoiNghiepVu, MaKhuyenMaiKhongHopLe)
from .forms import HanhKhachFormSet, ThongTinDatVeForm, TimChuyenForm
from .models import DonDatCho
from .services import DatVeService, TinhGiaService, giai_phong_va_thong_bao

PREFIX = "hk"


def _lay_chuyen(chuyen_id: int) -> ChuyenTau:
    try:
        return ChuyenTauDAO.lay_theo_id(chuyen_id)
    except ChuyenTau.DoesNotExist:
        raise Http404("Không tìm thấy chuyến tàu")


def _con_mo_ban(chuyen: ChuyenTau) -> bool:
    return chuyen.trang_thai == ChuyenTau.TrangThai.MO_BAN and timezone.now() < chuyen.thoi_diem_ngung_ban


def _url_tim_chuyen(chuyen: ChuyenTau | None = None, **tham_so) -> str:
    if chuyen is not None:
        tuyen = chuyen.lich_trinh.tuyen_duong
        tham_so = {"ga_di": tuyen.ga_di_id, "ga_den": tuyen.ga_den_id,
                   "ngay_di": chuyen.ngay_khoi_hanh.isoformat(), "so_hanh_khach": 1, **tham_so}
    url = reverse("tim_chuyen")
    return f"{url}?{urlencode(tham_so)}" if tham_so else url


def _url_chon_cho(chuyen_id: int, toa_id: int | None = None) -> str:
    url = reverse("chon_cho", args=[chuyen_id])
    return f"{url}?toa={toa_id}" if toa_id else url


def _doc_ds_ghe(du_lieu) -> list[int]:
    """Danh sách id ghế từ tham số `ghe` (bỏ giá trị lỗi, bỏ trùng, giữ thứ tự)."""
    ket_qua: list[int] = []
    for g in du_lieu.getlist("ghe"):
        try:
            gid = int(g)
        except (TypeError, ValueError):
            continue
        if gid not in ket_qua:
            ket_qua.append(gid)
    return ket_qua


def _thong_tin_ghe(ghe, gia_co_so=None) -> dict:
    return {"id": ghe.id, "so_ghe": ghe.so_ghe, "so_toa": ghe.toa_xe.so_toa,
            "loai_cho": ghe.toa_xe.loai_cho.ten_loai, "gia_co_so": gia_co_so}


class TimChuyenView(View):
    """Bước 1-2 và A1: tìm chuyến theo ga đi, ga đến, ngày đi, số hành khách."""

    template_name = "dat_ve/gd_tim_chuyen.html"

    def get(self, request):
        co_tham_so = any(k in request.GET for k in ("ga_di", "ga_den", "ngay_di", "so_hanh_khach"))
        ctx = {"buoc": 1, "da_tim": False, "ds_chuyen": [], "goi_y": []}
        if not co_tham_so:
            ctx["form"] = TimChuyenForm(initial={"ngay_di": timezone.localdate() + timedelta(days=1),
                                                 "so_hanh_khach": 1})
            return render(request, self.template_name, ctx)

        form = TimChuyenForm(request.GET)
        ctx["form"] = form
        if form.is_valid():
            cd = form.cleaned_data
            ds = ChuyenTauDAO.tim_chuyen_tau(cd["ga_di"].id, cd["ga_den"].id, cd["ngay_di"])
            for c in ds:
                c.gia_thap_nhat = ChuyenTauDAO.gia_thap_nhat(c)
                c.du_cho = c.so_cho_trong >= cd["so_hanh_khach"]
            ctx.update(da_tim=True, ds_chuyen=ds, so_hanh_khach=cd["so_hanh_khach"], ngay_di=cd["ngay_di"],
                       ga_di=cd["ga_di"], ga_den=cd["ga_den"])
            if not ds:
                ctx["goi_y"] = self._goi_y_ngay_lan_can(cd)
        return render(request, self.template_name, ctx)

    @staticmethod
    def _goi_y_ngay_lan_can(cd, tam: int = 7, toi_da: int = 6) -> list[dict]:
        """A1: gợi ý các ngày lân cận có chuyến (liên kết bấm được)."""
        hom_nay = timezone.localdate()
        ket_qua = []
        for delta in range(1, tam + 1):
            for huong in (-1, 1):
                try:
                    ngay = cd["ngay_di"] + timedelta(days=huong * delta)
                except OverflowError:  # ngày sát giới hạn của date: bỏ qua
                    continue
                if ngay < hom_nay:
                    continue
                ds = ChuyenTauDAO.tim_chuyen_tau(cd["ga_di"].id, cd["ga_den"].id, ngay)
                if ds:
                    ket_qua.append({
                        "ngay": ngay, "so_chuyen": len(ds),
                        "url": _url_tim_chuyen(ga_di=cd["ga_di"].id, ga_den=cd["ga_den"].id,
                                               ngay_di=ngay.isoformat(), so_hanh_khach=cd["so_hanh_khach"]),
                    })
        ket_qua.sort(key=lambda g: g["ngay"])
        return ket_qua[:toi_da]


class ChonChoView(View):
    """Bước 3-4 và A2: danh sách toa và sơ đồ chỗ."""

    template_name = "dat_ve/gd_chon_cho.html"

    def get(self, request, chuyen_id):
        chuyen = _lay_chuyen(chuyen_id)
        if not _con_mo_ban(chuyen):
            messages.error(request, "Chuyến tàu này đã ngừng bán hoặc không còn mở bán.")
            return redirect(_url_tim_chuyen(chuyen))
        ds_toa = GheNgoiDAO.lay_ds_toa(chuyen_id)
        tong_trong = sum(t.so_cho_trong for t in ds_toa)
        if not ds_toa or tong_trong == 0:  # A2
            messages.warning(request, "Chuyến tàu này đã hết chỗ. Vui lòng chọn chuyến hoặc ngày khác.")
            return redirect(_url_tim_chuyen(chuyen))

        try:
            toa_chon = int(request.GET.get("toa", ""))
        except ValueError:
            toa_chon = None
        if toa_chon not in {t.id for t in ds_toa}:
            toa_chon = next((t.id for t in ds_toa if t.so_cho_trong > 0 and t.gia_co_so is not None), ds_toa[0].id)
        for toa in ds_toa:
            toa.so_do = GheNgoiDAO.lay_so_do_cho(chuyen_id, toa.id)
            toa.cot = toa.loai_cho.so_cot_ghe
        try:
            so_hk = int(request.GET.get("so_hanh_khach", ""))
        except ValueError:
            so_hk = None
        return render(request, self.template_name, {
            "buoc": 2, "chuyen": chuyen, "ds_toa": ds_toa, "toa_chon": toa_chon, "tong_trong": tong_trong,
            "max_cho": settings.MAX_CHO_MOI_DON, "so_hanh_khach": so_hk,
            "url_tim": _url_tim_chuyen(chuyen, **({"so_hanh_khach": so_hk} if so_hk else {})),
        })


class _ThongTinMixin:
    """Dùng chung giữa ThongTinHanhKhachView và GiuChoView."""

    template_name = "dat_ve/gd_thong_tin_hanh_khach.html"

    @staticmethod
    def _ngu_canh(chuyen, form, formset, ds_ghe_id, **them):
        """Gắn thông tin ghế vào từng form hành khách và tính tạm tính giá cơ sở."""
        ghe_map = {g.id: g for g in GheNgoiDAO.lay_theo_ids(chuyen.id, ds_ghe_id)}
        tam_tinh = 0
        gia_theo_loai: dict[int, object] = {}
        for f, gid in zip(formset.forms, ds_ghe_id):
            ghe = ghe_map.get(gid)
            if ghe is None:
                f.ghe_info = None
                continue
            loai_id = ghe.toa_xe.loai_cho_id
            if loai_id not in gia_theo_loai:
                qt = QuyTacGiaDAO.tim_gia_ap_dung(chuyen.lich_trinh.tuyen_duong_id, loai_id, chuyen.ngay_khoi_hanh)
                gia_theo_loai[loai_id] = qt.gia_co_so if qt else None
            f.ghe_info = _thong_tin_ghe(ghe, gia_theo_loai[loai_id])
            tam_tinh += gia_theo_loai[loai_id] or 0
        ctx = {"buoc": 3, "chuyen": chuyen, "form": form, "formset": formset, "tam_tinh": tam_tinh,
               "max_cho": settings.MAX_CHO_MOI_DON, "ds_ghe_id": ds_ghe_id}
        ctx.update(them)
        return ctx


class ThongTinHanhKhachView(_ThongTinMixin, View):
    """Bước 5-6 và A3: biểu mẫu thông tin người đặt và từng hành khách."""

    def get(self, request, chuyen_id):
        chuyen = _lay_chuyen(chuyen_id)
        if not _con_mo_ban(chuyen):
            messages.error(request, "Chuyến tàu này đã ngừng bán hoặc không còn mở bán.")
            return redirect(_url_tim_chuyen(chuyen))
        ds_ghe_id = _doc_ds_ghe(request.GET)
        if not ds_ghe_id:
            messages.error(request, "Vui lòng chọn ít nhất một chỗ.")
            return redirect(_url_chon_cho(chuyen_id))
        if len(ds_ghe_id) > settings.MAX_CHO_MOI_DON:  # A3 (kiểm tra lại ở server)
            messages.error(request, f"Mỗi đơn chỉ được đặt tối đa {settings.MAX_CHO_MOI_DON} chỗ.")
            return redirect(_url_chon_cho(chuyen_id))
        ghe = GheNgoiDAO.lay_theo_ids(chuyen_id, ds_ghe_id)
        if len(ghe) != len(ds_ghe_id):
            messages.error(request, "Có chỗ không thuộc chuyến tàu này. Vui lòng chọn lại.")
            return redirect(_url_chon_cho(chuyen_id))
        da_chiem = set(GheNgoiDAO.lay_ghe_dang_chiem(chuyen_id, ds_ghe_id))
        if da_chiem:
            ten = ", ".join(f"toa {g.toa_xe.so_toa} ghế {g.so_ghe}" for g in ghe if g.id in da_chiem)
            messages.error(request, f"Chỗ vừa được người khác giữ hoặc mua: {ten}. Vui lòng chọn chỗ khác.")
            return redirect(_url_chon_cho(chuyen_id, ghe[0].toa_xe_id))

        # Thông tin đã nhập trước đó (lưu tạm khi gặp xung đột chỗ – A6)
        tam = request.session.pop("thong_tin_tam", None)
        if tam and tam.get("chuyen_id") != chuyen_id:
            tam = None
        initial_nguoi = tam["nguoi_dat"] if tam else {}
        if tam and tam.get("ma_km"):
            initial_nguoi = {**initial_nguoi, "ma_khuyen_mai": tam["ma_km"]}
        initial_hk = []
        sau = (tam or {}).get("hanh_khach", [])
        for i, gid in enumerate(ds_ghe_id):
            d = {"ghe_id": gid}
            if i < len(sau):
                d.update(sau[i])
            initial_hk.append(d)
        form = ThongTinDatVeForm(initial=initial_nguoi)
        formset = HanhKhachFormSet(initial=initial_hk, prefix=PREFIX)
        return render(request, self.template_name, self._ngu_canh(chuyen, form, formset, ds_ghe_id))


class GiuChoView(_ThongTinMixin, View):
    """Bước 7-11, A4, A5, A6: kiểm tra dữ liệu, tính giá và giữ chỗ."""

    def post(self, request, chuyen_id):
        chuyen = _lay_chuyen(chuyen_id)
        du_lieu = request.POST.copy()
        bo_ma = "bo_ma" in request.POST  # nút "Tiếp tục không dùng mã" (A5)
        if bo_ma:
            du_lieu["ma_khuyen_mai"] = ""
        form = ThongTinDatVeForm(du_lieu)
        formset = HanhKhachFormSet(du_lieu, prefix=PREFIX)
        ds_ghe_id = self._ghe_tu_formset(formset)

        # Bước 8: kiểm tra hợp lệ (A4) – lỗi gắn đúng trường, giữ dữ liệu đã nhập
        if not (form.is_valid() & formset.is_valid()):
            return render(request, self.template_name, self._ngu_canh(chuyen, form, formset, ds_ghe_id))

        ma_km = form.cleaned_data["ma_khuyen_mai"] or None
        ds_cho = [{"ghe_id": f.cleaned_data["ghe_id"], "ho_ten": f.cleaned_data["ho_ten"],
                   "doi_tuong": f.cleaned_data["doi_tuong"], "so_giay_to": f.cleaned_data["so_giay_to"]}
                  for f in formset.forms]
        nguoi_dat = {k: form.cleaned_data[k] for k in ("ho_ten", "so_dien_thoai", "email")}
        ds_ghe_id = [c["ghe_id"] for c in ds_cho]

        try:
            don = DatVeService.giu_cho(chuyen_id, ds_cho, nguoi_dat, ma_km)
        except ChoDaBiGiu as e:  # A6
            return self._xu_ly_xung_dot(request, chuyen, e, ds_cho, nguoi_dat, ma_km)
        except (MaKhuyenMaiKhongHopLe, KhuyenMaiHetLuot) as e:  # A5
            return self._xu_ly_ma_km(request, chuyen, form, formset, ds_ghe_id, ds_cho, e, ma_km)
        except ChuyenKhongMoBan:
            messages.error(request, "Chuyến tàu không còn mở bán (đã ngừng bán hoặc sắp khởi hành).")
            return redirect(_url_tim_chuyen(chuyen))
        except KhongCoGia:
            messages.error(request, "Chuyến chưa có giá cho loại chỗ này. Vui lòng chọn chỗ khác hoặc liên hệ quản lý.")
            return redirect(_url_chon_cho(chuyen_id))
        except (LoiNghiepVu, ValueError) as e:
            messages.error(request, f"Không thể giữ chỗ: {e}")
            return redirect(_url_chon_cho(chuyen_id))
        except DatabaseError:
            messages.error(request, "Không thể giữ chỗ do lỗi hệ thống tạm thời. Vui lòng thử lại.")
            return redirect(_url_chon_cho(chuyen_id))

        cua_toi = list(request.session.get("don_cua_toi", []))
        cua_toi.append(don.ma_dat_cho)
        request.session["don_cua_toi"] = cua_toi
        if ma_km and not any(v.khuyen_mai and v.khuyen_mai.ma_khuyen_mai == ma_km
                             for v in DonDatChoDAO.lay_ds_ve(don)):
            messages.warning(request, f"Mã {ma_km} hợp lệ nhưng không áp dụng được cho hành khách nào trong đơn "
                                      "(ví dụ sai đối tượng hoặc đã có khuyến mãi khác lợi hơn).")
        messages.success(request, "Giữ chỗ thành công. Vui lòng thanh toán trước khi hết thời gian giữ chỗ.")
        return redirect("ket_qua", ma_dat_cho=don.ma_dat_cho)

    @staticmethod
    def _ghe_tu_formset(formset) -> list[int]:
        ket_qua = []
        for f in formset.forms:
            try:
                ket_qua.append(int(f["ghe_id"].value()))
            except (TypeError, ValueError):
                ket_qua.append(0)
        return ket_qua

    def _xu_ly_xung_dot(self, request, chuyen, loi, ds_cho, nguoi_dat, ma_km):
        """A6: về sơ đồ chỗ của toa, báo ghế bị mất, lưu thông tin hành khách để điền lại."""
        request.session["thong_tin_tam"] = {
            "chuyen_id": chuyen.id,
            "nguoi_dat": nguoi_dat,
            "ma_km": ma_km or "",
            "hanh_khach": [{k: c[k] for k in ("ho_ten", "doi_tuong", "so_giay_to")} for c in ds_cho],
        }
        mat = GheNgoiDAO.lay_theo_ids(chuyen.id, loi.ds_ghe_id)
        if mat:
            ten = ", ".join(f"ghế {g.so_ghe} (toa {g.toa_xe.so_toa})" for g in mat)
            messages.error(request, f"Rất tiếc, {len(mat)} chỗ vừa được người khác giữ hoặc mua: {ten}. "
                                    "Vui lòng chọn chỗ khác; thông tin hành khách đã nhập được giữ lại.")
        else:
            messages.error(request, "Một số chỗ vừa được người khác giữ hoặc mua. Vui lòng chọn lại.")
        return redirect(_url_chon_cho(chuyen.id, mat[0].toa_xe_id if mat else None))

    def _xu_ly_ma_km(self, request, chuyen, form, formset, ds_ghe_id, ds_cho, loi, ma_km):
        """A5: lỗi gắn vào ô mã, hiển thị giá khi không dùng mã, kèm nút "Tiếp tục không dùng mã"."""
        if isinstance(loi, MaKhuyenMaiKhongHopLe):
            thong_bao = (f"Mã khuyến mãi “{loi.ma}” không tồn tại, đã hết hạn, hết lượt hoặc không đủ điều kiện "
                         "áp dụng cho chuyến này.")
        else:
            thong_bao = "Khuyến mãi vừa hết lượt sử dụng."
        if ma_km:
            form.add_error("ma_khuyen_mai", thong_bao)
        else:
            form.add_error(None, thong_bao)
        bang_gia, tong = [], 0
        try:
            ghe_map = {g.id: g for g in GheNgoiDAO.lay_theo_ids(chuyen.id, ds_ghe_id)}
            for c in ds_cho:
                ve = TinhGiaService.tinh_gia_ve(chuyen, ghe_map[c["ghe_id"]], c["doi_tuong"], None)
                bang_gia.append({"ghe": ghe_map[c["ghe_id"]], "ho_ten": c["ho_ten"], "ve": ve})
                tong += ve.gia_ve
        except (LoiNghiepVu, KeyError):
            bang_gia, tong = [], 0
        ctx = self._ngu_canh(chuyen, form, formset, ds_ghe_id, loi_ma_km=True, bang_gia_khong_ma=bang_gia,
                             tong_khong_ma=tong)
        return render(request, self.template_name, ctx)

    def get(self, request, chuyen_id):
        return redirect(_url_chon_cho(chuyen_id))


class KetQuaGiuChoView(View):
    """Bước 11-12 và A7: mã đặt chỗ, chi tiết vé, đồng hồ đếm ngược."""

    template_name = "dat_ve/gd_ket_qua_giu_cho.html"

    def get(self, request, ma_dat_cho):
        don = _lay_don_cua_toi(request, ma_dat_cho)
        now = timezone.now()
        if don.trang_thai == DonDatCho.TrangThai.DANG_GIU and don.thoi_diem_het_han <= now:
            giai_phong_va_thong_bao(don)  # A7: giải phóng ngay khi người dùng xem trang
            don = DonDatChoDAO.lay_theo_ma(ma_dat_cho)
        ds_ve = DonDatChoDAO.lay_ds_ve(don)
        con_lai = 0
        if don.trang_thai == DonDatCho.TrangThai.DANG_GIU:
            con_lai = max(0, int((don.thoi_diem_het_han - now).total_seconds()))
        chuyen = ds_ve[0].chuyen_tau if ds_ve else None
        return render(request, self.template_name, {
            "buoc": 4, "don": don, "ds_ve": ds_ve, "chuyen": chuyen, "con_lai_giay": con_lai,
            "tong_giam": sum(v.so_tien_giam for v in ds_ve),
            "tong_co_so": sum(v.gia_co_so for v in ds_ve),
        })


class ThanhToanGiaLapView(View):
    """Chỉ phục vụ demo, thay cho UC03: đổi trạng thái đơn sang đã thanh toán."""

    def post(self, request, ma_dat_cho):
        _lay_don_cua_toi(request, ma_dat_cho)
        try:
            DatVeService.thanh_toan_gia_lap(ma_dat_cho)
        except DonKhongThanhToanDuoc as e:
            messages.error(request, str(e))
            try:
                giai_phong_va_thong_bao(DonDatChoDAO.lay_theo_ma(ma_dat_cho))
            except DonDatCho.DoesNotExist:
                pass
        else:
            messages.success(request, "Thanh toán (giả lập) thành công. Các chỗ đã chuyển sang trạng thái đã bán.")
        return redirect("ket_qua", ma_dat_cho=ma_dat_cho)


def _lay_don_cua_toi(request, ma_dat_cho: str) -> DonDatCho:
    """Chỉ cho xem đơn do chính trình duyệt này vừa đặt (mã nằm trong session)."""
    if ma_dat_cho not in request.session.get("don_cua_toi", []):
        raise PermissionDenied("Bạn không có quyền xem đơn đặt chỗ này.")
    try:
        return DonDatChoDAO.lay_theo_ma(ma_dat_cho)
    except DonDatCho.DoesNotExist:
        raise Http404("Không tìm thấy đơn đặt chỗ")
