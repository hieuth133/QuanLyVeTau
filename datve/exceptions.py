"""Ngoại lệ nghiệp vụ của UC02. View bắt các ngoại lệ này để phản hồi thân thiện, không trả lỗi 500."""


class LoiNghiepVu(Exception):
    """Lớp cha của mọi ngoại lệ nghiệp vụ."""


class ChoDaBiGiu(LoiNghiepVu):
    """Luồng A6: một hoặc nhiều chỗ đã được người khác giữ hoặc mua."""

    def __init__(self, ds_ghe_id):
        self.ds_ghe_id = list(ds_ghe_id)
        super().__init__(f"Chỗ đã bị giữ: {self.ds_ghe_id}")


class KhongCoGia(LoiNghiepVu):
    """Tiền điều kiện 2: chưa có quy tắc giá cho tuyến và loại chỗ."""

    def __init__(self, chuyen_id, loai_cho_id):
        self.chuyen_id, self.loai_cho_id = chuyen_id, loai_cho_id
        super().__init__(f"Chuyến {chuyen_id} chưa có giá cho loại chỗ {loai_cho_id}")


class ChuyenKhongMoBan(LoiNghiepVu):
    """Tiền điều kiện 1: chuyến không còn mở bán hoặc đã qua thời điểm ngừng bán."""

    def __init__(self, chuyen_id):
        self.chuyen_id = chuyen_id
        super().__init__(f"Chuyến {chuyen_id} không còn mở bán")


class KhuyenMaiHetLuot(LoiNghiepVu):
    """Luồng A5: khuyến mãi vừa hết lượt sử dụng khi đang giữ chỗ."""

    def __init__(self, km_id):
        self.km_id = km_id
        super().__init__(f"Khuyến mãi {km_id} đã hết lượt")


class MaKhuyenMaiKhongHopLe(LoiNghiepVu):
    """Luồng A5: mã không tồn tại, đã hết hạn hoặc không đủ điều kiện."""

    def __init__(self, ma):
        self.ma = ma
        super().__init__(f"Mã khuyến mãi không hợp lệ: {ma}")


class DonKhongThanhToanDuoc(LoiNghiepVu):
    """Thanh toán giả lập chỉ chấp nhận đơn còn DANG_GIU và chưa hết hạn."""
