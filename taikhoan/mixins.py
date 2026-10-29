from django.contrib.auth.mixins import UserPassesTestMixin


class VaiTroRequiredMixin(UserPassesTestMixin):
    """Chỉ cho phép người dùng có vai trò trong `vai_tro_cho_phep` (superuser luôn được phép).

    Dùng cùng LoginRequiredMixin: chưa đăng nhập -> chuyển tới trang đăng nhập,
    đã đăng nhập nhưng không đủ quyền -> HTTP 403 (template 403.html)."""

    vai_tro_cho_phep: list[str] = []

    def test_func(self):
        u = self.request.user
        return u.is_authenticated and (u.is_superuser or u.vai_tro in self.vai_tro_cho_phep)
