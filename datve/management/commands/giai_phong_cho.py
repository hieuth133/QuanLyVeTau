"""Giải phóng các đơn đặt chỗ đã hết hạn giữ (thay cho Celery Beat trong bản demo)."""
import time

from django.core.management.base import BaseCommand

from datve.tasks import GiaiPhongChoTask


class Command(BaseCommand):
    help = "Chuyển đơn DANG_GIU đã quá hạn sang HET_HAN, vé sang DA_HUY và hoàn lượt khuyến mãi."

    def add_arguments(self, parser):
        parser.add_argument("--lap", type=int, default=0, metavar="N",
                            help="Lặp lại mỗi N giây (Ctrl+C để dừng). Mặc định chạy một lần.")

    def handle(self, *args, **options):
        lap = options["lap"]
        while True:
            so_don = GiaiPhongChoTask.chay()
            self.stdout.write(f"Đã giải phóng {so_don} đơn hết hạn.")
            if lap <= 0:
                return
            try:
                time.sleep(lap)
            except KeyboardInterrupt:
                self.stdout.write("Đã dừng.")
                return
