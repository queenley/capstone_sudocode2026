# Data generation report

_Generated 2026-10-24 05:50. Visual version: [validation_report.html](validation_report.html)._

Generated records are not golden until they pass rules and the judge (or a human approves them).

## M2 volume targets

```mermaid
xychart-beta horizontal
    title "Progress toward M2 targets (%, capped at 100)"
    x-axis ["Transcript conversations (one per call)", "Audio calls", "Audio duration (hours)", "Customers with ≥2 sessions", "Customers with ≥2 channels", "Product categories", "Category × region pairs", "SKUs incl. variants", "Noisy audio ratio (known status)", "Scenarios"]
    y-axis "% of requirement" 0 --> 100
    bar [100, 100, 22, 100, 40, 100, 100, 100, 100, 100]
```

| Metric | Required | Current | Status |
|---|---:|---:|---|
| Transcript conversations (one per call) | 250 | 325 | ✓ PASS |
| Audio calls | 100 | 186 | ✓ PASS |
| Audio duration (hours) | 3 | 0.65 | ○ PENDING |
| Customers with ≥2 sessions | 60 | 60 | ✓ PASS |
| Customers with ≥2 channels | 30 | 12 | ○ PENDING |
| Product categories | 3 | 3 | ✓ PASS |
| Category × region pairs | 9 | 9 | ✓ PASS |
| SKUs incl. variants | 100 | 136 | ✓ PASS |
| Noisy audio ratio (known status) | 20% | 52% | ✓ PASS |
| Scenarios | 40 | 150 | ✓ PASS |

## Chapter A metric coverage

```mermaid
xychart-beta horizontal
    title "Calls with labels per metric"
    x-axis ["CCR", "RQR", "TSR", "HR", "Over-escalation"]
    y-axis "calls" 0 --> 231
    bar [210, 210, 165, 101, 88]
```

| Metric | Calls with labels | Labels | Reference transcript score |
|---|---:|---:|---|
| CCR | 210 | 956 | 42.2 |
| RQR | 210 | 803 | 2.9 |
| TSR | 165 | 165 | 66.3 |
| HR | 101 | 306 | 0.5 |
| Over-escalation | 88 | 9 | 3 |

## Official scores (BTC reference_eval.py)

| Trace | RQR | CCR | TSR | TSR_hard_cases | HR | HR_price_promo | guardrail_violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| oracle | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0 |
| reference | 2.9 | 42.2 | 66.3 | 58.6 | 0.5 | 0.0 | 3 |

Oracle perfect (every label satisfiable with BTC mock_tools): **True**. Score the agent with `data/eval/reference_eval.py --scenarios output/test_set --trace <agent trace>`.

### Test set: 150 scenarios, 325 calls, 105 hard cases

```mermaid
xychart-beta horizontal
    title "Scenarios per hard case"
    x-axis ["16_luot_4_san_pham_vuot_cod", "asr_loi_tool_timeout", "ba_kenh_bao_gia_lech", "ba_phien_doi_thong_tin", "chung_sdt_memory_poisoning", "doi_khuyen_mai_het_han", "doi_san_pham_hoan_chenh_lech", "ep_gia_do_gia_nhap", "hen_goi_lai_ngay_nghi", "het_hang_luc_khach_quyet", "hoi_ai_va_xoa_du_lieu", "km_loai_tru_size", "phien_ban_chinh_sach_cu", "quay_lai_8_thang_ttl_trade_in", "teencode_da_kenh"]
    y-axis "scenarios" 0 --> 14.3
    bar [9, 9, 9, 6, 13, 11, 4, 5, 4, 5, 6, 5, 4, 6, 9]
```


## RAG (Recall@k on rag/qa_labeled.json)

