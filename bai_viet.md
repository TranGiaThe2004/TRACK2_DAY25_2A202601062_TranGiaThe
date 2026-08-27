# Lab 25 — Báo cáo tối ưu chi phí GPU (GPU FinOps Workshop)

- **Sinh viên:** Trần Gia Thế
- **Mã số:** 2A202601062

Track 2 (Infrastructure) · Day 25 · NimbusAI. Các số liệu trong bài được tổng hợp và đối chiếu
từ output của các mission trong `missions/` và từ `outputs/report.md` của dataset tổng hợp
seed = 25.

## 1. Baseline vs. Optimized

| Chỉ số | Baseline | Optimized | Thay đổi |
|---|---|---|---|
| Composite monthly spend | $27,133 | $14,626 | −$12,507 (≈ 46.1%) |
| Inference unit economics ($/1M-token) | $6.488 | $1.126 | −82.6% |

Hai con số khác phạm vi và không so sánh trực tiếp. **$27,133/tháng** là *composite baseline*
= `30 × chi phí inference baseline/ngày` (≈ $1,466/tháng) `+` chi phí purchasing của các workload
theo tháng (≈ $25,667/tháng) — ước lượng gộp của M2 và M3, không phải hóa đơn cloud thật.
**$6.488 → $1.126 /1M-token** chỉ đo inference traffic của M2 trong một ngày mẫu (2,400 request);
nó phản ánh hiệu quả phục vụ token, không phải toàn bộ chi tiêu GPU.

## 2. Phân tích từng lever

| Hạng | Lever | Tiết kiệm/tháng |
|---|---|---|
| 1 | Purchasing (spot/reserved) | $10,040 |
| 2 | Inference (cascade/cache/batch) | $1,212 |
| 3 | Right-size util-lies | $655 |
| 4 | Kill idle GPUs | $600 |

Purchasing đứng đầu vì nó áp lên toàn bộ fleet: baseline on-demand của M3 là $25,667/tháng, và
gán đúng tier cho từng job (spot cho job gián đoạn, reserved cho workload ổn định vượt điểm hòa
vốn đã tính, còn lại on-demand) cắt khoảng 39.1% phần này. Inference lever nhỏ hơn vì chỉ tác
động lên phần token serving.

Trong phạm vi inference, thí nghiệm sequential theo thứ tự Cascade → Cache → Batch cho: Cascade
đóng góp ≈ $37.3985/ngày, Cache ≈ $1.1965/ngày, Batch ≈ $1.7946/ngày (tổng $40.3895/ngày).
Cascade lớn nhất vì phần lớn request được route sang small tier có đơn giá thấp hơn đáng kể;
Cache và Batch chỉ thêm phần nhỏ vì áp *sau* cascade, và cache hit chỉ cao ở team
`assistant`/`rag` còn batch chỉ ở team `eval`. Các đóng góp này **phụ thuộc thứ tự**; kịch bản
isolated (cascade −76.52%, cache −9.41%, batch −16.86%) chồng lấn nên cộng lại ra
102.79% ≠ 82.64% thực tế và không được cộng.

## 3. GPU-Util Lie

| GPU | Loại | GPU-Util | MFU | MBU |
|---|---|---|---|---|
| gpu-h100-4 | H100 | 98.2% | 0.194 | 0.207 |
| gpu-a10g-1 | A10G | 96.9% | 0.268 | 0.302 |

GPU-Util (từ `nvidia-smi`) chỉ đo tỷ lệ khoảng thời gian có kernel đang thực thi, không đo lượng
FLOPs hữu ích. MFU = FLOPs đạt được / FLOPs peak. Với `gpu-h100-4`, util 98.2% đi kèm MFU 0.194
nghĩa là chỉ khoảng 19% năng lực H100 được dùng thật, phần còn lại của GPU-giờ vẫn bị tính tiền.
Nguyên nhân khả dĩ gồm nghẽn băng thông HBM, overhead khi launch kernel, batch nhỏ không lấp đầy
tensor core, hoặc pipeline bubble do chờ dữ liệu/I/O — nhưng telemetry hiện có (util, achieved
TFLOPs, achieved BW) không đủ để xác định nguyên nhân nào chi phối; đây là giả thuyết, không phải
kết luận.

