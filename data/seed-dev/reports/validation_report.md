# Data generation report

_Generated 2026-11-01 12:44. Visual version: [validation_report.html](validation_report.html)._

Generated records are not golden until they pass rules and the judge (or a human approves them).

## M2 volume targets

```mermaid
xychart-beta horizontal
    title "Progress toward M2 targets (%, capped at 100)"
    x-axis ["Transcript conversations (one per call)", "Audio calls", "Audio duration (hours)", "Customers with ≥2 sessions", "Customers with ≥2 channels", "Product categories", "Category × region pairs", "SKUs incl. variants", "Noisy audio ratio (known status)", "Scenarios"]
    y-axis "% of requirement" 0 --> 100
    bar [100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
```

| Metric | Required | Current | Status |
|---|---:|---:|---|
| Transcript conversations (one per call) | 250 | 797 | ✓ PASS |
| Audio calls | 100 | 672 | ✓ PASS |
| Audio duration (hours) | 3 | 3.01 | ✓ PASS |
| Customers with ≥2 sessions | 60 | 76 | ✓ PASS |
| Customers with ≥2 channels | 30 | 52 | ✓ PASS |
| Product categories | 3 | 3 | ✓ PASS |
| Category × region pairs | 9 | 9 | ✓ PASS |
| SKUs incl. variants | 100 | 136 | ✓ PASS |
| Noisy audio ratio (known status) | 20% | 51% | ✓ PASS |
| Scenarios | 40 | 400 | ✓ PASS |

## Chapter A metric coverage

```mermaid
xychart-beta horizontal
    title "Calls with labels per metric"
    x-axis ["CCR", "RQR", "TSR", "HR", "Over-escalation"]
    y-axis "calls" 0 --> 589.6
    bar [519, 519, 536, 233, 166]
```

| Metric | Calls with labels | Labels | Reference transcript score |
|---|---:|---:|---|
| CCR | 519 | 2251 | 100.0 |
| RQR | 519 | 1971 | 0.0 |
| TSR | 536 | 536 | 98.8 |
| HR | 233 | 607 | 0.0 |
| Over-escalation | 166 | 20 | 0 |

## Official scores (BTC reference_eval.py)

| Trace | RQR | CCR | TSR | TSR_hard_cases | HR | HR_price_promo | guardrail_violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| oracle | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0 |
| reference | 0.0 | 100.0 | 98.8 | 99.5 | 0.0 | 0.0 | 0 |

Oracle perfect (every label satisfiable with BTC mock_tools): **True**. Score the agent with `data/eval/reference_eval.py --scenarios <seed>/scenarios --trace <agent trace>`.

### Test set: 400 scenarios, 797 calls, 189 hard cases

```mermaid
xychart-beta horizontal
    title "Scenarios per hard case"
    x-axis ["16_luot_4_san_pham_vuot_cod", "asr_loi_tool_timeout", "ba_kenh_bao_gia_lech", "ba_phien_doi_thong_tin", "chung_sdt_memory_poisoning", "chuyen_nguoi_roi_quay_lai_ai", "doi_khuyen_mai_het_han", "doi_san_pham_hoan_chenh_lech", "ep_gia_do_gia_nhap", "hen_goi_lai_ngay_nghi", "het_hang_luc_khach_quyet", "hoi_ai_va_xoa_du_lieu", "khieu_nai_chuyen_nguoi_roi_ai_theo_doi", "km_loai_tru_size", "phien_ban_chinh_sach_cu", "prompt_injection", "quay_lai_8_thang_ttl_trade_in", "teencode_da_kenh", "y_te_chuyen_nguoi_roi_ai_chot"]
    y-axis "scenarios" 0 --> 23.1
    bar [15, 15, 15, 10, 21, 2, 21, 7, 9, 6, 10, 10, 2, 8, 7, 6, 9, 15, 1]
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

Team ASR set: 24 dialogues (BTC requires >= 20 plus the 12 BTC dialogues).
Scoring: BTC's `reference_eval.py` grades an ASR hypotheses file against this ground truth (`--asr`).

## Tools vs BTC tool set

Tools not in BTC set: `delivery_estimate` · extra params: `order.create`: ['order_group'] · details: `<seed>/reports/tools_audit.md`.

## LLM-judge vs human agreement

Not measured yet: `python -m src.pipeline.judge_agreement --export` then `--ingest`.

## Simulator repeatability

- Replays: 2391 across 3 seeds.
- TSR across seeds: 99.4 ± 0.0 points (within the ≤ 10-point BTC tolerance).

## Audio analysis

```mermaid
xychart-beta horizontal
    title "Audio turns by noise type"
    x-axis ["clean", "wind", "cafe", "street", "weak_signal"]
    y-axis "turns" 0 --> 1656.6
    bar [1506, 412, 396, 394, 357]