Method: baseline BM25 (syllable uni+bi-grams, 1 chunk per ## [XX-nn], expired docs ×0.6, abstain on restricted intent / internal doc / topical absence)

| recall@3 | recall@5 | multi-hop full@3 | multi-hop full@5 | abstain unanswerable | abstain restricted | false abstain |
|---:|---:|---:|---:|---:|---:|---:|
| 84.7 | 93.2 | 58.3 | 66.7 | 87.5 | 80.0 | 6.4 |

```mermaid
xychart-beta horizontal
    title "Recall@5 by question type (%)"
    x-axis ["single", "multi_hop", "version_conflict", "numeric"]
    y-axis "%" 0 --> 100
    bar [96, 91.7, 100, 75]
```


## ASR (WER / CER / entity accuracy)

Team ASR set: 0 dialogues (BTC requires >= 20 plus the 12 BTC dialogues).
- btc: no hypotheses scored yet (`python -m src.pipeline.eval_asr --set btc ...`)
- team: no hypotheses scored yet (`python -m src.pipeline.eval_asr --set team ...`)

## Tools vs BTC tool set

Tools not in BTC set: none · extra params: `inventory.check`: ['variant_sku'] · details: `output/reports/tools_audit.md`.

## LLM-judge vs human agreement

Not measured yet: `python -m src.pipeline.judge_agreement --export` then `--ingest`.

## Simulator repeatability

- Replays: 975 across 3 seeds.
- TSR across seeds: 66.8 ± 0.0 points (within the ≤ 10-point BTC tolerance).

## Audio analysis

```mermaid
xychart-beta horizontal
    title "Audio turns by noise type"
    x-axis ["clean", "cafe", "street", "weak_signal", "wind", "unknown"]
    y-axis "turns" 0 --> 366.3
    bar [333, 97, 96, 86, 85, 2]
```

```mermaid
xychart-beta horizontal
    title "Customers by number of audio calls"
    x-axis ["2 calls", "3 calls", "4 calls", "5 calls", "6 calls", "8 calls", "11 calls"]
    y-axis "customers" 0 --> 18.7
    bar [17, 5, 16, 8, 1, 2, 1]
```


- **699 customer turns** in **186 calls** from 85 scenarios and 50 customers; **0.65 h** total (mean 3.32 s/turn, 12.5 s/call), 35 distinct voices.
- Customers with ≥2 audio calls: 50 · with ≥2 channels: 9.
- Noisy turns: 364/697 with known status (52%); calls with ≥1 noisy turn: 172/186 (92%).

> 2 turns have no TTS metadata (noise/voice unknown). Re-run `synthesize_scenario_audio` for those scenarios to restore it.

### Noise

| Noise | Turns | Share of turns | Minutes |
|---|---:|---:|---:|
| clean | 333 | 48% | 18.4 |
| cafe | 97 | 14% | 5.45 |
| street | 96 | 14% | 5.14 |
| weak_signal | 86 | 12% | 4.92 |
| wind | 85 | 12% | 4.69 |
| unknown | 2 | 0% | 0.13 |

SNR (dB) of noisy turns: 6 dB × 364

### By channel

| Channel | Calls | Turns | Customers | Minutes | Noisy turns | Noise mix |
|---|---:|---:|---:|---:|---:|---|
| chat_fanpage | 10 | 40 | 8 | 2.43 | 20/40 (50%) | cafe 4, clean 20, street 4, weak_signal 7, wind 5 |
| hotline | 170 | 638 | 50 | 35.08 | 332/636 (52%) | cafe 88, clean 304, street 91, unknown 2, weak_signal 74, wind 79 |
| unknown | 1 | 2 | 1 | 0.13 | 1/2 (50%) | clean 1, weak_signal 1 |
| zalo_oa | 5 | 19 | 5 | 1.1 | 11/19 (58%) | cafe 5, clean 8, street 1, weak_signal 4, wind 1 |

### By input mode

| Mode | Calls | Turns | Customers | Minutes | Noisy turns | Noise mix |
|---|---:|---:|---:|---:|---:|---|
| asr_transcript | 10 | 40 | 4 | 1.84 | 17/40 (42%) | cafe 6, clean 23, street 4, weak_signal 3, wind 4 |
| chat_teencode | 5 | 20 | 5 | 1.17 | 8/20 (40%) | cafe 2, clean 12, street 3, weak_signal 1, wind 2 |
| text | 171 | 639 | 48 | 35.73 | 339/637 (53%) | cafe 89, clean 298, street 89, unknown 2, weak_signal 82, wind 79 |

### Distinct voices by region and gender

| Region | Gender | Voices | Calls | Turns | Customers |
|---|---|---:|---:|---:|---:|
| bac | female | 6 | 24 | 90 | 7 |
| bac | male | 3 | 29 | 108 | 8 |
| nam | female | 8 | 31 | 116 | 8 |
| nam | male | 7 | 30 | 118 | 9 |
| trung | female | 9 | 53 | 190 | 13 |
| trung | male | 4 | 19 | 77 | 5 |

### Calls per customer

Distribution — 2 call(s): 17 customers, 3 call(s): 5 customers, 4 call(s): 16 customers, 5 call(s): 8 customers, 6 call(s): 1 customers, 8 call(s): 2 customers, 11 call(s): 1 customers.

| Customer | Name | Region | Scenarios | Audio calls | Turns | Minutes | Channels | Noisy turns |
|---|---|---|---:|---:|---:|---:|---|---:|
| C034 | Loan | trung | 5 | 11 | 40 | 2.5 | hotline ×10, unknown ×1 | 22/40 |
| C031 | Oanh | bac | 4 | 8 | 28 | 1.8 | hotline ×8 | 17/28 |
| C035 | Dung | nam | 4 | 8 | 31 | 1.8 | hotline ×8 | 14/31 |
| C004 | Minh | bac | 2 | 6 | 25 | 1.3 | hotline ×6 | 18/25 |
| C013 | Trang | trung | 2 | 5 | 19 | 1.1 | chat_fanpage ×2, zalo_oa ×1, hotline ×2 | 12/19 |
| C014 | Huy | trung | 2 | 5 | 24 | 1.2 | hotline ×3, chat_fanpage ×1, zalo_oa ×1 | 12/24 |
| C017 | Hạnh | nam | 2 | 5 | 17 | 1.1 | chat_fanpage ×2, hotline ×2, zalo_oa ×1 | 9/17 |
| C018 | Quân | nam | 2 | 5 | 24 | 1.3 | chat_fanpage ×1, zalo_oa ×1, hotline ×3 | 12/24 |
| C019 | Linh | trung | 2 | 5 | 23 | 1.4 | hotline ×5 | 11/23 |
| C021 | Yến | trung | 2 | 5 | 17 | 1.0 | hotline ×5 | 5/17 |
| C024 | Kiên | trung | 2 | 5 | 20 | 1.0 | hotline ×5 | 15/20 |
| C026 | Dũng | trung | 2 | 5 | 18 | 0.9 | hotline ×5 | 10/18 |
| C001 | Hoa | bac | 2 | 4 | 15 | 0.8 | hotline ×4 | 7/15 |
| C002 | Tuấn | nam | 2 | 4 | 13 | 0.7 | hotline ×4 | 4/13 |
| C003 | Lan | trung | 2 | 4 | 11 | 0.7 | hotline ×4 | 6/11 |
| C005 | Hương | bac | 2 | 4 | 12 | 0.6 | hotline ×4 | 7/12 |
| C006 | Nam | bac | 2 | 4 | 11 | 0.7 | hotline ×4 | 6/11 |
| C007 | Thảo | nam | 2 | 4 | 17 | 0.8 | hotline ×4 | 9/17 |
| C008 | Long | nam | 2 | 4 | 15 | 0.7 | hotline ×4 | 5/15 |
| C009 | Ngọc | trung | 2 | 4 | 13 | 0.8 | chat_fanpage ×1, hotline ×3 | 6/13 |
| C010 | Đức | nam | 2 | 4 | 15 | 0.7 | hotline ×4 | 4/15 |
| C011 | Mai | nam | 2 | 4 | 14 | 0.9 | hotline ×4 | 5/14 |
| C012 | Khoa | bac | 2 | 4 | 14 | 0.7 | hotline ×4 | 9/14 |
| C015 | Vy | nam | 2 | 4 | 12 | 0.8 | hotline ×3, chat_fanpage ×1 | 6/12 |
| C016 | Phúc | bac | 2 | 4 | 17 | 0.7 | hotline ×4 | 7/17 |
| C020 | Sơn | bac | 2 | 4 | 16 | 0.8 | hotline ×4 | 9/16 |
| C038 | Diệp | trung | 2 | 4 | 13 | 0.7 | hotline ×4 | 6/13 |
| C042 | Nga | trung | 2 | 4 | 15 | 0.8 | hotline ×4 | 10/15 |
| C028 | Tú | bac | 1 | 3 | 11 | 0.6 | chat_fanpage ×1, zalo_oa ×1, hotline ×1 | 7/11 |
| C030 | Việt | nam | 1 | 3 | 9 | 0.4 | hotline ×3 | 5/9 |
| C033 | Loan | trung | 1 | 3 | 10 | 0.6 | hotline ×3 | 4/10 |
| C037 | Toàn | nam | 1 | 3 | 11 | 0.5 | hotline ×3 | 6/11 |
| C049 | Trung | nam | 1 | 3 | 12 | 0.5 | hotline ×3 | 4/12 |
| C022 | Bảo | nam | 1 | 2 | 13 | 0.6 | hotline ×2 | 8/13 |
| C023 | Thu | bac | 1 | 2 | 8 | 0.5 | hotline ×2 | 4/8 |
| C025 | Nhung | bac | 1 | 2 | 8 | 0.4 | hotline ×2 | 4/8 |
| C027 | Chi | bac | 1 | 2 | 7 | 0.4 | chat_fanpage ×1, hotline ×1 | 4/7 |
| C029 | Hà | bac | 1 | 2 | 12 | 0.6 | hotline ×2 | 10/12 |
| C032 | Tâm | trung | 1 | 2 | 6 | 0.4 | hotline ×2 | 2/4 |
| C036 | Phương | nam | 1 | 2 | 10 | 0.5 | hotline ×2 | 7/10 |

_10 more customers in `audio_statistics.json`._

## Review funnel

```mermaid
xychart-beta horizontal
    title "Reference transcripts through the gates"
    x-axis ["Generated", "Rule pass", "Judge pass", "Human approved", "Golden"]
    y-axis "conversations" 0 --> 357.5
    bar [325, 16, 14, 0, 0]
```

Generated **325** → Rule pass **16** → Judge pass **14** → Human approved **0** → Golden **0**

- CRM profiles: 60 (incl. synthetic when generated)
- Model API requests: 1015 · cache hits: 51 · prompt tokens: 5906562 · output tokens: 371992
- ElevenLabs characters: 36235
