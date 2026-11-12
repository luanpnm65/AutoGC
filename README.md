# Grow Castle Auto cho BlueStacks 5 (hỗ trợ cả LDPlayer 9)

Tool Python đọc màn hình Grow Castle để đánh wave tiếp theo, Skip 30 hoặc Replay, kích hoạt kỹ năng đã hồi, tự nâng cấp Hero hoặc Tháp bằng kim cương và xem quảng cáo thưởng vàng. Với `--auto-captcha`, auto play tự thử giải CAPTCHA rồi tiếp tục khi nhận ra màn game đã trở lại. Tool mặc định chạy cho **BlueStacks 5** (kể cả cài ổ đĩa tùy chỉnh và chạy nhiều cửa sổ **Multi-Instance** cùng lúc) và vẫn giữ tương thích với **LDPlayer 9**.

## 1. Cài đặt

- **Windows** với Python 3.10 trở lên. Chế độ đọc video dùng Windows Media Foundation.
- **BlueStacks 5** cho chế độ chạy trực tiếp:
  - Trong **Settings → Display**: chọn **Landscape**, độ phân giải **1280 × 720 (16:9)** và **240 DPI** cho từng instance để khớp với ảnh mẫu trong `video2.mp4`.
  - Trong **Settings → Advanced**: bật **Android Debug Bridge (ADB)** cho mọi instance cần chạy auto.
- **NumPy** và **Pillow** được liệt kê trong [requirements.txt](requirements.txt). Giữ [play_templates.npz](play_templates.npz) và [tower_templates.npz](tower_templates.npz) cùng thư mục với mã nguồn.

Mở PowerShell và chạy các lệnh sau (thay `D:\AutoGC` bằng thư mục dự án của bạn):

```powershell
Set-Location 'D:\AutoGC'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Chạy thử trên video

```powershell
.\.venv\Scripts\python.exe autoplay.py --video video2.mp4
.\.venv\Scripts\python.exe autoplay.py --video video2.mp4 --mode replay
.\.venv\Scripts\python.exe captcha.py video1.mp4
```

- `video2.mp4` có đoạn đánh wave, xem quảng cáo nhận vàng và chơi Replay. Auto play in các hành động dự kiến với tiền tố `PREVIEW`.
- `video1.mp4` có ba lượt CAPTCHA. `captcha.py` in thời gian, vị trí cốc ban đầu, vị trí dự đoán cuối và số khung hình hỗ trợ dự đoán.

## 3. Chạy trên BlueStacks 5

Tool **tự động dò đường dẫn cài đặt BlueStacks 5** (`HD-Adb.exe` và `bluestacks.conf`) qua Windows Registry, tiến trình đang chạy và các ổ đĩa (`C:`, `D:`, `E:`, ...) kể cả khi bạn cài ở ổ đĩa/thư mục tùy chỉnh. Tool cũng **tự động `adb connect`** tới cổng TCP hiện hành (`status.adb_port`) của từng instance.

1. Mở Grow Castle trên BlueStacks 5 và để game ở màn chính có nút **Battle** và **Replay**. Tự đóng các hộp thoại lạ đang che màn hình (như hộp vật phẩm **Staff**).
2. Kiểm tra danh sách các instance BlueStacks 5 mà tool nhận diện được:

```powershell
.\.venv\Scripts\python.exe autoplay.py --list
```

Lệnh `--list` hiển thị đường dẫn `HD-Adb.exe`, `bluestacks.conf`, cùng danh sách từng instance (`--index`, `--instance`, tiêu đề cửa sổ, cổng `127.0.0.1:<port>` và trạng thái cửa sổ).

### Khi chỉ mở 1 cửa sổ BlueStacks 5

Nếu trên máy chỉ đang mở đúng một cửa sổ BlueStacks 5, tool tự chọn cửa sổ đó mà không cần truyền thêm tham số định danh:

```powershell
# Xem trước tool sẽ bấm gì trong 15 giây
.\.venv\Scripts\python.exe autoplay.py --seconds 15

# Bấm thật, bắt đầu bằng wave mới
.\.venv\Scripts\python.exe autoplay.py --tap

# Bấm thật, bắt đầu bằng Replay 100%
.\.venv\Scripts\python.exe autoplay.py --mode replay --tap

