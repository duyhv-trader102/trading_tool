# Market States & Theory: The Physics of Institutional Trading

> [!IMPORTANT]
> **Nguyên tắc chung**: Quản trị sự bất định của Market không dựa trên kỳ vọng, mà dựa trên các hành vi có tính quy luật của Market.

---

## I. MARKET LAWS (CÁC QUY LUẬT THỊ TRƯỜNG)

### Quy luật 1: Institutional Flow (Dòng tiền tổ chức)
Market không vận hành ngẫu nhiên mà chịu sự chi phối của tổ chức và dòng tiền lớn. Giá di chuyển nhằm phục vụ mục tiêu **xây dựng, phân phối và tái cấu trúc inventory** của các chủ thể có khả năng giao dịch khối lượng lớn, chứ không phải để phản ánh cung–cầu tức thời của retail.

### Quy luật 2: Balance Necessity (Sự cần thiết của trạng thái Cân bằng)
Do hạn chế về thanh khoản, tổ chức không thể mua hoặc bán khối lượng lớn trong trạng thái imbalance mà không tự làm xấu giá.
- Market buộc phải tạo ra trạng thái **Balance (Range)** để tổ chức có thể đồng thời mua và bán, hấp thụ thanh khoản hai chiều và xây dựng inventory.
- `Balance` không phải là tác dụng phụ (side-effect), mà là **điều kiện cần** để triển khai vốn.

### Quy luật 3: Dual-Sided Inventory (Inventory hai chiều)
Trong vùng Balance, tổ chức thực hiện cả hoạt động mua và bán nhằm trung bình hóa:
- Giá mua về mức tối ưu nhất.
- Giá bán về mức tối ưu nhất.
- Khối lượng lớn nhất có thể.
> [!NOTE]
> Đây là lý do Market xoay trục (rotate), xuất hiện mức giá kiểm soát (Mean/Control Price) và các nhịp Pull–Push.

### Quy luật 4: Saturation/Compression (Sự nén/Bão hòa)
Balance đạt trạng thái nén khi khả năng cải thiện giá không còn. Lúc này, tổ chức đã đạt được mức giá mua và bán tối ưu trong cấu trúc hiện tại.

### Quy luật 5: Economic Attrition (Sự bào mòn kinh tế)
Việc duy trì Balance khi không còn cải thiện được chất lượng giá sẽ:
- Tăng chi phí giữ vị thế.
- Giữ nguyên rủi ro.
- Bào mòn biên lợi nhuận.
> [!TIP]
> Market không sinh ra thêm giá trị cho tổ chức trong trạng thái này. Đây là lý do **kinh tế**, không phải kỹ thuật.

### Quy luật 6: Imbalance Obligation (Nghĩa vụ dịch chuyển)
Khi Balance không còn hiệu quả phân phối lợi nhuận, market **buộc phải** chuyển sang Imbalance để tái tạo lợi thế (Edge).
- **Imbalance không phải là lựa chọn, mà là nghĩa vụ.**

### Quy luật 7: Liquidity Displacement (Sự dịch chuyển thanh khoản)
Mọi nhịp đẩy giá (Imbalance) mạnh mẽ đều cần một lượng thanh khoản đối ứng cực lớn để khớp lệnh.
- **Hành vi**: Market thường có xu hướng quét qua các vùng thanh khoản lộ liễu (Liquidity Sweeps) như đỉnh/đáy cũ ngay trước khi đảo chiều.

### Quy luật 8: Law of Freshness (Tính hiệu lực của vùng giá)
Một vùng Inventory (OB/iZ) có giá trị cao nhất ở lần chạm (Mitigation) đầu tiên.

### Quy luật 9: Path of Least Resistance (Con đường ít trở lực nhất)
Giá không di chuyển đến nơi có nhiều lệnh chờ, nó di chuyển đến nơi **dễ dàng khớp lệnh nhất** để tái cấu trúc Inventory.

