# tts-service

VieNeu-TTS (ONNX Runtime, CPU) as its own service: the voice of the calls. The agent streams each sentence from it
when `TTS_URL` is set and `VOICE_TTS=vieneu:` (`apps/ai-agent-service/.../components/voice/tts.py`,
`RemoteVieNeuVoice`), so the agent image carries neither VieNeu nor its 1.4 GB of weights, and synthesis never takes
CPU from a turn.

```
POST /v1/speak      {"text": "Dạ, máy còn hàng ạ.", "voice": null}
                    -> 16-bit little-endian mono PCM, streamed; the rate in X-Sample-Rate
GET  /health        alive
GET  /health/ready  503 until the model is loaded and warmed
```

| Variable | Default | |
|---|---|---|
| `OMP_NUM_THREADS` | all CPUs | ONNX Runtime's threads: set it to the container's CPU limit |
| `TTS_MODE` | `v3nano` | VieNeu's model: `v3turbo` streams, 48 kHz, about 1.7 GiB; `v3nano` is lighter (about 0.7 GiB, 24 kHz) and returns each sentence whole |
| `TTS_CONCURRENCY` | 1 | sentences synthesised at once; on a small CPU share more only slows each one |
| `TTS_MAX_CHARS` | 600 | longest text a request; the agent sends one sentence |
| `TTS_API_KEY` | empty | required as `Authorization: Bearer` when set |
| `HF_HOME` | `/models/huggingface` | where the weights download on the first start |

Locally: `docker compose --profile tts up -d tts-service`, then `TTS_URL=http://tts-service:8600` and
`VOICE_TTS=vieneu:` for the agent. On EKS: [tts.yaml](../../infra/kubernetes/overlays/aws-production/tts.yaml)
(0.1 vCPU and 2 GiB reserved, bursting to 2 vCPUs).

## Measured (2026-11-28)

On a laptop whose Docker CPU does about 4 GFLOPS (numpy 1024² matmul; a current EC2 core does several times that),
so these are a floor, not the cluster's figures:

| Model | vCPU | RAM | First audio | Synthesis time ÷ speech length |
|---|---|---|---|---|
| v3turbo | 2 | 1.6-1.75 GiB | 2.6-8 s | 8.6-13 |
| v3turbo | 4 | 1.7 GiB | 4-20 s | 9-26 (the machine was busy) |
| v3nano | 2 | 0.7 GiB | 17-38 s (whole sentence) | 5.4-15 |

A call needs the second figure under 1. EKS keeps `openai:coral` until the same timing on a node
(`python apps/tts-service/tts_time.py` against `kubectl port-forward deploy/tts-service 8600`) says VieNeu keeps up.
