#!/usr/bin/env python3
"""
简化版 warmup bucket 分析脚本 - 不需要 HPU 环境
"""

import math

def exponential_range(bmin, bstep, bmax, num_buckets):
    """模拟 exponential bucketing 生成的范围"""
    if bmin == 0:
        bmin = bstep
    
    if num_buckets <= 1:
        return [bmax]
    
    buckets = []
    for i in range(num_buckets):
        power = bmin * math.pow(bmax / bmin, (1.0 / float(num_buckets - 1)) * i)
        bucket = math.ceil(power / bstep) * bstep
        buckets.append(bucket)
    
    # Remove duplicates
    buckets = sorted(list(set(buckets)))
    
    # Ensure last bucket is bmax
    if buckets and buckets[-1] > bmax:
        buckets[-1] = bmax
    
    return buckets

def analyze_config():
    print("=" * 100)
    print("VLLM Gaudi Warmup Bucket 分析 (简化版)")
    print("=" * 100)
    
    # 用户配置
    config = {
        'max_model_len': 131072,
        'block_size': 128,
        'max_num_seqs': 2,
        'max_num_batched_tokens': 32768,  # 默认值
        
        # Prompt bucketing
        'prompt_bs_min': 1,
        'prompt_bs_max': 4,
        'prompt_query_min': 640,  # 估计的默认值
        'prompt_query_max': 8192,  # 估计的默认值
        'prompt_ctx_min': 2048,
        'prompt_ctx_max': 8192,
        
        # 计算出的参数
        'prompt_bs_step': 1,
        'prompt_query_step': 640,  # 估计
        'prompt_ctx_step': 128,
        'prompt_bs_limit': 4,
        'prompt_query_limit': 4,
        'prompt_ctx_limit': 4,
    }
    
    print("\n[当前配置]")
    print(f"  max_model_len: {config['max_model_len']}")
    print(f"  block_size: {config['block_size']}")
    print(f"  max_num_seqs: {config['max_num_seqs']}")
    print(f"  max_num_batched_tokens: {config['max_num_batched_tokens']}")
    print(f"\n  Prompt BS: min={config['prompt_bs_min']}, max={config['prompt_bs_max']}, step={config['prompt_bs_step']}, limit={config['prompt_bs_limit']}")
    print(f"  Prompt Query: min={config['prompt_query_min']}, max={config['prompt_query_max']}, step={config['prompt_query_step']}, limit={config['prompt_query_limit']}")
    print(f"  Prompt Context: min={config['prompt_ctx_min']}, max={config['prompt_ctx_max']}, step={config['prompt_ctx_step']}, limit={config['prompt_ctx_limit']}")
    
    # 生成 ranges
    bs_range = exponential_range(
        config['prompt_bs_min'],
        config['prompt_bs_step'],
        config['prompt_bs_max'],
        config['prompt_bs_limit']
    )
    
    query_range = exponential_range(
        config['prompt_query_min'],
        config['prompt_query_step'],
        config['prompt_query_max'],
        config['prompt_query_limit']
    )
    
    ctx_range = exponential_range(
        config['prompt_ctx_min'],
        config['prompt_ctx_step'],
        config['prompt_ctx_max'],
        config['prompt_ctx_limit']
    )
    
    print(f"\n[生成的 ranges]")
    print(f"  bs_range ({len(bs_range)} values): {bs_range}")
    print(f"  query_range ({len(query_range)} values): {query_range}")
    print(f"  ctx_range ({len(ctx_range)} values): {ctx_range}")
    
    # 分析第一个 warmup bucket (从最大的开始)
    print("\n[第一个 warmup bucket 分析]")
    print("-" * 100)
    
    first_bs = bs_range[-1]
    first_query = query_range[-1]
    first_ctx = ctx_range[-1]
    
    total_tokens = first_bs * first_query
    ctx_tokens = first_ctx * config['block_size']
    total_seq_len = first_query + ctx_tokens
    
    print(f"  bucket: (bs={first_bs}, query={first_query}, ctx={first_ctx})")
    print(f"  total_tokens = bs × query = {first_bs} × {first_query} = {total_tokens}")
    print(f"  ctx_tokens = ctx × block_size = {first_ctx} × {config['block_size']} = {ctx_tokens}")
    print(f"  total_seq_len = query + ctx_tokens = {first_query} + {ctx_tokens} = {total_seq_len}")
    
    # 检查限制
    print("\n[限制检查]")
    print("-" * 100)
    
    issues = []
    
    if total_tokens > config['max_num_batched_tokens']:
        issues.append(f"❌ total_tokens ({total_tokens}) > max_num_batched_tokens ({config['max_num_batched_tokens']})")
    else:
        print(f"✓ total_tokens ({total_tokens}) <= max_num_batched_tokens ({config['max_num_batched_tokens']})")
    
    if total_seq_len > config['max_model_len']:
        issues.append(f"❌ total_seq_len ({total_seq_len}) > max_model_len ({config['max_model_len']})")
    else:
        print(f"✓ total_seq_len ({total_seq_len}) <= max_model_len ({config['max_model_len']})")
    
    if first_bs > first_ctx:
        issues.append(f"❌ bs ({first_bs}) > ctx ({first_ctx})")
    else:
        print(f"✓ bs ({first_bs}) <= ctx ({first_ctx})")
    
    if issues:
        print("\n⚠️  发现问题:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✓ 所有检查通过")
    
    # 估算资源需求
    print("\n[资源需求估算]")
    print("-" * 100)
    
    # 粗略估算：每 token 需要约 16-32 bytes 的 KV cache (FP8)
    kv_cache_per_token = 16  # bytes (FP8)
    model_weights_gb = 122 * 2 / 1024  # 122B params in FP16 ≈ 244GB, but FP8 ≈ 122GB
    
    kv_cache_mb = (total_tokens + ctx_tokens) * kv_cache_per_token / 1024 / 1024
    print(f"  模型权重 (FP8): ~{model_weights_gb:.1f} GB")
    print(f"  KV Cache (估算): ~{kv_cache_mb:.1f} MB")
    print(f"  总序列长度：{total_seq_len}")
    print(f"  总 tokens: {total_tokens + ctx_tokens}")
    
    # 建议
    print("\n[建议]")
    print("-" * 100)
    
    if first_ctx > 128:
        print(f"⚠️  ctx ({first_ctx}) 较大")
        print(f"   建议：将 VLLM_PROMPT_CTX_BUCKET_MAX 降低到 2048 或更小")
        print(f"   这将使第一个 bucket 的 ctx 约为 {first_ctx // 4} 左右")
    
    if first_bs > 2:
        print(f"⚠️  bs ({first_bs}) 可能过大")
        print(f"   建议：将 VLLM_PROMPT_BS_BUCKET_MAX 降低到 2")
    
    if first_query > 256:
        print(f"⚠️  query ({first_query}) 可能过大")
        print(f"   建议：设置 VLLM_PROMPT_QUERY_BUCKET_MIN=64, VLLM_PROMPT_QUERY_BUCKET_MAX=256")
    
    print("\n[推荐的配置]")
    print("-" * 100)
    print("export VLLM_PROMPT_BS_BUCKET_MAX=2")
    print("export VLLM_PROMPT_CTX_BUCKET_MIN=512")
    print("export VLLM_PROMPT_CTX_BUCKET_MAX=2048")
    print("export VLLM_PROMPT_QUERY_BUCKET_MIN=64")
    print("export VLLM_PROMPT_QUERY_BUCKET_MAX=256")
    print("export VLLM_WARMUP_DEBUG=1")
    print("export VLLM_WARMUP_TIMEOUT=600")
    
    print("\n[预期效果]")
    print("-" * 100)
    print("第一个 warmup bucket 将变为约 (bs=2, query=256, ctx=512)")
    print("这将显著减少首次 graph capture 的内存和计算压力")
    print(f"  新的 total_tokens = 2 × 256 = 512")
    print(f"  新的 ctx_tokens = 512 × 128 = 65536")
    print(f"  新的 total_seq_len = 256 + 65536 = 65792")

if __name__ == '__main__':
    analyze_config()