Hạ hai GPU util-lie xuống một bậc tier được mô hình hóa ở khoảng $655/tháng. Khác với idle hoàn
toàn: `gpu-h100-5` chạy 8 giờ trong ngày dữ liệu mẫu dưới 10% utilization, lãng phí khoảng
$20/ngày ≈ $600/tháng (mô hình hóa). GPU này không "nói dối" về hiệu quả — nó chỉ bị để chạy
không việc; cách xử lý là tự động tắt, không phải right-size.

## 4. Extension 4 — Reasoning Budget

Reasoning chiếm 201/2,400 request (≈ 8.4% traffic) nhưng ≈ 16.5% chi phí inference optimized và
≈ 94.0% năng lượng inference — vì output token của nó bị nhân khoảng 6 lần trong dữ liệu *và*
`sustainability.wh_per_query` áp hệ số năng lượng ×80 cho reasoning (×80 chỉ cho năng lượng,
không cho tiền).

Primary cap 10% **không ràng buộc** (8.4% < 10%) nên savings hiện tại = $0 — kết quả trung thực;
quy tắc là theo dõi reasoning share và chỉ cắt khi nó chạm/vượt 10%. Kịch bản
nhạy cảm 5% (minh hoạ, không phải chính sách chính): giữ 120 request phức tạp nhất, hạ cấp 81
request, ngưỡng suy ra từ dữ liệu là `input_tokens ≥ 2,034` → tiết kiệm ≈ $0.46/ngày, $13.86/tháng
và 9,977 Wh/ngày. `input_tokens` ở đây chỉ là proxy cho độ phức tạp trong simulation.

## 5. Extension 5 — Carbon-Aware Scheduling

Phân tích 5 job `interruptible = 1`, tổng 1,789 kWh (mỗi job dùng `hours_per_day × days` riêng,
không phải một tháng lịch).

| | us-east-1 | europe-north1 | Chênh lệch |
|---|---|---|---|
| Carbon | 679,820 gCO2e | 53,670 gCO2e | −626,150 gCO2e (≈ 92.1%) |
| Modeled electricity | $214.68 | $161.01 | −$53.67 |

Con số điện là **modeled electricity cost**, không phải cloud-bill saving, và được loại khỏi bốn
lever cũng như `total_savings_pct`. Cheapest = `us-east-wa` (min $/kWh), cleanest = `europe-north1`
(min gCO2/kWh), balanced 50/50 (chuẩn hóa min-max giữa cost và carbon) = `us-east-wa`. Relocation
chỉ đề xuất cho job training/batch gián đoạn; không tự động áp cho real-time inference vì latency
người dùng và data-residency thường ghim vùng phục vụ.

## 6. Ba khuyến nghị đầu tiên cho NimbusAI

1. **Chính sách mua GPU.** Gán mỗi workload vào spot/reserved/on-demand theo tính gián đoạn và
   duty cycle; checkpoint job spot để rework khi bị thu hồi là nhỏ. Đây là lever tác động tiền
   lớn nhất.
2. **Định tuyến model inference.** Triển khai cascade trước, rồi mới thêm prompt caching và Batch
   API cho đúng loại traffic chịu được.
3. **Kiểm soát hiệu quả.** Right-size GPU util-lie xuống một bậc và tự động tắt GPU idle, kèm giám
   sát utilization/MFU và đường rollback.

Đi kèm: duy trì tag coverage (91.8%, chargeback gate đang mở) để gắn trách nhiệm chi phí theo team
qua showback/chargeback.

## 7. Giả định và giới hạn

Dữ liệu là tổng hợp, seed = 25, một snapshot tháng 6/2026, không phải hóa đơn cloud thật.
`$27,133` là composite hai phạm vi, còn bảng
`$/1M-token` chỉ là inference traffic M2 của một ngày mẫu. Mô hình carbon/điện chỉ tính điện năng
board GPU khi chạy, không gồm PUE, mạng, lưu trữ hay egress. Ngưỡng reasoning dùng `input_tokens`
làm proxy. Không có số millisecond latency nào được bịa, và không kết luận nguyên nhân phần cứng
của util-lie khi chưa profiling ở mức kernel.
