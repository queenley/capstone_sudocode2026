from __future__ import annotations
import argparse, hashlib, json, random
from pathlib import Path
import numpy as np, soundfile as sf, yaml
from src.elevenlabs_client import ElevenLabsClient
from src.schemas.catalog import CustomerCatalog
from src.schemas.conversation import Conversation
from src.utils.audio_noise import NOISE_TYPES, add_noise
from src.utils.io import load_model
ROOT=Path(__file__).resolve().parents[2]
def main():
    p=argparse.ArgumentParser(); p.add_argument("--limit",type=int,default=100); p.add_argument("--noise-persona",action="append",default=[]); a=p.parse_args()
    cfg=yaml.safe_load((ROOT/"config/settings.yaml").read_text(encoding="utf-8")); budget=cfg["budget"]["max_elevenlabs_chars_per_run"]
    tts=ElevenLabsClient(ROOT/"config/voices.yaml",ROOT/"output/audio",budget)
    customer_rows=load_model(ROOT/"data/catalog/crm_seed.json",CustomerCatalog).customers
    synthetic=ROOT/"data/catalog/crm_seed_synthetic.json"
    if synthetic.exists(): customer_rows.extend(load_model(synthetic,CustomerCatalog).customers)
    customer_by_id={c.customer_id:c for c in customer_rows}
    for conv_index,cp in enumerate(sorted((ROOT/"output/conversations").glob("*.json"))[:a.limit]):
        conv=load_model(cp,Conversation); seed=int.from_bytes(hashlib.sha256(conv.conversation_id.encode()).digest()[:4],"big"); rng=random.Random(seed)
        rendered=[]; meta_turns=[]; cursor=0
        for turn in conv.turns:
            item=turn.root; role="agent" if item.speaker.startswith("agent") else "customer"
            customer=customer_by_id.get(conv.customer_id)
            honorific=(customer.honorific.lower() if customer else "")
            gender=("female" if role=="agent" else "male" if honorific in ("anh","chú","ông","em trai") else "female")
            age_band=("adult" if role=="agent" else "senior" if honorific in ("cô","chú","bác","ông","bà") else "adult")
            voice=tts.pick_voice(role,gender,conv.region,age_band,conv.customer_id)
            pcm=tts.synthesize_turn(item.text,voice); samples=np.frombuffer(pcm,dtype="<i2").astype(np.float32)/32768
            pause=int(item.pause_before_ms*16)
            if item.barge_in and pause<0 and rendered:
                trim=min(-pause,len(rendered[-1]))
                rendered[-1]=rendered[-1][:-trim] if trim else rendered[-1]
                cursor-=trim
                if meta_turns: meta_turns[-1]["end_ms"]=round(cursor/16)
                pause=0
            if pause>0: rendered.append(np.zeros(pause,dtype=np.float32)); cursor+=pause
            start=cursor; rendered.append(samples); cursor+=len(samples)
            meta_turns.append({"speaker":item.speaker,"start_ms":round(start/16),"end_ms":round(cursor/16),"voice_id":voice,"text":item.text})
        if not rendered: continue
        clean=np.concatenate(rendered); kind=None; snr=None
        force_weak=any(tag in " ".join([conv.persona]).lower() for tag in a.noise_persona) or "asr" in conv.persona.lower()
        if force_weak or conv_index % 5 == 0:
            kind="weak_signal" if force_weak else NOISE_TYPES[(conv_index//5)%len(NOISE_TYPES)]; snr=rng.choice([5,8,10,15])
        output=add_noise(clean,16000,kind,snr,seed)
        out=ROOT/"output/audio"/(cp.stem+".wav"); out.parent.mkdir(parents=True,exist_ok=True); sf.write(out,output,16000,subtype="PCM_16")
        meta={"conversation_id":conv.conversation_id,"language_detection":"auto","model_id":"eleven_v4",
              "sample_rate":16000,"duration_seconds":len(output)/16000,
              "noise":None if kind is None else {"type":kind,"snr_db":snr},"turns":meta_turns}
        out.with_suffix(".meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    (ROOT/"output/reports").mkdir(parents=True,exist_ok=True)
    (ROOT/"output/reports/elevenlabs_usage.json").write_text(json.dumps({"characters_sent":tts.characters_sent,"budget":budget},indent=2),encoding="utf-8")
    print(f"Audio characters sent: {tts.characters_sent}/{budget}")
if __name__=="__main__":main()
