# Báo cáo cá nhân — Day 6

**Học viên:** Vũ Duy Khánh · 2A202603865 · L3B

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang.**
  - Corpus gồm Bộ luật Lao động **2012** (10/2012/QH13, lấy từ caselaw.vn) và **2019** (45/2019/QH14, lấy từ Cổng PBGDPL Cần Thơ). Cả hai truy cập ngày 2026-11-14.
  - Quyền sử dụng: văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả (Điều 15 Luật SHTT). Bài chỉ dùng phần thân luật. Không commit HTML gốc, vì trang web chứa nội dung biên tập và chú thích của bên thứ ba.
  - Không dùng PDF vì các bản PDF tìm được đều là scan. HTML không có trang vật lý, nên theo GUIDE §1, **mỗi Điều là một đơn vị nguồn**, với `page` = số Điều.
  - Quy mô: **462 Điều** (242 + 220), 17 Chương mỗi bộ, **344.465 ký tự**, tương đương khoảng 114 trang A4. Có 38 Điều dài ≥1.500 ký tự.
  - Chỉ tính thân văn bản, từ "Chương I" đến trước câu "Bộ luật này (đã) được Quốc hội… thông qua". Chi tiết ở [data/manifest.json](../../data/manifest.json).
- **Chuẩn hóa, lỗi và giới hạn.**
  - Dùng BeautifulSoup lấy từng `<p>`, chuẩn hóa Unicode NFC, khoảng trắng và NBSP, giữ một đoạn trên một dòng.
  - Đã loại menu web, **mục lục ở đầu trang caselaw** (trong đó có chú thích "được hướng dẫn bởi Nghị định…", không phải nội dung luật) và bảng chữ ký.
  - Tiêu đề "Điều N." chỉ được nhận khi N đúng là số kế tiếp. Cách này loại được 4 tham chiếu chéo "Điều X." trong thân bản 2019.
  - Pipeline tự kiểm tra đủ 1→242 và 1→220 Điều, nếu thiếu thì báo lỗi. Log ở [results/ingest_log.json](../../results/ingest_log.json): không có Điều rỗng hay ngắn bất thường.
  - Giới hạn: đây là **bản gốc**, không gồm các sửa đổi về sau. Nguồn là trang tổng hợp, không phải Công báo.
- **Embedding, vector store, metric, lệnh chạy và chi phí.**
  - Embedding: `intfloat/multilingual-e5-base` chạy local bằng sentence-transformers 6.3.0 và torch 2.15.0 trên Apple MPS. Vector 768 chiều, tối đa 512 token, tiền tố `query: ` và `passage: `, đã chuẩn hóa L2.
  - Lý do không dùng `paraphrase-multilingual-MiniLM-L12-v2`: model này chỉ đọc 128 token, sẽ cắt cụt chunk 500–1.000 ký tự.
  - Vector store: PostgreSQL 16.16 + pgvector 0.8.7 chạy trong Docker. Metric cosine (`<=>`), **tìm kiếm chính xác** (quét tuần tự), lọc metadata bằng `WHERE year = %s` có tham số hóa.
  - Lệnh chạy: `python -m src.run --rebuild` rồi `python -m src.audit`.
  - Chi phí **0 USD**.
- **Metadata.**
  - Trường bắt buộc: `document_id`, `source` (URL), `page` (số Điều).
  - Trường lọc bổ sung là `year` (2012/2019, kiểu integer). Giá trị lấy từ số hiệu văn bản, không suy đoán. Lý do chọn: hai phiên bản luật có nhiều Điều cùng chủ đề nhưng khác số liệu.
  - Trường phụ: `pages` (các Điều mà chunk bao phủ), `chuong`, `chuong_title`, `muc`, `dieu_title`.

## Cấu hình và benchmark

- **A / B / C.**
  - **A**: cửa sổ cố định 500 ký tự, overlap 50, chạy trên toàn văn bản và **bỏ qua ranh giới Điều**. Điểm cắt lùi về khoảng trắng gần nhất. Không filter.
  - **B**: một Điều thành một chunk nếu dài ≤1.000 ký tự. Điều dài hơn được tách theo khoản; mỗi chunk con lặp lại tiêu đề Điều, và nếu chunk bắt đầu bằng điểm a), b)… thì lặp thêm câu dẫn của khoản (cắt ở 200 ký tự). Không filter.
  - **C**: dùng **chung index B** và thêm `WHERE year = …` cho 8 câu có filter. 16 câu còn lại chạy giống hệt B.
  - Khác biệt duy nhất giữa B và C là có filter hay không. Giữa A và B chỉ khác cách chunk; model, store, metric, top-k=3 và metadata đều giống nhau.
- **Benchmark ([benchmark/](../../benchmark/README.md)).**
  - 24 câu, chia **18 dev / 6 test theo chủ đề** trước khi chạy retrieval.
  - Có 8 câu filter `year` (6 dev, 2 test). Mỗi câu có loại (`truc_tiep`, `dien_dat_lai`, `dieu_kien`, `metadata_filter`).
  - Mọi `evidence_quote` và `alt_gold` được kiểm tra tự động là có trong Điều nguồn trước khi chạy ([results/benchmark_validation.json](../../results/benchmark_validation.json): 100% tìm thấy).
