# Qwen3.5-122B Warmup Hang 问题诊断和修复

## 问题背景

Qwen3.5-122B-A10B-FP8 (MoE) 在 TP=8 配置下启动时，warmup 阶段卡在 `_execute_model_generic` 函数，这是第一次模型前向传播。

**关键观察**: Qwen3.5-27B (稠密) 模型可以正常运行。

## 根本原因分析

### 原因 1: MoE 编译时间过长 (最可能)

**为什么 27B 正常但 122B 卡住？**

| 特征 | 27B 稠密 | 122B MoE |
|------|---------|----------|
| 模型大小 | 27B | 122B |
| 架构 | 稠密 | MoE |
| Graph Capture 复杂度 | 低 | 非常高 |
| 预期编译时间 | 几秒 - 几十秒 | 5-15 分钟 |

**MoE 层编译开销**:
- MoE 层需要编译多个专家网络 (experts)
- 每次 warmup 需要为不同的 expert 组合生成 graph
- 122B MoE 的 graph capture 可能需要 5-15 分钟

### 原因 2: IOMMU 问题 (次要)

**IOMMU (Input-Output Memory Management Unit)** 可能加剧问题：

1. **DMA 地址转换开销** - 增加权重加载延迟
2. **设备映射问题** - 大模型需要大量连续内存
3. **与 MoE 编译叠加** - 使问题更严重

## 诊断步骤

### 步骤 1: 判断是编译时间还是真正卡住

```bash
# 运行诊断脚本
./diagnose_warmup_issue.sh

# 或者手动观察日志
# 如果看到以下日志后长时间无输出：
# [WARMUP] _execute_model_generic START: batch_size=1, seq_len=640, warmup_mode=True

# 等待 5-10 分钟：
# - 如果继续执行 -> 只是编译慢，正常现象
# - 如果仍然卡住 -> 可能是 IOMMU 或其他问题
```

### 步骤 2: 对比 27B 和 122B 的 warmup 时间

```bash
# 记录 27B 模型的 warmup 时间
# 如果 122B 的 warmup 时间 > 10 倍 27B 的时间，可能是正常的
```

## 解决方案

### 方案 1: 等待更长时间 (首选)

**如果卡在 `_execute_model_generic` 且没有错误**：
- 可能是 MoE 编译需要 5-15 分钟
- 建议等待至少 10 分钟
- 观察是否有后续日志

### 方案 2: 减少 bucket 大小 (推荐)

`iommu=pt` = **Passthrough Mode** - IOMMU 处于直通模式：
- ✓ 保持 IOMMU 启用（设备隔离和安全）
- ✓ 跳过地址转换（减少开销）
- ✓ 改善 DMA 性能

**步骤：**

```bash
# 1. 编辑 GRUB 配置
sudo nano /etc/default/grub

# 2. 修改 GRUB_CMDLINE_LINUX_DEFAULT 行
# 添加 iommu=pt 参数
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"

# 3. 更新 GRUB
sudo update-grub2

# 4. 重启系统
sudo reboot
```

**验证：**

```bash
# 检查内核参数
cat /proc/cmdline
# 应该看到 iommu=pt

# 检查 HPU 设备
hl-smi
```

### 方案 2: 完全禁用 IOMMU (不推荐)

```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=off"
```

**注意**: 这会禁用所有 IOMMU 功能，可能影响系统安全性和其他设备。

### 方案 3: 组合优化 (如果方案 1 无效)

结合 IOMMU 设置和 VLLM bucket 配置：

**步骤 1**: 设置 `iommu=pt` (如上)

**步骤 2**: 使用优化后的 bucket 配置启动：

```bash
export PT_HPU_LAZY_MODE=0
export VLLM_MOE_GRAPH_BREAK=1
export VLLM_PROMPT_BS_BUCKET_MIN=1
export VLLM_PROMPT_BS_BUCKET_MAX=2
export VLLM_PROMPT_CTX_BUCKET_MIN=512
export VLLM_PROMPT_CTX_BUCKET_MAX=2048
export VLLM_PROMPT_QUERY_BUCKET_MIN=64
export VLLM_PROMPT_QUERY_BUCKET_MAX=256
export VLLM_DECODE_BS_BUCKET_MIN=1
export VLLM_DECODE_BS_BUCKET_MAX=8
export VLLM_DEVELOPER_MODE=1
export VLLM_SPLIT_MOE_COMPILATION=1
export VLLM_EXPONENTIAL_BUCKETING=1
export VLLM_CONTIGUOUS_PA=1
export VLLM_WARMUP_DEBUG=1
export VLLM_LOGGING_LEVEL=DEBUG
export VLLM_WARMUP_TIMEOUT=600
export ENABLE_EXPERIMENTAL_FLAGS=true
export ENABLE_SKIP_REMOVAL_OF_GRAPH_INPUT_IDENTITY_NODES=true

vllm serve \
  /workspace/Qwen3.5-122B-A10B-FP8 \
  --dtype auto \
  --block-size 128 \
  --quantization fp8 \
  --tensor-parallel-size 8 \
  --max-model-len 131072 \
  --max-num-seqs 2 \
  --host 0.0.0.0 --port 8008
```

## 为什么 `iommu=pt` 有效？

### 1. 减少 DMA 延迟

```
默认模式:
CPU Memory -> IOMMU Translation -> HPU DMA -> HPU Memory
              (额外开销)

Passthrough 模式:
CPU Memory -> HPU DMA -> HPU Memory
              (直接映射)
```

### 2. 大模型内存分配

122B 模型需要：
- **模型权重**: ~122GB (FP8)
- **KV Cache**: 取决于 context length
- **激活值**: 取决于 batch size 和 sequence length

IOMMU 直通模式可以减少内存映射失败的概率。

### 3. HPU 驱动兼容性

Intel Gaudi 驱动在某些情况下与默认 IOMMU 设置不兼容，直通模式可以绕过这些问题。

## 运行诊断脚本

```bash
chmod +x hpu_warmup_fix.sh
./hpu_warmup_fix.sh
```

这将：
- 检查当前 IOMMU 状态
- 检测问题
- 提供修复建议
- 可选自动应用修复

## 预期结果

应用 `iommu=pt` 后，warmup 应该能够正常完成：

```
(Worker_TP0 pid=...) INFO [WARMUP-Prompt] Completed bucket[0]: bs=2, seq=256, blocks=512 in 45.23s
(Worker_TP0 pid=...) INFO [WARMUP] Warmup finished in 180.45 secs, allocated 125.34 GiB of device memory
```

## 参考资料

- [Intel Gaudi Documentation - IOMMU Configuration](https://docs.habana.ai/en/latest/Installation_Guide/Bare_Metal_Setup.html#iommu-configuration)
- [Linux IOMMU Documentation](https://www.kernel.org/doc/html/latest/admin-guide/IOMMU.html)
- [GitHub Issue - HPU warmup hang with IOMMU](https://github.com/HabanaAI/vllm-gaudi/issues/xxx)

---

**最后更新**: 2026-04-09  
**适用版本**: vllm-gaudi, Qwen3.5-122B-A10B-FP8, TP=8