# Bấm thật, bật chế độ Skip 30 WAVES khi kim cương trắng >= 30
.\.venv\Scripts\python.exe autoplay.py --mode skip --tap
```

### Khi chạy nhiều cửa sổ cùng lúc (Multi-Instance)

Mở một cửa sổ PowerShell riêng cho mỗi giả lập cần chạy và chỉ định giả lập qua `--instance` (khóa nội bộ như `Pie64`, `Pie64_1`, `Rvc64_1` hoặc tên đặt trong Multi-Instance Manager), `--index` hoặc `--serial`:

```powershell
# PowerShell 1 — điều khiển instance đầu tiên
.\.venv\Scripts\python.exe autoplay.py --instance Pie64 --tap --auto-captcha

# PowerShell 2 — điều khiển instance thứ hai chạy song song
.\.venv\Scripts\python.exe autoplay.py --instance Pie64_1 --tap --auto-captcha

# Hoặc chọn theo tên hiển thị của cửa sổ / theo số thứ tự / theo serial ADB:
.\.venv\Scripts\python.exe autoplay.py --instance "BlueStacks App Player 1" --tap
.\.venv\Scripts\python.exe autoplay.py --index 1 --tap
.\.venv\Scripts\python.exe autoplay.py --serial 127.0.0.1:5565 --tap
```

Nếu bạn dùng bản BlueStacks 5 di động không ghi Registry, có thể chỉ định trực tiếp đường dẫn bằng `--adb "D:\BlueStacks_nxt\HD-Adb.exe"` và `--conf "D:\BlueStacks_nxt\bluestacks.conf"`.

Chỉ `--tap` mới gửi thao tác bấm. Mỗi instance có khóa phiên riêng (`.autoplay-*.lock`) và nhật ký nâng cấp riêng (`.hero-upgrade-*.json` hoặc `.tower-upgrade-*.json`) theo tên instance nên nhiều phiên chạy song song không xung đột nhau, kể cả khi BlueStacks đổi cổng ADB động sau lần khởi động lại. Trước mỗi cú bấm, tool đều xác nhận Grow Castle đang là ứng dụng hiển thị trên thiết bị đó. Dùng `Ctrl+C` để dừng hoặc thêm `--seconds 60` để giới hạn thời gian chạy.

## 4. Auto play hoạt động thế nào

| Tình huống | Hành động |
| --- | --- |
| Màn chính | Tool nhận diện các nút từ ảnh mẫu và bấm **Battle** hoặc **Replay** theo chế độ đang chạy. Trong menu Replay, tool chọn ô **100%**. |
| Đang đánh | Nhận diện cả thanh tiến trình **WAVE** lẫn thanh máu **BOSS** (dù đầy máu hay cạn máu), theo dõi thanh hồi kỹ năng của **2 đơn vị bên trái tháp** (ưu tiên bấm trước) cùng **9 ô Hero** trên tháp. Khi thanh xanh đầy, tool bấm một lần và chờ thanh rời trạng thái đầy trước khi bấm lại ở lần hồi tiếp theo. |
| Rương **Mimic** | Ở mọi chế độ auto (`wave`, `replay`, màn thường, màn Boss hay màn chính), khi thấy rương **Mimic** mở miệng có bàn tay chỉ vào trên sân, tool ưu tiên bấm trực tiếp vào rương để nhận thưởng ngay. |
| Hộp **Wave Skip** | Mặc định bấm **X** để đóng hộp và tiếp tục đánh. Khi bật `--mode skip` (hoặc `--skip`), nếu số **kim cương trắng** trên thanh đầu màn hình từ **30 trở lên** (bỏ qua phần cộng thêm màu cam như `+500`), tool chọn **30 WAVES** thay vì đóng hộp; nếu dưới 30 thì bấm **X** như bình thường. |
| **Victory** | Tool chờ về màn chính, ưu tiên hộp thưởng vàng nếu đã bật tự xem quảng cáo, rồi tiếp tục theo chế độ hiện tại. |
| HP lâu đài về **0** | Tool nhận diện số 0 cùng thanh HP cạn, chuyển từ wave sang Replay và giữ Replay đến khi kết thúc phiên chạy. |
| **CAPTCHA** | Tool tạm dừng đánh. Nếu bật `--auto-captcha`, tool thử chọn một lần. Khi cần giải tay, auto play chờ bạn xử lý rồi tiếp tục. |
| Màn hình chưa nhận diện | Tool chờ. Nếu đang có hộp thoại lạ, hãy tự xử lý để game quay lại màn đã biết. |

Tool lấy ảnh qua ADB, chuẩn hóa ảnh về 1280 × 720 để đối chiếu mẫu, rồi quy đổi tọa độ bấm theo kích thước ảnh thật.

### Nâng Hero hoặc Tháp bằng kim cương

Tính năng mặc định tắt. Dùng `--upgrade-hero [SỐ_KC]` (nâng Hero gắn ở ô góc trên bên phải của lâu đài) hoặc `--upgrade-tower [SỐ_KC]` (nâng tầng tháp thứ hai từ dưới lên) kết hợp cùng bất kỳ chế độ đánh nào (`wave`, `skip`, `replay`). Nếu không truyền số theo sau thì mặc định kích hoạt ở mốc **50 kim cương trắng**.

```powershell
# Chạy Wave và tự nâng Hero góc trên bên phải khi kim cương trắng >= 50 (mặc định)
.\.venv\Scripts\python.exe autoplay.py --tap --upgrade-hero

