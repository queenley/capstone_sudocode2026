# SUDO Project workspace

## Mở workspace này

Mở [SUDO_PROJECT_MAIN.code-workspace](SUDO_PROJECT_MAIN.code-workspace), thay vì workspace cũ trong `temp-repo-for-agent/docs/`. Một cửa sổ VS Code, ba nhóm Explorer theo thứ tự công việc:

| Nhóm | Folder thật | Dùng để làm gì |
| --- | --- | --- |
| 01 Evaluation — ACTIVE | [evaluation](evaluation/README.md) | Phần đang triển khai; checkpoint P0–P5 và kế hoạch P6 tiếp theo |
| 02 Product — RUNTIME | [temp-repo-for-agent](temp-repo-for-agent/README.md) | Sản phẩm Agent/backend/frontend; tích hợp runtime khi được giao |
| 03 BTC — REFERENCE | [BTC-Data-Vong1-TEAMS](BTC-Data-Vong1-TEAMS/README.md) | Symlink tới Downloads; đối chiếu tài nguyên, không sửa để hợp scorer |

Đây là phân nhóm hiển thị và chỉ dẫn, **không phải cơ chế read-only**. Không chuyển/đổi tên file vật lý, không thay import/AssetRef/hash hoặc kết quả đã pin. JSON format-on-save tắt trong workspace để tránh tự đổi bytes của fixture/GT/lock; vẫn có thể format thủ công file mới chưa pin.

## Ngày mai đọc theo thứ tự

1. [Evaluation README + checkpoint](evaluation/README.md): việc đã làm, giới hạn, phần bảo vệ, quyết định dùng dataset tạm và trạng thái tạm dừng.
2. [Implementation plan](evaluation/evaluation-implementation-plan.md): đọc P6 và dependencies trước khi implement; P0–P5 là code đã kiểm offline, không phải benchmark thật hoàn chỉnh.
3. [Runner flow](evaluation/evaluation-runner-flow.md), rồi [flow đầy đủ](evaluation/evaluation-flow.md) khi cần hiểu lifecycle.
4. [Contract matrix](evaluation/evaluation-contracts/schema-contract-matrix.md), [report/formulas](evaluation/evaluation-contracts/report-schemas.md), [acceptance](evaluation/evaluation-contracts/harness-acceptance-tests.md).
5. Code `evaluation/eval_harness/`, tests `evaluation/tests/`; đối chiếu report P4/P5 được link trong checkpoint. Không mở đầu bằng hình cũ hoặc runs lịch sử để suy ra trạng thái hiện tại.

Chỉ tiếp tục implementation khi user yêu cầu lại; việc sắp xếp workspace không tự bắt đầu P6.

## Bản đồ phần Evaluation

| Khu vực | Đường dẫn | Vai trò / nguyên tắc |
| --- | --- | --- |
| Bối cảnh và kế hoạch | `evaluation/README.md`, `evaluation-implementation-plan.md`, các flow `.md` | Đọc trước khi code; quyết định hiện hành ở README |
| Code đang phát triển | `evaluation/eval_harness/`, `evaluation/run_eval.py` | P0–P5 evaluator; P6 trở đi chưa implement |
| Kiểm thử | `evaluation/tests/`, `evaluation/asr/test_asr.py` | Gần nhất84 evaluator tests +15 ASR tests đạt |
| Contracts nhóm | `evaluation/evaluation-contracts/` | Schemas, công thức, checker, fixtures; thay đổi phải có kiểm thử/version phù hợp |
| Nguồn BTC chuẩn đã pin | `evaluation/evaluation-contracts/sources/btc/`, `sources.lock.json` | 46 source hashes; tuyệt đối không sửa để làm điểm đẹp |
| Settings và registry bộ tạm | `evaluation/p*-settings.example.json`, `evaluation/datasets/p5-current/registry.json` | Entry points/dataset pins; thay bộ đúng bằng version/settings/run mới |
| ASR tái sử dụng | `evaluation/asr/` | Runner/text processing có sẵn; Medium dev lock, dev4/eval20; P5 mới chỉ chạy replay |
| Kết quả chạy | `evaluation/runs/`, `evaluation/asr/runs/` | Raw/evidence/report/locks đã đóng; không overwrite hoặc sửa lịch sử |
| Thiết kế bổ sung | `exemplar-bank-design.md`, `reflection-ab-design.md` trong `evaluation/` | Chỉ đọc sâu khi phase/runtime dùng các cơ chế này |
| Nguồn/hình/lịch sử | `evaluation/source/`, `evaluation/output/`, các `.archive/`, tài liệu BTC/phân công cũ | Tham khảo, không thay code/contracts/checkpoint hiện hành |

Model/datasets ASR, runs, output và archive được loại khỏi **tìm kiếm mặc định**, không bị xóa. Cache/venv được ẩn khỏi Explorer. Khi cần tìm evidence/dataset, mở folder/file trực tiếp hoặc tắt tùy chọn dùng exclude settings trong Search.

## Những bản dễ nhầm

- `evaluation/evaluation-contracts/sources/btc/` là nguồn chạy scorer/checker đã pin. `evaluation/BTC-Data-Vong1-TEAMS/` là snapshot tham khảo; root `BTC-Data-Vong1-TEAMS/` trỏ Downloads và có thể thay đổi. Không tự đồng bộ bản mới vào benchmark.
- `temp-repo-for-agent/` ở root là repo sản phẩm thật. `evaluation/temp-repo-for-agent/docs/` chỉ là tài nguyên tài liệu tham khảo; không phải nơi implement runtime.
- Workspace ở root này là entry point hiện hành; workspace cũ trong `temp-repo-for-agent/docs/` giữ nguyên để bảo toàn tài liệu gốc.
- Các bản trùng/output cũ giữ tại [.archive/workspace-before-evaluation-separation-2026-10-03](.archive/workspace-before-evaluation-separation-2026-10-03/) để có thể khôi phục; không phải bản đang sử dụng. File `:memory:.ses` giữ nguyên, không thuộc entry point evaluator.

## Bản snapshot trên GitHub

Nhánh đích: [queenley/capstone_sudocode2026 — Evaluation](https://github.com/queenley/capstone_sudocode2026/tree/Evaluation). Snapshot chứa code, docs, contracts/BTC, dataset/audio và evidence/runs hiện tại, kể cả tài liệu archive; không chứa credentials `.env*` (trừ example), virtualenv, model weights, download/cache, Git metadata lồng hoặc session local. Các file này vẫn giữ nguyên trên máy, không bị xóa.

Trong snapshot GitHub, root `BTC-Data-Vong1-TEAMS/` là bản copy bytes của symlink hiện tại để clone không phụ thuộc đường dẫn Downloads trên máy này. `temp-repo-for-agent/` là cây source trong cùng repository snapshot, không phải submodule; Git/remote gốc trên máy không thay đổi. Nguồn scorer/checker vẫn là snapshot đã pin trong `evaluation/evaluation-contracts/sources/btc/`, không chuyển sang dùng BTC root.

Clone mới cần tạo môi trường Python và cài dependencies từ `evaluation/evaluation-contracts/requirements.txt` / `evaluation/asr/requirements.txt` trước khi chạy tests. ASR inference cần model local đúng dev lock, model weights không được đưa lên Git; replay không gọi model. Evidence cũ có thể giữ absolute paths của máy tạo run: không sửa bytes để đổi paths; chọn settings và output/run mới khi chạy lại.
