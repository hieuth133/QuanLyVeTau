from django.contrib.auth.views import LogoutView


class DangXuatView(LogoutView):
    """Đăng xuất nhưng giữ lại danh sách đơn đặt chỗ của trình duyệt (session['don_cua_toi']).

    Đăng xuất làm session.flush(); nếu không giữ lại, khách vừa giữ chỗ sẽ không xem/thanh toán được đơn của mình."""

    def post(self, request, *args, **kwargs):
        don_cua_toi = list(request.session.get("don_cua_toi", []))
        response = super().post(request, *args, **kwargs)
        if don_cua_toi:
            request.session["don_cua_toi"] = don_cua_toi
        return response
