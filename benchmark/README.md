# Benchmark — Bộ luật Lao động 2012 / 2019

File: [questions.json](questions.json) · 24 câu · **18 dev / 6 test** · 8 câu có metadata filter (6 dev, 2 test).

## Cách xây dựng

- `evidence_quote` được trích **nguyên văn** từ Điều nguồn sau chuẩn hóa. `src.run` kiểm chứng tự động mọi trích dẫn (kể cả `alt_gold`) **trước khi truy xuất**. Kết quả nằm ở [results/benchmark_validation.json](../results/benchmark_validation.json), đạt 100%.
- `gold_page` là **số Điều**: corpus là HTML nên không có trang vật lý.
- Nếu nội dung giống nhau ở cả hai bộ luật và câu hỏi không nêu năm, cả hai Điều đều là gold hợp lệ (`alt_gold`).
- `evidence_quote` có thể là một danh sách. Khi đó **mọi** đoạn phải nằm trong cùng một chunk thì mới tính là hit (ví dụ q11 cần cả "không cần báo trước" và "quấy rối tình dục").
- Không đưa đáp án hay gold source vào query hoặc filter. Filter `year` lấy từ năm mà người dùng nêu rõ trong câu hỏi ("Theo Bộ luật Lao động 2019…"), tức là có sẵn trước khi truy xuất.

## Loại câu

| type | Số câu | Ý nghĩa |
|---|---:|---|
| truc_tiep | 9 | Hỏi đúng thuật ngữ trong luật |
| dien_dat_lai | 4 | Dùng từ đời thường ("Tết Nguyên đán", "bố mẹ qua đời") |
| dieu_kien | 4 | Cần điều kiện hoặc ngoại lệ |
| metadata_filter | 7 (+ q01) | Hai phiên bản luật quy định khác nhau, cần lọc theo `year` |

## Chia dev / test

Chia **theo chủ đề**, cố định trước khi chạy retrieval:
- Test gồm tuổi nghỉ hưu, nghỉ việc riêng, trợ cấp mất việc làm, nghỉ giữa giờ ban đêm, thời hiệu Hội đồng trọng tài.
- Không có Điều gold nào của test xuất hiện trong dev.

**Rủi ro rò rỉ:** q22 (trợ cấp mất việc, test) gần với q13 và q15 (trợ cấp thôi việc, dev); q23 (nghỉ giữa giờ ban đêm) gần với q09 (giờ làm ban đêm). Các câu này dùng Điều khác nhau nhưng chủ đề liền kề.

## Tiêu chí chọn chiến lược

Thứ tự ưu tiên, áp dụng **trên dev**: (1) Evidence Hit@3 → (2) Hit@1 → (3) độ tuân thủ filter → (4) coherence → (5) tài nguyên (số chunk, thời gian).

Tiêu chí lấy theo ví dụ trong GUIDE §4.5 và được quyết định trước lần chạy đầu, nhưng chỉ được ghi thành văn bản sau lần chạy đó. Test chỉ dùng để xác nhận, không dùng để chỉnh cấu hình.
