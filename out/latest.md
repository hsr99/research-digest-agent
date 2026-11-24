# AI Digest: 2026-11-24

## 30-second version

- LLMs can't self-detect math errors; external low-confidence tokens boost correction up to 22.5 points.
- Conformal Text-to-SQL method certifies risk bounds; accepts 52.4% at 15% risk, 9.1% error.
- SPROUT predicts prompt utility via text-only model, matching uniform sampling in 44% of iterations.
- Corrective Prefix Attention boosts speculative decoding speed 3.37× and token commitment 13–26% on Qwen3.
- Ai2's RoboTrack provides 307 videos and 15M synthetic tracks; trackers reach state-of-the-art on four benchmarks.

## 1. LLMs fail to self-monitor errors but steer when uncertainty injected externally

`Research` · [arxiv](https://arxiv.org/abs/2611.31228v1) · score 8.0

According to the authors, four open-weights models (Qwen2.5-7B, Llama-3.1-8B, Mistral-7B, Phi-4) were evaluated on 15,200 math benchmark attempts. The study finds models cannot detect their own reasoning errors — verbalized confidence stays near 95–99.9% even at the first mistake, with AUROCs of 0.50–0.56. However, injecting a low-confidence token (10%) at the error step significantly increases correction rates across all models (+3.7 to +22.5 points over 95% certainty).

**Why it matters:** Practitioners relying on self-reported confidence for error detection or backtracking in agentic workflows should not trust models to flag their own mistakes; external uncertainty signals are more effective for steering corrections.

## 2. Conformal confidence estimation reduces Text-to-SQL errors with certified risk bounds

`Research` · [arxiv](https://arxiv.org/abs/2611.31190v1) · score 8.0

Researchers propose a probabilistic validation framework that separates SQL generation from critique, using a generator LLM and a separate critic LLM whose scores are fused with generator uncertainty features in a Random Forest. Two calibration steps provide finite-sample guarantees: a Learn-then-Test threshold certifies the error rate among accepted queries stays below a user-defined budget with probability 1-δ, and a conformal p-value bounds false abstentions. On Spider with GPT-OSS-120B as generator and Gemma-4-31B as critic, the method achieves 0.899 AUARC; at a 15% risk budget (δ=0.1), it accepts 52.4% of queries with 9.1% observed error versus 22.6% error without abstention.

**Why it matters:** Practitioners can deploy Text-to-SQL systems with statistically guaranteed error-rate control, enabling safe automation by abstaining on low-confidence predictions rather than returning silently wrong queries.

## 3. SPROUT predicts prompt utility for efficient text-to-image preference tuning

`Research` · [arxiv](https://arxiv.org/abs/2611.31163v1) · score 8.0

Researchers propose SPROUT, a prompt selection framework that uses a text-only model to predict the objective-grounded utility (gradient norm) of each prompt for direct group preference optimization (DGPO). On Stable Diffusion 1.5 fine-tuned on GenEval, SPROUT matches uniform sampling's final score in about 44% of the iterations and improves the area under the learning curve compared to both uniform sampling and the variance-based CGPO sampler. The efficiency gains transfer to four held-out reward models and carry over to DPG-Bench and T2I-Com benchmarks.

**Why it matters:** SPROUT reduces wasted compute in preference tuning by selecting prompts that yield higher alignment signal per generated image, directly lowering training cost and time for text-to-image diffusion models.

## 4. Corrective Prefix Attention boosts parallel speculative decoding acceptance and speed

`Research` · [arxiv](https://arxiv.org/abs/2611.31112v1) · score 8.0

Researchers introduce Corrective Prefix Attention (CPA), a method that lets parallel draft tokens attend to earlier choices within a block and uses an auxiliary autoregressive loss to train on clean prefixes. On eight benchmarks with Qwen3-4B and Qwen3-8B targets on Ascend NPUs, CPA commits 13–15% more tokens per verification round than DSpark and 25–26% more than DFlash, achieving mean speedups of 3.35× and 3.37× under greedy decoding and 2.86× under sampling.

**Why it matters:** CPA shows that adding causal information to parallel proposals can significantly improve acceptance rates and decoding speed without expensive sequential computation, offering a practical path for faster LLM inference on hardware like Ascend NPUs.

## 5. Ai2 releases RoboTrack benchmark and models for robotic point tracking

`Research` · [rss](https://huggingface.co/blog/allenai/robotrack) · score 5.0

Ai2 introduced RoboTrack, a benchmark and training data suite for point tracking in robotic manipulation. RoboTrack-Bench comprises 307 human-annotated videos from multiple datasets covering diverse robots, human hands, cluttered scenes, and viewpoints, with 2,522 verified point tracks. RoboTrack-15M is a synthetic dataset of 15 million point tracks generated from the MolmoSpaces simulation ecosystem. Evaluations show leading trackers score significantly lower on RoboTrack-Bench than on existing benchmarks, and adding RoboTrack-15M to training improves performance on real manipulation footage and other tracking benchmarks. Ai2 also released two models, RoboTracker and RoboTracker-Warp, which improve average AJ across three robotics benchmarks, with RoboTracker-Warp achieving state-of-the-art on four of five benchmarks evaluated.

**Why it matters:** RoboTrack provides a more realistic benchmark for point tracking under real-world robotic manipulation conditions, addressing gaps in current benchmarks. The synthetic training data and improved models enable better tracking in cluttered, occluded, and multi-view scenarios, directly benefiting engineers building perception systems for robot manipulation tasks such as lab automation.

## 6. Datasette Charts Plugin Aggregates Millions of Rows via SQL

`Tools` · [rss](https://simonwillison.net/2026/Nov/24/datasette-charts/) · score 5.0

Simon Willison released datasette-charts 0.1a0, a Datasette plugin that visualizes data using D3 and Observable Plot with heuristic chart suggestions. Unlike previous plugins limited to the current page of results, it compiles charts to SQL queries that aggregate across entire result sets—potentially millions of rows—using GROUP BY, time bucketing, and window functions, with results capped at 5,000 rows for display.

**Why it matters:** Practitioners can now visualize large datasets in Datasette without sampling bias, as charts reflect full-table aggregations rather than paginated subsets, and shareable URLs preserve chart state.

Also at: <https://simonwillison.net/2026/Nov/23/datasette-charts/>

## 7. OpenAI and Cisco launch Shirudo open-source runtime for live Linux patching

`Infra` · [rss](https://openai.com/index/introducing-shirudo) · score 5.0

OpenAI and Cisco introduced Shirudo, an open-source runtime that uses eBPF to apply targeted security shields to running Linux systems without restarts. In a controlled test, a Codex-generated shield blocked a Java4Shell exploit against a live Elasticsearch service while allowing legitimate traffic. The project combines OpenAI's AI and security research with Cisco's infrastructure expertise.

**Why it matters:** Shirudo addresses the critical gap between vulnerability discovery and patch deployment, letting security teams block exploits on production systems without downtime. Its eBPF-based approach with cryptographic verification and TPM-backed attestation offers a practical path for AI-assisted, runtime vulnerability mitigation.

## 8. Claude Ship beta automates PR review, fixes, and approvals

`Agents` · [hackernews](https://claude.com/resources/articles/introducing-claude-ship) · score 5.0

The Claude Code team says it has launched Claude Ship in beta, a system that reviews pull requests, fixes them, and decides what is ready to merge based on team policies. It combines generally available Code Review with two new beta agents, PR Steward and Claude Approvals. Developers can invoke it with a /ship command in Claude Code or enable it across a repository.

**Why it matters:** Engineers can delegate routine review, CI fixes, and merge decisions to AI agents while keeping human oversight through observe-only modes and repository-controlled approval policies.

---

87 fetched → 85 unique → 75 new → 60 ranked → 8 published in 230.8s
- `nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`: 2 calls (0 cached), 6692 tokens, ~20947 ms avg
- `openrouter/baidu/ernie-5.5-flash-preview:free`: 3 calls (0 cached), 9828 tokens, ~10485 ms avg
- `openrouter/google/gemma-4-31b-it:free`: 2 calls (0 cached), 0 tokens, ~191 ms avg
- `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`: 9 calls (0 cached), 9828 tokens, ~12859 ms avg
- `openrouter/nvidia/nemotron-3.5-super-vl:free`: 3 calls (0 cached), 5353 tokens, ~10984 ms avg
