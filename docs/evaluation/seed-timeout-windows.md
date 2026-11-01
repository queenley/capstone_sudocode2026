# Seed Memory timeout trên Windows: điều tra và đường chạy an toàn

## Bằng chứng trong ảnh

- Hai cấu hình đều dừng ở `seed S-OLD-1`, tool `memory_commit_facts`, mã `TIMEOUT`, deadline 10 giây.
- Không có lượt **được chấm**: `labelled 0 turns`, `n_turns: 0`, `scenarios_stopped: 1`. Bảng 0/None sau đó là cohort chưa chạy, không chứng minh agent đạt 0 điểm. Retrieval offline vẫn có thể có số riêng và không chứng minh hội thoại đã chạy.
- Ảnh ghi `product-extractor-v5`; main khảo sát `1a812462` dùng v7. Chưa biết commit/dependency và log PostgreSQL/MCP của máy Windows, nên không khẳng định timeout này do một nguyên nhân duy nhất.
- `labelled 0` không đồng nghĩa không tốn tiền: mặc định có ba lượt warm-up gọi model **trước** lần seed đầu tiên.

## Điểm đã sửa trong code

1. `pipeline/eval/cli.py`: khôi phục lời gọi `use_selector_loop_on_windows()` trước các nhánh `asyncio.run`, cả chạy mới và relabel. MCP subprocess đã có hook này; CLI local bị thiếu. Async psycopg cần Selector trên Windows; MCP SDK đang cài có đường Popen fallback cho subprocess. Chưa kiểm chứng trực tiếp runtime Windows.
2. `pipeline/eval/report.py`: lỗi scenario bị dừng/từ chối và trace rỗng đều là blocker chung. `grade()` cũng từ chối trace thiếu/rỗng trước khi gọi scorer. Giữ nguyên công thức/scorer BTC và extractor v7.
3. `cli.py`: seed lỗi không label, không bắt đầu baseline, không chạy retrieval/grade. Giữ trace và ghi `scenario-errors.jsonl` với config/scenario/lý do, manifest ghi `INCOMPLETE`, thoát mã 1. `failed_turns` vẫn có thể là 0 vì seed chưa phải một lượt; `scenarios_stopped` và `empty_trace` mới phản ánh lỗi đó.
4. `runner.py`: seed đọc envelope thay vì bỏ mất error qua `.data()`. Lỗi nêu rõ stage/tool/code; không in nguyên args/message có thể chứa dữ liệu riêng. Identity lookup thất bại không được coi là “chưa có khách” rồi tạo owner khác. Không retry write, không tăng timeout để che lỗi.
5. `relabel.py`: kiểm nguồn trước khi gọi extractor; nguồn rỗng, manifest báo lỗi thực thi, hoặc diagnostics/after-call lỗi đều không được chấm lại thành kết quả hợp lệ. Lỗi extractor cũ vẫn được sửa trên trace đã chạy. Run nguồn không bị sửa.

Chỉ sửa điều khiển evaluation và lỗi hạ tầng. Không triển khai skill/context reducer của kế hoạch harness; không sửa dataset, seed label, pack BTC hoặc điểm benchmark.

## Timeout chưa được chứng minh nguyên nhân trên máy Windows

Writer mở pool PostgreSQL lazily. Pool có `wait(timeout=12)` trong khi ToolBox writer chờ tối đa 10 giây. Khách đã có trong CRM có thể đi thẳng tới `memory_commit_facts` mà không đọc identity trước, nên đó có thể là lần đầu pool writer kết nối. Cold connection, DB thiếu kết nối, sai cấu hình hoặc lock còn tồn tại đều cần được phân biệt bằng log. Đây là các khả năng, không phải kết luận từ ảnh.

Ảnh đã đi tới seed sau `reset()` của harness, vì vậy cũng không thể lấy riêng ảnh làm bằng chứng parent Proactor gây lỗi. Parent reset dùng autocommit, không thấy transaction được giữ xuyên sang seed. Không tự kill backend PostgreSQL, retry write hoặc xóa/recreate ledger ngân sách.

## Thu thập chẩn đoán trên PowerShell — không gọi model

Từ thư mục repo bên Windows:

```powershell
git rev-parse --short HEAD
docker compose ps postgres
& .\apps\ai-agent-service\.venv\Scripts\python.exe -c "import sys; from importlib.metadata import version; print(sys.version); print({n:version(n) for n in ['mcp','fastmcp','psycopg','psycopg-pool','anyio']})"
Select-String -Path .\evaluation\runs\seed-dev-smoke-3\mcp-servers.log -Pattern 'Proactor|PoolTimeout|connection|timeout|ERROR|Traceback' | Select-Object -Last 40
```

Nếu PostgreSQL nằm trong Compose của repo, query chỉ đọc dưới đây cho biết wait/blocking, không in SQL hoặc nội dung khách:

```powershell
docker compose exec -T postgres psql -U postgres -d postgres -c "SELECT pid, state, wait_event_type, wait_event, pg_blocking_pids(pid) FROM pg_stat_activity WHERE right(datname,5)='_eval';"
```

Chỉ một runner dùng database `_eval` tại một thời điểm; runner reset dữ liệu giữa scenario. Kiểm log để phân biệt không kết nối được, hết slot kết nối, đang chờ lock và write thực sự chậm. Không dùng log raw hoặc `.env` làm file commit.

## Chạy lại một scenario sau khi xử lý hạ tầng

Đây là lệnh **có thể tốn phí model**, chỉ dùng sau khi đã lấy bản sửa và xác nhận DB/MCP hoạt động. Giữ ledger ngân sách đang dùng, không tạo lại để vượt cap. Dùng đúng thư mục scenario trên máy đó như lệnh trong ảnh; không đổi nhãn.

```powershell
$env:EVAL_BUDGET_DB = "evaluation/runs/20261024-work/budget.sqlite"
if (-not (Test-Path $env:EVAL_BUDGET_DB)) { throw "Không tìm thấy ledger hiện có; không tạo ledger mới để chạy tiếp." }
& .\apps\ai-agent-service\.venv\Scripts\python.exe run_eval.py --scenarios data/seed-dev/scenarios --only SCN-GEN-0001 --warmup 0 --out evaluation/runs/seed-dev-smoke-fixed-new
$LASTEXITCODE
```

Chọn một output directory mới, không ghi đè `seed-dev-smoke-3`. `--warmup 0` bỏ ba lượt khởi động khi chẩn đoán, nên không so latency lượt đầu với phép chạy benchmark đã warm-up. `--no-extract` vẫn gọi model agent, không phải dry run miễn phí.

Nếu seed vẫn timeout: exit 1, manifest `INCOMPLETE`, có tool/code ở `scenario-errors.jsonl`, không có bảng BTC mới. Một write timeout có thể đã commit; kiểm trạng thái/log trước khi quyết định chạy lại. Nếu không còn lỗi: trace có lượt thật rồi mới kiểm scoring và độ phủ. Không biến một run lỗi hạ tầng thành điểm 0.

## Kiểm chứng trong phiên này

`pytest tests/agent -q`: **964 passed, 1 skipped**. Các test dùng fake model/tool hoặc ToolBox timeout ngắn với hàm giả; không gọi provider, không nạp/gắn nhãn bộ kiểm thử và không chạy lại cohort trả phí. Windows event-loop hook được kiểm bằng test thứ tự gọi, không thay thế chạy trên máy Windows.
