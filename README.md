# Quản lý bán vé tàu – hệ thống thử nghiệm (demo)

Cài đặt hai use case đã phân tích chi tiết trong báo cáo **PTTK – Trịnh Hoàng Hiếu – K23DTCN353**:

- **UC14 – Quản lý giá vé và khuyến mãi** (Quản lý): luồng chính A, B và rẽ nhánh E1–E5.
- **UC02 – Đặt vé (giữ chỗ)** (Khách hàng): luồng chính 1–12 và rẽ nhánh A1–A8.

Thiết kế chi tiết nằm ở `THIET_KE_HE_THONG_DEMO.md`; tên lớp, tên bảng (`db_table`), tên phương thức trong mã nguồn giữ nguyên như tài liệu đó để đối chiếu với báo cáo.

Công nghệ: Python 3.12, Django 5.2, PostgreSQL 16 (bắt buộc: dùng khóa hàng `SELECT … FOR UPDATE` và ràng buộc `EXCLUDE`), Bootstrap 5.3 (đã kèm sẵn trong `static/vendor`, chạy được khi không có mạng), JavaScript thuần.

## 1. Yêu cầu

- Windows 10/11, PowerShell, Python 3.12.
- PostgreSQL 16 theo **một trong hai** cách: bản portable đặt trong `.tools` (mục 2.1) hoặc Docker (mục 2.2).

## 2. Cài đặt

### 2.1. PostgreSQL portable trong `.tools` (không cần Docker)

Giải nén bản binaries PostgreSQL 16 vào `.tools\pgsql` (có `.tools\pgsql\bin\pg_ctl.exe`), sau đó:

```powershell
.\scripts\setup.ps1        # tạo .venv, pip install, tạo .env, khởi động PostgreSQL, migrate, seed_demo
.\scripts\run.ps1          # mở http://127.0.0.1:8000/
```

Các script khác: `.\scripts\db_start.ps1` (tự `initdb` nếu `.tools\pgdata` chưa có, tạo role `qlvt`/CSDL `quanlyvetau`, rồi khởi động), `.\scripts\db_stop.ps1` (dừng). Mọi script dùng đường dẫn tương đối theo vị trí của chính nó.

### 2.2. Docker

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
docker compose up -d db
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Nếu đã có PostgreSQL riêng, chỉ cần sửa `DB_*` trong `.env`. Tài khoản kết nối phải đủ quyền tạo extension `btree_gist` (migration `giave/0002_exclusion_constraint.py` cần) và tạo CSDL test khi chạy `pytest`.

### 2.3. Cấu hình `.env`

```text
DB_NAME=quanlyvetau   DB_USER=qlvt   DB_PASSWORD=qlvt   DB_HOST=localhost   DB_PORT=5432
GIU_CHO_PHUT=15        # thời gian giữ chỗ (QT02); đặt 1 khi demo để thấy chỗ tự giải phóng
MAX_CHO_MOI_DON=6      # số chỗ tối đa một đơn (A3)
NGUNG_BAN_TRUOC_PHUT=60
```

## 3. Chạy

```powershell
.\scripts\run.ps1                           # hoặc: .venv\Scripts\python.exe manage.py runserver
.venv\Scripts\python.exe manage.py giai_phong_cho --lap 60   # (tùy chọn) giải phóng chỗ hết hạn mỗi 60 giây
```

Hệ thống vẫn đúng khi không chạy `giai_phong_cho`: chỗ của đơn đã quá hạn luôn hiển thị là trống, và đơn hết hạn được giải phóng ngay khi có người đặt lại chỗ đó hoặc mở trang kết quả của đơn.

| Địa chỉ | Nội dung |
|---|---|
| `/` → `/dat-ve/` | Tìm chuyến, chọn chỗ, giữ chỗ (không cần đăng nhập) |
| `/quan-ly/gia-ve/` | Quản lý giá vé và khuyến mãi (chỉ Quản lý) |
| `/accounts/login/` | Đăng nhập (đăng xuất bằng nút trên thanh menu, gửi POST) |
| `/admin/` | Django Admin (tài khoản `quantri`); `NhatKyThayDoi` chỉ đọc |

## 4. Tài khoản demo (do `seed_demo` tạo)

| Tài khoản | Mật khẩu | Vai trò |
|---|---|---|
| `quantri` | `Quantri@123` | Quản trị hệ thống (superuser, vào được Admin) |
| `quanly` | `Quanly@123` | Quản lý (được vào `/quan-ly/gia-ve/`) |
| `nhanvien` | `Nhanvien@123` | Nhân viên bán vé (bị chặn HTTP 403 ở trang quản lý giá) |

