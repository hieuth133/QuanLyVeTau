"""Thử đặt đồng thời: nhiều luồng cùng giữ MỘT chỗ để chứng minh chỉ một luồng thành công."""
import threading
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections
from django.utils import timezone

from danhmuc.dao import ChuyenTauDAO, GheNgoiDAO
from danhmuc.models import ChuyenTau
from datve.exceptions import ChoDaBiGiu, LoiNghiepVu
from datve.models import Ve
from datve.services import DatVeService


class Command(BaseCommand):
    help = ("Chạy N luồng cùng gọi DatVeService.giu_cho cho một ghế. "
            "Nếu không truyền --chuyen/--ghe, tự chọn chuyến mở bán và ghế trống đầu tiên.")

    def add_arguments(self, parser):
        parser.add_argument("--so-luong", type=int, default=5, help="Số luồng chạy đồng thời (mặc định 5).")
        parser.add_argument("--chuyen", type=int, help="Mã chuyến tàu (tùy chọn).")
        parser.add_argument("--ghe", type=int, help="Mã ghế (tùy chọn).")

    def handle(self, *args, **options):
        so_luong = options["so_luong"]
        if so_luong < 1:
            raise CommandError("--so-luong phải >= 1")
        chuyen_id, ghe_id = self._chon_chuyen_ghe(options["chuyen"], options["ghe"])
        ghe = GheNgoiDAO.lay_theo_ids(chuyen_id, [ghe_id])
        ten_ghe = f"toa {ghe[0].toa_xe.so_toa} ghế {ghe[0].so_ghe}" if ghe else f"ghế #{ghe_id}"
        self.stdout.write(f"Chuyến #{chuyen_id}, {ten_ghe}: {so_luong} luồng cùng giữ chỗ...")

        barrier = threading.Barrier(so_luong)
        ket_qua: list[tuple[int, str, str, float]] = []
        khoa = threading.Lock()

        def chay(i: int):
            ho_ten = f"Khách thử #{i}"
            try:
                connection.ensure_connection()  # mở sẵn kết nối để các luồng xuất phát cùng lúc
                barrier.wait()
                bat_dau = time.perf_counter()
                try:
                    don = DatVeService.giu_cho(
                        chuyen_id,
                        [{"ghe_id": ghe_id, "ho_ten": ho_ten, "doi_tuong": Ve.DoiTuong.NGUOI_LON,
                          "so_giay_to": f"TEST{i:06d}"}],
                        {"ho_ten": ho_ten, "so_dien_thoai": f"09000000{i:02d}", "email": ""},
                        None)
                    loai, chi_tiet = "THANH_CONG", don.ma_dat_cho
                except ChoDaBiGiu:
                    loai, chi_tiet = "ChoDaBiGiu", "chỗ đã bị luồng khác giữ"
                except (LoiNghiepVu, ValueError) as e:
                    loai, chi_tiet = "LOI", f"{type(e).__name__}: {e}"
                with khoa:
                    ket_qua.append((i, loai, chi_tiet, time.perf_counter() - bat_dau))
            except threading.BrokenBarrierError:
                with khoa:
                    ket_qua.append((i, "LOI", "BrokenBarrierError", 0.0))
            finally:
                connections.close_all()  # mỗi luồng đóng kết nối của mình khi xong

        luong = [threading.Thread(target=chay, args=(i,), name=f"khach-{i}") for i in range(1, so_luong + 1)]
        for t in luong:
            t.start()
        for t in luong:
            t.join()

        for i, loai, chi_tiet, giay in sorted(ket_qua):
            self.stdout.write(f"  Luồng {i:>2}: {loai:<10} {chi_tiet} ({giay * 1000:.0f} ms)")
        thanh_cong = sum(1 for r in ket_qua if r[1] == "THANH_CONG")
        bi_giu = sum(1 for r in ket_qua if r[1] == "ChoDaBiGiu")
        loi = len(ket_qua) - thanh_cong - bi_giu
        self.stdout.write(self.style.SUCCESS(
            f"Kết quả: {thanh_cong} thành công, {bi_giu} ChoDaBiGiu" + (f", {loi} lỗi khác" if loi else "")))
        if thanh_cong == 1 and bi_giu == so_luong - 1:
            self.stdout.write(self.style.SUCCESS("Đúng kỳ vọng: chỉ một người giữ được chỗ."))
        else:
            self.stdout.write(self.style.WARNING("Kết quả KHÔNG như kỳ vọng (1 thành công, còn lại ChoDaBiGiu)."))

    def _chon_chuyen_ghe(self, chuyen_id, ghe_id):
        if chuyen_id is None:
            now = timezone.now()
            chuyen = next((c for c in ChuyenTauDAO.danh_sach_mo_ban_tu(timezone.localdate())
                           if now < c.thoi_diem_ngung_ban), None)
            if chuyen is None:
                raise CommandError("Không có chuyến mở bán. Hãy chạy: python manage.py seed_demo")
            chuyen_id = chuyen.id
        else:
            try:
                chuyen = ChuyenTauDAO.lay_theo_id(chuyen_id)
            except ChuyenTau.DoesNotExist:
                raise CommandError(f"Không có chuyến #{chuyen_id}")
        if ghe_id is None:
            for toa in GheNgoiDAO.lay_ds_toa(chuyen_id):
                if toa.gia_co_so is None:
                    continue
                for g in GheNgoiDAO.lay_so_do_cho(chuyen_id, toa.id):
                    if g["trang_thai"] == "TRONG":
                        return chuyen_id, g["ghe_id"]
            raise CommandError("Chuyến này không còn ghế trống (có giá).")
        if not GheNgoiDAO.lay_theo_ids(chuyen_id, [ghe_id]):
            raise CommandError(f"Ghế #{ghe_id} không thuộc đoàn tàu của chuyến #{chuyen_id}")
        return chuyen_id, ghe_id
