# Prompts

Mọi prompt đưa cho model đều nằm ở đây, mỗi thư mục con ứng với một project. Code chỉ đọc file, không viết prompt trong code.

| File | Dùng ở | Ghi chú |
|---|---|---|
| `agent/advisor/rules.md` | `agents/advisor.py` (`HARD_RULES`) | Luật cứng, mục đầu của system prompt |
| `agent/advisor/notes.yaml` | `agents/advisor.py` | Ghi chú theo lane, câu xác minh danh tính, lời mở đầu, copilot, kênh chat/thoại. `{must_not_ask}` được điền lúc chạy |
| `agent/memory_extractor.md` | `agents/memory.py` | Rút thông tin khách sau cuộc gọi. `{slots}` được điền lúc chạy |
| `agent/context_compactor.md` | `components/context/compact.py` | Tóm tắt lượt cũ. `{previous}`, `{turns}` |
| `agent/tts_openai.md` | `components/voice/tts.py` | Chỉ dẫn giọng đọc cho model gpt-4o TTS |
| `evaluation/extractor.txt` | `components/evaluation/scorers.py` | Prompt của extractor gắn nhãn câu hỏi, claim và `facts_used`. Nạp nguyên văn, không `.format` |
| `data-generation/*.jinja` | `evaluation/data-generation/src/pipeline/generate_{scenarios,dialogue}.py` | `voice_direction.jinja` hiện chưa có code dùng |
| `data-generation/synthetic_customers.md` | `generate_synthetic_customers.py` | Sinh hồ sơ CRM giả lập |

Lưu ý khi sửa:

- Nội dung file chính là prompt. Code đọc CRLF thành LF và bỏ đúng một dòng trống cuối file, nên editor tự đổi những thứ đó cũng không sao. Riêng `evaluation/extractor.txt` và các `.jinja` được đọc nguyên văn.
- `memory_extractor.md` nằm trong `PROMPT_SHA` của agent, và `evaluation/extractor.txt` nằm trong khóa cache của extractor (`scorers.prompt_sha()`). Sửa một trong hai file thì nhãn cũ trong cache không còn được dùng lại.
- Image Docker của agent copy `agent/` vào `/app/agent/prompts` (`PROMPTS_DIR`). Manifest của mỗi run ghi hash các prompt.
- Persona khách (`data/btc/simulator/personas.json`) và rubric judge là dữ liệu của BTC, không chuyển về đây.
