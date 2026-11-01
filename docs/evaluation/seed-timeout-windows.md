# Seed Memory timeout trên Windows: điều tra và đường chạy an toàn

## Bằng chứng trong ảnh

- Hai cấu hình đều dừng ở `seed S-OLD-1`, tool `memory_commit_facts`, mã `TIMEOUT`, deadline 10 giây.
- Không có lượt **được chấm**: `labelled 0 turns`, `n_turns: 0`, `scenarios_stopped: 1`. Bảng 0/None sau đó là cohort chưa chạy, không chứng minh agent đạt 0 điểm. Retrieval offline vẫn có thể có số riêng và không chứng minh hội thoại đã chạy.
- Ảnh ghi `product-extractor-v5`; main khảo sát `1a812462` dùng v7. Người dùng xác nhận ảnh thuộc main trước merge local. Bản `284c6546` trước merge đã gọi hook Windows ở CLI, nên thiếu hook ở một bản local không đủ giải thích ảnh này. Chưa có SHA/dependency/log của máy Windows để kết luận nguyên nhân cụ thể.
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

Các test của lần sửa đầu dùng fake model/tool và kiểm thứ tự gọi hook, không thay thế chạy trên Windows. Lần audit tiếp theo đã chạy thêm PostgreSQL/MCP thật và một scenario có model, như dưới đây.

## Audit xuyên suốt ngày 2026-11-02

Đã rà root CLI → chọn database `_eval` → role MCP → reset/seed → warm-up/graph/after-call → extractor → schema/blocker → freeze → retrieval → scorer → report/table. ASR vẫn là nhánh độc lập; `--config` chỉ xuất trace, còn không truyền `--config` mới chạy cả full/baseline và xuất bảng. Kiểm hash xác nhận pack BTC/scorer không đổi.

Các lỗi được tái hiện bằng test và sửa trong đợt audit:

| Điểm | Sửa và kiểm chứng |
|---|---|
| Pool khởi tạo lỗi/bị hủy | Đóng pool chưa công bố kể cả `CancelledError` và AnyIO cancel scope, shield thao tác dọn tài nguyên. Không retry write hoặc tăng deadline. |
| Encoding khi xuất bảng | Tái hiện `UnicodeEncodeError` khi subprocess dùng `cp1252`; root CLI và subprocess scorer dùng UTF-8. Có test gọi root CLI thật và scorer thật qua pipe encoding cũ. |
| Output đã có dữ liệu | Từ chối trước khi kết nối DB/gọi model, cả chạy mới và relabel. Single-config vẫn có thể dùng thư mục chung với prefix khác. Không để bảng cũ tồn tại bên trace vừa bị ghi đè. |
| Trạng thái hoàn thành quá sớm | Khởi tạo manifest `INCOMPLETE`, dùng `TRACED` sau khi có trace hợp lệ, chỉ ghi `COMPLETE` sau scorer và file output thành công. Lỗi setup/graph/RAG ghi log riêng; scorer lỗi không tạo `table.txt`. |
| Relabel trace từ `--config` | Kiểm cả `full.manifest.json`/`baseline.manifest.json` và diagnostics có prefix, để lỗi thực thi của run một cấu hình không bị bỏ qua. |

Test tích hợp mới `tests/agent/test_eval_seed_postgres.py` dùng database local kết thúc bằng `_eval`, schema UUID riêng và MCP stdio thật, không gọi model. Nó kiểm writer cold-start ghi seed, role khác đọc được facts/episodes, rồi parent reset và seed lại không bị giữ khóa. CI có PostgreSQL và bật test này qua `EVAL_TEST_DATABASE_URL`; thiếu biến thì test skip rõ ràng.

Kiểm tra cuối toàn repo: `python -m pytest -q`, với DB test riêng và không có weights ASR, **1045 passed, 16 skipped**. Các test pytest chặn provider; chỉ smoke command dưới đây gọi model.

Đã chạy đúng root entrypoint trên **một scenario** `SCN-GEN-0001` từ `data/seed-dev/scenarios`, với PostgreSQL Docker tmpfs riêng, model cấu hình thực tế, `--warmup 0`, extractor v7 và ledger đang dùng:

```text
run_eval.py --scenarios data/seed-dev/scenarios --only SCN-GEN-0001 --warmup 0 --out evaluation/runs/20261102-pipeline-audit-main-01
```

- Exit **0**, manifest **COMPLETE**, **8 full + 8 baseline**; lỗi turn, label, after-call, schema, rejected/stopped và empty trace đều **0**.
- Có `report.json`, `table.txt`, `errors.jsonl`, snapshots scenario và RAG; scorer hash `18f1fa0881a345b8dd01c4160ec8fc31aea5ff8385c09a3eb3db96a88372843e`.
- TSR smoke vẫn **0**: scorer ghi thiếu `order.create`/`order.status` khớp yêu cầu và các điều kiện lời nói. Đây là kết quả nghiệp vụ cần phân tích riêng; không phải lượt chạy rỗng hay lỗi xuất bảng. Không đổi agent, nhãn hoặc prompt để làm đẹp ca này.
- Ledger tăng **1.822040678 USD** theo đơn vị sổ; trong đó **1.689228800 USD** là 4 reservation của stream chưa có usage chắc chắn. Đây không phải kết luận số tiền provider đã thu. Giữ nguyên reservation và cap, không reset/hoàn trả thủ công để chạy tiếp.
- Bằng chứng có thể chứa hội thoại, chỉ giữ trong `evaluation/runs/` đã ignore. Kiểm tra này chạy trên macOS với PostgreSQL Docker, chưa xác nhận trực tiếp Windows. `--warmup 0` và 8 lượt mỗi cấu hình không đủ để kết luận latency benchmark hoặc chất lượng toàn bộ cohort.

