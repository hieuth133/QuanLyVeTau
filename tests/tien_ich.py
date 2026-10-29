"""Hàm tiện ích dùng chung cho các file test."""
from datetime import date, datetime, time, timedelta

from django.utils import timezone


def cho(ghe, ho_ten="Hành Khách", doi_tuong="NGUOI_LON", so_giay_to="012345678"):
    """Một phần tử của ds_cho cho DatVeService.giu_cho."""
    return {"ghe_id": ghe.id, "ho_ten": ho_ten, "doi_tuong": doi_tuong, "so_giay_to": so_giay_to}


def thoi_diem_khoi_hanh_sau(phut: int) -> tuple[date, time]:
    """(ngày, giờ) địa phương cách bây giờ `phut` phút – dùng để tạo chuyến sắp chạy."""
    t: datetime = timezone.localtime(timezone.now() + timedelta(minutes=phut))
    return t.date(), t.time().replace(second=0, microsecond=0)
