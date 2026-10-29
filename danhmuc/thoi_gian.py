"""Hàm thời gian dùng chung cho chuyến tàu.

Thời điểm khởi hành = `ngay_khoi_hanh` + `gio_khoi_hanh` của lịch trình, tính theo múi giờ
của dự án (Asia/Ho_Chi_Minh) và trả về datetime có múi giờ (aware)."""
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


def thoi_diem_khoi_hanh(chuyen) -> datetime:
    return timezone.make_aware(
        datetime.combine(chuyen.ngay_khoi_hanh, chuyen.lich_trinh.gio_khoi_hanh),
        timezone.get_default_timezone(),
    )


def thoi_diem_den(chuyen) -> datetime:
    return thoi_diem_khoi_hanh(chuyen) + timedelta(minutes=chuyen.lich_trinh.thoi_gian_chay)


def thoi_diem_ngung_ban(chuyen) -> datetime:
    """Thời điểm ngừng bán vé = giờ tàu chạy trừ NGUNG_BAN_TRUOC_PHUT phút."""
    return thoi_diem_khoi_hanh(chuyen) - timedelta(minutes=settings.NGUNG_BAN_TRUOC_PHUT)