Điều kiện vận hành vẫn áp dụng: một runner cho mỗi database `_eval`, PostgreSQL còn kết nối/slot, model provider hoạt động và ledger đủ ngân sách. Bộ test cùng một smoke scenario xác nhận đường đã kiểm, không bảo đảm mọi môi trường hoặc mọi kịch bản sẽ thành công.

## Guardrails bổ sung sau audit ngày 2026-11-02

Đợt bổ sung này kiểm đường agent, relabel, RAG và ASR ở tải một hoặc nhiều CLI process; không chạy model. Giữ nguyên pack/scorer main, prompt extractor, scenario và ground-truth. Các thay đổi đã có trong working tree trước audit được giữ lại.

| Lỗi đã xác nhận | Guardrail đã thêm |
|---|---|
| Thiếu ledger vẫn có thể gọi model; SDK retry che usage của request trước | Bắt buộc ledger hiện hữu, hợp lệ và còn cap trước DB/model, cả `--no-extract`/`--relabel`. Chặn tiền âm/NaN/infinity, không tự tạo lại file mất, yêu cầu SDK `max_retries=0`. |
| Hai runner reset chung database; URL query có thể chọn database khác phần path | Giữ PostgreSQL advisory lock xuyên toàn run, fail ngay khi bị chiếm. Kiểm tên database thực qua libpq và `current_database()`; kết nối tạo DB luôn trỏ `postgres`. |
| Hai process có thể cùng thấy output rỗng rồi ghi chồng; nguồn scenario có thể đổi sau khi load | Giữ chỗ output độc quyền, kiểm cả cohort và prefix cấu hình. Freeze từ `Scenario.data` trước model, manifest hash và scorer dùng snapshot đó. |
| Scenario hỏng vẫn tiêu model rồi mới lỗi schema | Chặn ID trùng/thiếu, `--only` không tồn tại, call sai tên/kiểu hoặc quá ba cuộc, lượt khách không phải list chuỗi không rỗng và seed sai slot/kiểu/ngày/kênh trước model. |
| Trace thiếu/trùng/trộn run vẫn có thể được scorer chấp nhận | Kiểm đúng scenario/call/turn, config, lời khách và một run ID trước extractor, single-config export, scorer và relabel. Lưu replies/diagnostics/usage sau mỗi scenario. |
| Lỗi extractor bị ghi nhầm thành lỗi thực thi, làm relabel không sửa được | Ghi `stage=extraction` riêng; trace đầy đủ có thể relabel. Seed/graph/after-call lỗi hoặc manifest có failure chưa rõ vẫn chặn, không biến thành số đo hợp lệ. |
| After-call bỏ qua lỗi đọc memory/ghi episode, hoặc mất bằng chứng facts đã commit khi QA/summarizer lỗi | Trả `failed` thay vì `done`, giữ `memory_writes` đã ghi; chỉ ghi loại exception trong lỗi trả về. Trace của các cuộc đã hoàn thành vẫn được giữ nếu cuộc sau lỗi. |
| Cache hỏng thành nhãn rỗng thành công; hai writer đụng cùng file tạm | V8 validate cache hit bằng `Items`; cache sai thành miss. File tạm riêng + atomic replace chặn crash do writer khác. |
| RAG tuning/report tính `by_type_recall@5` trên mẫu số cả bộ | Đưa snapshot câu hỏi tập con cho scorer main; không sửa công thức scorer. |
| Package/review ASR hỏng làm thoát bất ngờ; scorer ASR lỗi hoặc thiếu số vẫn có thể trông như hoàn tất | Kiểm schema/ID/path/duplicate key/provenance trước output; lỗi scorer hoặc WER/CER/count không hợp lệ thành `INCOMPLETE`. Transcript của `--asr-audio` chỉ nằm trong bằng chứng riêng. |

Kiểm tra cuối bằng Python của agent: **1156 passed, 16 skipped** (`python -m pytest -q`), có `EVAL_TEST_DATABASE_URL` trỏ PostgreSQL 17 tạm trên localhost. Test chạy MCP stdio thật, writer cold-start, reset/seed lại, cạnh tranh advisory lock và giải phóng lock sau exception. Container tạm đã được dọn. Các test tích hợp backend PostgreSQL/Redis riêng không được cấu hình vẫn skip; không tính skip là pass.

Extractor đổi từ `product-extractor-v7` sang **v8** vì source/hash của instrument đổi để thêm guardrail cache. Prompt, schema và phép chiếu nhãn giữ nguyên. Không so trực tiếp số v7/v8; dùng `run_eval.py --relabel` trên cùng replies khi đủ ngân sách. Đợt bổ sung này có **0 request provider**, không sửa ledger/reservation; tại lúc kiểm chỉ đọc, ledger còn khoảng **1,64 USD** trong cap 50 USD.

Giới hạn còn lại: chưa chạy provider thật với v8 hoặc runtime Windows. Cache JSON có thể mất hit giữa hai writer snapshot, dẫn đến cache miss thêm trong cap; file vẫn nguyên vẹn. Các kiểm tất định chứng minh hình dạng/nguồn bằng chứng, không thay thế duyệt đúng sai ngữ nghĩa của extractor hoặc đo chất lượng agent.
