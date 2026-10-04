import fs from 'node:fs';
import path from 'node:path';
const dir=path.dirname(new URL(import.meta.url).pathname);
const esc=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;');
function drawing(name,title,subtitle,w,h,build){
  // Square export canvas prevents Quick Look's square thumbnail from cropping the right branch.
  h=w;
  const parts=[`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="#62758a"/></marker></defs><rect width="100%" height="100%" fill="#f7fafc"/><style>text{font-family:Arial,sans-serif;fill:#18334e}.title{font-size:28px;font-weight:700}.sub{font-size:17px;fill:#526a80}.label{font-size:19px;font-weight:600}.body{font-size:17px}.edge{fill:none;stroke:#62758a;stroke-width:2;marker-end:url(#arrow)}</style><text x="40" y="45" class="title">${esc(title)}</text><text x="40" y="78" class="sub">${esc(subtitle)}</text>`];
  function box(x,y,bw,bh,lines,color='#e5f2ff'){parts.push(`<rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="13" fill="${color}" stroke="#9ab1c5"/>`);lines.forEach((s,i)=>parts.push(`<text x="${x+bw/2}" y="${y+30+i*25}" text-anchor="middle" class="${i?'body':'label'}">${esc(s)}</text>`));}
  function line(points,label='',lx,ly){parts.push(`<polyline points="${points.map(p=>p.join(',')).join(' ')}" class="edge"/>`);if(label)parts.push(`<text x="${lx}" y="${ly}" class="sub">${esc(label)}</text>`);}
  build(box,line,parts);parts.push('</svg>');fs.writeFileSync(path.join(dir,name+'.svg'),parts.join('\n'));
}
drawing('runner-01-execution','1. Chuẩn bị và chạy Evaluation Runner','Fixed-turn là phép đo chính; ASR là suite độc lập, có thể liên kết bằng scenario_id.',1320,1050,(b,l)=>{
 b(40,110,370,115,['Frozen / scenario + contract','M1: ≥20 đa phiên + ≥5 ca khó','M2: ≥40; khai báo suite áp dụng']);
 b(475,110,370,115,['Cấu hình + GT cố định','Model, prompt, tools, KB, seed','Catalog / policy đúng ngày gọi']);
 b(910,110,370,115,['ASR eval set riêng','Audio + transcript / entity chuẩn','BTC khi phát + ≥20 file nhóm']);
 l([[225,225],[225,260],[420,260],[420,285]]);l([[660,225],[660,260],[420,260]]);
 b(190,285,460,95,['Preflight + manifest','Schema, ID, hash, expected call/turn']);
 l([[420,380],[420,420]]);
 b(190,420,460,90,['Evaluation Runner — một lệnh','Hai state độc lập, cùng scenario / seed']);
 l([[310,510],[310,550],[220,550],[220,580]]);l([[530,510],[530,550],[660,550],[660,580]]);
 b(40,580,360,140,['System: Memory ON','Call 1 → chờ after-call / memory','Đổi ngày → Call 2 / Call 3…','Đọc memory đúng khách'], '#dcf7ed');
 b(480,580,360,140,['Baseline: Memory OFF','Cùng call / ngày / tools / KB','Chặn đọc memory hội thoại cũ','Working memory vẫn có'], '#eef0ff');
 l([[220,720],[220,760],[420,760],[420,800]]);l([[660,720],[660,760],[420,760]]);
 b(190,800,460,140,['Evidence tách theo config','Transcript + tool request/result/error','State, Call Brief / Handoff nếu có','Backend timestamps + tokens / cost']);
 l([[1095,225],[1095,285]]);
 b(910,285,370,125,['ASR local + hypothesis','Giữ raw text → normalize WER/CER','ITN tiền / SĐT → entity riêng','M2: speaker + segments']);
 l([[1095,410],[1095,450]]);
 b(910,450,370,110,['ASR Evidence','hypotheses + GT + coverage','Không có audio: chưa đo được']);
 l([[420,940],[420,990]],'Sang bước 2',440,980);l([[1095,560],[1095,990]],'Sang ASR Scorer ở bước 2',880,740);
});
drawing('runner-02-scoring','2. Kiểm chứng evidence → chấm → báo cáo','Giữ report BTC nguyên bản; kiểm tra bổ sung và coverage được báo riêng.',1320,1140,(b,l)=>{
 b(40,110,790,100,['Evidence Memory ON + OFF','Validate schema, ID trùng/thiếu, call/turn, artifact và GT coverage']);
 b(910,110,370,100,['ASR / M2 suite evidence','Kiểm đủ audio_id / qid / seed']);
 l([[435,210],[435,265]]);l([[1095,210],[1095,265]]);
 b(40,265,220,130,['Questions extractor','Slot + open / confirm','→ RQR','Không chỉ đếm text']);
 b(300,265,220,130,['Fact usage checker','facts_used + tool args','→ CCR','Bổ sung đúng value']);
 b(560,265,270,130,['Assertion Runner','success_if từng call','→ TSR + TSR hard','Guardrail / memory checks']);
 b(910,265,370,130,['ASR / RAG / simulator scorers','ASR: WER, CER, tiền / SĐT','M2: diarization, RAG, 3 seed','Không gộp simulator vào fixed-turn']);
 l([[435,240],[150,240],[150,265]]);l([[435,240],[695,240],[695,265]]);
 b(40,460,350,130,['Claims ↔ GT đúng thời điểm','Giá / KM nguyên tử → HR','Thiếu GT → chưa đủ bằng chứng','Không coi không có claim là đạt']);
 b(450,460,380,130,['Latency + usage scorer','M1: TTFT / total / Call Brief','3 warm-up chỉ bỏ khỏi latency','M2: TTFA + ≥2 phiên đồng thời']);
 b(910,460,370,130,['Quality judge khi áp dụng','Criterion BTC + evidence PASS/FAIL','≥20 mẫu người, báo agreement','Judge lỗi → chưa chấm hoàn tất']);
 l([[40,160],[20,160],[20,435],[215,435],[215,460]]);
 l([[830,160],[865,160],[865,435],[640,435],[640,460]]);
 l([[1280,160],[1300,160],[1300,435],[1095,435],[1095,460]]);
 l([[150,395],[150,415],[420,415],[420,655]]);
 l([[410,395],[410,405],[880,405],[880,655]]);
 l([[1095,395],[1095,420],[895,420],[895,655]]);
 l([[695,395],[855,395],[855,655]]);l([[215,590],[215,655]]);l([[640,590],[640,655]]);l([[1095,590],[1095,655]]);
 l([[215,655],[1095,655]]);l([[660,655],[660,705]]);
 b(260,705,800,110,['Tổng hợp theo suite / cohort — không thay mẫu số âm thầm','BTC raw report + supplemental metrics + validation / coverage','PASS / FAIL riêng với completeness; hard FAIL vẫn giữ']);
 l([[660,815],[660,860]]);
 b(260,860,800,110,['Bảng A.6: Baseline | System | Delta + kiểm ngưỡng','RQR giảm tương đối ≥40%; TSR ≥70%; HR giá/KM ≤5%','RQR baseline=0 / thiếu GT / thiếu evidence → N/A hoặc INCOMPLETE']);
 l([[660,970],[660,1010]]);
 b(260,1010,800,90,['Xuất báo cáo + evidence có thể truy vết','manifest · trace · report_btc · coverage · table · errors (≥10 lỗi)']);
});
drawing('runner-03-assertion-judge','3. Assertion và LLM-judge — hai kết quả tách biệt','Judge-only / Hybrid AND là cách chấm bổ sung của nhóm, không ghi đè TSR reference BTC.',1320,1050,(b,l)=>{
 b(370,110,580,100,['Scenario + grading contract + validated evidence','Ghim mode / applicability / criterion trước run']);l([[660,210],[660,255]]);
 b(370,255,580,100,['Luôn chạy scorer BTC cho phần áp dụng','success_if từng call → TSR chính thức','Không có success_if: ghi coverage, không tự PASS']);l([[660,355],[660,400]]);
 b(370,400,580,95,['Có mục tiêu chất lượng cần Judge?','Theo contract / rubric, không phải assertion FAIL thì đổi judge']);
 l([[370,445],[210,445],[210,540]],'Không',245,430);l([[950,445],[1110,445],[1110,540]],'Có',1005,430);
 b(40,540,340,110,['Assertion-only bổ sung','Kiểm tool thành công / state / PII','Handoff: đủ schema + đúng scope']);
 b(910,540,370,140,['Criterion selector → Judge','Chọn J01–J12 theo applicability','Output PASS/FAIL + evidence','Lỗi: sửa output tối đa 1 lần [nhóm]']);
 l([[1110,680],[1110,725]]);
 b(910,725,370,100,['Judge result hợp lệ?','Không: INCOMPLETE / review','Có: aggregate tiêu chí đã chọn']);
 l([[210,650],[210,865],[660,865],[660,900]]);l([[1110,825],[1110,865],[660,865]]);
 b(260,900,800,110,['Supplemental verdict + completeness','Hybrid: assertion AND judge; lỗi judge không thành PASS','Hard FAIL đã chứng minh vẫn FAIL, dù evidence còn thiếu']);
});
