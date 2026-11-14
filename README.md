# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.

---

# Bài làm: Bộ luật Lao động 2012 & 2019

Học viên: **Vũ Duy Khánh** · 2A202603865 · L3B
Báo cáo: [report/individual/2A202603865_VuDuyKhanh.md](report/individual/2A202603865_VuDuyKhanh.md)

Corpus gồm 462 Điều của Bộ luật Lao động 2012 và 2019. Embedding dùng `intfloat/multilingual-e5-base` chạy local (768 chiều, chi phí 0). Vector store là PostgreSQL 16 + pgvector 0.8.7 chạy trong Docker, tìm kiếm cosine chính xác. Có ba chiến lược:
- **A:** chia cố định 500 ký tự, overlap 50.
- **B:** chia theo Điều, tối đa 1.000 ký tự.
- **C:** như B, thêm filter `year`.

| Strategy | Dev Hit@1 | Dev Hit@3 | Test Hit@1 | Test Hit@3 |
|---|---|---|---|---|
| A | 11/18 | 16/18 | 3/6 | 6/6 |
| B | 14/18 | 17/18 | 5/6 | 6/6 |
| **C** | **16/18** | 17/18 | **6/6** | 6/6 |

## Cách chạy

Yêu cầu: Docker Desktop, Python 3.11–3.14, khoảng 1,2 GB dung lượng trống cho model. Model được tải tự động ở lần chạy đầu.

```bash
cd starter
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py            # phải hiện "Setup OK"

# Tải corpus (HTML toàn văn, truy cập ngày 2026-11-14; không commit vì chứa nội dung web bên thứ ba)
curl -sSL -o data/blld-2019_pbgdpl-cantho.html "https://pbgdpl.cantho.gov.vn/attachment/261"
curl -sSL -A "Mozilla/5.0" -o data/blld-2012_caselaw.html \
  "https://caselaw.vn/van-ban-phap-luat/115774-bo-luat-lao-dong-so-10-2012-qh13-ngay-18-06-2012-cua-quoc-hoi"

python -m src.run --rebuild   # ingest -> chunk A/B -> embed -> pgvector -> truy xuất A/B/C -> chỉ số
python -m src.audit           # kiểm tra metadata + tổng hợp nhãn chấm tay

# Demo: so sánh top-3 của A/B/C
python -m src.demo --id q03                                  # chạy lại câu benchmark, có chấm Hit
python -m src.demo "Làm thêm tối đa mấy giờ một tháng?" --year 2019
python -m src.demo                                           # hỏi tự do; thêm @2019 hoặc @2012 ở cuối câu để lọc năm

docker compose -p day6_student_starter stop   # tắt database, dữ liệu vẫn giữ
```

`src.run` dừng và báo lỗi trong các trường hợp sau:
- không tách đủ 242 hoặc 220 Điều;
- có gold evidence không tìm thấy trong nguồn;
- benchmark dưới mức tối thiểu;
- số bản ghi trong DB lệch với số chunk.

Không có fallback sang vector giả. Nếu trang nguồn thay đổi, dùng [data/corpus_articles.jsonl](data/corpus_articles.jsonl) (thân văn bản luật đã tách theo Điều) để đối chiếu.

## Vị trí các file

| Nội dung | Đường dẫn |
|---|---|
| Code pipeline | [starter/src/](starter/src/) |
| Manifest và corpus đã tách | [data/manifest.json](data/manifest.json), [data/corpus_articles.jsonl](data/corpus_articles.jsonl) |
| Benchmark (24 câu, 18 dev / 6 test) | [benchmark/](benchmark/README.md) |
| Nhật ký thí nghiệm | [artifacts/experiment_log.csv](artifacts/experiment_log.csv) |
| Kết quả, trace, thông tin lần chạy | [results/summary.md](results/summary.md), [results/traces.jsonl](results/traces.jsonl), [results/run_info.json](results/run_info.json) |
| Nhãn chấm tay và audit | [results/audit/](results/audit/), [results/manual_summary.md](results/manual_summary.md) |
