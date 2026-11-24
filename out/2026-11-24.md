# AI Digest: 2026-11-24

## 30-second version

- Hugging Face details agentic evaluation design, hub now 17k datasets, new primitives.
- TipSweep transfers learning rates across block counts, discovers precision-dependent scaling.
- Ollama v0.40.18 adds Metal optimizations, llama.cpp update, drops JetPack 5.
- LocalCode brings open-source agentic coding to Mac with local inference.
- ToolSmith automates tool generation for multimodal search agents, improves performance across benchmarks.

## 1. Hugging Face Details Agentic Evaluation Design and Infrastructure

`Research` · [rss](https://huggingface.co/blog/agentic-evals) · score 8.0

Hugging Face's blog outlines the evolution of AI evaluations from question-answer benchmarks to agentic and multi-agent systems, emphasizing that agentic evaluations are now prominent in model releases. The post details the anatomy of an agentic evaluation — task, agent harness, environment, rollout, and checks — and notes that changing the agent harness alone can shift accuracy by up to 29.9 percentage points, as shown in a Terminal-Bench audit. Hugging Face also highlights its hub's growth to roughly 17,000 evaluation datasets and new primitives like Traces, Benchmarks, and Environments for agentic workflows.

**Why it matters:** Practitioners building or comparing agents must account for the full evaluation stack, not just the model, because harness and environment choices materially affect reported scores. Open tooling and shared evaluation components enable reproducibility and faster iteration.

## 2. TipSweep transfers learning rates across block counts in LLM post-training

`Research` · [arxiv](https://arxiv.org/abs/2611.31166v1) · score 8.0

Researchers propose TipSweep, a method that finds the optimal learning rate by training only the last transformer block (k₀=1) and then predicts the rate for any number of blocks k. They discover precision-dependent scaling: optimal LR scales as k⁻¹ with FP32 master weights but as k⁻¹ᐟ² when updating BF16 weights directly, explained by an analytical model of update rounding.

**Why it matters:** Practitioners can reduce costly learning-rate grid searches in SFT, DPO, and RLVR by profiling a single block on consumer GPUs, then applying the precision-aware scaling rule to full-model runs.

## 3. Ollama v0.40.18 adds Metal optimizations and llama.cpp update

`Tools` · [github](https://github.com/ollama/ollama/releases/tag/v0.40.18) · score 7.0

Ollama released v0.40.18 with MLX improvements including fused Inkling residual mixing on Metal and faster decode, prefill, and draft rounds for Inkling2. The release also shares tensor helpers across architectures in mlxrunner, bumps llama.cpp to version b12651, and drops JetPack 5 support.

**Why it matters:** Practitioners running models on Apple Silicon get faster inference through Metal optimizations, while the llama.cpp update brings upstream fixes and performance improvements. Removal of JetPack 5 support may affect users on older NVIDIA Jetson platforms.

## 4. LocalCode brings open-source agentic coding to Mac with local inference

`Tools` · [hackernews](https://github.com/mjwsolo/localcode) · score 7.0

LocalCode is an open-source agentic coding tool for Mac that runs entirely locally via a single command install. It offers 12 models with 169 quantization options from Hugging Face, featuring speculative decoding for Gemma, Qwen, and Muse models, precompiled GPU kernels, and an OpenAI-compatible API endpoint.

**Why it matters:** Practitioners get a fully local coding agent with model flexibility and no data leaving the machine, while still supporting web tools and MCP servers when needed.

## 5. ToolSmith Automates Tool Generation for Multimodal Search Agents

`Research` · [arxiv](https://arxiv.org/abs/2611.31198v1) · score 7.0

The authors propose ToolSmith, an automatic tool-generation framework that expands a lean base tool library by creating and reusing modules. Evaluated on three in-domain and ten out-of-domain multimodal search benchmarks using a VLM-as-a-Judge protocol, ToolSmith consistently improves performance across agents of varying scales, with larger backbones showing greater gains.

**Why it matters:** For practitioners building multimodal search agents, ToolSmith reduces the manual effort of crafting and maintaining tool libraries while enabling adaptation to new query types and evidence formats, and scales with larger models.

## 6. Attention Temperature Miscalibration Confounds Zero-Shot Context Extension Results

`Research` · [arxiv](https://arxiv.org/abs/2611.31113v1) · score 7.0

The paper demonstrates that evaluating context extension at default temperature τ=1 can falsely favor attention modifications due to baseline miscalibration. Under standard fp32 training, 8k-trained baselines are 8-15% miscalibrated at 30k context; in pure-bf16 without master weights, miscalibration reaches 37-58% because AdamW steps on gain parameters are smaller than bf16 precision, freezing gains for 22 checkpoints. Calibrating temperature per model and length eliminates apparent advantages of block-sparse attention, attention dropout, and ALiBi, while unfreezing gains reverses or substantially reduces the block-sparse benefit.

**Why it matters:** Practitioners must report context extension results at calibrated temperatures and verify that normalization gains actually update during training, otherwise architectural improvements may be misattributed to what are essentially evaluation artifacts.

## 7. Greptile tests LLMs with screenshots vs accessibility trees for computer use

`Agents` · [hackernews](https://www.greptile.com/blog/trex-computer-use) · score 6.0

Greptile evaluated seven models on 172 OSWorld tasks using three vision setups: screenshots only, screenshots plus accessibility tree, and element-ID selection. GPT-4.1 achieved 5.4% with screenshots alone, while GPT-6.1 Sol reached 83.8%; the accessibility tree provides element positions and IDs, removing the need for models to predict pixel coordinates.

**Why it matters:** Coordinate prediction remains a major failure mode for computer-use agents, especially on high-resolution screens; exposing the accessibility tree or letting models select elements by ID can dramatically improve reliability without requiring stronger vision models.

## 8. Beginner's guide to running local LLMs with Unsloth, Qwen, and Inkling on Windows

`Tools` · [hackernews](https://www.gpupartner.com/blog/beginners-guide-local-ai-inkling-qwen-unsloth) · score 6.0

The author describes setting up a private, free ChatGPT alternative on a home PC using Unsloth Desktop and quantized open-weight models like Qwen and Inkling. The guide covers VRAM requirements, quantization tradeoffs (Q8 to Q2), and recommends MoE models such as Qwen3.6-35B and Inkling 2 Mini for consumer GPUs with 16GB VRAM, achieving ~47 tokens/second on an RTX 5060 Ti.

**Why it matters:** Shows engineers a practical, no-terminal path to run capable local models on Windows hardware, with concrete VRAM-to-model mappings and quantization guidance for balancing context length, speed, and quality.

---

87 fetched → 85 unique → 83 new → 60 ranked → 8 published in 193.5s
- `openrouter/baidu/ernie-5.5-flash-preview:free`: 3 calls (0 cached), 13419 tokens, ~13482 ms avg
- `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`: 9 calls (0 cached), 11968 tokens, ~16016 ms avg