`seed_demo` chạy lại nhiều lần không nhân đôi dữ liệu. Dữ liệu gồm 3 ga, 2 tuyến (`HN-DN`, `HN-SG`), 2 loại chỗ (`NM`, `K4`), 2 tàu (`SE19`, `SE1`, mỗi tàu toa 1 ngồi mềm 24 ghế, toa 2 nằm khoang 4 gồm 16 giường), chuyến mỗi ngày từ hôm nay đến +14 ngày, bảng giá ngày thường/cuối tuần/lễ (giả lập từ ngày +10 đến +12) và hai khuyến mãi `DATSOM10` (tự động) và `SV80K` (nhập mã). Tên tàu, giờ chạy, giá vé là dữ liệu giả lập.

## 5. Kịch bản demo (khoảng 10 phút)

Chuẩn bị: `.\scripts\setup.ps1`, đặt `GIU_CHO_PHUT=1` trong `.env`, `.\scripts\run.ps1`. Mở hai trình duyệt (một cửa sổ thường, một cửa sổ ẩn danh).

| Bước | Thao tác | Điều cần chỉ ra |
|---|---|---|
| 1 | Đăng nhập `nhanvien`, mở `/quan-ly/gia-ve/` | Bị chặn 403: chỉ Quản lý được quản lý giá |
| 2 | Đăng nhập `quanly`, mở thẻ Giá vé, lọc tuyến HN-DN | Danh sách quy tắc giá theo tuyến, loại chỗ, loại thời điểm (A3–A4) |
| 3 | Thêm quy tắc giá âm | Lỗi E1, dữ liệu nhập được giữ lại |
| 4 | Thêm quy tắc HN-DN, NM, CUOI_TUAN trùng thời gian với quy tắc có sẵn | Lỗi E2, hiển thị quy tắc bị trùng |
| 5 | Thẻ Khuyến mãi: thêm mã `HE2026` giảm 20% tối đa 150.000 đ, bắt buộc nhập mã | Lưu thành công (B5–B9) |
| 6 | Cửa sổ ẩn danh: Đặt vé HN-DN, ngày +8, chọn 2 ghế toa 1 | Sơ đồ chỗ, giá theo loại chỗ (bước 1–6) |
| 7 | Nhập 2 hành khách (1 người lớn, 1 sinh viên), mã `SV80K` | Vé người lớn giảm theo DATSOM10 (10%); vé sinh viên giảm theo SV80K (80.000 đ lớn hơn 10%); mã đặt chỗ và đồng hồ đếm ngược (bước 7–11) |
| 8 | Cửa sổ thường: mở cùng chuyến, xem đúng ghế vừa giữ | Ghế hiển thị "Đang giữ", không chọn được |
| 9 | `.venv\Scripts\python.exe manage.py thu_dong_thoi --so-luong 5` | In ra 1 thành công, 4 `ChoDaBiGiu` (A6) |
| 10 | Chờ quá 1 phút, tải lại trang kết quả và sơ đồ chỗ | Đơn chuyển HET_HAN, ghế trở lại trống (A7) |
| 11 | Quản lý sửa quy tắc giá vừa được dùng ở bước 7 | Hệ thống kết thúc quy tắc cũ, tạo phiên bản mới (E4); vé ở bước 7 giữ nguyên giá cũ (QT05) |
| 12 | Đăng nhập `quantri`, mở `/admin/giave/nhatkythaydoi/` | Nhật ký ghi đủ người sửa, thời điểm, giá trị cũ và mới |

Ghi chú: ở bước 9 nếu không truyền `--chuyen`, `--ghe` thì lệnh tự chọn chuyến mở bán đầu tiên và ghế trống đầu tiên; có thể chỉ định `--chuyen <id> --ghe <id>`. Thư xác nhận giữ chỗ (nếu nhập email) được in ra cửa sổ chạy server (console email backend).

## 6. Chạy test

```powershell
.venv\Scripts\python.exe -m pytest -q
```

pytest-django tự tạo CSDL `test_quanlyvetau` (tài khoản `qlvt` cần quyền SUPERUSER để bật `btree_gist`). Các file test:

