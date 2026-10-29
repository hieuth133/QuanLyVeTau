/* Sơ đồ chỗ: đếm số ghế chọn, chặn vượt giới hạn mỗi đơn (A3), cập nhật tạm tính giá cơ sở. */
(function () {
  "use strict";
  var form = document.getElementById("form-chon-cho");
  if (!form) return;
  var max = parseInt(form.getAttribute("data-max"), 10) || 6;
  var boxes = Array.prototype.slice.call(form.querySelectorAll('input[name="ghe"]'));
  var list = document.getElementById("ds-da-chon");
  var emptyMsg = document.getElementById("chua-chon");
  var totalEl = document.getElementById("tam-tinh");
  var countEl = document.getElementById("so-da-chon");
  var warn = document.getElementById("canh-bao-toi-da");
  var btn = document.getElementById("nut-tiep-tuc");

  function vnd(n) { return n.toLocaleString("vi-VN") + " đ"; }

  function dangChon() {
    return boxes.filter(function (b) { return b.checked; });
  }

  function refresh() {
    var chon = dangChon();
    var tong = 0;
    list.innerHTML = "";
    chon.forEach(function (b) {
      var gia = parseInt(b.getAttribute("data-gia"), 10) || 0;
      tong += gia;
      var li = document.createElement("li");
      var a = document.createElement("span");
      a.textContent = b.getAttribute("data-ten");
      var c = document.createElement("span");
      c.className = "text-money text-muted";
      c.textContent = vnd(gia);
      li.appendChild(a);
      li.appendChild(c);
      list.appendChild(li);
    });
    emptyMsg.classList.toggle("d-none", chon.length > 0);
    totalEl.textContent = vnd(tong);
    countEl.textContent = chon.length + "/" + max;
    btn.disabled = chon.length === 0;
  }

  boxes.forEach(function (b) {
    b.addEventListener("change", function () {
      if (dangChon().length > max) {
        b.checked = false;
        warn.classList.remove("d-none");
        window.setTimeout(function () { warn.classList.add("d-none"); }, 4000);
      } else {
        warn.classList.add("d-none");
      }
      refresh();
    });
  });

  form.addEventListener("submit", function (e) {
    var n = dangChon().length;
    if (n === 0 || n > max) { e.preventDefault(); }
  });
  refresh();
})();
