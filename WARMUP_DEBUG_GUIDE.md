# VLLM Gaudi Qwen3.5-122B Warmup 卡住问题诊断报告

## 问题描述

在 TP=8 配置下启动 Qwen3.5-122B-A10B-FP8 模型时，warmup 阶段在第一个 prompt bucket 卡住：
- **bucket**: `(batch_size=2, query_len=640, num_blocks=203)`
- **日志**: `Prompt warmup processing: 0%| 0/50 [00:00<?, ?item/s)`
- **超时**: EngineCore 报告 shared memory broadcast timeout

## 根本原因分析

### 1. Bucket 配置问题

当前配置：
```bash
VLLM_PROMPT_CTX_BUCKET_MIN=2048
VLLM_PROMPT_CTX_BUCKET_MAX=8192
VLLM_PROMPT_BS_BUCKET_MAX=4
VLLM_PROMPT_QUERY_BUCKET_MIN=640 (默认值)
```

第一个 warmup bucket 计算：
- `ctx_range` 最大值 = 203 (从 exponential bucketing 计算得出)
- `query_range` 最大值 = 640 (默认值)
- `bs_range` 最大值 = 4 (但你设置 max_num_seqs=2)

### 2. 资源需求估算

第一个 bucket `(bs=2, query=640, ctx=203)`:
- **总 tokens**: 2 × 640 = 1280 tokens
- **Context tokens**: 203 × 128 = 25984 tokens
- **总序列长度**: 640 + 25984 = 26624 tokens
- **对于 122B 模型**: 这个规模需要大量 HPU 内存和编译时间

### 3. 卡住的可能原因

1. **编译超时**: 122B 模型 + 大 context 的 graph capture 可能超过默认超时
2. **内存分配**: 虽然显示 free_mem:15.07 GiB，但可能无法满足大块分配
3. **TP 同步**: 8 个 rank 中某个 rank 卡住导致整体阻塞

## 解决方案

### 方案 1: 减少第一个 warmup bucket 大小 (推荐)

修改启动配置：

```bash
export PT_HPU_LAZY_MODE=0
export VLLM_MOE_GRAPH_BREAK=1
export VLLM_PROMPT_BS_BUCKET_MIN=1
export VLLM_PROMPT_BS_BUCKET_MAX=2          # 从 4 降到 2
export VLLM_PROMPT_CTX_BUCKET_MIN=512       # 从 2048 降到 512
export VLLM_PROMPT_CTX_BUCKET_MAX=2048      # 从 8192 降到 2048
export VLLM_PROMPT_QUERY_BUCKET_MIN=64
export VLLM_PROMPT_QUERY_BUCKET_MAX=1024    # 明确设置 query bucket
export VLLM_DECODE_BS_BUCKET_MIN=1
export VLLM_DECODE_BS_BUCKET_MAX=8
export VLLM_DEVELOPER_MODE=1
export VLLM_SPLIT_MOE_COMPILATION=1
export VLLM_EXPONENTIAL_BUCKETING=1
export VLLM_CONTIGUOUS_PA=1
export VLLM_WARMUP_DEBUG=1                  # 新增：启用 warmup 调试
export VLLM_LOGGING_LEVEL=DEBUG
export ENABLE_EXPERIMENTAL_FLAGS=true
export ENABLE_SKIP_REMOVAL_OF_GRAPH_INPUT_IDENTITY_NODES=true
export VLLM_WARMUP_TIMEOUT=600              # 新增：设置 10 分钟超时
```

**预期效果**:
- 第一个 bucket 变为 `(bs=2, query=1024, ctx=512)` 或更小
- 减少首次 graph capture 的内存和计算压力
- 通过 `VLLM_WARMUP_DEBUG` 获取详细日志

### 方案 2: 跳过 warmup (快速测试)

```bash
# 添加以下参数
export skip_warmup=true
```

**注意**: 这会导致运行时性能下降，仅用于测试

### 方案 3: 使用自定义 bucketing 文件

创建 `prompt_buckets.txt` 和 `decode_buckets.txt`:

**prompt_buckets.txt**:
```
1,64,64
1,128,128
1,256,256
2,256,256
2,512,512
2,1024,1024
```

**decode_buckets.txt**:
```
1,1,64
2,1,128
4,1,256
8,1,512
```

然后设置:
```bash
export VLLM_BUCKETING_FROM_FILE=prompt_buckets.txt,decode_buckets.txt
```

### 方案 4: 增加系统超时和调试

```bash
# 增加 HPU 编译超时
export PT_HPU_COMPILE_TIMEOUT=600

# 增加 Dynamo 缓存限制
export torch._dynamo.config.cache_size_limit=64
export torch._dynamo.config.accumulated_cache_size_limit=512

# 启用详细日志
export VLLM_WARMUP_DEBUG=1
export VLLM_LOGGING_LEVEL=DEBUG
export VLLM_DEVELOPER_MODE=1
```

## 调试步骤

### 1. 运行诊断脚本

```bash
python debug_warmup_buckets.py
```

这将显示：
- 当前配置生成的所有 bucket
- 潜在的问题 bucket
- 第一个 warmup bucket 的详细分析

### 2. 查看详细日志

启动后关注以下日志：

```
[WARMUP-Prompt] Starting bucket[X]: bs=Y, seq=Z, blocks=W
[WARMUP-Prompt] total_tokens=..., max_model_len=..., max_num_tokens=...
[WARMUP-Prompt] Entering HabanaMemoryProfiler
[WARMUP-Prompt] Calling _prepare_dummy_scenario
[WARMUP] Executing dummy scenario with N requests
[WARMUP] First execute_model completed in X.XXs
```

### 3. 检查 HPU 状态

在另一个终端运行：

```bash
# 查看 HPU 利用率
hl-smi

# 查看编译进度
htop  # 查看 CPU 使用率

# 查看是否有 deadlock
ps -ef | grep vllm
```

## 预期日志 (修复后)

```
(Worker_TP0 pid=...) INFO [WARMUP-Prompt] Starting bucket[0]: bs=2, seq=1024, blocks=512
(Worker_TP0 pid=...) INFO [WARMUP-Prompt] total_tokens=2048, max_model_len=131072, max_num_tokens=32768
(Worker_TP0 pid=...) INFO [WARMUP-Prompt] Entering HabanaMemoryProfiler
(Worker_TP0 pid=...) INFO [WARMUP-Prompt] Calling _prepare_dummy_scenario
(Worker_TP0 pid=...) INFO [WARMUP] Executing dummy scenario with 2 requests
(Worker_TP0 pid=...) INFO [WARMUP] First execute_model completed in 45.23s
(Worker_TP0 pid=...) INFO [WARMUP-Prompt] Completed bucket[0]: bs=2, seq=1024, blocks=512 in 52.45s
```

## 联系支持

如果以上方案都不起作用，请收集以下信息：

1. **完整日志**: `vllm serve ... 2>&1 | tee vllm_startup.log`
2. **HPU 状态**: `hl-smi --query-all`
3. **诊断脚本输出**: `python debug_warmup_buckets.py > bucket_analysis.txt`
4. **系统信息**: `hl-smi --version` 和 `python -c "import habana_frameworks as hf; print(hf.__version__)"`

---

**最后更新**: 2026-04-09
**适用版本**: vllm-gaudi, Qwen3.5-122B-A10B-FP8, TP=8
