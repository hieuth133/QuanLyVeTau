"""Tác vụ giải phóng chỗ hết hạn (thay cho Celery Beat trong bản demo)."""
from django.utils import timezone

from .dao import DonDatChoDAO
from .services import giai_phong_va_thong_bao


class GiaiPhongChoTask:
    @staticmethod
    def chay() -> int:
        """Giải phóng mọi đơn DANG_GIU đã quá hạn (mỗi đơn một giao dịch) và báo cho khách;
        trả về số đơn đã giải phóng."""
        dem = 0
        for don in DonDatChoDAO.tim_don_het_han(timezone.now()):
            if giai_phong_va_thong_bao(don):
                dem += 1
        return dem