- **Tiêu chí chọn chiến lược** (trên dev): Hit@3 → Hit@1 → filter tuân thủ → coherence → tài nguyên.
  - *Trung thực:* tiêu chí này lấy theo ví dụ GUIDE §4.5 và được quyết định trước khi chạy, nhưng chỉ được ghi thành văn bản sau lần chạy đầu.
  - Sau khi đã xem kết quả lần đầu, mình **sửa một lỗi** ở B: một chunk dài 1.097 ký tự, vượt `max_size`. Đây là sửa lỗi để B đúng tham số đã khai báo, không phải tinh chỉnh. Sau khi sửa, B dev Hit@3 **giảm** từ 18/18 xuống 17/18. Mình giữ kết quả sau sửa.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/18 | 16/18 | 772 | embed 10,82 s | 0 |
| A | test | 3/6 | 6/6 | 772 | ″ | 0 |
| B | dev | 14/18 | 17/18 | 600 | embed 9,63 s | 0 |
| B | test | 5/6 | 6/6 | 600 | ″ | 0 |
| C | dev | **16/18** | 17/18 | 600 (index B) | không embed thêm; truy vấn TB 12,6 ms (B: 13,2 ms) | 0 |
| C | test | **6/6** | 6/6 | 600 | ″ | 0 |

Tài nguyên:
- **A**: 383.251 ký tự / 100.890 token. Overlap và việc cắt ngang Điều làm tổng lớn hơn corpus 11%. Có 451/772 chunk trải ≥2 Điều.
- **B**: 357.352 ký tự / 93.216 token. Chunk dài nhất 285 token, không chunk nào vượt 512.
- Đọc và tách HTML mất 0,2 s.
- Nạp lại cùng phiên bản: **0 chunk embed lại**, số bản ghi không đổi (772 và 600).

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,6 (10): 4×0, 6×1 | 18/18 | test 1/2 · dev 0/6 | 0/1/5 → 1,83 |
| B | 2,0 (10) | 18/18 | test 1/2 · dev 0/6 | 0/0/6 → 2,0 |
| C | 2,0 (10), giống chunk B | 18/18 | **test 2/2 · dev 6/6** | 0/0/6 → 2,0 |

Thời điểm chạy, phiên bản thư viện và thời gian chi tiết được ghi tự động trong [results/run_info.json](../../results/run_info.json).

**Đường dẫn và cách chọn mẫu.**
- Trace: [results/traces.jsonl](../../results/traces.jsonl), lưu câu hỏi, filter, chunk_id, text, score và metadata của top-3, kèm cờ `page_match`, `evidence_hit`, `filter_ok`.
- Nhãn: [results/audit/](../../results/audit/).
- Coherence: 10 vị trí **chọn trước khi chấm**, là đoạn giữa các Điều 1, 23, 45, … 199 (bước 22) của bản 2019. Chấm chunk chứa vị trí đó.
- Metadata: 6 câu test × top-3. Mỗi trường (`year`, `chuong`, `dieu_title`, `source`, `page` ∈ `pages`, text khớp các Điều trong `pages`) được đối chiếu tự động với nguồn bằng `src.audit`.
- Filter tuân thủ: tất cả top-3 phải đúng `year` mà câu hỏi yêu cầu. Chỉ số này đo cả với A và B (không áp filter) để thấy mức nhiễu phiên bản.

> **Khai báo AI và độ thiên lệch:** Pipeline, bộ câu hỏi và các nhãn coherence/grounding do **Claude (Claude Code) soạn nháp**. Tác giả đã đọc toàn bộ 24 câu hỏi và xác nhận chúng hợp lệ, không sửa câu nào. Evidence của các câu này cũng đã được kiểm chứng tự động. Các nhãn coherence/grounding do Claude chấm nháp kèm lý do, sau đó **tác giả (Vũ Duy Khánh) đọc và duyệt toàn bộ**, giữ nguyên điểm. Tác giả là người chấm chính thức. Nhãn không được chấm độc lập từ đầu, nên có nguy cơ tác giả bị neo theo điểm nháp. Người chấm nhãn đã biết chiến lược và kết quả Hit@3, nên có rủi ro thiên lệch. Kiểm tra metadata chạy tự động nên tái lập được.

## Phân tích và kết luận

**So sánh A–B (thay cách chunk).**
- B tốt hơn A ở mọi chỉ số chính: dev Hit@1 11→14/18, Hit@3 16→17/18, coherence 0,6→2,0, và ít hơn 172 chunk.
- A cắt ngang Điều nên evidence thường bị tách đôi. Ví dụ: q08, q14, q15 và q21 có top-1 đúng Điều nhưng thiếu một phần evidence; ở q19, đáp án "55 tuổi 04 tháng" nằm ở chunk A:0300, mất mốc "Kể từ năm 2021" và tiêu đề Điều 169 (grounding = 1).
- Ở A, trường `page` chỉ ghi Điều đầu tiên. Với 11/18 bản ghi trải nhiều Điều, phải dùng `pages` mới truy vết đúng.

