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

# Bấm thật, bật chế độ Skip WAVES (chọn 10, 20 hoặc mặc định 30 khi đủ kim cương trắng tương ứng)
.\.venv\Scripts\python.exe autoplay.py --skip --tap
.\.venv\Scripts\python.exe autoplay.py --skip 20 --tap
.\.venv\Scripts\python.exe autoplay.py --skip 10 --tap
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
| Hộp **Wave Skip** | Mặc định bấm **X** để đóng hộp và tiếp tục đánh. Khi bật `--skip [10\|20\|30]` (mặc định `30` nếu không truyền số, hoặc `--mode skip` / `skip10` / `skip20` / `skip30`), nếu số **kim cương trắng** trên thanh đầu màn hình đạt từ mốc đã chọn trở lên (`>= 10`, `20` hoặc `30`, bỏ qua phần cộng thêm màu cam như `+500`), tool chọn đúng nút **10 / 20 / 30 WAVES**; nếu chưa đủ thì bấm **X** như bình thường. |
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

# Tự chọn mốc kim cương trắng để bắt đầu nâng Hero (ví dụ đủ 30 hoặc 80 kim cương trắng là nâng)
.\.venv\Scripts\python.exe autoplay.py --mode replay --tap --upgrade-hero 30
.\.venv\Scripts\python.exe autoplay.py --instance Pie64_1 --mode replay --tap --upgrade-hero 80

# Tự nâng Tháp (tầng 2 từ dưới lên) ở mốc mặc định 50 hoặc tự chọn mốc 30 / 60 kim cương trắng
.\.venv\Scripts\python.exe autoplay.py --tap --upgrade-tower
.\.venv\Scripts\python.exe autoplay.py --mode replay --tap --upgrade-tower 30
.\.venv\Scripts\python.exe autoplay.py --tap --upgrade-tower 60
```

1. Khi thấy số **kim cương trắng đạt mốc đã chọn** (mặc định `50`, tự bỏ qua phần kim cương cộng thêm màu cam như `+500`):
   - Với `--upgrade-hero`: tool bấm vào **ô Hero góc trên bên phải** `(461, 92)` để mở bảng thông tin của bất kỳ Hero nào đang gắn tại ô đó.
   - Với `--upgrade-tower`: tool bấm ô chuyển tầng tháp `(380, 457)` rồi mở ô tầng tháp thứ hai từ dưới lên `(380, 366)` (nhận diện mọi loại tháp lâu đài đang gắn tại ô đó như Lightning, Minigun, Ballista, Cannon, Shield, Gold...).
2. Tool đọc cấp hiện tại và giá kim cương trên nút **LV UP** (`💎 1`, `2` hoặc `3` kim cương) tại `(896, 470)`. Sau khi nâng 10 cấp và thanh **`LV UP +10`** bật lên ở phía dưới, nếu số kim cương trắng còn lại đủ cho nút **LV UP +10** (`💎 10`, `20`...) và số cấp cần nâng còn từ `10` trở lên thì tool tự động bấm **LV UP +10** `(405, 628)` để tiết kiệm thời gian; khi kim cương trắng còn ít hơn giá `+10` thì tự quay về bấm **LV UP** đơn cho đến hết kim cương trắng.
3. Sau mỗi lần bấm (`+1` hoặc `+10`), tool xác nhận cấp tăng đúng tương ứng và số kim cương trắng giảm đúng giá vừa đọc. Đợt nâng kết thúc khi đủ số cấp mục tiêu (`max(50, mốc kim cương)`, hoặc tùy chỉnh bằng `--upgrade-levels`), hoặc dừng sớm ngay khi số kim cương trắng còn lại nhỏ hơn giá nâng tiếp theo để **không bao giờ trừ lẹm vào phần kim cương cam (`+500`)**.
4. Tool bấm nút **X** `(994, 160)` để đóng bảng thông tin Hero/Tháp, bấm tiếp nút **X** `(1247, 76)` để đóng danh sách Hero/Tháp bên phải (khôi phục lại giao diện ô Hero nếu vừa nâng Tháp), rồi tiếp tục đánh theo chế độ đang chọn. Nếu có cú bấm bị hụt nhịp hoặc gặp bất kỳ lỗi đọc số liệu nào giữa chừng, tool tự động thử bấm lại hoặc đóng toàn bộ bảng nâng cấp để thoát ra màn chính và tiếp tục đi wave theo chế độ đã chọn (không bị kẹt lại trong bảng nâng cấp).

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

### Tự giải CAPTCHA cốc kim cương

Tính năng **mặc định bật sẵn** mỗi khi chạy kèm `--tap` (có thể truyền rõ `--auto-captcha` hoặc tắt bằng `--no-auto-captcha`).

```powershell
# Tự đánh + tự nâng Hero + tự giải CAPTCHA (mặc định bật sẵn khi có --tap)
.\.venv\Scripts\python.exe autoplay.py --serial 127.0.0.1:5555 --mode replay --tap --upgrade-hero 30

