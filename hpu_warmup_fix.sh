#!/bin/bash
# HPU Warmup Hang 诊断和修复脚本
# 针对 Qwen3.5-122B 在 warmup 阶段卡住的问题

set -e

echo "=========================================="
echo "HPU Warmup Hang 诊断工具"
echo "=========================================="

# 检查 IOMMU 状态
echo -e "\n[1] 检查 IOMMU 状态"
echo "-------------------------------------------"
if [ -f /sys/kernel/debug/iommu/translated ]; then
    echo "IOMMU 状态: $(cat /sys/kernel/debug/iommu/translated)"
else
    echo "IOMMU 信息不可用"
fi

# 检查当前内核参数
echo -e "\n[2] 当前内核参数"
echo "-------------------------------------------"
cat /proc/cmdline

# 检查是否有 iommu 参数
if grep -q "iommu" /proc/cmdline; then
    echo "✓ 已设置 IOMMU 参数"
    grep -o "iommu=[^ ]*" /proc/cmdline || true
else
    echo "⚠ 未设置 IOMMU 参数"
    echo "  建议添加：iommu=pt"
fi

# 检查 HPU 设备
echo -e "\n[3] HPU 设备状态"
echo "-------------------------------------------"
if command -v hl-smi &> /dev/null; then
    hl-smi --query-gpu=index,name --format=csv
else
    echo "hl-smi 不可用"
fi

# 检查 HPU 驱动
echo -e "\n[4] HPU 驱动版本"
echo "-------------------------------------------"
if command -v hpu_sm &> /dev/null; then
    hpu_sm --version 2>/dev/null || echo "无法获取版本"
else
    echo "hpu_sm 不可用"
fi

# 检查内存
echo -e "\n[5] 系统内存状态"
echo "-------------------------------------------"
free -h

# 检查 Dmesg 中的 HPU 相关错误
echo -e "\n[6] 最近的 HPU 相关错误"
echo "-------------------------------------------"
dmesg 2>/dev/null | grep -i "hpu\|habana\|iommu" | tail -20 || echo "无相关信息"

# 提供修复建议
echo -e "\n[7] 修复建议"
echo "-------------------------------------------"

if ! grep -q "iommu=pt" /proc/cmdline; then
    echo "⚠ 建议修复：添加 iommu=pt 参数"
    echo ""
    echo "执行以下步骤："
    echo "  1. sudo nano /etc/default/grub"
    echo "  2. 修改 GRUB_CMDLINE_LINUX_DEFAULT 为："
    echo '     GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"'
    echo "  3. sudo update-grub2"
    echo "  4. sudo reboot"
    echo ""
    read -p "是否自动应用修复？(y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "应用修复..."
        sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="[^"]*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt /' /etc/default/grub
        echo "已修改 /etc/default/grub"
        echo "请运行 sudo update-grub2 && sudo reboot 应用更改"
    fi
else
    echo "✓ IOMMU 参数已设置"
fi

echo -e "\n[8] VLLM 启动优化建议"
echo "-------------------------------------------"
echo "如果问题仍然存在，尝试以下配置："
echo ""
echo "export VLLM_PROMPT_BS_BUCKET_MAX=2"
echo "export VLLM_PROMPT_CTX_BUCKET_MIN=512"
echo "export VLLM_PROMPT_CTX_BUCKET_MAX=2048"
echo "export VLLM_PROMPT_QUERY_BUCKET_MIN=64"
echo "export VLLM_PROMPT_QUERY_BUCKET_MAX=256"
echo "export VLLM_WARMUP_DEBUG=1"
echo "export VLLM_WARMUP_TIMEOUT=600"
echo ""
echo "或者跳过 warmup（仅用于测试）："
echo "export skip_warmup=true"

echo -e "\n=========================================="
echo "诊断完成"
echo "=========================================="