**So sánh B–C (chỉ thêm filter `year`).**
- Chunk giống nhau, nên coherence và Hit@3 không đổi. Hit@1 dev tăng 14→16/18 và test 5→6/6.
- Filter tuân thủ tăng từ 0/6 lên 6/6 (dev) và từ 1/2 lên 2/2 (test).
- Không có filter, top-1 của B lấy nhầm phiên bản ở q03 (hỏi bản 2019, top-1 là Điều 106 bản 2012: "30 giờ/tháng" thay vì 40), q05 và q20. Điều này nguy hiểm vì người đọc sẽ nhận số liệu của luật đã hết hiệu lực. Filter loại hẳn lỗi này.
- Chi phí của C gần bằng 0: không thêm chunk hay embedding, thời gian truy vấn tương đương.

**Hai ví dụ sai.**
1. **q18** (dev, cả B và C trượt; gold là `blld-2019` Điều 36).
   - Câu hỏi: "Công ty đơn phương chấm dứt HĐLĐ không xác định thời hạn phải báo trước ít nhất bao nhiêu ngày?"
   - B tách khoản 2 Điều 36 làm hai: điểm a) "Ít nhất 45 ngày…" nằm cuối chunk `B:blld-2019:036:2`, còn chunk được truy xuất `B:blld-2019:036:3` bắt đầu từ b) "30 ngày".
   - Top-1 lại là Điều 37 bản 2012 (người lao động báo trước), một Điều sai chủ thể nhưng rất giống về từ ngữ.
   - Đây là điểm yếu của cách tách theo khoản: câu dẫn được lặp lại, nhưng các điểm của một khoản vẫn có thể bị chia ra.
2. **q11** (dev, A trượt, B/C trúng ở top-2; gold là `blld-2019` Điều 35).
   - Câu hỏi về quấy rối tình dục và nghỉ không cần báo trước.
   - Cả ba chiến lược đều xếp **Điều 3 (định nghĩa "quấy rối tình dục")** lên top-1, vì trùng từ khóa nhưng không trả lời câu hỏi.
   - Với A, "không cần báo trước" và "Bị quấy rối tình dục" nằm ở hai chunk khác nhau nên không chunk nào đủ evidence.
   - Bài học: một câu hỏi điều kiện cần cả quy tắc lẫn trường hợp; chunk theo cấu trúc giữ được cả hai.

**Chiến lược chọn: C**, theo tiêu chí đã nêu.
- Trên dev, Hit@3 của C bằng B (17/18) và hơn A (16/18). Hit@1 cao nhất (16/18). Filter tuân thủ 6/6.
- Test xác nhận: 6/6 Hit@1 và 6/6 Hit@3.
- Đánh đổi: C chỉ có tác dụng khi người dùng nêu rõ năm hoặc phiên bản. Với câu không nêu năm, C hoạt động như B và vẫn có thể trộn hai phiên bản trong top-3.
- Điều kiện áp dụng: corpus có nhiều phiên bản và metadata phiên bản đáng tin.

**Hạn chế.**
- Mẫu nhỏ: test chỉ 6 câu, dev 18 câu. Chênh lệch 1–2 câu chưa có ý nghĩa thống kê, nên không suy rộng ngoài corpus này.
- Grounding bị **trần điểm**: 17/18 nhãn đạt 2, nên chỉ số này phân biệt kém.
- 10 vị trí coherence rơi vào các Điều ngắn, nên B đạt 2,0. Mẫu này không bắt được lỗi tách khoản như q18. Coherence thực của B trên các Điều dài sẽ thấp hơn.
- Câu hỏi và nhãn do AI soạn nháp, có thể thiên về từ ngữ giống luật, nên truy xuất dễ hơn câu hỏi thực tế. Hit@3 tự động yêu cầu khớp nguyên văn sau chuẩn hóa, nên có thể đánh trượt chunk chứa evidence tương đương nhưng viết khác.
- Thời gian đo trên một máy (MacBook, MPS), chạy một lần, có tính cả thời gian nạp model.

**Nếu làm lại hoặc mở rộng.**
1. Ở B, không tách điểm a) khỏi câu dẫn của khoản; nếu phải tách thì cho các chunk liền kề chồng lên nhau một điểm. Nhắm vào lỗi q18.
2. Thêm metadata `hieu_luc` (đang hiệu lực / hết hiệu lực) và mặc định lọc theo luật đang hiệu lực khi câu hỏi không nêu năm.
3. Thử hybrid BM25 + dense trên dev để giảm lỗi kiểu q11 (trùng từ khóa với Điều định nghĩa).
4. Mở rộng test lên ≥15 câu có câu hỏi viết theo cách người dùng thật hỏi, và nhờ một người khác chấm nhãn độc lập.
