from datetime import date

from django import forms
from django.utils import timezone

from datve.models import Ve

from .dao import KhuyenMaiDAO
from .models import KhuyenMai, QuyTacGia


def _date_widget():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class QuyTacGiaForm(forms.ModelForm):
    """Biểu mẫu quy tắc giá (bước A6-A8 của UC14). Lỗi gắn vào đúng trường (luồng E1)."""

    class Meta:
        model = QuyTacGia
        fields = ["tuyen_duong", "loai_cho", "gia_co_so", "loai_thoi_diem", "ngay_bat_dau", "ngay_ket_thuc", "ghi_chu"]
        widgets = {
            "ngay_bat_dau": _date_widget(),
            "ngay_ket_thuc": _date_widget(),
            "ghi_chu": forms.TextInput(),
        }

    def __init__(self, *args, hom_nay: date | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hom_nay = hom_nay or timezone.localdate()
        self.fields["tuyen_duong"].empty_label = "— Chọn tuyến —"
        self.fields["loai_cho"].empty_label = "— Chọn loại chỗ —"
        self.fields["loai_thoi_diem"].choices = [("", "— Chọn loại thời điểm —")] + list(
            QuyTacGia.LoaiThoiDiem.choices)
        self.fields["ngay_ket_thuc"].help_text = "Để trống nếu áp dụng không giới hạn thời gian."

    def clean(self):
        cleaned = super().clean()
        gia = cleaned.get("gia_co_so")
        bd, kt = cleaned.get("ngay_bat_dau"), cleaned.get("ngay_ket_thuc")
        if gia is not None and gia <= 0:
            self.add_error("gia_co_so", "Giá cơ sở phải lớn hơn 0.")
        if bd and kt and kt < bd:
            self.add_error("ngay_ket_thuc", "Ngày kết thúc không được trước ngày bắt đầu.")
        if bd and self.instance.pk is None and bd < self.hom_nay:
            self.add_error("ngay_bat_dau", "Ngày bắt đầu không được ở quá khứ.")
        return cleaned


class KhuyenMaiForm(forms.ModelForm):
    """Biểu mẫu khuyến mãi (bước B6-B8 của UC14)."""

    doi_tuong_ap_dung = forms.ChoiceField(
        label="Đối tượng áp dụng", required=False,
        choices=[("", "Mọi đối tượng")] + list(Ve.DoiTuong.choices))

    class Meta:
        model = KhuyenMai
        exclude = ["so_luot_da_dung", "trang_thai"]
        widgets = {
            "ngay_bat_dau": _date_widget(),
            "ngay_ket_thuc": _date_widget(),
            "ma_khuyen_mai": forms.TextInput(attrs={"style": "text-transform:uppercase"}),
        }

    def __init__(self, *args, hom_nay: date | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hom_nay = hom_nay or timezone.localdate()
        self.fields["tuyen_duong"].empty_label = "Tất cả tuyến"
        self.fields["loai_cho"].empty_label = "Tất cả loại chỗ"
        self.fields["hinh_thuc_giam"].choices = [("", "— Chọn hình thức —")] + list(KhuyenMai.HinhThucGiam.choices)
        self.fields["gia_tri_giam"].help_text = "Phần trăm (0-100) hoặc số tiền (đ) tùy hình thức giảm."
        self.fields["muc_giam_toi_da"].help_text = "Để trống nếu không giới hạn."
        self.fields["so_luot_toi_da"].help_text = "Để trống nếu không giới hạn số lượt."
        self.fields["bat_buoc_nhap_ma"].help_text = (
            "Bật: chỉ áp dụng khi khách nhập mã. Tắt: tự động áp dụng cho vé đủ điều kiện.")

    def clean_ma_khuyen_mai(self):
        ma = "".join(self.cleaned_data["ma_khuyen_mai"].split()).upper()
        if not ma:
            raise forms.ValidationError("Vui lòng nhập mã khuyến mãi.")
        if KhuyenMaiDAO.ton_tai_ma(ma, self.instance.pk):
            raise forms.ValidationError("Mã khuyến mãi này đã tồn tại.")
        return ma

    def clean_doi_tuong_ap_dung(self):
        dt = self.cleaned_data.get("doi_tuong_ap_dung", "")
        if dt and dt not in Ve.DoiTuong.values:
            raise forms.ValidationError("Đối tượng áp dụng không hợp lệ.")
        return dt

    def clean(self):
        cleaned = super().clean()
        hinh_thuc, gia_tri = cleaned.get("hinh_thuc_giam"), cleaned.get("gia_tri_giam")
        bd, kt = cleaned.get("ngay_bat_dau"), cleaned.get("ngay_ket_thuc")
        toi_da, luot = cleaned.get("muc_giam_toi_da"), cleaned.get("so_luot_toi_da")
        if gia_tri is not None:
            if gia_tri <= 0:
                self.add_error("gia_tri_giam", "Giá trị giảm phải lớn hơn 0.")
            elif hinh_thuc == KhuyenMai.HinhThucGiam.PHAN_TRAM and gia_tri > 100:
                self.add_error("gia_tri_giam", "Tỷ lệ giảm phải nằm trong khoảng 0-100%.")
        if bd and kt and kt < bd:
            self.add_error("ngay_ket_thuc", "Ngày kết thúc không được trước ngày bắt đầu.")
        elif kt and self.instance.pk is None and kt < self.hom_nay:
            self.add_error("ngay_ket_thuc", "Ngày kết thúc không được ở quá khứ.")
        if toi_da is not None and toi_da <= 0:
            self.add_error("muc_giam_toi_da", "Mức giảm tối đa phải lớn hơn 0.")
        if luot is not None:
            if luot <= 0:
                self.add_error("so_luot_toi_da", "Số lượt tối đa phải lớn hơn 0.")
            elif self.instance.pk and luot < self.instance.so_luot_da_dung:
                self.add_error("so_luot_toi_da",
                               f"Số lượt tối đa không được nhỏ hơn số lượt đã dùng ({self.instance.so_luot_da_dung}).")
        return cleaned
