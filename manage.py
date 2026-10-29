#!/usr/bin/env python
"""Công cụ dòng lệnh của Django cho dự án Quản lý bán vé tàu."""
import os
import sys


def _dung_utf8_khi_chuyen_huong():
    """Khi đầu ra bị chuyển hướng (pipe/file) trên Windows, mặc định là cp1252 và không in được tiếng Việt."""
    for luong in (sys.stdout, sys.stderr):
        try:
            if luong is not None and not luong.isatty():
                luong.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    _dung_utf8_khi_chuyen_huong()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quanlyvetau.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Không import được Django. Hãy kích hoạt môi trường ảo (.venv) và cài requirements.txt."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