# Tự chọn mốc kim cương trắng để bắt đầu nâng (ví dụ đủ 30 hoặc 80 kim cương trắng là nâng)
.\.venv\Scripts\python.exe autoplay.py --mode replay --tap --upgrade-hero 30
.\.venv\Scripts\python.exe autoplay.py --instance Pie64_1 --mode replay --tap --upgrade-hero 80

# Chạy Wave và tự nâng Tháp khi kim cương trắng >= 60
.\.venv\Scripts\python.exe autoplay.py --tap --upgrade-tower 60
```

1. Khi thấy số **kim cương trắng đạt mốc đã chọn** (mặc định `50`, tự bỏ qua phần kim cương cộng thêm màu cam như `+500`):
   - Với `--upgrade-hero`: tool bấm vào **ô Hero góc trên bên phải** `(461, 92)` để mở bảng thông tin của bất kỳ Hero nào đang gắn tại ô đó.
   - Với `--upgrade-tower`: tool bấm ô chuyển tầng tháp `(380, 457)` rồi mở ô tầng tháp thứ hai từ dưới lên `(380, 366)`.
2. Tool đọc cấp hiện tại và giá kim cương trên nút **LV UP** (`💎 1`, `2` hoặc `3` kim cương) tại `(896, 470)`, tiếp tục nâng bình thường kể cả khi thanh `LV UP +10 / +100 / +1000` bật thêm ở phía dưới sau 10 lần bấm.
3. Sau mỗi lần bấm, tool xác nhận cấp tăng đúng 1 và số kim cương trắng giảm đúng giá vừa đọc. Đợt nâng kết thúc khi đủ số cấp mục tiêu (`max(50, mốc kim cương)`, hoặc tùy chỉnh bằng `--upgrade-levels`), hoặc dừng sớm ngay khi số kim cương trắng còn lại nhỏ hơn giá nâng tiếp theo để **không bao giờ trừ lẹm vào phần kim cương cam (`+500`)**.
4. Tool bấm nút **X** `(994, 160)` để đóng bảng thông tin Hero/Tháp, bấm tiếp nút **X** `(1247, 76)` để đóng danh sách Hero/Tháp bên phải (khôi phục lại giao diện ô Hero nếu vừa nâng Tháp), rồi tiếp tục đánh theo chế độ đang chọn.

### Quảng cáo thưởng vàng

Tool mặc định tự xem quảng cáo thưởng vàng. Dùng `--ads` để bật hoặc `--no-ads` để bỏ qua **GET** và tiếp tục chơi. Cả hai tùy chọn dùng được với Wave, Skip, Replay, `--auto-captcha`, `--upgrade-hero` và `--upgrade-tower`.

```powershell
# Chạy Wave và tự xem quảng cáo
.\.venv\Scripts\python.exe autoplay.py --mode wave --tap --ads