| File | Nội dung |
|---|---|
| `tests/test_tinh_gia.py` | Chọn quy tắc giá theo ngày/loại thời điểm, khuyến mãi (phần trăm, tối đa, làm tròn, có lợi nhất, đặt trước, mã sai) |
| `tests/test_quy_tac_gia.py` | Form E1, tìm trùng E2, ràng buộc `EXCLUDE`, ngừng áp dụng E3, sửa quy tắc đã dùng E4, nhật ký, phân quyền 403 |
| `tests/test_khuyen_mai.py` | Mã trùng, phần trăm > 100, `tang_luot_dung`, kết thúc khuyến mãi, trạng thái suy ra từ ngày |
| `tests/test_giu_cho.py` | Giữ chỗ, xung đột A6, hết hạn A7, giải phóng, thanh toán giả lập, luồng HTTP A1–A8 |
| `tests/test_dong_thoi.py` | 5 luồng cùng giữ một ghế: đúng 1 thành công, 4 `ChoDaBiGiu` |
| `tests/test_lenh_quan_tri.py` | `seed_demo` (chạy lại không nhân đôi), `giai_phong_cho` |

Test dùng ngày tương đối so với hôm nay (hoặc truyền `hom_nay`) nên không phụ thuộc ngày chạy.

## 7. Cấu trúc thư mục

```text
quanlyvetau/   cấu hình dự án (settings đọc .env, urls)
taikhoan/      ThanhVien (custom user), QuanLy (proxy), VaiTroRequiredMixin
danhmuc/       danh mục + DAO tìm chuyến/sơ đồ chỗ + seed_demo + template filter (vnd)
giave/         UC14: QuyTacGia, KhuyenMai, NhatKyThayDoi, DAO, Form, View, migration EXCLUDE
datve/         UC02: KhachHang, DonDatCho, Ve, TinhGiaService, DatVeService, GiaiPhongChoTask, lệnh quản trị
templates/     base, 403, 404, registration/login, quan_ly/*, dat_ve/*
static/        css, js, vendor/bootstrap (5.3.3)
scripts/       db_start, db_stop, setup, run (PowerShell)
tests/         pytest
```

## 8. Một số điểm cài đặt đáng chú ý

- Chống bán trùng chỗ ở tầng CSDL: `SELECT … FOR UPDATE` trên ghế (khóa theo thứ tự id để tránh deadlock) và chỉ mục duy nhất một phần `uq_ve_cho_con_hieu_luc`.
- Chống trùng thời gian áp dụng giá (QT03): ràng buộc `EXCLUDE USING gist` (`ex_quy_tac_khong_trung`); `IntegrityError` được hiển thị như luồng E2.
- Quy tắc giá đã dùng cho vé không bao giờ bị sửa/xóa trực tiếp: sửa → kết thúc bản cũ + tạo phiên bản mới (E4); `Ve.quy_tac_gia` dùng `PROTECT`.
- Giá vé được chốt tại thời điểm giữ chỗ (QT05); lượt khuyến mãi được hoàn lại khi đơn hết hạn.
- Thời điểm khởi hành = `ngay_khoi_hanh` + `gio_khoi_hanh` theo múi giờ Asia/Ho_Chi_Minh; hàm dùng chung `danhmuc.thoi_gian.thoi_diem_ngung_ban`.
- Thông báo khi hết hạn giữ chỗ (UC02-A7): mọi nơi giải phóng đơn đi qua `datve.services.giai_phong_va_thong_bao` (DAO không gửi mail); email báo hết hạn gửi bằng console backend sau `transaction.on_commit` nếu khách có nhập email. Đây là điều chỉnh so với thiết kế mục 7.6 (chỉ nêu giải phóng, chưa nêu gửi thông báo).
- Khuyến mãi còn ít lượt hơn số vé của đơn: `TinhGiaService.tinh_gia_ve(..., luot_tam=...)` gán tạm lượt cho từng vé nên chỉ các vé trong giới hạn còn lại được giảm; `KhuyenMaiHetLuot` chỉ còn là lưới an toàn khi tranh chấp đồng thời.
- Django Admin cũng kiểm tra trùng thời gian áp dụng của `QuyTacGia` (không trả 500) và ghi `NhatKyThayDoi` cho thêm/sửa/xóa `QuyTacGia`, `KhuyenMai` (thêm hành động `XOA`, migration `giave/0003`).
- Tìm chuyến chỉ nhận ngày đi trong vòng 1 năm tới; đăng xuất giữ lại danh sách đơn của trình duyệt (`don_cua_toi`).
