from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations

SQL_TAO = """
ALTER TABLE "tblQuyTacGia" ADD CONSTRAINT ex_quy_tac_khong_trung
  EXCLUDE USING gist (
    tuyen_duong_id WITH =, loai_cho_id WITH =, loai_thoi_diem WITH =,
    daterange(ngay_bat_dau, ngay_ket_thuc, '[]') WITH &&
  ) WHERE (trang_thai = 'DANG_AP_DUNG');
"""
SQL_XOA = 'ALTER TABLE "tblQuyTacGia" DROP CONSTRAINT ex_quy_tac_khong_trung;'


class Migration(migrations.Migration):
    dependencies = [("giave", "0001_initial")]
    operations = [
        BtreeGistExtension(),
        migrations.RunSQL(SQL_TAO, SQL_XOA),
    ]
