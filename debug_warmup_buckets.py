#!/usr/bin/env python3
"""
诊断脚本：分析 warmup bucket 配置，帮助识别可能导致卡住的 bucket
"""

import os
import sys
import math

# Set environment variables before importing vllm modules
os.environ['PT_HPU_LAZY_MODE'] = '0'
os.environ['VLLM_EXPONENTIAL_BUCKETING'] = '1'
os.environ['VLLM_CONTIGUOUS_PA'] = '1'
os.environ['VLLM_PROMPT_BS_BUCKET_MIN'] = '1'
os.environ['VLLM_PROMPT_BS_BUCKET_MAX'] = '4'
os.environ['VLLM_PROMPT_CTX_BUCKET_MIN'] = '2048'
os.environ['VLLM_PROMPT_CTX_BUCKET_MAX'] = '8192'
os.environ['VLLM_DECODE_BS_BUCKET_MIN'] = '1'
os.environ['VLLM_DECODE_BS_BUCKET_MAX'] = '8'
os.environ['VLLM_DEVELOPER_MODE'] = '1'

from vllm_gaudi.extension.config import get_config
from vllm_gaudi.extension.bucketing.common import HPUBucketingManager
from vllm_gaudi.extension.bucketing.exponential import ExponentialBucketingStrategy