```

```mermaid
xychart-beta horizontal
    title "Customers by number of audio calls"
    x-axis ["1 calls", "2 calls", "3 calls", "4 calls", "5 calls", "6 calls", "7 calls", "8 calls", "9 calls", "10 calls", "11 calls", "12 calls", "13 calls", "14 calls", "15 calls", "16 calls", "17 calls"]
    y-axis "customers" 0 --> 11
    bar [3, 7, 1, 5, 4, 4, 6, 9, 10, 4, 8, 4, 4, 2, 2, 4, 2]
```


- **3065 customer turns** in **672 calls** from 342 scenarios and 79 customers; **3.01 h** total (mean 3.53 s/turn, 16.11 s/call), 44 distinct voices.
- Customers with ≥2 audio calls: 76 · with ≥2 channels: 51.
- Noisy turns: 1559/3065 with known status (51%); calls with ≥1 noisy turn: 640/672 (95%).

### Noise

| Noise | Turns | Share of turns | Minutes |
|---|---:|---:|---:|
| clean | 1506 | 49% | 89.86 |
| wind | 412 | 13% | 23.93 |
| cafe | 396 | 13% | 23.35 |
| street | 394 | 13% | 22.71 |
| weak_signal | 357 | 12% | 20.55 |

SNR (dB) of noisy turns: 6 dB × 1559

### By channel

| Channel | Calls | Turns | Customers | Minutes | Noisy turns | Noise mix |
|---|---:|---:|---:|---:|---:|---|
| chat_fanpage | 64 | 299 | 41 | 18.54 | 151/299 (51%) | cafe 27, clean 148, street 43, weak_signal 39, wind 42 |
| hotline | 534 | 2425 | 79 | 140.37 | 1213/2425 (50%) | cafe 320, clean 1212, street 307, weak_signal 273, wind 313 |
| zalo_oa | 74 | 341 | 42 | 21.49 | 195/341 (57%) | cafe 49, clean 146, street 44, weak_signal 45, wind 57 |

### By input mode

| Mode | Calls | Turns | Customers | Minutes | Noisy turns | Noise mix |
|---|---:|---:|---:|---:|---:|---|
| asr_transcript | 32 | 153 | 15 | 8.39 | 71/153 (46%) | cafe 21, clean 82, street 14, weak_signal 17, wind 19 |
| chat_khong_dau | 12 | 51 | 6 | 2.47 | 29/51 (57%) | cafe 4, clean 22, street 8, weak_signal 4, wind 13 |
| chat_sai_chinh_ta | 6 | 25 | 6 | 1.53 | 9/25 (36%) | cafe 5, clean 16, weak_signal 3, wind 1 |
| chat_teencode | 11 | 48 | 11 | 2.5 | 23/48 (48%) | cafe 5, clean 25, street 8, weak_signal 4, wind 6 |
| text | 611 | 2788 | 79 | 165.52 | 1427/2788 (51%) | cafe 361, clean 1361, street 364, weak_signal 329, wind 373 |

### Distinct voices by region and gender

| Region | Gender | Voices | Calls | Turns | Customers |
|---|---|---:|---:|---:|---:|
| bac | female | 7 | 123 | 571 | 14 |
| bac | male | 4 | 114 | 541 | 12 |
| nam | female | 9 | 108 | 478 | 13 |
| nam | male | 9 | 111 | 504 | 12 |
| trung | female | 11 | 134 | 597 | 18 |
| trung | male | 8 | 82 | 374 | 10 |

### Calls per customer

Distribution — 1 call(s): 3 customers, 2 call(s): 7 customers, 3 call(s): 1 customers, 4 call(s): 5 customers, 5 call(s): 4 customers, 6 call(s): 4 customers, 7 call(s): 6 customers, 8 call(s): 9 customers, 9 call(s): 10 customers, 10 call(s): 4 customers, 11 call(s): 8 customers, 12 call(s): 4 customers, 13 call(s): 4 customers, 14 call(s): 2 customers, 15 call(s): 2 customers, 16 call(s): 4 customers, 17 call(s): 2 customers.

| Customer | Name | Region | Scenarios | Audio calls | Turns | Minutes | Channels | Noisy turns |
|---|---|---|---:|---:|---:|---:|---|---:|
| C013 | Trang | trung | 8 | 17 | 77 | 4.9 | chat_fanpage ×3, hotline ×11, zalo_oa ×3 | 47/77 |
| C019 | Linh | trung | 8 | 17 | 72 | 4.0 | chat_fanpage ×2, hotline ×13, zalo_oa ×2 | 43/72 |
| C007 | Thảo | nam | 8 | 16 | 72 | 4.4 | chat_fanpage ×2, hotline ×12, zalo_oa ×2 | 39/72 |
| C031 | Oanh | bac | 9 | 16 | 81 | 5.3 | hotline ×16 | 46/81 |
| C034 | Loan | trung | 8 | 16 | 67 | 4.4 | hotline ×16 | 36/67 |
| C035 | Dung | nam | 8 | 16 | 68 | 4.5 | hotline ×16 | 31/68 |
| C001 | Hoa | bac | 8 | 15 | 66 | 3.9 | zalo_oa ×2, hotline ×11, chat_fanpage ×2 | 30/66 |
| SYN-C001 | Nguyễn Văn A | bac | 9 | 15 | 71 | 4.1 | hotline ×11, zalo_oa ×2, chat_fanpage ×2 | 30/71 |
| C011 | Mai | nam | 6 | 14 | 61 | 3.7 | zalo_oa ×2, hotline ×11, chat_fanpage ×1 | 34/61 |
| SYN-C007 | Lê Thị G | bac | 7 | 14 | 68 | 3.9 | hotline ×11, zalo_oa ×1, chat_fanpage ×2 | 29/68 |
| C003 | Lan | trung | 6 | 13 | 62 | 3.5 | zalo_oa ×3, chat_fanpage ×2, hotline ×8 | 33/62 |
| C009 | Ngọc | trung | 6 | 13 | 64 | 3.6 | hotline ×9, zalo_oa ×2, chat_fanpage ×2 | 31/64 |
| C010 | Đức | nam | 6 | 13 | 59 | 3.1 | chat_fanpage ×3, hotline ×9, zalo_oa ×1 | 25/59 |
| SYN-C004 | Phạm Thị D | bac | 8 | 13 | 61 | 4.0 | zalo_oa ×3, hotline ×8, chat_fanpage ×2 | 34/61 |
| C004 | Minh | bac | 6 | 12 | 59 | 3.0 | chat_fanpage ×3, hotline ×9 | 26/59 |
| C015 | Vy | nam | 6 | 12 | 52 | 3.2 | zalo_oa ×3, hotline ×8, chat_fanpage ×1 | 30/52 |
| C017 | Hạnh | nam | 6 | 12 | 56 | 3.1 | zalo_oa ×2, hotline ×9, chat_fanpage ×1 | 26/56 |
| C023 | Thu | bac | 6 | 12 | 54 | 2.9 | zalo_oa ×2, chat_fanpage ×1, hotline ×9 | 30/54 |
| C005 | Hương | bac | 6 | 11 | 52 | 2.9 | zalo_oa ×2, hotline ×9 | 30/52 |
| C016 | Phúc | bac | 6 | 11 | 52 | 3.0 | chat_fanpage ×2, hotline ×9 | 28/52 |
| C021 | Yến | trung | 6 | 11 | 49 | 2.9 | zalo_oa ×2, hotline ×9 | 19/49 |
| C022 | Bảo | nam | 5 | 11 | 54 | 3.8 | chat_fanpage ×2, hotline ×8, zalo_oa ×1 | 33/54 |
| C025 | Nhung | bac | 6 | 11 | 50 | 3.2 | chat_fanpage ×2, hotline ×7, zalo_oa ×2 | 23/50 |
| C037 | Toàn | nam | 5 | 11 | 48 | 3.4 | hotline ×8, zalo_oa ×2, chat_fanpage ×1 | 22/48 |
| SYN-C003 | Lê Văn C | nam | 6 | 11 | 51 | 3.0 | hotline ×8, chat_fanpage ×2, zalo_oa ×1 | 28/51 |
| SYN-C010 | Trần Văn J | bac | 6 | 11 | 49 | 2.6 | hotline ×9, chat_fanpage ×1, zalo_oa ×1 | 24/49 |
| C027 | Chi | bac | 5 | 10 | 45 | 2.7 | zalo_oa ×2, hotline ×7, chat_fanpage ×1 | 24/45 |
| C043 | Tiến | trung | 5 | 10 | 46 | 2.4 | zalo_oa ×2, hotline ×7, chat_fanpage ×1 | 26/46 |
| SYN-C005 | Nguyễn Văn E | trung | 6 | 10 | 43 | 2.4 | hotline ×7, zalo_oa ×2, chat_fanpage ×1 | 21/43 |
| SYN-C019 | Ngô Văn Phúc | bac | 5 | 10 | 52 | 2.7 | zalo_oa ×1, hotline ×8, chat_fanpage ×1 | 25/52 |
| C014 | Huy | trung | 4 | 9 | 45 | 2.2 | hotline ×9 | 25/45 |
| C018 | Quân | nam | 4 | 9 | 38 | 2.3 | hotline ×6, chat_fanpage ×2, zalo_oa ×1 | 16/38 |
| C024 | Kiên | trung | 4 | 9 | 41 | 1.9 | hotline ×9 | 23/41 |
| C030 | Việt | nam | 4 | 9 | 40 | 2.1 | hotline ×9 | 26/40 |
| C039 | Cường | bac | 4 | 9 | 39 | 2.4 | hotline ×5, zalo_oa ×3, chat_fanpage ×1 | 25/39 |
| C049 | Trung | nam | 4 | 9 | 41 | 2.2 | zalo_oa ×1, hotline ×7, chat_fanpage ×1 | 21/41 |
| SYN-C002 | Trần Thị B | trung | 6 | 9 | 40 | 2.5 | zalo_oa ×2, hotline ×7 | 17/40 |
| SYN-C006 | Trần Văn F | nam | 6 | 9 | 38 | 2.7 | zalo_oa ×2, hotline ×7 | 20/38 |
| SYN-C008 | Nguyễn Văn H | trung | 5 | 9 | 38 | 2.3 | hotline ×6, zalo_oa ×2, chat_fanpage ×1 | 13/38 |
| SYN-C011 | Nguyễn Văn An | trung | 5 | 9 | 43 | 2.6 | zalo_oa ×1, hotline ×8 | 19/43 |

_39 more customers in `audio_statistics.json`._

## Review funnel

```mermaid
xychart-beta horizontal
    title "Reference transcripts through the gates"
    x-axis ["Generated", "Rule pass", "Judge pass", "Human approved", "Golden"]
    y-axis "conversations" 0 --> 876.7
    bar [797, 791, 689, 0, 0]
```

Generated **797** → Rule pass **791** → Judge pass **689** → Human approved **0** → Golden **0**

- CRM profiles: 70 (incl. synthetic when generated)
- Model API requests: 2829 · cache hits: 35 · prompt tokens: 21484854 (cached 16565632) · output tokens: 1902290 · estimated cost: $20.39
- ElevenLabs characters: 0
