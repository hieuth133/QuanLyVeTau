#!/usr/bin/env python
"""Kiểm thử kịch bản demo 12 bước (mục 10 của THIET_KE_HE_THONG_DEMO.md) qua HTTP với server thật.

Chỉ dùng thư viện chuẩn. Chuẩn bị (KHÔNG chạy trên CSDL demo `quanlyvetau`):

    createdb quanlyvetau_qa                      (hoặc psql: CREATE DATABASE quanlyvetau_qa)
    set DB_NAME=quanlyvetau_qa
    python manage.py migrate && python manage.py seed_demo
    python manage.py runserver 8001 --noreload   (cùng biến DB_NAME)
    python scripts/kiem_thu_kich_ban.py --base http://127.0.0.1:8001 --db quanlyvetau_qa

Script giả định CSDL vừa được seed (chưa có mã HE2026, chưa có đơn đặt chỗ nào).
Hết hạn giữ chỗ được mô phỏng bằng cách cập nhật `thoi_diem_het_han` về quá khứ qua psql; nếu chạy server với
GIU_CHO_PHUT=1 có thể thêm `--cho-that` để chờ ~65 giây thay vì dùng psql.
Exit code 0 nếu mọi bước PASS, 1 nếu có FAIL.
"""
import argparse
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar

# --------------------------------------------------------------------------- cấu hình / kết quả
GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KET_QUA: list[tuple[str, str, str]] = []          # (trạng thái, mã bước, chi tiết)
LOI_HTML: list[str] = []
BUOC_HIEN_TAI = ["-"]
ARGS = None
S: dict = {}                                       # trạng thái dùng chung giữa các bước


def ghi(ok: bool, mo_ta: str, chi_tiet: str = ""):
    KET_QUA.append(("PASS" if ok else "FAIL", BUOC_HIEN_TAI[0], mo_ta + (f"  -> {chi_tiet}" if (chi_tiet and not ok) else "")))
    print(f"[{'PASS' if ok else 'FAIL'}] {BUOC_HIEN_TAI[0]}: {mo_ta}" + (f"\n         {chi_tiet}" if (chi_tiet and not ok) else ""))
    return ok


def buoc(ma: str, tieu_de: str):
    BUOC_HIEN_TAI[0] = ma
    print(f"\n=== {ma}. {tieu_de}")


def cat(s: str, n: int = 200) -> str:
    s = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))
    return s[:n]


# --------------------------------------------------------------------------- HTTP
class KhongTheoChuyenHuong(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Resp:
    def __init__(self, status, body, headers, url, lich_su):
        self.status, self.body, self.headers, self.url, self.lich_su = status, body, headers, url, lich_su

    @property
    def location(self):
        return self.headers.get("Location", "")


class Browser:
    """Một "trình duyệt": cookie jar riêng, theo dõi chuyển hướng thủ công, quét HTML mọi phản hồi."""

    def __init__(self, ten: str):
        self.ten = ten
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), KhongTheoChuyenHuong)

    def _mot_lan(self, url, data=None):
        req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("Referer", url)
        try:
            r = self.opener.open(req, timeout=60)
            status, hdr, raw = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, hdr, raw = e.code, e.headers, e.read()
        return status, hdr, raw.decode("utf-8", "replace")

    def request(self, path, data=None, follow=True) -> Resp:
        url = urllib.parse.urljoin(ARGS.base, path)
        lich_su = []
        for _ in range(10):
            status, hdr, body = self._mot_lan(url, data)
            quet_html(url, status, hdr, body)
            if status in (301, 302, 303, 307) and follow:
                lich_su.append((status, hdr.get("Location")))
                url = urllib.parse.urljoin(url, hdr.get("Location"))
                data = None
                continue
            return Resp(status, body, hdr, url, lich_su)
        raise RuntimeError("Quá nhiều chuyển hướng")

    def get(self, path, follow=True, **params):
        if params:
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode(params, doseq=True)
        return self.request(path, None, follow)

    def post(self, path, fields: dict, follow=True):
        return self.request(path, urllib.parse.urlencode(fields, doseq=True).encode(), follow)

    def dang_nhap(self, ten, mat_khau):
        r = self.get("/accounts/login/")
        f = form_theo_truong(r.body, "username")
        f["username"], f["password"] = ten, mat_khau
        return self.post("/accounts/login/", f, follow=False)

    def csrf(self) -> str:
        for c in self.jar:
            if c.name == "csrftoken":
                return c.value
        return ""

    def dang_xuat(self):
        r = self.get("/dat-ve/")
        f = form_theo_truong(r.body, "csrfmiddlewaretoken", hanh_dong="logout")
        return self.post("/accounts/logout/", f)


# --------------------------------------------------------------------------- phân tích HTML
class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms, self.cur, self.sel, self.ta = [], None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.cur = {"action": a.get("action", ""), "fields": {}}
            self.forms.append(self.cur)
            return
        if self.cur is None:
            return
        f = self.cur["fields"]
        if tag == "input":
            t, n = a.get("type", "text").lower(), a.get("name")
            if not n or t in ("submit", "button", "image"):
                return
            if t in ("checkbox", "radio"):
                if "checked" in a:
                    f[n] = a.get("value", "on")
            else:
                f[n] = a.get("value", "") or ""
        elif tag == "select":
            self.sel = a.get("name")
            f.setdefault(self.sel, "")
        elif tag == "option" and self.sel and "selected" in a:
            f[self.sel] = a.get("value", "")
        elif tag == "textarea":
            self.ta = a.get("name")
            f[self.ta] = ""

    def handle_data(self, data):
        if self.ta and self.cur is not None:
            self.cur["fields"][self.ta] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self.cur = None
        elif tag == "select":
            self.sel = None
        elif tag == "textarea":
            self.ta = None


def cac_form(html):
    p = _FormParser()
    p.feed(html)
    return p.forms


def form_theo_truong(html, ten_truong, hanh_dong=None) -> dict:
    """Giá trị mặc định của biểu mẫu (kể cả csrfmiddlewaretoken) có trường `ten_truong`."""
    for f in cac_form(html):
        if ten_truong in f["fields"] and (hanh_dong is None or hanh_dong in f["action"]):
            return dict(f["fields"])
    raise LookupError(f"Không thấy biểu mẫu có trường {ten_truong}")


def lay_ghe(html):
    """[{id, cls, ten, khoa}] các ô ghế trên trang chọn chỗ."""
    ket_qua = []
    for m in re.finditer(r'<label class="seat ([^"]*)"[^>]*>(.*?)</label>', html, re.S):
        inp = m.group(2)
        v = re.search(r'value="(\d+)"', inp)
        ten = re.search(r'data-ten="([^"]*)"', inp)
        ket_qua.append({"id": int(v.group(1)), "cls": m.group(1), "ten": ten.group(1) if ten else "",
                        "khoa": " disabled" in inp or "disabled>" in inp})
    return ket_qua


def tuyen_chon(html, ten_select, bat_dau_bang):
    m = re.search(rf'<select[^>]*name="{ten_select}".*?</select>', html, re.S)
    for o in re.finditer(r'<option value="(\d+)"[^>]*>\s*([^<]*?)\s*</option>', m.group(0)):
        if o.group(2).startswith(bat_dau_bang):
            return int(o.group(1))
    raise LookupError(bat_dau_bang)


MONEY_RE = re.compile(r"(?<![\w.,:])(-?[\d.,]+)\s*đ(?!\w)")


def quet_html(url, status, hdr, body):
    """Quét mọi trang HTML: không còn thẻ template thô, không có traceback, tiêu đề tiếng Việt, tiền đúng định dạng."""
    ct = hdr.get("Content-Type", "") if hdr else ""
    if "text/html" not in ct:
        return
    duong = urllib.parse.urlparse(url).path
    if status == 302 or status == 301:
        return
    nhan = f"{status} {duong}"
    if not body.strip():
        return                                           # ví dụ 405 không có thân
    if status == 404 and "Page not found at" in body:     # trang 404 kỹ thuật của DEBUG=True (404.html chỉ hiện khi DEBUG=0)
        S.setdefault("ghi_chu", []).append(f"{nhan}: DEBUG=True nên hiện trang 404 kỹ thuật, không phải templates/404.html")
        return
    if "charset=utf-8" not in ct.lower():
        LOI_HTML.append(f"{nhan}: Content-Type không có charset=utf-8 ({ct})")
    if status >= 500:
        LOI_HTML.append(f"{nhan}: máy chủ trả lỗi {status}")
    for tok in ("{{", "{%", "{#", "%}", "}}"):
        if tok in body:
            LOI_HTML.append(f"{nhan}: còn chuỗi template thô {tok!r} trong HTML")
            break
    for tok in ("Traceback (most recent call last)", "Exception Value", "Server Error (500)", "TemplateSyntaxError"):
        if tok in body:
            LOI_HTML.append(f"{nhan}: HTML chứa {tok!r}")
    if re.search(r"Ã.|Ä.|áº|á»|�", body):
        LOI_HTML.append(f"{nhan}: nghi ngờ lỗi mã hóa tiếng Việt (mojibake)")
    if not duong.startswith("/admin/"):
        t = re.search(r"<title>(.*?)</title>", body, re.S)
        if not t or "Quản lý bán vé tàu" not in t.group(1):
            LOI_HTML.append(f"{nhan}: thiếu <title> tiếng Việt có dấu ({t.group(1) if t else None!r})")
        van_ban = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
        van_ban = re.sub(r"<[^>]+>", " ", van_ban)
        if re.search(r"\bNone\b", van_ban):
            LOI_HTML.append(f"{nhan}: hiển thị chữ 'None' ra giao diện")
        for m in MONEY_RE.finditer(van_ban):
            if not re.fullmatch(r"-?\d{1,3}(\.\d{3})*", m.group(1)):
                LOI_HTML.append(f"{nhan}: tiền sai định dạng {m.group(0)!r}")