# Chạy Wave và bỏ qua quảng cáo
.\.venv\Scripts\python.exe autoplay.py --mode wave --tap --no-ads
```

1. Sau khi thắng, tool chờ hộp thưởng xuất hiện trước khi đánh tiếp, nhận diện biểu tượng vàng cùng nút **GET** (có hoặc không có dòng đếm ngược) rồi bấm một lần.
2. Khi cửa sổ quảng cáo đang hiển thị (AdMob, UnityAds, AppLovin, IronSource, Vungle, Mintegral...), tool tạm dừng vào trận, dùng kỹ năng, giải CAPTCHA và nâng tháp.
3. Khi quảng cáo phát xong, tool kết hợp 4 lớp để đóng quảng cáo trên cả **màn hình ngang (`16:9`) lẫn quảng cáo xoay dọc (`9:16`)**, hỗ trợ cả **Tiếng Việt lẫn Tiếng Anh**:
   - Đối chiếu nhanh các mẫu ảnh kết thúc quen thuộc (**Reward granted**, **Learn More**, **Watch now**).
   - Đọc trực tiếp cây giao diện Android (`uiautomator dump`) để lấy tọa độ thật của nút **Đóng / Close / Bỏ qua / Skip / `>>` / `✕`** hoặc nút cạnh nhãn *Đã trao phần thưởng* (tự chờ nếu còn bộ đếm ngược, và tự bấm **Tiếp tục xem / Resume** nếu hiện hộp thoại cảnh báo mất thưởng).
   - Dò hình học biểu tượng nút **`X`** ở góc trên màn hình cho các quảng cáo WebGL/Canvas không xuất cây UI.
   - Tự gửi phím **BACK** của Android nếu quảng cáo tự bật bảng Google Play đè lên hoặc bị kẹt ở màn kết thúc sau khi đã hết giờ.
4. Game tự cộng vàng khi quay lại màn chính (`gold HUD changed`).

### Tự giải CAPTCHA trong auto play

```powershell
# Đánh wave mới và tự giải CAPTCHA
.\.venv\Scripts\python.exe autoplay.py --mode wave --tap --auto-captcha

# Replay trên nhiều instance và tự giải CAPTCHA
.\.venv\Scripts\python.exe autoplay.py --instance Pie64_1 --mode replay --tap --auto-captcha
```

Tool hỗ trợ 3 tầng thu hình CAPTCHA theo thứ tự ưu tiên:
1. **Chụp khung game 16:9 của cửa sổ BlueStacks 5** (hoạt động cho cả các cửa sổ xếp cạnh nhau trên màn hình dù không phải cửa sổ đang active chuột, hoặc qua `PrintWindow` khi bị che trên chế độ DirectX).
2. **Ghi hình ngắn qua `adb shell screenrecord`** bên trong Android nếu cửa sổ đang thu nhỏ hoặc không chụp được.
3. **Luồng `adb exec-out screencap` thô tốc độ cao** nếu bản Android của BlueStacks 5 không hỗ trợ bộ mã hóa video của `screenrecord` (tool tự đo tốc độ khung hình trước khi bấm **Start** để không làm mất lượt nếu máy quá tải).

Khi tool đã bắt đầu lượt mà chưa gửi được cú chọn cốc, bản ghi được lưu trong `logs` (MP4 hoặc NPZ) để kiểm tra lại bằng `captcha.py`.

### Bộ dò CAPTCHA độc lập

```powershell
# Liệt kê các cửa sổ BlueStacks 5
.\.venv\Scripts\python.exe bluestacks_captcha.py --list

# Quan sát CAPTCHA trực tiếp từ một cửa sổ BlueStacks 5
.\.venv\Scripts\python.exe bluestacks_captcha.py --instance Pie64

# Thử bấm đúng một lần rồi thoát, sau khi xác minh bàn cốc qua ADB
.\.venv\Scripts\python.exe bluestacks_captcha.py --instance Pie64 --tap
```

## 5. Chạy trên LDPlayer 9

Nếu vẫn muốn chạy trên LDPlayer 9, thêm `--emulator ldplayer` hoặc truyền đường dẫn `--ldconsole` như trước:

```powershell
.\.venv\Scripts\python.exe autoplay.py --emulator ldplayer --index 0 --tap
.\.venv\Scripts\python.exe autoplay.py --ldconsole "D:\LDPlayer\LDPlayer9\ldconsole.exe" --index 0 --tap
.\.venv\Scripts\python.exe ldplayer_captcha.py --index 0 --tap
```
