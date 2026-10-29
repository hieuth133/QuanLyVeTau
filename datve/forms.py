import re
from datetime import date, timedelta

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from danhmuc.models import GaTau

from .models import Ve

SDT_RE = re.compile(r"^0\d{9}$")
GIAY_TO_RE = re.compile(r"^[A-Za-z0-9]{6,20}$")
NGAY_TOI_DA_TIM = 365  # chỉ cho tìm chuyến trong vòng 1 năm tới


class TimChuyenForm(forms.Form):
    """Bước 2: ga đi, ga đến, ngày đi, số hành khách."""

    ga_di = forms.ModelChoiceField(GaTau.objects.none(), label="Ga đi", empty_label="— Chọn ga đi —")
    ga_den = forms.ModelChoiceField(GaTau.objects.none(), label="Ga đến", empty_label="— Chọn ga đến —")
    ngay_di = forms.DateField(label="Ngày đi", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    so_hanh_khach = forms.IntegerField(label="Số hành khách", min_value=1, initial=1)

    def __init__(self, *args, hom_nay: date | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hom_nay = hom_nay or timezone.localdate()
        ga = GaTau.objects.order_by("ten_ga")
        self.fields["ga_di"].queryset = ga
        self.fields["ga_den"].queryset = ga
        self.fields["so_hanh_khach"].max_value = settings.MAX_CHO_MOI_DON
        self.fields["so_hanh_khach"].widget.attrs.update({"min": 1, "max": settings.MAX_CHO_MOI_DON})
        self.fields["ngay_di"].widget.attrs["min"] = self.hom_nay.isoformat()

    def clean(self):
        cleaned = super().clean()
        di, den, ngay = cleaned.get("ga_di"), cleaned.get("ga_den"), cleaned.get("ngay_di")
        if di and den and di == den:
            self.add_error("ga_den", "Ga đến phải khác ga đi.")
        if ngay and ngay < self.hom_nay:
            self.add_error("ngay_di", "Ngày đi không được ở quá khứ.")
        elif ngay and ngay > self.hom_nay + timedelta(days=NGAY_TOI_DA_TIM):
            self.add_error("ngay_di", "Chỉ tìm được chuyến trong vòng 1 năm tới.")
        so = cleaned.get("so_hanh_khach")
        if so and so > settings.MAX_CHO_MOI_DON:
            self.add_error("so_hanh_khach", f"Mỗi đơn tối đa {settings.MAX_CHO_MOI_DON} hành khách.")
        return cleaned


class ThongTinDatVeForm(forms.Form):
    """Thông tin người đặt và mã khuyến mãi (bước 6-7)."""

    ho_ten = forms.CharField(label="Họ tên người đặt", max_length=100)
    so_dien_thoai = forms.CharField(label="Số điện thoại", max_length=15)
    email = forms.EmailField(label="Email", required=False, max_length=254,
                             help_text="Dùng để nhận xác nhận giữ chỗ (không bắt buộc).")
    ma_khuyen_mai = forms.CharField(label="Mã khuyến mãi", required=False, max_length=30)

    def clean_ho_ten(self):
        ten = " ".join(self.cleaned_data["ho_ten"].split())
        if not ten:
            raise ValidationError("Vui lòng nhập họ tên.")
        return ten

    def clean_so_dien_thoai(self):
        sdt = re.sub(r"[\s.\-]", "", self.cleaned_data["so_dien_thoai"])
        if not SDT_RE.match(sdt):
            raise ValidationError("Số điện thoại phải gồm 10 chữ số và bắt đầu bằng 0.")
        return sdt

    def clean_ma_khuyen_mai(self):
        return "".join(self.cleaned_data.get("ma_khuyen_mai", "").split()).upper()


class HanhKhachForm(forms.Form):
    """Thông tin một hành khách ứng với một ghế (QT07)."""

    ghe_id = forms.IntegerField(widget=forms.HiddenInput)
    ho_ten = forms.CharField(label="Họ tên hành khách", max_length=100)
    doi_tuong = forms.ChoiceField(label="Đối tượng", choices=Ve.DoiTuong.choices, initial=Ve.DoiTuong.NGUOI_LON)
    so_giay_to = forms.CharField(label="Số giấy tờ (CCCD/hộ chiếu/thẻ SV)", max_length=20)

    def clean_ho_ten(self):
        ten = " ".join(self.cleaned_data["ho_ten"].split())
        if not ten:
            raise ValidationError("Vui lòng nhập họ tên hành khách.")
        return ten

    def clean_so_giay_to(self):
        so = self.cleaned_data["so_giay_to"].strip()
        if not GIAY_TO_RE.match(so):
            raise ValidationError("Số giấy tờ gồm 6-20 ký tự chữ hoặc số, không có khoảng trắng.")
        return so.upper()


class BaseHanhKhachFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        so_form = len(self.forms)
        if not 1 <= so_form <= settings.MAX_CHO_MOI_DON:
            raise ValidationError(f"Mỗi đơn phải có từ 1 đến {settings.MAX_CHO_MOI_DON} chỗ.")
        da_thay = set()
        for form in self.forms:
            ghe_id = form.cleaned_data.get("ghe_id") if hasattr(form, "cleaned_data") else None
            if ghe_id is None:
                continue
            if ghe_id in da_thay:
                raise ValidationError("Một chỗ không được chọn nhiều lần trong cùng một đơn.")
            da_thay.add(ghe_id)


HanhKhachFormSet = formset_factory(HanhKhachForm, formset=BaseHanhKhachFormSet, extra=0, max_num=1000)