# Nếu muốn tắt tự giải CAPTCHA để tự chọn bằng tay
.\.venv\Scripts\python.exe autoplay.py --mode wave --tap --no-auto-captcha
```

Tool hỗ trợ 3 tầng thu hình CAPTCHA theo thứ tự ưu tiên để đạt độ chính xác cao nhất:
1. **Quay trực tiếp 60 FPS bên trong Android qua `adb shell screenrecord` (ưu tiên mặc định)**: lấy trọn vẹn chuyển động ~60 FPS mượt mà, **hoàn toàn không dính các nút phím ảo (`B`, `N`, `M`) của BlueStacks**, không bị đen hình trên OpenGL/Vulkan và giải được ngay cả khi cửa sổ giả lập đang bị cửa sổ khác che khuất hoặc chạy nhiều instance cùng lúc.
2. **Luồng `adb exec-out screencap` thô tốc độ cao** nếu bản Android của giả lập không hỗ trợ `screenrecord`.
3. **Chụp khung game 16:9 của cửa sổ giả lập trên Windows** làm phương án dự phòng cuối.

Nếu một lượt tráo quá chồng lấp chưa đủ độ tin cậy hoặc hiện lại nút **START**, tool tự thử lại tối đa 3 lần trước khi tạm dừng chờ người chơi. Tối đa 10 bản ghi `.mp4` chưa chọn gần nhất được giữ trong `logs` để kiểm tra lại bằng `captcha.py`.

### Kỹ năng hồi máu khẩn cấp Smith & cơ chế giả lập thao tác người thật (`--humanize`)

- **Tự cast Smith khi máu lâu đài `< 50%`**: Tool theo dõi thanh hồi chiêu của ô Hero **hàng trên cùng ở giữa** `(373, 92)` và mức máu tại mốc `50%` của thanh **Castle HP**. Khi máu `>= 50%` tool giữ nguyên không bấm phí; ngay khi máu tụt `< 50%` sẽ ưu tiên bấm Smith trước tiên.
- **Mặc định bật `--humanize` khi chạy `--tap`** (có thể tắt bằng `--no-humanize`):
  - Biến thiên tọa độ chạm theo phân phối chuẩn nằm gọn trong vùng an toàn của từng nút, kết hợp thời gian giữ ngón tay tự nhiên (`46–162ms`) và độ trượt vi mô (`0–2px`) thay vì lệnh `input tap` `0ms` cố định 1 điểm ảnh.
  - Xáo trộn thứ tự bấm giữa các kỹ năng cùng nhóm ưu tiên (vẫn giữ **Smith khẩn cấp → 2 kỹ năng Town Archer bên trái → 9 Hero**), ngẫu nhiên hóa nhịp phản xạ giữa các lần bấm, nhịp nâng cấp và tự nghỉ ngắn vài giây ở màn chính sau mỗi `18–32` trận.
  - Đặt tên file quay tạm trung lập trong Android (`/data/local/tmp/scr_*.mp4`) và tự xóa sạch sau mỗi lượt CAPTCHA.

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

## 6. Tổng hợp nhanh các cờ dòng lệnh (`autoplay.py`)

| Nhóm | Cờ | Mặc định | Tác dụng ngắn gọn |
| --- | --- | --- | --- |
| **Chế độ chạy** | `--tap` | Tắt (`PREVIEW`) | Gửi thao tác bấm thật vào giả lập. |
| | `--mode {wave,replay,skip,skip10,skip20,skip30}` | `wave` | Chọn chế độ: đi `wave` mới, đánh lại `replay` 100%, hoặc đi wave kèm `skip` (`30` / `10` / `20`). |
| | `--skip [{10,20,30}]` | Tắt (`30` nếu bật không số) | Chọn mốc **10**, **20** hoặc **30 WAVES** ở hộp Wave Skip khi kim cương trắng `>=` mốc đã chọn. |
| | `--seconds N` | `0` (vô hạn) | Giới hạn thời gian chạy `N` giây rồi tự dừng. |
| | `--video FILE` | — | Chạy thử/xem trước quyết định trên file video `.mp4`. |
| **Tự động & chống bot** | `--ads` / `--no-ads` | `--ads` | Bật / tắt tự mở và đóng quảng cáo thưởng vàng **GET**. |
| | `--auto-captcha` / `--no-auto-captcha` | `--auto-captcha` | Bật / tắt tự giải CAPTCHA cốc kim cương khi chạy `--tap`. |
| | `--humanize` / `--no-humanize` | `--humanize` | Bật / tắt giả lập ngón tay người thật, xáo trộn nhịp bấm & nghỉ ngắn chống phát hiện bot. |
| **Nâng cấp kim cương** | `--upgrade-hero [GEMS]` | Tắt (`50` nếu bật) | Tự nâng Hero ô góc trên phải `(461, 92)` khi kim cương trắng `>= GEMS` (hỗ trợ nút `+10`). |
| | `--upgrade-tower [GEMS]` | Tắt (`50` nếu bật) | Tự nâng Tháp tầng 2 lâu đài `(380, 366)` khi kim cương trắng `>= GEMS` (hỗ trợ nút `+10`). |
| | `--upgrade-gems GEMS` | — | Ghi đè mốc kim cương trắng kích hoạt cho `--upgrade-hero` / `--upgrade-tower`. |
| | `--upgrade-levels LEVELS` | `max(50, GEMS)` | Số cấp nâng tối đa trong mỗi đợt nâng cấp. |
| **Chọn giả lập** | `--list` | — | Liệt kê danh sách các instance giả lập nhận diện được rồi thoát. |
| | `--instance TÊN` | Tự chọn nếu 1 cửa sổ | Chọn cửa sổ BlueStacks 5 theo mã (`Pie64`, `Pie64_1`) hoặc tên tiêu đề cửa sổ. |
| | `--index N` | — | Chọn instance giả lập theo số thứ tự (`0`, `1`, `2`, ...). |
| | `--serial SERIAL` | Tự dò | Chỉ định trực tiếp địa chỉ ADB (`127.0.0.1:5555`, `emulator-5554`, ...). |
| | `--emulator {bluestacks,ldplayer}` | `bluestacks` | Chọn loại giả lập mục tiêu. |
| | `--adb PATH` | Tự dò | Đường dẫn tới `HD-Adb.exe` hoặc `adb.exe`. |
| | `--conf PATH` | Tự dò | Đường dẫn tới `bluestacks.conf`. |
| | `--ldconsole PATH` | — | Đường dẫn tới `ldconsole.exe` (dành cho LDPlayer 9). |

**Ví dụ kết hợp thường dùng:**

```powershell
# Đi wave + Skip 20 + không xem quảng cáo + tự nâng Hero khi đủ 60 kim cương trắng
.\.venv\Scripts\python.exe autoplay.py --tap --skip 20 --no-ads --upgrade-hero 60

# Đi wave + Skip 30 (mặc định khi dùng --skip không kèm số) + xem quảng cáo
.\.venv\Scripts\python.exe autoplay.py --tap --skip

# Treo Replay trên cửa sổ Pie64_1 + xem quảng cáo + tự nâng Tháp khi đủ 50 kim cương trắng
.\.venv\Scripts\python.exe autoplay.py --instance Pie64_1 --mode replay --tap --upgrade-tower 50
```
