from django.urls import path

from . import views

urlpatterns = [
    path("gia-ve/", views.QuanLyGiaVeView.as_view(), name="quan_ly_gia_ve"),
    path("gia-ve/them/", views.QuyTacGiaView.as_view(), name="quy_tac_them"),
    path("gia-ve/<int:id>/sua/", views.QuyTacGiaView.as_view(), name="quy_tac_sua"),
    path("gia-ve/<int:id>/ngung/", views.NgungApDungView.as_view(), name="quy_tac_ngung"),
    path("khuyen-mai/them/", views.KhuyenMaiView.as_view(), name="khuyen_mai_them"),
    path("khuyen-mai/<int:id>/sua/", views.KhuyenMaiView.as_view(), name="khuyen_mai_sua"),
    path("khuyen-mai/<int:id>/ket-thuc/", views.KetThucKhuyenMaiView.as_view(), name="khuyen_mai_ket_thuc"),
]