def analyze_buckets():
    print("=" * 100)
    print("VLLM Gaudi Warmup Bucket 诊断工具")
    print("=" * 100)
    
    config = get_config()
    
    print("\n[配置参数]")
    print(f"  VLLM_EXPONENTIAL_BUCKETING: {config.exponential_bucketing}")
    print(f"  VLLM_CONTIGUOUS_PA: {config.use_contiguous_pa}")
    print(f"  VLLM_PROMPT_BS_BUCKET_MIN: {config.VLLM_PROMPT_BS_BUCKET_MIN}")
    print(f"  VLLM_PROMPT_BS_BUCKET_MAX: {config.VLLM_PROMPT_BS_BUCKET_MAX}")
    print(f"  VLLM_PROMPT_CTX_BUCKET_MIN: {config.VLLM_PROMPT_CTX_BUCKET_MIN}")
    print(f"  VLLM_PROMPT_CTX_BUCKET_MAX: {config.VLLM_PROMPT_CTX_BUCKET_MAX}")
    
    # 创建模拟的 bucketing manager
    max_model_len = 131072
    block_size = 128
    max_num_seqs = 2
    max_num_batched_tokens = 32768  # 默认值
    
    print(f"\n[模型参数]")
    print(f"  max_model_len: {max_model_len}")
    print(f"  block_size: {block_size}")
    print(f"  max_num_seqs: {max_num_seqs}")
    print(f"  max_num_batched_tokens: {max_num_batched_tokens}")
    
    strategy = ExponentialBucketingStrategy()
    
    print("\n[Prompt Bucket 配置]")
    bs_cfg, query_cfg, ctx_cfg = strategy.get_prompt_cfgs(
        max_num_prefill_seqs=max_num_seqs,
        block_size=block_size,
        max_num_batched_tokens=max_num_batched_tokens,
        max_model_len=max_model_len
    )
    print(f"  bs_cfg: {bs_cfg}")
    print(f"  query_cfg: {query_cfg}")
    print(f"  ctx_cfg: {ctx_cfg}")
    
    bs_range = strategy.get_range(bs_cfg)
    query_range = strategy.get_range(query_cfg)
    ctx_range = strategy.get_range(ctx_cfg)
    
    print(f"\n  bs_range ({len(bs_range)} values): {bs_range}")
    print(f"  query_range ({len(query_range)} values): {query_range}")
    print(f"  ctx_range ({len(ctx_range)} values): {ctx_range}")
    
    print("\n[分析潜在问题]")
    print("-" * 100)
    
    problem_buckets = []
    
    for bs in bs_range:
        for query in query_range:
            for ctx in ctx_range:
                total_tokens = bs * query
                total_ctx_blocks = ctx
                ctx_tokens = ctx * block_size
                total_seq_len = query + ctx_tokens
                
                # 检查各种限制
                issues = []
                
                if total_tokens > max_num_batched_tokens:
                    issues.append(f"OVER_BUDGET: {total_tokens} > {max_num_batched_tokens}")
                
                if total_seq_len > max_model_len:
                    issues.append(f"OVER_MAX_MODEL: {total_seq_len} > {max_model_len}")
                
                if bs > ctx:
                    issues.append(f"BS_GT_CTX: {bs} > {ctx}")
                
                if issues:
                    problem_buckets.append({
                        'bs': bs,
                        'query': query,
                        'ctx': ctx,
                        'total_tokens': total_tokens,
                        'ctx_tokens': ctx_tokens,
                        'total_seq_len': total_seq_len,
                        'issues': issues
                    })
    
    if problem_buckets:
        print(f"\n发现 {len(problem_buckets)} 个潜在问题 bucket:")
        for i, pb in enumerate(problem_buckets[:10]):
            print(f"\n  [{i+1}] bs={pb['bs']}, query={pb['query']}, ctx={pb['ctx']}")
            print(f"      total_tokens={pb['total_tokens']}, ctx_tokens={pb['ctx_tokens']}, total_seq_len={pb['total_seq_len']}")
            for issue in pb['issues']:
                print(f"      ⚠️  {issue}")
    else:
        print("\n✓ 所有 bucket 组合都在限制范围内")
    
    print("\n[第一个 warmup bucket 分析]")
    print("-" * 100)
    
    # 根据代码逻辑，warmup 从最大的 bucket 开始
    first_bucket_bs = bs_range[-1] if bs_range else 2
    first_bucket_query = query_range[-1] if query_range else 640
    first_bucket_ctx = ctx_range[-1] if ctx_range else 203
    
    print(f"第一个 bucket: bs={first_bucket_bs}, query={first_bucket_query}, ctx={first_bucket_ctx}")
    print(f"  total_tokens = bs * query = {first_bucket_bs} * {first_bucket_query} = {first_bucket_bs * first_bucket_query}")
    print(f"  ctx_tokens = ctx * block_size = {first_bucket_ctx} * {block_size} = {first_bucket_ctx * block_size}")
    print(f"  total_seq_len = query + ctx_tokens = {first_bucket_query} + {first_bucket_ctx * block_size} = {first_bucket_query + first_bucket_ctx * block_size}")
    
    print("\n[建议]")
    print("-" * 100)
    
    if first_bucket_bs * first_bucket_query > max_num_batched_tokens:
        print(f"⚠️  第一个 bucket 的 total_tokens ({first_bucket_bs * first_bucket_query}) 超过 max_num_batched_tokens ({max_num_batched_tokens})")
        print("   建议：增加 VLLM_PROMPT_BS_BUCKET_MAX 或 VLLM_PROMPT_QUERY_BUCKET_MAX")
    
    if first_bucket_ctx * block_size > max_model_len:
        print(f"⚠️  第一个 bucket 的 ctx_tokens ({first_bucket_ctx * block_size}) 超过 max_model_len ({max_model_len})")
        print("   建议：降低 VLLM_PROMPT_CTX_BUCKET_MAX")
    
    if first_bucket_ctx > 100:
        print(f"⚠️  第一个 bucket 的 ctx ({first_bucket_ctx}) 较大")
        print("   对于 122B 模型，大 context 的 graph capture 可能非常耗时")
        print("   建议：尝试设置 VLLM_PROMPT_CTX_BUCKET_MAX=128 或更小进行测试")
    
    print("\n[调试建议]")
    print("-" * 100)
    print("添加以下环境变量来获取更详细的调试信息:")
    print("  export VLLM_WARMUP_DEBUG=1")
    print("  export VLLM_LOGGING_LEVEL=DEBUG")
    print("  export VLLM_DEVELOPER_MODE=1")
    print("  export PT_HPU_ENABLE_PROFILING=1")
    print("  export PT_HPU_METRICS_GC_DETAILS=1")
    print("\n如果仍然卡住，可以尝试:")
    print("  1. 设置 VLLM_PROMPT_CTX_BUCKET_MAX=128 减少第一个 bucket 的大小")
    print("  2. 设置 VLLM_SPLIT_MOE_COMPILATION=1 (已经设置)")
    print("  3. 设置 skip_warmup=true 跳过 warmup (不推荐生产环境)")

if __name__ == '__main__':
    analyze_buckets()
