#!/bin/bash
# Docker 环境下 HPU Warmup Hang 诊断脚本

set -e

echo "=========================================="
echo "Docker 环境 HPU Warmup Hang 诊断"
echo "=========================================="

# 检查是否在 Docker 容器内
if [ -f /.dockerenv ]; then
    IN_DOCKER=true
    echo "⚠️  检测到在 Docker 容器内运行"
else
    IN_DOCKER=false
    echo "✓ 在宿主机上运行"
fi

# 检查 IOMMU 设置
echo -e "\n[1] IOMMU 设置检查"
echo "-------------------------------------------"
CURRENT_CMDLINE=$(cat /proc/cmdline)
echo "当前内核参数：$CURRENT_CMDLINE"

if echo "$CURRENT_CMDLINE" | grep -q "iommu=pt"; then
    echo "✓ IOMMU 已设置为 passthrough 模式"
    IOMMU_OK=true
elif echo "$CURRENT_CMDLINE" | grep -q "iommu=off"; then
    echo "⚠️  IOMMU 已禁用"
    IOMMU_OK=true  # 禁用也可以工作
else
    echo "⚠️  IOMMU 未设置为 passthrough 模式"
    IOMMU_OK=false
    
    if [ "$IN_DOCKER" = true ]; then
        echo ""
        echo "⚠️  注意：在 Docker 容器内无法修改 IOMMU 设置！"
        echo ""
        echo "请在宿主机上执行以下操作："
        echo "-------------------------------------------"
        echo "1. 退出 Docker 容器"
        echo "   exit"
        echo ""
        echo "2. 在宿主机修改 GRUB"
        echo "   sudo nano /etc/default/grub"
        echo '   # 修改为：'
        echo '   GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"'
        echo ""
        echo "3. 更新 GRUB 并重启宿主机"
        echo "   sudo update-grub2"
        echo "   sudo reboot"
        echo ""
        echo "4. 重启后重新运行 Docker"
        echo "   docker run --device /dev/hpu0 ..."
        echo "-------------------------------------------"
    else
        echo ""
        echo "建议修改 GRUB 设置："
        echo "  sudo nano /etc/default/grub"
        echo '  GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"'
        echo "  sudo update-grub2 && sudo reboot"
    fi
fi

# 检查模型类型
echo -e "\n[2] 模型配置检查"
echo "-------------------------------------------"
if [ -n "$VLLM_SPLIT_MOE_COMPILATION" ]; then
    echo "✓ VLLM_SPLIT_MOE_COMPILATION=$VLLM_SPLIT_MOE_COMPILATION (MoE 模型)"
    MODEL_TYPE="MoE"
else
    echo "- 未设置 VLLM_SPLIT_MOE_COMPILATION"
    MODEL_TYPE="Unknown"
fi

# 检查 bucket 配置
echo -e "\n[3] Bucket 配置检查"
echo "-------------------------------------------"
echo "VLLM_PROMPT_BS_BUCKET_MAX: ${VLLM_PROMPT_BS_BUCKET_MAX:-default}"
echo "VLLM_PROMPT_CTX_BUCKET_MAX: ${VLLM_PROMPT_CTX_BUCKET_MAX:-default}"
echo "VLLM_PROMPT_QUERY_BUCKET_MAX: ${VLLM_PROMPT_QUERY_BUCKET_MAX:-default}"

# 诊断结论
echo -e "\n[4] 诊断结论"
echo "-------------------------------------------"

if [ "$IN_DOCKER" = true ]; then
    echo "运行环境：Docker 容器"
    echo ""
fi

if [ "$MODEL_TYPE" = "MoE" ]; then
    echo "检测到 MoE 模型（如 Qwen3.5-122B）"
    echo ""
    echo "可能的问题："
    echo "  1. MoE 编译时间过长（5-15 分钟）"
    echo "  2. IOMMU 设置不当（需要在宿主机修改）"
    echo ""
    echo "建议："
    echo ""
    echo "【方案 A】先等待观察（首选）"
    echo "  - 等待至少 10 分钟"
    echo "  - 观察日志是否有进展"
    echo "  - 如果 10 分钟后仍有日志输出，说明正在编译"
    echo ""
    echo "【方案 B】使用小 bucket 配置（推荐）"
    echo "  添加以下环境变量："
    echo "  export VLLM_PROMPT_BS_BUCKET_MAX=2"
    echo "  export VLLM_PROMPT_CTX_BUCKET_MIN=512"
    echo "  export VLLM_PROMPT_CTX_BUCKET_MAX=2048"
    echo "  export VLLM_PROMPT_QUERY_BUCKET_MIN=64"
    echo "  export VLLM_PROMPT_QUERY_BUCKET_MAX=256"
    echo ""
    echo "【方案 C】修改宿主机 IOMMU 设置（如果方案 A/B 失败）"
    echo "  在宿主机执行："
    echo "  sudo nano /etc/default/grub"
    echo '  GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"'
    echo "  sudo update-grub2 && sudo reboot"
else
    echo "检测到稠密模型（如 Qwen3.5-27B）"
    echo "如果卡住，很可能是 IOMMU 问题"
    echo ""
    echo "建议修改宿主机 IOMMU 设置："
    echo "  sudo nano /etc/default/grub"
    echo '  GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt"'
    echo "  sudo update-grub2 && sudo reboot"
fi

echo -e "\n[5] Docker 环境特殊说明"
echo "-------------------------------------------"
echo ""
echo "✓ Docker 容器共享宿主机内核"
echo "✓ IOMMU 设置在宿主机上生效"
echo "✓ 容器内可以读取 /proc/cmdline 验证"
echo ""
echo "验证方法："
echo "  cat /proc/cmdline  # 应该看到 iommu=pt"
echo ""
echo "如果看到不同的参数，说明：1) 未正确设置 2) 未重启宿主机"

echo -e "\n=========================================="
echo "诊断完成"
echo "=========================================="
