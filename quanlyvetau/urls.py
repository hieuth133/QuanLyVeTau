from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from taikhoan.views import DangXuatView

admin.site.site_header = "Quản trị Bán vé tàu"
admin.site.site_title = "Quản trị Bán vé tàu"
admin.site.index_title = "Dữ liệu hệ thống"

urlpatterns = [
    path("", RedirectView.as_view(url="/dat-ve/", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/logout/", DangXuatView.as_view(), name="logout"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("quan-ly/", include("giave.urls")),
    path("dat-ve/", include("datve.urls")),
]