---

## II. QUẢN TRỊ BẤT ĐỊNH

> [!IMPORTANT]
> ## QUẢN TRỊ SỰ BẤT ĐỊNH CỦA MARKET KHÔNG DỰA TRÊN KỲ VỌNG, MÀ DỰA TRÊN CÁC HÀNH VI CÓ TÍNH QUY LUẬT CỦA MARKET

### Tại sao không dựa trên kỳ vọng?
**Kỳ vọng** (Prediction) là việc đoán trước market sẽ đi đâu:
- ❌ "Tôi nghĩ giá sẽ tăng"
- ❌ "Tôi kỳ vọng market sẽ breakout"
→ **Vấn đề**: Kỳ vọng dựa trên niềm tin chủ quan, không có cơ sở khách quan → Không thể quản lý rủi ro.

### Quản trị bằng hành vi có tính quy luật
**Hành vi có tính quy luật** (Rule-based Behavior) là những gì market **BUỘC PHẢI** làm do các Market Laws.
**Không đoán market sẽ đi đâu. Chỉ phản ứng với những gì market BUỘC PHẢI làm.**

---

## III. NGUYÊN LÝ CỐT LÕI: MARKET CHỈ CÓ 2 TRẠNG THÁI

> [!IMPORTANT]
> ## MARKET CHỈ TỒN TẠI TRONG 2 TRẠNG THÁI RÕ RÀNG: **BALANCE** VÀ **IMBALANCE**
> 
> ### Chu kỳ vận hành: **IMBALANCE → BALANCE → IMBALANCE → BALANCE → ...**

| Trạng thái | Nghĩa vụ chính | Hành vi đặc trưng | Chiến thuật |
|---|---|---|---|
| **BALANCE** | Build Position, Seek Liquidity, Hedge Risk | Rotation & Pull-Push | Counter tại biên, Avoid Mean |
| **IMBALANCE** | Defend Trend, Expand Inventory | Trend Following | Follow trend, Position Layering |

---

## IV. MACRO RANGE (BALANCE)

### 1. Hành vi
**Mean Reversion** (Duy trì và kiểm tra sự cân bằng quanh Control Price).
- **Control Price = Vùng BẤT ĐỊNH**: Giá Chaos, không nên phản ứng.
- **Biên = Vùng QUY LUẬT**: Hành vi Pullback từ biên về Mean có tính lặp lại cao → Có thể quản lý.

### 2. Giai đoạn của Balance
1. **Early Balance**: Range mới hình thành.
2. **Mid Balance**: Rotate ổn định quanh Mean.
3. **Late Balance (Compression)**: Range thu hẹp dần → Chuẩn bị chuyển sang Imbalance.

### 3. Phương án xử lý
- **Ở Biên**: Counter-trend theo hướng Pullback (Buy Low / Sell High).
- **Ở Control Price**: Đứng ngoài, trừ khi có **Compression topdown** (Monthly/Weekly) báo hiệu một "New Beginning" sắp tới.

---

## V. MACRO TREND (IMBALANCE)

### 1. Hành vi
**Trend Following** - Market di chuyển một chiều để hiện thực hóa lợi nhuận.
- **Single Prints cao**: Market không quay lại test các vùng giá đã đi qua.
- **Pullback có kiểm soát**: Chỉ để Hedge Profit, không phải đảo chiều.

### 2. Phương án xử lý
- **Trend mạnh**: Follow trend (Buy High / Sell Low) khi có Pullback nhanh/nông.
- **Trend suy yếu**: Khi HTF Responsive Participants xuất hiện hoặc Pull-Push nhen nhóm → Chờ Balance mới.

### 3. Chuyển tiếp Imbalance → Balance
Xảy ra khi đạt **HTF Target** hoặc gặp **HTF Resistance**. Market **BUỘC PHẢI** tạo Balance mới để Build Position.
