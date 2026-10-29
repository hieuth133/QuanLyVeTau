from django.urls import path

from . import views

urlpatterns = [
    path("", views.TimChuyenView.as_view(), name="tim_chuyen"),
    path("chuyen/<int:chuyen_id>/", views.ChonChoView.as_view(), name="chon_cho"),
    path("chuyen/<int:chuyen_id>/thong-tin/", views.ThongTinHanhKhachView.as_view(), name="thong_tin"),
    path("chuyen/<int:chuyen_id>/giu-cho/", views.GiuChoView.as_view(), name="giu_cho"),
    path("don/<str:ma_dat_cho>/", views.KetQuaGiuChoView.as_view(), name="ket_qua"),
    path("don/<str:ma_dat_cho>/thanh-toan-gia-lap/", views.ThanhToanGiaLapView.as_view(), name="thanh_toan_gia_lap"),
]
