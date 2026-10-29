/* Đồng hồ đếm ngược đến hết hạn giữ chỗ; về 0 thì tự tải lại trang để thấy trạng thái HET_HAN (A7). */
(function () {
  "use strict";
  var el = document.getElementById("dem-nguoc");
  if (!el) return;
  var conLai = parseInt(el.getAttribute("data-con-lai"), 10);
  if (isNaN(conLai)) return;
  var ketThuc = Date.now() + conLai * 1000;

  function dinhDang(giay) {
    var m = Math.floor(giay / 60), s = giay % 60;
    return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  function tick() {
    var giay = Math.max(0, Math.ceil((ketThuc - Date.now()) / 1000));
    el.textContent = dinhDang(giay);
    el.classList.toggle("low", giay <= 60);
    if (giay <= 0) {
      el.textContent = "Hết hạn";
      window.setTimeout(function () { window.location.reload(); }, 1500);
      return;
    }
    window.setTimeout(tick, 250);
  }
  tick();
})();
