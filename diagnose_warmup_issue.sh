#!/bin/bash
# 验证 warmup 卡住是 IOMMU 问题还是 MoE 编译问题

set -e

echo "=========================================="
echo "Warmup Hang 原因诊断"
echo "=========================================="

# 检查当前配置
echo -e "\n[1] 检查 IOMMU 设置"
echo "-------------------------------------------"
if grep -q "iommu=pt" /proc/cmdline; then
    echo "✓ IOMMU 已设置为 passthrough 模式"
    IOMMU_OK=true
else
    echo "⚠ IOMMU 未设置为 passthrough 模式"
    echo "  当前参数：$(cat /proc/cmdline)"
    IOMMU_OK=false
fi

# 检查模型类型
echo -e "\n[2] 检查模型配置"
echo "-------------------------------------------"
if [ -n "$VLLM_SPLIT_MOE_COMPILATION" ]; then
    echo "✓ VLLM_SPLIT_MOE_COMPILATION=$VLLM_SPLIT_MOE_COMPILATION (MoE 模型)"
    MODEL_TYPE="MoE"
else
    echo "- 未设置 VLLM_SPLIT_MOE_COMPILATION"
    MODEL_TYPE="Unknown"
fi

# 检查 bucket 配置
echo -e "\n[3] 检查 Bucket 配置"
echo "-------------------------------------------"
echo "VLLM_PROMPT_BS_BUCKET_MAX: ${VLLM_PROMPT_BS_BUCKET_MAX:-default}"
echo "VLLM_PROMPT_CTX_BUCKET_MAX: ${VLLM_PROMPT_CTX_BUCKET_MAX:-default}"
echo "VLLM_PROMPT_QUERY_BUCKET_MAX: ${VLLM_PROMPT_QUERY_BUCKET_MAX:-default}"

# 计算第一个 bucket 的规模
echo -e "\n[4] 第一个 warmup bucket 规模估算"
echo "-------------------------------------------"
BS_MAX=${VLLM_PROMPT_BS_BUCKET_MAX:-4}
CTX_MAX=${VLLM_PROMPT_CTX_BUCKET_MAX:-8192}
QUERY_MAX=${VLLM_PROMPT_QUERY_BUCKET_MAX:-8192}
BLOCK_SIZE=128

echo "最大 bucket: bs=$BS_MAX, ctx=$CTX_MAX, query=$QUERY_MAX"
echo "总 tokens: $BS_MAX * $QUERY_MAX = $((BS_MAX * QUERY_MAX))"
echo "Context tokens: $CTX_MAX * $BLOCK_SIZE = $((CTX_MAX * BLOCK_SIZE))"

if [ $((BS_MAX * QUERY_MAX)) -gt 32768 ]; then
    echo "⚠️  警告：total_tokens 超过 32768，可能导致编译时间过长"
fi

if [ $CTX_MAX -gt 2048 ]; then
    echo "⚠️  警告：ctx_blocks 超过 2048，可能导致内存分配问题"
fi

# 提供诊断建议
echo -e "\n[5] 诊断结论和建议"
echo "-------------------------------------------"

if [ "$MODEL_TYPE" = "MoE" ]; then
    echo "检测到 MoE 模型，问题可能是:"
    echo ""
    echo "1. **MoE 编译时间过长** (最可能)"
    echo "   - 122B MoE 的 graph capture 可能需要 5-10 分钟"
    echo "   - 建议：等待更长时间观察"
    echo ""
    echo "2. **IOMMU 问题** (次要)"
    echo "   - 如果等待 10 分钟后仍然卡住，尝试添加 iommu=pt"
    echo ""
    echo "3. **Bucket 太大** (次要)"
    echo "   - 建议：使用更小的 bucket 配置"
    echo ""
    
    echo "推荐的 bucket 配置:"
    echo "  export VLLM_PROMPT_BS_BUCKET_MAX=2"
    echo "  export VLLM_PROMPT_CTX_BUCKET_MAX=2048"
    echo "  export VLLM_PROMPT_QUERY_BUCKET_MAX=256"
fi

if [ "$IOMMU_OK" = false ]; then
    echo ""
    echo "建议添加 iommu=pt 参数:"
    echo "  sudo nano /etc/default/grub"
    echo '  GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"'
    echo "  sudo update-grub2 && sudo reboot"
fi

echo -e "\n[6] 验证步骤"
echo "-------------------------------------------"
echo ""
echo "步骤 1: 使用小 bucket 配置测试"
echo "-------------------------------------------"
cat << 'EOF'
export VLLM_PROMPT_BS_BUCKET_MAX=2
export VLLM_PROMPT_CTX_BUCKET_MIN=512
export VLLM_PROMPT_CTX_BUCKET_MAX=2048
export VLLM_PROMPT_QUERY_BUCKET_MIN=64
export VLLM_PROMPT_QUERY_BUCKET_MAX=256
export VLLM_WARMUP_DEBUG=1
export VLLM_LOGGING_LEVEL=INFO

# 启动并观察日志
# 如果 5 分钟内完成 -> bucket 问题
# 如果仍然卡住 -> 可能是 IOMMU 问题
EOF

echo ""
echo "步骤 2: 如果步骤 1 失败，添加 iommu=pt"
echo "-------------------------------------------"
cat << 'EOF'
# 修改 GRUB 并重启
sudo nano /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"
sudo update-grub2
sudo reboot

# 重启后再次测试
EOF

echo ""
echo "步骤 3: 对比 27B 和 122B 的 warmup 时间"
echo "-------------------------------------------"
echo "记录 27B 模型的 warmup 时间作为参考"
echo "如果 122B 的 warmup 时间 > 10 倍 27B 的时间，可能是正常的"

echo -e "\n=========================================="
echo "诊断完成"
echo "=========================================="