# --------------------------------------------------------------------------- CSDL / lệnh quản trị
def psql_duong_dan():
    return os.path.join(GOC, ".tools", "pgsql", "bin", "psql.exe" if os.name == "nt" else "psql")


def sql(truy_van: str) -> list[list[str]]:
    env = dict(os.environ, PGPASSWORD="qlvt", PGCLIENTENCODING="UTF8")
    p = subprocess.run([psql_duong_dan(), "-h", "localhost", "-U", "qlvt", "-d", ARGS.db, "-AtF", "|", "-c", truy_van],
                       capture_output=True, env=env, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("psql lỗi: " + p.stderr.decode("utf-8", "replace"))
    return [dong.split("|") for dong in p.stdout.decode("utf-8").splitlines() if dong.strip()]


def sql1(truy_van):
    kq = sql(truy_van)
    return kq[0][0] if kq else None


def manage(*tham_so, env_them=None) -> subprocess.CompletedProcess:
    py = ARGS.python or os.path.join(GOC, ".venv", "Scripts" if os.name == "nt" else "bin",
                                     "python.exe" if os.name == "nt" else "python")
    env = dict(os.environ, DB_NAME=ARGS.db, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.update(env_them or {})
    return subprocess.run([py, os.path.join(GOC, "manage.py"), *tham_so], capture_output=True, env=env, cwd=GOC,
                          timeout=300)


# --------------------------------------------------------------------------- tính kỳ vọng theo dữ liệu seed
GIA_SEED = {"HN-DN": {"NM": (450_000, 500_000), "K4": (750_000, 820_000)},
            "HN-SG": {"NM": (900_000, 990_000), "K4": (1_500_000, 1_650_000)}}


def gia_co_so_seed(tuyen, loai, ngay: date, hom_nay: date) -> int:
    thuong, cuoi_tuan = GIA_SEED[tuyen][loai]
    if hom_nay + timedelta(days=10) <= ngay <= hom_nay + timedelta(days=12):
        return thuong * 13 // 10
    return cuoi_tuan if ngay.weekday() >= 5 else thuong


def giam_datsom10(gia: int) -> int:
    return min(gia * 10 // 100, 100_000) // 1000 * 1000


def vnd(n: int) -> str:
    return f"{n:,}".replace(",", ".") + " đ"


def du_lieu_giu_cho(f: dict, ghe_ids, nguoi, hanh_khach, ma=""):
    d = dict(f)
    d.update({"hk-TOTAL_FORMS": str(len(ghe_ids)), "hk-INITIAL_FORMS": str(len(ghe_ids)), "hk-MIN_NUM_FORMS": "0",
              "hk-MAX_NUM_FORMS": "1000", "ho_ten": nguoi["ho_ten"], "so_dien_thoai": nguoi["sdt"],
              "email": nguoi.get("email", ""), "ma_khuyen_mai": ma})
    for i, (gid, hk) in enumerate(zip(ghe_ids, hanh_khach)):
        d[f"hk-{i}-ghe_id"] = str(gid)
        d[f"hk-{i}-ho_ten"], d[f"hk-{i}-doi_tuong"], d[f"hk-{i}-so_giay_to"] = hk
    return d


def tim_chuyen_id(br: Browser, tuyen_ma: str, ngay: date, so_hk: int):
    """Tìm chuyến qua giao diện; trả về (id_chuyen, html_ket_qua)."""
    trang = br.get("/dat-ve/")
    ga = {"HN-DN": ("Hà Nội", "Đà Nẵng"), "HN-SG": ("Hà Nội", "Sài Gòn")}[tuyen_ma]
    r = br.get("/dat-ve/", ga_di=tuyen_chon(trang.body, "ga_di", ga[0]), ga_den=tuyen_chon(trang.body, "ga_den", ga[1]),
               ngay_di=ngay.isoformat(), so_hanh_khach=so_hk)
    ids = re.findall(r'/dat-ve/chuyen/(\d+)/\?so_hanh_khach=', r.body)
    return (int(ids[0]) if ids else None), r


# =========================================================================== CÁC BƯỚC
def chuan_bi():
    buoc("B0", "Chuẩn bị")
    ghi(ARGS.db != "quanlyvetau", f"Không chạy trên CSDL demo (đang dùng {ARGS.db})")
    if ARGS.db == "quanlyvetau":
        print("Từ chối chạy trên CSDL demo `quanlyvetau`.")
        sys.exit(2)
    S["hom_nay"] = datetime.now(timezone(timedelta(hours=7))).date()      # Asia/Ho_Chi_Minh
    S["ngay8"] = S["hom_nay"] + timedelta(days=8)
    r = urllib.request.urlopen(urllib.request.Request(ARGS.base + "/dat-ve/"), timeout=30)
    ghi(r.status == 200, "Server trả lời tại " + ARGS.base)
    so_don = int(sql1('select count(*) from "tblDonDatCho"'))
    ghi(so_don == 0, "CSDL QA vừa seed (chưa có đơn đặt chỗ)", f"đã có {so_don} đơn")
    ghi(sql1("select count(*) from \"tblKhuyenMai\" where ma_khuyen_mai='HE2026'") == "0", "Chưa có khuyến mãi HE2026")
    S["luot0"] = {m: int(sql1(f"select so_luot_da_dung from \"tblKhuyenMai\" where ma_khuyen_mai='{m}'"))
                  for m in ("SV80K", "DATSOM10")}


def buoc1_nhan_vien_403():
    buoc("B01", "Đăng nhập nhanvien, mở /quan-ly/gia-ve/ -> 403")
    anon = Browser("anon0")
    r = anon.get("/quan-ly/gia-ve/", follow=False)
    ghi(r.status == 302 and r.location.startswith("/accounts/login/?next="), "Chưa đăng nhập -> chuyển tới trang đăng nhập", f"{r.status} {r.location}")
    nv = Browser("nhanvien")
    r = nv.dang_nhap("nhanvien", "sai-mat-khau")
    ghi(r.status == 200 and "Hãy nhập đúng" in r.body or "đúng tên" in r.body or "is-invalid" in r.body or "alert-danger" in r.body,
        "Đăng nhập sai mật khẩu bị từ chối và hiện lỗi", f"{r.status} {cat(r.body)}")
    r = nv.dang_nhap("nhanvien", "Nhanvien@123")
    ghi(r.status == 302, "Đăng nhập nhanvien thành công (302)", str(r.status))
    r = nv.get("/quan-ly/gia-ve/")
    ghi(r.status == 403, "GET /quan-ly/gia-ve/ -> 403", str(r.status))
    ghi("Bạn không có quyền truy cập" in r.body and "Quản lý" in r.body, "Trang 403 tiếng Việt, nêu vai trò Quản lý", cat(r.body))
    for p in ("/quan-ly/gia-ve/them/", "/quan-ly/khuyen-mai/them/"):
        ghi(nv.get(p).status == 403, f"GET {p} -> 403")
    f = form_theo_truong(nv.get("/dat-ve/").body, "csrfmiddlewaretoken", "logout")
    ghi(nv.post("/quan-ly/gia-ve/them/", {**f, "gia_co_so": "1"}).status == 403, "POST trực tiếp thêm quy tắc -> 403")
    ghi(nv.post("/quan-ly/khuyen-mai/them/", {**f, "ma_khuyen_mai": "HACK"}).status == 403, "POST trực tiếp thêm KM -> 403")
    ghi(sql1('select count(*) from "tblNhatKyThayDoi"') == "0", "Nhân viên không để lại nhật ký / dữ liệu")
    r = nv.dang_xuat()
    ghi(r.status == 200 and "Đăng nhập" in r.body, "Đăng xuất bằng POST thành công")
    ghi(nv.get("/accounts/logout/").status == 405, "Đăng xuất bằng GET bị từ chối (405)")


def buoc2_danh_sach_loc():
    buoc("B02", "Đăng nhập quanly, thẻ Giá vé, lọc tuyến HN-DN")
    ql = Browser("quanly")
    S["ql"] = ql
    r = ql.dang_nhap("quanly", "Quanly@123")
    ghi(r.status == 302, "Đăng nhập quanly thành công", str(r.status))
    r = ql.get("/quan-ly/gia-ve/")
    ghi(r.status == 200 and "Quản lý giá vé và khuyến mãi" in r.body, "Mở trang quản lý giá vé (200)")
    ghi("Quản lý giá vé</a>" in r.body, "Menu có mục 'Quản lý giá vé' cho Quản lý")
    S["tuyen_dn"] = tuyen_chon(r.body, "tuyen", "HN-DN")
    S["tuyen_sg"] = tuyen_chon(r.body, "tuyen", "HN-SG")
    S["nm"] = tuyen_chon(r.body, "loai_cho", "Ngồi mềm")
    S["k4"] = tuyen_chon(r.body, "loai_cho", "Nằm khoang")
    so_tat_ca = len(re.findall(r"/quan-ly/gia-ve/\d+/sua/", r.body))
    ghi(so_tat_ca == 12, "Không lọc: 12 quy tắc giá có thể sửa", str(so_tat_ca))
    r = ql.get("/quan-ly/gia-ve/", the="gia-ve", tuyen=S["tuyen_dn"])
    dong = re.findall(r"<tr class=.*?</tr>", r.body, re.S)
    ghi(len(dong) == 6 and all("HN-DN" in d for d in dong) and "HN-SG" not in re.sub(r"<option.*?</option>", "", r.body, flags=re.S),
        "Lọc HN-DN: đúng 6 quy tắc, không có HN-SG", f"{len(dong)} dòng")
    for tien in ("450.000 đ", "500.000 đ", "585.000 đ", "750.000 đ", "820.000 đ", "975.000 đ"):
        ghi(tien in r.body, f"Danh sách có giá {tien}")
    ghi("Ngày thường" in r.body and "Cuối tuần" in r.body and "Lễ, Tết" in r.body, "Hiển thị đủ loại thời điểm")
    r = ql.get("/quan-ly/gia-ve/", the="gia-ve", tuyen=S["tuyen_dn"], loai_cho=S["k4"], trang_thai="DANG_AP_DUNG")
    ghi(len(re.findall(r"/sua/", r.body)) == 3, "Lọc HN-DN + K4 + đang áp dụng: 3 quy tắc")
    r = ql.get("/quan-ly/gia-ve/", the="khuyen-mai")
    ghi("DATSOM10" in r.body and "SV80K" in r.body and "Nhập mã" in r.body and "Tự động" in r.body,
        "Thẻ Khuyến mãi liệt kê DATSOM10 (tự động) và SV80K (nhập mã)")
    ghi("10%" in r.body and "80.000 đ" in r.body and "100.000 đ" in r.body, "Hiển thị mức giảm 10% / 80.000 đ / tối đa 100.000 đ")
    r = ql.get("/quan-ly/gia-ve/", the="khuyen-mai", trang_thai="DA_KET_THUC")
    ghi("DATSOM10" not in r.body, "Lọc khuyến mãi 'Đã kết thúc' không có DATSOM10")
    r = ql.get("/quan-ly/gia-ve/", the="khuyen-mai", trang_thai="SAP_AP_DUNG")
    ghi("DATSOM10" not in r.body, "Lọc khuyến mãi 'Sắp áp dụng' không có DATSOM10 (đang áp dụng)")
    r = ql.get("/quan-ly/gia-ve/?the=bay&tuyen=abc&loai_cho=xyz&trang_thai=%27%3B--")
    ghi(r.status == 200, "Tham số lọc rác không gây lỗi", str(r.status))


def buoc3_e1_gia_am():
    buoc("B03", "E1: thêm quy tắc giá âm, dữ liệu nhập được giữ lại")
    ql = S["ql"]
    trang = ql.get("/quan-ly/gia-ve/them/")
    ghi(trang.status == 200 and "Thêm quy tắc giá" in trang.body, "Mở biểu mẫu thêm quy tắc giá")
    f = form_theo_truong(trang.body, "gia_co_so")
    f.update({"tuyen_duong": str(S["tuyen_dn"]), "loai_cho": str(S["nm"]), "gia_co_so": "-500", "loai_thoi_diem": "NGAY_THUONG",
              "ngay_bat_dau": (S["hom_nay"] + timedelta(days=30)).isoformat(), "ngay_ket_thuc": "", "ghi_chu": "Giữ lại ghi chú E1"})
    r = ql.post("/quan-ly/gia-ve/them/", f)
    ghi(r.status == 200, "Giá âm -> hiển thị lại biểu mẫu (200, không chuyển hướng)", str(r.status))
    ghi("Giá cơ sở phải lớn hơn 0" in r.body, "Thông báo lỗi tiếng Việt gắn vào trường giá")
    ghi('value="-500"' in r.body and "Giữ lại ghi chú E1" in r.body, "Dữ liệu đã nhập (giá, ghi chú) được giữ lại")
    ghi(re.search(r'<option value="%d" selected' % S["tuyen_dn"], r.body) is not None, "Tuyến đã chọn được giữ lại")
    ghi(sql1('select count(*) from "tblQuyTacGia"') == "12", "Không có quy tắc nào được lưu")
    f["gia_co_so"], f["ngay_ket_thuc"] = "450000", (S["hom_nay"] + timedelta(days=20)).isoformat()
    r = ql.post("/quan-ly/gia-ve/them/", f)
    ghi(r.status == 200 and "Ngày kết thúc không được trước ngày bắt đầu" in r.body, "Ngày kết thúc trước ngày bắt đầu -> lỗi E1")
    f["ngay_bat_dau"], f["ngay_ket_thuc"] = (S["hom_nay"] - timedelta(days=1)).isoformat(), ""
    r = ql.post("/quan-ly/gia-ve/them/", f)
    ghi(r.status == 200 and "quá khứ" in r.body, "Ngày bắt đầu ở quá khứ -> lỗi")
    f2 = dict(f, gia_co_so="", tuyen_duong="", ngay_bat_dau="")
    r = ql.post("/quan-ly/gia-ve/them/", f2)
    ghi(r.status == 200 and r.body.count("This field") + r.body.count("trường này") + r.body.count("bắt buộc") >= 3,
        "Bỏ trống trường bắt buộc -> lỗi từng trường", cat(r.body))


def buoc4_e2_trung():
    buoc("B04", "E2: quy tắc HN-DN, NM, CUOI_TUAN trùng thời gian -> hiện quy tắc trùng")
    ql = S["ql"]
    trang = ql.get("/quan-ly/gia-ve/them/")
    f = form_theo_truong(trang.body, "gia_co_so")
    f.update({"tuyen_duong": str(S["tuyen_dn"]), "loai_cho": str(S["nm"]), "gia_co_so": "510000", "loai_thoi_diem": "CUOI_TUAN",
              "ngay_bat_dau": (S["hom_nay"] + timedelta(days=1)).isoformat(), "ngay_ket_thuc": "", "ghi_chu": "thử trùng"})
    r = ql.post("/quan-ly/gia-ve/them/", f)
    ghi(r.status == 200, "Trùng thời gian -> không lưu, hiển thị lại biểu mẫu", str(r.status))
    ghi("Quy tắc bị trùng thời gian áp dụng (1)" in r.body, "Hiển thị bảng quy tắc bị trùng (1 quy tắc)")
    ghi("500.000 đ" in r.body and "HN-DN" in r.body and "không giới hạn" in r.body, "Bảng nêu rõ quy tắc đang trùng (500.000 đ, không giới hạn)")
    ghi('value="510000"' in r.body, "Dữ liệu nhập vẫn được giữ")
    ghi(sql1('select count(*) from "tblQuyTacGia"') == "12", "Không lưu quy tắc trùng")
    f["loai_thoi_diem"] = "NGAY_THUONG"
    r = ql.post("/quan-ly/gia-ve/them/", f)
    ghi(r.status == 200 and "Quy tắc bị trùng" in r.body, "Trùng cả ngày thường (cùng tuyến/loại chỗ) -> E2")
    ghi('href="/quan-ly/gia-ve/?the=gia-ve"' in r.body and "Hủy" in r.body, "E5: nút Hủy là liên kết về danh sách")


def buoc5_them_khuyen_mai():
    buoc("B05", "Thẻ Khuyến mãi: thêm HE2026 giảm 20% tối đa 150.000 đ, bắt buộc nhập mã")
    ql = S["ql"]
    trang = ql.get("/quan-ly/khuyen-mai/them/")
    ghi(trang.status == 200 and "Thêm khuyến mãi" in trang.body, "Mở biểu mẫu thêm khuyến mãi")
    f = form_theo_truong(trang.body, "ma_khuyen_mai")
    f.update({"ma_khuyen_mai": "he2026", "ten": "Khuyến mãi hè 2026", "hinh_thuc_giam": "PHAN_TRAM", "gia_tri_giam": "120",
              "muc_giam_toi_da": "150000", "ngay_bat_dau": S["hom_nay"].isoformat(),
              "ngay_ket_thuc": (S["hom_nay"] + timedelta(days=60)).isoformat(), "so_ngay_dat_truoc": "0",
              "bat_buoc_nhap_ma": "on"})
    r = ql.post("/quan-ly/khuyen-mai/them/", f)
    ghi(r.status == 200 and "0-100%" in r.body, "E1: giảm 120% -> lỗi 0-100%")
    f["gia_tri_giam"], f["ma_khuyen_mai"] = "20", "datsom10"
    r = ql.post("/quan-ly/khuyen-mai/them/", f)
    ghi(r.status == 200 and "đã tồn tại" in r.body, "Mã trùng (khác hoa thường) bị từ chối")
    f["ma_khuyen_mai"] = "he2026"
    r = ql.post("/quan-ly/khuyen-mai/them/", f)
    ghi(r.status == 200 and "the=khuyen-mai" in r.url and "Lưu thành công" in r.body,
        "Lưu thành công, chuyển về danh sách khuyến mãi", f"{r.status} {r.url}")
    ghi("HE2026" in r.body and "20%" in r.body and "150.000 đ" in r.body and "Nhập mã" in r.body,
        "Danh sách có HE2026, 20%, tối đa 150.000 đ, nhãn Nhập mã")
    ghi(sql1("select ma_khuyen_mai||'/'||hinh_thuc_giam||'/'||gia_tri_giam from \"tblKhuyenMai\" where ma_khuyen_mai='HE2026'") == "HE2026/PHAN_TRAM/20.00",
        "CSDL: mã được chuẩn hóa in hoa, 20%")
    ghi(sql1("select count(*) from \"tblNhatKyThayDoi\" where hanh_dong='THEM' and loai_doi_tuong='KhuyenMai'") == "1", "Nhật ký ghi THEM khuyến mãi")
    # Sửa KM giữ nguyên mã của chính nó
    km_id = sql1("select id from \"tblKhuyenMai\" where ma_khuyen_mai='HE2026'")
    trang = ql.get(f"/quan-ly/khuyen-mai/{km_id}/sua/")
    f = form_theo_truong(trang.body, "ma_khuyen_mai")
    ghi(f["ma_khuyen_mai"] == "HE2026" and f.get("bat_buoc_nhap_ma") == "on", "Biểu mẫu sửa điền sẵn dữ liệu")
    f["ten"] = "Khuyến mãi hè 2026 (sửa)"
    r = ql.post(f"/quan-ly/khuyen-mai/{km_id}/sua/", f)
    ghi(r.status == 200 and "Lưu thành công" in r.body and "(sửa)" in r.body, "Sửa KM giữ nguyên mã -> không báo trùng")
    ghi(sql1("select count(*) from \"tblNhatKyThayDoi\" where hanh_dong='SUA' and loai_doi_tuong='KhuyenMai'") == "1", "Nhật ký ghi SUA khuyến mãi")


def buoc6_7_dat_ve_an_danh():
    buoc("B06", "Cửa sổ ẩn danh: đặt vé HN-DN, ngày +8, chọn 2 ghế toa 1")
    hom_nay, ngay8 = S["hom_nay"], S["ngay8"]
    an = Browser("an_danh")
    S["an"] = an
    trang = an.get("/dat-ve/")
    ghi(trang.status == 200 and "Tìm chuyến tàu" in trang.body, "Trang đặt vé mở được không cần đăng nhập")
    ghi('href="/accounts/login/' in trang.body and "Đăng nhập" in trang.body, "Menu hiển thị nút Đăng nhập, không có 'Quản lý giá vé'")
    ghi("Quản lý giá vé</a>" not in trang.body, "Khách ẩn danh không thấy menu Quản lý giá vé")
    chuyen_id, r = tim_chuyen_id(an, "HN-DN", ngay8, 2)
    ghi(chuyen_id is not None, f"Tìm HN-DN ngày {ngay8}: có 1 chuyến", cat(r.body))
    S["chuyen"] = chuyen_id
    gia = gia_co_so_seed("HN-DN", "NM", ngay8, hom_nay)
    S["gia_nm"] = gia
    ghi(vnd(gia) in r.body and "40" in r.body, f"Kết quả tìm kiếm có giá thấp nhất {vnd(gia)} và số chỗ trống")
    ghi("20:05" in r.body, "Hiển thị giờ đi 20:05")
    r = an.get(f"/dat-ve/chuyen/{chuyen_id}/", so_hanh_khach=2)
    ghi(r.status == 200 and "40 chỗ trống" in r.body, "Sơ đồ chỗ: 40 chỗ trống", cat(r.body, 300))
    ghi(vnd(gia) in r.body and vnd(gia_co_so_seed("HN-DN", "K4", ngay8, hom_nay)) in r.body, "Giá theo loại chỗ hiển thị trên từng toa")
    ghe = lay_ghe(r.body)
    toa1 = [g for g in ghe if g["ten"].startswith("Toa 1 ")]
    ghi(len(toa1) == 24 and all("seat-trong" in g["cls"] and not g["khoa"] for g in toa1), "Toa 1: 24 ghế, tất cả trống và chọn được")
    S["ghe"] = [toa1[0]["id"], toa1[1]["id"]]
    S["ten_ghe"] = [toa1[0]["ten"], toa1[1]["ten"]]
    r = an.get(f"/dat-ve/chuyen/{chuyen_id}/thong-tin/", ghe=[g["id"] for g in ghe[:7]], follow=True)
    ghi("tối đa 6 chỗ" in r.body, "A3: chọn 7 chỗ bị chặn phía server")

    buoc("B07", "Nhập 2 hành khách (người lớn + sinh viên), mã SV80K -> giữ chỗ")
    r = an.get(f"/dat-ve/chuyen/{chuyen_id}/thong-tin/", ghe=S["ghe"])
    ghi(r.status == 200 and "Hành khách 1" in r.body and "Hành khách 2" in r.body, "Biểu mẫu thông tin hành khách cho 2 ghế")
    ghi(vnd(2 * gia) in r.body, f"Tạm tính giá cơ sở {vnd(2 * gia)}")
    f = form_theo_truong(r.body, "hk-TOTAL_FORMS")
    nguoi = {"ho_ten": "Nguyễn Văn An", "sdt": "0912345678", "email": "an@example.com"}
    hk = [("Nguyễn Văn An", "NGUOI_LON", "012345678901"), ("Trần Thị Bình", "SINH_VIEN", "SV2026001")]
    d = du_lieu_giu_cho(f, S["ghe"], nguoi, hk, ma="sv80k")
    # A4: sai số điện thoại trước
    sai = dict(d, so_dien_thoai="12345")
    r = an.post(f"/dat-ve/chuyen/{chuyen_id}/giu-cho/", sai)
    ghi(r.status == 200 and "Số điện thoại phải gồm 10 chữ số" in r.body and 'value="Trần Thị Bình"' in r.body,
        "A4: SĐT sai -> lỗi đúng trường, dữ liệu hành khách được giữ")
    ghi(sql1('select count(*) from "tblDonDatCho"') == "0", "A4: chưa tạo đơn")
    r = an.post(f"/dat-ve/chuyen/{chuyen_id}/giu-cho/", d, follow=False)
    ghi(r.status == 302 and re.fullmatch(r"/dat-ve/don/[A-Z2-9]{8}/", r.location) is not None, "Giữ chỗ thành công -> chuyển tới trang kết quả", f"{r.status} {r.location}")
    ma = r.location.split("/")[3] if r.status == 302 else None
    S["ma_don"] = ma
    r = an.get(r.location)
    giam_nl = giam_datsom10(gia)
    giam_sv = max(80_000, giam_datsom10(gia))
    tong = (gia - giam_nl) + (gia - giam_sv)
    S["tong7"], S["giam_nl"], S["giam_sv"] = tong, giam_nl, giam_sv
    ghi(ma in r.body and "Đang giữ chỗ" in r.body, "Trang kết quả có mã đặt chỗ và trạng thái 'Đang giữ chỗ'")
    ghi(vnd(tong) in r.body, f"Tổng tiền đúng {vnd(tong)} (= {vnd(gia - giam_nl)} + {vnd(gia - giam_sv)})", cat(r.body, 400))
    ghi(f"-{vnd(giam_nl)}" in r.body and "DATSOM10" in r.body, f"Vé người lớn giảm {vnd(giam_nl)} theo DATSOM10")
    ghi(f"-{vnd(giam_sv)}" in r.body and "SV80K" in r.body, f"Vé sinh viên giảm {vnd(giam_sv)} theo SV80K (lớn hơn 10%)")
    m = re.search(r'data-con-lai="(\d+)"', r.body)
    ghi(m is not None and 0 < int(m.group(1)) <= 15 * 60 and 'id="dem-nguoc"' in r.body, "Đồng hồ đếm ngược còn lại hợp lệ", m.group(1) if m else "không thấy")
    hang = sql("select v.doi_tuong, v.gia_co_so, v.so_tien_giam, v.gia_ve, k.ma_khuyen_mai, v.trang_thai from \"tblVe\" v "
               "join \"tblDonDatCho\" d on d.id=v.don_dat_cho_id left join \"tblKhuyenMai\" k on k.id=v.khuyen_mai_id "
               f"where d.ma_dat_cho='{ma}' order by v.id")
    ghi(hang == [["NGUOI_LON", str(gia), str(giam_nl), str(gia - giam_nl), "DATSOM10", "DANG_GIU"],
                 ["SINH_VIEN", str(gia), str(giam_sv), str(gia - giam_sv), "SV80K", "DANG_GIU"]], "CSDL: 2 vé đúng giá cơ sở/giảm/giá vé/KM", str(hang))
    luot = {m_: int(sql1(f"select so_luot_da_dung from \"tblKhuyenMai\" where ma_khuyen_mai='{m_}'")) for m_ in ("SV80K", "DATSOM10")}
    ghi(luot["SV80K"] == S["luot0"]["SV80K"] + 1 and luot["DATSOM10"] == S["luot0"]["DATSOM10"] + 1, "Lượt dùng KM tăng đúng (SV80K +1, DATSOM10 +1)", str(luot))
    S["luot7"] = luot
    ghi(sql1("select count(*) from \"tblKhuyenMai\" where ma_khuyen_mai='HE2026' and so_luot_da_dung>0") == "0", "HE2026 (bắt buộc nhập mã) không tự áp dụng")


def buoc8_cua_so_thuong():
    buoc("B08", "Cửa sổ thường: cùng chuyến, ghế vừa giữ hiển thị 'Đang giữ' và không chọn được")
    th = Browser("thuong")
    S["th"] = th
    r = th.get(f"/dat-ve/chuyen/{S['chuyen']}/")
    ghe = {g["id"]: g for g in lay_ghe(r.body)}
    for gid, ten in zip(S["ghe"], S["ten_ghe"]):
        g = ghe[gid]
        ghi("seat-dang_giu" in g["cls"] and g["khoa"], f"{ten}: lớp 'seat-dang_giu' và bị vô hiệu hóa")
    ghi("38 chỗ trống" in r.body, "Tổng chỗ trống giảm còn 38")
    ghi("Đang được giữ" in r.body, "Chú thích 'Đang được giữ' trên ô ghế")
    r = th.get(f"/dat-ve/chuyen/{S['chuyen']}/thong-tin/", ghe=S["ghe"][0], follow=True)
    ghi("vừa được người khác giữ" in r.body and r.url.split("?")[0].endswith(f"/dat-ve/chuyen/{S['chuyen']}/"), "Ép vào bước thông tin với ghế đang giữ -> bị trả về sơ đồ kèm thông báo")
    ghi(th.get(f"/dat-ve/don/{S['ma_don']}/").status == 403, "Trình duyệt khác không xem được đơn (403)")
    ghi(sql1('select count(*) from "tblDonDatCho"') == "1", "Chưa có đơn nào khác")
    # A6: giữ chỗ trực tiếp ghế đã bị giữ
    r = th.get(f"/dat-ve/chuyen/{S['chuyen']}/", so_hanh_khach=1)
    ghe_ok = [g["id"] for g in lay_ghe(r.body) if g["ten"].startswith("Toa 1 ") and not g["khoa"]][0]
    form = form_theo_truong(th.get(f"/dat-ve/chuyen/{S['chuyen']}/thong-tin/", ghe=ghe_ok).body, "hk-TOTAL_FORMS")
    d = du_lieu_giu_cho(form, [S["ghe"][0], ghe_ok], {"ho_ten": "Lê Văn Cường", "sdt": "0987654321", "email": ""},
                        [("Lê Văn Cường", "NGUOI_LON", "098765432100"), ("Phạm Thị Dung", "TRE_EM", "TE2026001")])
    r = th.post(f"/dat-ve/chuyen/{S['chuyen']}/giu-cho/", d)
    ghi("Rất tiếc" in r.body and "vừa được người khác giữ hoặc mua" in r.body, "A6: giữ chỗ trùng ghế -> thông báo xung đột chỗ", cat(r.body, 300))
    ghi(sql1('select count(*) from "tblDonDatCho"') == "1" and sql1(f'select count(*) from "tblVe" where chuyen_tau_id={S["chuyen"]}') == "2",
        "A6: hoàn tác toàn bộ - không tạo đơn/vé nào (kể cả ghế còn trống trong cùng yêu cầu)")
    trang = th.get(f"/dat-ve/chuyen/{S['chuyen']}/thong-tin/", ghe=ghe_ok)
    ghi('value="Lê Văn Cường"' in trang.body or "Lê Văn Cường" in trang.body, "A6: thông tin đã nhập được điền lại ở bước kế tiếp")


def buoc9_dong_thoi():
    buoc("B09", "thu_dong_thoi --so-luong 5 -> 1 thành công, 4 ChoDaBiGiu")
    p = manage("thu_dong_thoi", "--so-luong", "5")
    out = p.stdout.decode("utf-8", "replace")
    ghi(p.returncode == 0, "Lệnh chạy xong, exit code 0", p.stderr.decode("utf-8", "replace")[-300:])
    ghi("5 luồng" in out, "In ra 5 luồng", out[:200])
    ghi("Kết quả: 1 thành công, 4 ChoDaBiGiu" in out, "Kết quả: 1 thành công, 4 ChoDaBiGiu", out[-300:])
    ghi("Đúng kỳ vọng" in out, "Lệnh báo 'Đúng kỳ vọng: chỉ một người giữ được chỗ.'")
    ghi(len(re.findall(r"THANH_CONG", out)) == 1 and len(re.findall(r"ChoDaBiGiu", out.split("Kết quả")[0])) == 4, "Chi tiết từng luồng: 1 THANH_CONG, 4 ChoDaBiGiu")
    m = re.search(r"Chuyến #(\d+)", out)
    if m:
        S["chuyen_dt"] = int(m.group(1))
        kq = sql(f'select ghe_ngoi_id, count(*) from "tblVe" where chuyen_tau_id={m.group(1)} and trang_thai in (\'DANG_GIU\',\'DA_THANH_TOAN\') group by 1')
        ghi(len(kq) == 1 and kq[0][1] == "1", "CSDL: đúng 1 vé còn hiệu lực cho ghế tranh chấp", str(kq))
        S["don_dt"] = sql1(f'select d.ma_dat_cho from "tblDonDatCho" d join "tblVe" v on v.don_dat_cho_id=d.id where v.chuyen_tau_id={m.group(1)} limit 1')
    ghi(p.returncode == 0 and "Traceback" not in out + p.stderr.decode("utf-8", "replace"), "Không có traceback")


def buoc10_het_han():
    buoc("B10", "Chờ quá hạn, tải lại trang kết quả và sơ đồ chỗ: HET_HAN, ghế trống lại")
    if ARGS.cho_that:
        print("   (--cho-that) chờ 65 giây cho đơn tự hết hạn...")
        time.sleep(65)
    else:
        sql(f"update \"tblDonDatCho\" set thoi_diem_het_han = now() - interval '1 minute' where ma_dat_cho='{S['ma_don']}'")
    an, th = S["an"], S["th"]
    # Trước khi ai mở trang kết quả: sơ đồ chỗ đã coi ghế là trống (tính theo thời điểm hết hạn)
    r = th.get(f"/dat-ve/chuyen/{S['chuyen']}/")
    ghe = {g["id"]: g for g in lay_ghe(r.body)}
    ghi(all("seat-trong" in ghe[g]["cls"] and not ghe[g]["khoa"] for g in S["ghe"]), "Sơ đồ chỗ: 2 ghế hiển thị Trống ngay cả khi lệnh giải phóng chưa chạy")
    ghi(sql1(f"select trang_thai from \"tblDonDatCho\" where ma_dat_cho='{S['ma_don']}'") == "DANG_GIU", "(đơn vẫn DANG_GIU trong CSDL đến khi có người chạm vào)")
    r = an.get(f"/dat-ve/don/{S['ma_don']}/")
    ghi(r.status == 200 and "Hết hạn" in r.body and "Đã hủy" in r.body, "Trang kết quả: đơn 'Hết hạn', vé 'Đã hủy'")
    ghi('id="dem-nguoc"' not in r.body and "Thanh toán ngay" not in r.body, "Không còn đồng hồ đếm ngược / nút thanh toán")
    ghi(sql1(f"select trang_thai from \"tblDonDatCho\" where ma_dat_cho='{S['ma_don']}'") == "HET_HAN", "CSDL: đơn HET_HAN")
    ghi(sql1(f"select string_agg(v.trang_thai, ',') from \"tblVe\" v join \"tblDonDatCho\" d on d.id=v.don_dat_cho_id where d.ma_dat_cho='{S['ma_don']}'") == "DA_HUY,DA_HUY", "CSDL: 2 vé DA_HUY")
    luot = {m_: int(sql1(f"select so_luot_da_dung from \"tblKhuyenMai\" where ma_khuyen_mai='{m_}'")) for m_ in ("SV80K", "DATSOM10")}
    ghi(luot == S["luot0"], "Lượt KM được hoàn lại đúng (về giá trị ban đầu)", str(luot))
    r = th.get(f"/dat-ve/chuyen/{S['chuyen']}/")
    ghi("40 chỗ trống" in r.body, "Sơ đồ chỗ: 40 chỗ trống trở lại")
    # Thanh toán đơn đã hết hạn bị từ chối
    r = an.post(f"/dat-ve/don/{S['ma_don']}/thanh-toan-gia-lap/", {"csrfmiddlewaretoken": an.csrf()})
    ghi("không còn ở trạng thái đang giữ chỗ" in r.body or "hết thời gian giữ chỗ" in r.body, "Thanh toán đơn hết hạn bị từ chối", cat(r.body, 300))
    # lệnh giai_phong_cho cho đơn của thu_dong_thoi
    if S.get("don_dt"):
        sql(f"update \"tblDonDatCho\" set thoi_diem_het_han = now() - interval '1 minute' where ma_dat_cho='{S['don_dt']}'")
        p = manage("giai_phong_cho")
        o = p.stdout.decode("utf-8", "replace")
        ghi("Đã giải phóng 1 đơn hết hạn" in o, "giai_phong_cho: giải phóng 1 đơn (đơn thu_dong_thoi)", o)
        p = manage("giai_phong_cho")
        ghi("Đã giải phóng 0 đơn hết hạn" in p.stdout.decode("utf-8", "replace"), "giai_phong_cho chạy lần 2: 0 đơn (không hoàn lượt hai lần)")
        luot = {m_: int(sql1(f"select so_luot_da_dung from \"tblKhuyenMai\" where ma_khuyen_mai='{m_}'")) for m_ in ("SV80K", "DATSOM10")}
        ghi(luot == S["luot0"], "Lượt KM vẫn đúng sau hai lần giải phóng", str(luot))


def buoc11_sua_quy_tac_da_dung():
    buoc("B11", "Quản lý sửa quy tắc giá đã dùng -> kết thúc bản cũ, tạo bản mới (E4); vé cũ giữ giá (QT05)")
    ql, an = S["ql"], S["an"]
    qt_id = sql1(f"select v.quy_tac_gia_id from \"tblVe\" v join \"tblDonDatCho\" d on d.id=v.don_dat_cho_id where d.ma_dat_cho='{S['ma_don']}' limit 1")
    S["qt_cu"] = qt_id
    r = ql.get("/quan-ly/gia-ve/", the="gia-ve", tuyen=S["tuyen_dn"], loai_cho=S["nm"])
    ghi("Đã dùng" in r.body, "Danh sách đánh dấu quy tắc 'Đã dùng'")
    trang = ql.get(f"/quan-ly/gia-ve/{qt_id}/sua/")
    ghi(trang.status == 200 and "đã được dùng để tính giá vé" in trang.body, "Biểu mẫu sửa cảnh báo quy tắc đã dùng (sẽ tạo phiên bản mới)")
    f = form_theo_truong(trang.body, "gia_co_so")
    ghi(f["gia_co_so"] in (str(S["gia_nm"]), f"{S['gia_nm']}.00"), "Biểu mẫu điền sẵn giá cũ", f["gia_co_so"])
    f["gia_co_so"], f["ghi_chu"] = "470000", "Tăng giá E4"
    r = ql.post(f"/quan-ly/gia-ve/{qt_id}/sua/", f)
    ghi(r.status == 200 and "Quy tắc cũ đã được kết thúc và tạo phiên bản mới" in r.body, "Thông báo: kết thúc quy tắc cũ, tạo phiên bản mới", cat(r.body, 300))
    cu = sql(f"select trang_thai, ngay_ket_thuc, gia_co_so from \"tblQuyTacGia\" where id={qt_id}")[0]
    ghi(cu[0] == "NGUNG_AP_DUNG" and cu[1] == S["hom_nay"].isoformat() and cu[2] == str(S["gia_nm"]), "Bản cũ NGUNG_AP_DUNG, kết thúc hôm nay, giữ giá cũ", str(cu))
    moi = sql("select id, trang_thai, gia_co_so, ngay_bat_dau, ngay_ket_thuc from \"tblQuyTacGia\" "
              f"where tuyen_duong_id={S['tuyen_dn']} and loai_cho_id={S['nm']} and loai_thoi_diem='NGAY_THUONG' and trang_thai='DANG_AP_DUNG'")
    ghi(len(moi) == 1 and moi[0][2] == "470000" and moi[0][3] == S["hom_nay"].isoformat() and moi[0][4] == "" and moi[0][0] != str(qt_id),
        "Bản mới DANG_AP_DUNG: 470000, hiệu lực từ hôm nay, không giới hạn", str(moi))
    ve_cu = sql(f"select string_agg(gia_co_so::text||'/'||gia_ve::text, ',' order by id) from \"tblVe\" where quy_tac_gia_id={qt_id}")[0][0]
    ghi(ve_cu == f"{S['gia_nm']}/{S['gia_nm'] - S['giam_nl']},{S['gia_nm']}/{S['gia_nm'] - S['giam_sv']}", "Vé cũ giữ nguyên giá đã chốt (QT05)", ve_cu)
    r = an.get(f"/dat-ve/don/{S['ma_don']}/")
    ghi(vnd(S["gia_nm"]) in r.body and vnd(S["tong7"]) in r.body and "470.000 đ" not in r.body, "Trang kết quả của đơn cũ vẫn hiện giá cũ")
    # Đặt vé mới -> giá mới
    chuyen = S["chuyen"]
    ghe = S["ghe"][:1]
    form = form_theo_truong(an.get(f"/dat-ve/chuyen/{chuyen}/thong-tin/", ghe=ghe).body, "hk-TOTAL_FORMS")
    d = du_lieu_giu_cho(form, ghe, {"ho_ten": "Nguyễn Văn An", "sdt": "0912345678", "email": ""}, [("Nguyễn Văn An", "TRE_EM", "TE2026009")])
    r = an.post(f"/dat-ve/chuyen/{chuyen}/giu-cho/", d)
    giam = giam_datsom10(470_000)
    ghi(vnd(470_000 - giam) in r.body, f"Đặt mới sau khi sửa: giá cơ sở 470.000 đ, sau DATSOM10 còn {vnd(470_000 - giam)}", cat(r.body, 300))
    ve_moi = sql("select quy_tac_gia_id, gia_co_so from \"tblVe\" order by id desc limit 1")[0]
    ghi(ve_moi[1] == "470000" and ve_moi[0] == moi[0][0], "Vé mới tham chiếu quy tắc phiên bản mới")
    # E3/E5: ngừng áp dụng + kết thúc khuyến mãi
    trang = ql.get("/quan-ly/gia-ve/them/")
    f = form_theo_truong(trang.body, "gia_co_so")
    f.update({"tuyen_duong": str(S["tuyen_dn"]), "loai_cho": str(S["k4"]), "gia_co_so": "900000", "loai_thoi_diem": "LE_TET",
              "ngay_bat_dau": (S["hom_nay"] + timedelta(days=40)).isoformat(), "ngay_ket_thuc": (S["hom_nay"] + timedelta(days=45)).isoformat(), "ghi_chu": "để thử ngừng"})
    r = ql.post("/quan-ly/gia-ve/them/", f)
    ghi("the=gia-ve" in r.url and "Lưu thành công" in r.body, "Thêm quy tắc LE_TET K4 hợp lệ (tương lai)", f"{r.status} {r.url} {cat(r.body, 200)}")
    nid = sql1("select max(id) from \"tblQuyTacGia\"")
    r = ql.get(f"/quan-ly/gia-ve/{nid}/ngung/")
    ghi(r.status == 200 and "Xác nhận ngừng áp dụng" in r.body, "E3: GET hiển thị trang xác nhận, chưa ngừng")
    ghi(sql1(f"select trang_thai from \"tblQuyTacGia\" where id={nid}") == "DANG_AP_DUNG", "E3: GET không làm thay đổi dữ liệu")
    f = form_theo_truong(r.body, "csrfmiddlewaretoken", "logout")
    r = ql.post(f"/quan-ly/gia-ve/{nid}/ngung/", f)
    ghi("Đã ngừng áp dụng quy tắc giá" in r.body and sql1(f"select trang_thai from \"tblQuyTacGia\" where id={nid}") == "NGUNG_AP_DUNG", "E3: POST ngừng áp dụng thành công")
    km_id = sql1("select id from \"tblKhuyenMai\" where ma_khuyen_mai='HE2026'")
    r = ql.get(f"/quan-ly/khuyen-mai/{km_id}/ket-thuc/")
    ghi(r.status == 200 and "Xác nhận kết thúc" in r.body, "E3: trang xác nhận kết thúc khuyến mãi")
    f = form_theo_truong(r.body, "csrfmiddlewaretoken", "logout")
    r = ql.post(f"/quan-ly/khuyen-mai/{km_id}/ket-thuc/", f)
    ghi("Đã kết thúc chương trình khuyến mãi" in r.body and sql1(f"select trang_thai from \"tblKhuyenMai\" where id={km_id}") == "DA_KET_THUC", "E3: kết thúc khuyến mãi HE2026 thành công")
    ghi(ql.get(f"/quan-ly/khuyen-mai/{km_id}/sua/", follow=True).body.count("đã kết thúc nên không thể sửa") == 1, "Không sửa được KM đã kết thúc")
    ghi(ql.get("/quan-ly/gia-ve/99999/sua/").status == 404 and ql.get("/quan-ly/khuyen-mai/99999/ket-thuc/").status == 404, "id không tồn tại -> 404")
    # dọn đơn mới (không để đơn DANG_GIU làm nhiễu bước sau)
    sql(f"update \"tblDonDatCho\" set thoi_diem_het_han = now() - interval '1 minute' where trang_thai='DANG_GIU'")
    manage("giai_phong_cho")


def buoc12_nhat_ky():
    buoc("B12", "quantri mở /admin/giave/nhatkythaydoi/ -> nhật ký đầy đủ")
    ad = Browser("quantri")
    r = ad.get("/admin/login/?next=/admin/giave/nhatkythaydoi/")
    f = form_theo_truong(r.body, "username")
    f.update({"username": "quantri", "password": "Quantri@123"})
    r = ad.post("/admin/login/?next=/admin/giave/nhatkythaydoi/", f)
    ghi(r.status == 200 and r.url.endswith("/admin/giave/nhatkythaydoi/"), "Đăng nhập quantri vào thẳng trang nhật ký", f"{r.status} {r.url}")
    ghi(r.status == 200 and "nhật ký thay đổi" in r.body.lower(), "Trang danh sách nhật ký thay đổi (Django Admin, tiếng Việt)")
    ghi("quanly" in r.body, "Cột người thực hiện: quanly")
    ghi("Thêm" in r.body and "Ngừng áp dụng" in r.body and "Sửa" in r.body and "Kết thúc" in r.body, "Có đủ các hành động Thêm / Sửa / Ngừng áp dụng / Kết thúc")
    ghi("add/" not in r.body.split('class="object-tools')[-1][:300] if 'class="object-tools' in r.body else True, "Không có nút thêm nhật ký (chỉ đọc)")
    so_dong = sql1('select count(*) from "tblNhatKyThayDoi"')
    hien = re.search(r"(\d+) nhật ký thay đổi", r.body)
    ghi(hien is not None and hien.group(1) == so_dong, f"Số dòng hiển thị khớp CSDL ({so_dong})", hien.group(0) if hien else cat(r.body, 200))
    ids = re.findall(r"/admin/giave/nhatkythaydoi/(\d+)/change/", r.body)
    ghi(len(ids) > 0, "Có liên kết xem chi tiết từng dòng")
    nk = sql1("select id from \"tblNhatKyThayDoi\" where hanh_dong='NGUNG_AP_DUNG' and loai_doi_tuong='QuyTacGia' order by id limit 1")
    r = ad.get(f"/admin/giave/nhatkythaydoi/{nk}/change/")
    ghi(r.status == 200 and "gia_co_so" in r.body and str(S["gia_nm"]) in r.body and "Lưu" not in re.sub(r"<[^>]+>", " ", r.body.split('class="submit-row"')[-1])[:80],
        "Chi tiết nhật ký: có giá trị cũ/mới (gia_co_so), chỉ đọc", cat(r.body, 200))
    ghi(ad.post(f"/admin/giave/nhatkythaydoi/{nk}/delete/", {"csrfmiddlewaretoken": ad.csrf(), "post": "yes"}).status == 403, "Không xóa được nhật ký qua Admin (403)")
    hd = [x[0] for x in sql('select hanh_dong from "tblNhatKyThayDoi" order by id')]
    ghi(hd.count("THEM") >= 3 and "SUA" in hd and "NGUNG_AP_DUNG" in hd and "KET_THUC" in hd, "CSDL nhật ký đủ loại hành động", str(hd))
    r = ad.get("/quan-ly/gia-ve/")
    ghi(r.status == 200, "quantri (superuser) cũng vào được trang quản lý giá")
    ghi(sql1("select count(*) from \"tblNhatKyThayDoi\" n left join \"tblThanhVien\" u on u.id=n.nguoi_thuc_hien_id where u.id is null") == "0", "Mọi dòng nhật ký có người thực hiện")


def luong_uc02_thanh_toan():
    buoc("U02", "UC02 đầy đủ với thanh toán giả lập (HN-SG, toa 2 K4, ngày +9)")
    hom_nay = S["hom_nay"]
    ngay = hom_nay + timedelta(days=9)
    kh = Browser("khach2")
    chuyen_id, r = tim_chuyen_id(kh, "HN-SG", ngay, 2)
    ghi(chuyen_id is not None, "Tìm HN-SG ngày +9 thấy 1 chuyến", cat(r.body, 200))
    gia = gia_co_so_seed("HN-SG", "K4", ngay, hom_nay)
    ghi(vnd(gia_co_so_seed("HN-SG", "NM", ngay, hom_nay)) in r.body and "19:30" in r.body, "Giá thấp nhất (NM) và giờ 19:30 hiển thị")
    r = kh.get(f"/dat-ve/chuyen/{chuyen_id}/", toa="", so_hanh_khach=2)
    toa2_id = re.search(r'data-bs-target="#toa-(\d+)"[^>]*>\s*Toa 2', r.body)
    r = kh.get(f"/dat-ve/chuyen/{chuyen_id}/", toa=toa2_id.group(1) if toa2_id else "", so_hanh_khach=2)
    ghe = [g for g in lay_ghe(r.body) if g["ten"].startswith("Toa 2 ")]
    ghi(len(ghe) == 16 and "giường" in ghe[0]["ten"], "Toa 2 có 16 giường", str(len(ghe)))
    chon = [ghe[4]["id"], ghe[5]["id"]]
    form = form_theo_truong(kh.get(f"/dat-ve/chuyen/{chuyen_id}/thong-tin/", ghe=chon).body, "hk-TOTAL_FORMS")
    d = du_lieu_giu_cho(form, chon, {"ho_ten": "Hoàng Minh Đức", "sdt": "0933445566", "email": "duc@example.com"},
                        [("Hoàng Minh Đức", "NGUOI_LON", "079123456789"), ("Hoàng Gia Hân", "TRE_EM", "TE2026777")])
    r = kh.post(f"/dat-ve/chuyen/{chuyen_id}/giu-cho/", d, follow=False)
    ghi(r.status == 302, "Giữ chỗ 2 giường thành công", f"{r.status}")
    ma = r.location.split("/")[3]
    giam = giam_datsom10(gia)
    r = kh.get(r.location)
    ghi(vnd(2 * (gia - giam)) in r.body, f"Tổng tiền {vnd(2 * (gia - giam))} (DATSOM10 giảm {vnd(giam)}/vé, tối đa 100.000 đ)", cat(r.body, 300))
    f = form_theo_truong(r.body, "csrfmiddlewaretoken", "thanh-toan")
    r = kh.post(f"/dat-ve/don/{ma}/thanh-toan-gia-lap/", f)
    ghi("Thanh toán (giả lập) thành công" in r.body and "Đã thanh toán" in r.body, "Thanh toán giả lập thành công, trạng thái 'Đã thanh toán'")
    ghi(sql1(f"select trang_thai from \"tblDonDatCho\" where ma_dat_cho='{ma}'") == "DA_THANH_TOAN", "CSDL: đơn DA_THANH_TOAN")
    ghi(sql1(f"select string_agg(v.trang_thai, ',') from \"tblVe\" v join \"tblDonDatCho\" d on d.id=v.don_dat_cho_id where d.ma_dat_cho='{ma}'") == "DA_THANH_TOAN,DA_THANH_TOAN", "CSDL: 2 vé DA_THANH_TOAN")
    r = kh.post(f"/dat-ve/don/{ma}/thanh-toan-gia-lap/", {"csrfmiddlewaretoken": f["csrfmiddlewaretoken"]})
    ghi("không còn ở trạng thái đang giữ chỗ" in r.body, "Thanh toán lần hai bị từ chối")
    # người khác thấy ghế 'Đã bán'
    khac = Browser("khach3")
    r = khac.get(f"/dat-ve/chuyen/{chuyen_id}/")
    gh = {g["id"]: g for g in lay_ghe(r.body)}
    ghi(all("seat-da_ban" in gh[c]["cls"] and gh[c]["khoa"] for c in chon), "Người khác thấy 2 giường 'Đã bán' và không chọn được")
    # đơn quá hạn mà chưa thanh toán -> không thanh toán được
    form = form_theo_truong(khac.get(f"/dat-ve/chuyen/{chuyen_id}/thong-tin/", ghe=ghe[0]["id"]).body, "hk-TOTAL_FORMS")
    d = du_lieu_giu_cho(form, [ghe[0]["id"]], {"ho_ten": "Vũ Thị Lan", "sdt": "0944556677", "email": ""}, [("Vũ Thị Lan", "NGUOI_CAO_TUOI", "012345678123")])
    r = khac.post(f"/dat-ve/chuyen/{chuyen_id}/giu-cho/", d, follow=False)
    ma2 = r.location.split("/")[3]
    page = khac.get(r.location)
    f = form_theo_truong(page.body, "csrfmiddlewaretoken", "thanh-toan")
    sql(f"update \"tblDonDatCho\" set thoi_diem_het_han = now() - interval '2 minutes' where ma_dat_cho='{ma2}'")
    r = khac.post(f"/dat-ve/don/{ma2}/thanh-toan-gia-lap/", f)
    ghi("hết thời gian giữ chỗ" in r.body and "Hết hạn" in r.body, "Thanh toán đơn đã hết hạn bị từ chối, đơn chuyển 'Hết hạn'", cat(r.body, 300))
    ghi(sql1(f"select trang_thai from \"tblDonDatCho\" where ma_dat_cho='{ma2}'") == "HET_HAN", "CSDL: đơn quá hạn là HET_HAN")


def kiem_tra_trang_chinh():
    buoc("H01", "Quét tiêu đề tiếng Việt, chuỗi template thô, định dạng tiền ở các trang chính")
    ql, an = Browser("quet_ql"), Browser("quet_an")
    ql.dang_nhap("quanly", "Quanly@123")
    kiem = [
        (an, "/dat-ve/", "Tìm chuyến tàu"),
        (an, "/accounts/login/", "Đăng nhập"),
        (ql, "/quan-ly/gia-ve/", "Quản lý giá vé và khuyến mãi"),
        (ql, "/quan-ly/gia-ve/?the=khuyen-mai", "Quản lý giá vé và khuyến mãi"),
        (ql, "/quan-ly/gia-ve/them/", "Thêm quy tắc giá"),
        (ql, "/quan-ly/khuyen-mai/them/", "Thêm khuyến mãi"),
    ]
    for br, p, tieu_de in kiem:
        r = br.get(p)
        if tieu_de:
            t = re.search(r"<title>(.*?)</title>", r.body, re.S)
            ghi(t is not None and tieu_de in t.group(1), f"{p}: tiêu đề chứa '{tieu_de}'", t.group(1) if t else "không có <title>")
    sua_id = sql1("select id from \"tblQuyTacGia\" where trang_thai='DANG_AP_DUNG' order by id limit 1")
    km_id = sql1("select id from \"tblKhuyenMai\" where ma_khuyen_mai='SV80K'")
    for p, tieu_de in ((f"/quan-ly/gia-ve/{sua_id}/sua/", "Sửa quy tắc giá"), (f"/quan-ly/gia-ve/{sua_id}/ngung/", "Ngừng áp dụng quy tắc giá"),
                       (f"/quan-ly/khuyen-mai/{km_id}/sua/", "Sửa khuyến mãi"), (f"/quan-ly/khuyen-mai/{km_id}/ket-thuc/", "Kết thúc chương trình khuyến mãi")):
        r = ql.get(p)
        t = re.search(r"<title>(.*?)</title>", r.body, re.S)
        ghi(r.status == 200 and t is not None and tieu_de in t.group(1), f"{p}: tiêu đề '{tieu_de}'", f"{r.status} {t.group(1) if t else None}")
    r = ql.get("/quan-ly/gia-ve/", the="khuyen-mai")
    ghi(vnd(80_000) in r.body, "Định dạng tiền kiểu Việt Nam (80.000 đ)")


def tong_ket():
    print("\n" + "=" * 70)
    ghi_loi = LOI_HTML
    BUOC_HIEN_TAI[0] = "HTML"
    print("=== Quét HTML toàn bộ phản hồi trong phiên chạy")
    ghi(not ghi_loi, "Mọi trang HTML: không còn {{ / {% thô, không traceback, <title> tiếng Việt, tiền đúng định dạng, UTF-8",
        "; ".join(sorted(set(ghi_loi))[:15]))
    if ARGS.server_log and os.path.exists(ARGS.server_log):
        BUOC_HIEN_TAI[0] = "LOG"
        nd = open(ARGS.server_log, encoding="utf-8", errors="replace").read()
        # Django ghi traceback cho mọi 403 PermissionDenied (hành vi mặc định, có chủ đích) -> chỉ đếm traceback khác
        khoi = re.split(r"(?m)^(?=Forbidden \(Permission denied\)|Internal Server Error|Bad Request|Not Found)", nd)
        co_tb = any("Traceback" in k and not k.startswith("Forbidden (Permission denied)") for k in khoi)
        m5 = re.findall(r'" 5\d\d ', nd)
        ghi(not co_tb and not m5, "Log server không có traceback / mã 5xx", f"traceback={co_tb}, 5xx={len(m5)}")
    for ghi_chu in sorted(set(S.get("ghi_chu", []))):
        print(f"[GHI CHÚ] {ghi_chu}")
    so_pass = sum(1 for k in KET_QUA if k[0] == "PASS")
    so_fail = sum(1 for k in KET_QUA if k[0] == "FAIL")
    print(f"\nTỔNG: {so_pass} PASS, {so_fail} FAIL")
    if so_fail:
        print("\nCác mục FAIL:")
        for k in KET_QUA:
            if k[0] == "FAIL":
                print(f"  - {k[1]}: {k[2]}")
    return 1 if so_fail else 0


def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--db", default="quanlyvetau_qa")
    ap.add_argument("--python", default=None, help="python dùng chạy manage.py (mặc định .venv của dự án)")
    ap.add_argument("--server-log", default=None, help="file log của runserver để kiểm tra traceback")
    ap.add_argument("--cho-that", action="store_true", help="chờ 65 giây (server chạy GIU_CHO_PHUT=1) thay vì dùng psql")
    ARGS = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cac_buoc = [chuan_bi, buoc1_nhan_vien_403, buoc2_danh_sach_loc, buoc3_e1_gia_am, buoc4_e2_trung, buoc5_them_khuyen_mai,
                buoc6_7_dat_ve_an_danh, buoc8_cua_so_thuong, buoc9_dong_thoi, buoc10_het_han, buoc11_sua_quy_tac_da_dung,
                buoc12_nhat_ky, luong_uc02_thanh_toan, kiem_tra_trang_chinh]
    for ham in cac_buoc:
        try:
            ham()
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001 - một bước hỏng không làm dừng cả kịch bản
            ghi(False, f"Bước {ham.__name__} gặp ngoại lệ", f"{type(e).__name__}: {e}")
            traceback.print_exc()
    sys.exit(tong_ket())


if __name__ == "__main__":
    main()
