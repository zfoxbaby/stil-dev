#!/usr/bin/env python3
"""
性能测试脚本 - 比较优化前后的转换性能
"""

import time
import os
import psutil
from datetime import datetime
from STILToGasc import STILToGasc

def get_memory_usage():
    """获取当前内存使用量(MB)"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def test_file_conversion(test_file_path, output_path):
    """测试文件转换性能"""
    print(f"\n{'='*60}")
    print(f"测试文件: {test_file_path}")
    
    if not os.path.exists(test_file_path):
        print(f"错误: 测试文件不存在 {test_file_path}")
        return
    
    file_size = os.path.getsize(test_file_path) / (1024 * 1024)  # MB
    print(f"文件大小: {file_size:.1f} MB")
    
    # 记录初始内存
    initial_memory = get_memory_usage()
    print(f"初始内存使用: {initial_memory:.1f} MB")
    
    start_time = datetime.now()
    peak_memory = initial_memory
    vector_count = 0
    
    def progress_callback(message):
        """进度回调，记录内存峰值和向量计数"""
        nonlocal peak_memory, vector_count
        current_memory = get_memory_usage()
        peak_memory = max(peak_memory, current_memory)
        
        if "个向量" in message:
            # 提取向量数量
            try:
                vector_count = int(message.split()[1])
            except:
                pass
        
        elapsed = datetime.now() - start_time
        print(f"[{elapsed.total_seconds():.1f}s] {message} (内存: {current_memory:.1f}MB)")
    
    # 执行转换
    converter = STILToGasc(test_file_path, output_path, fast_mode=True)
    
    try:
        result = converter.convert(progress_callback)
        end_time = datetime.now()
        
        total_time = (end_time - start_time).total_seconds()
        final_memory = get_memory_usage()
        memory_increase = peak_memory - initial_memory
        
        print(f"\n{'='*40}")
        print(f"转换完成!")
        print(f"总耗时: {total_time:.2f} 秒")
        print(f"初始内存: {initial_memory:.1f} MB")
        print(f"峰值内存: {peak_memory:.1f} MB") 
        print(f"内存增长: {memory_increase:.1f} MB")
        print(f"最终内存: {final_memory:.1f} MB")
        print(f"处理速度: {file_size/total_time:.2f} MB/秒")
        
        if vector_count > 0:
            print(f"向量处理数量: {vector_count:,}")
            print(f"向量处理速度: {vector_count/total_time:.0f} 向量/秒")
        
        # 检查输出文件
        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path) / (1024 * 1024)
            print(f"输出文件大小: {output_size:.1f} MB")
        
        return {
            'file_size_mb': file_size,
            'total_time': total_time,
            'peak_memory_mb': peak_memory,
            'memory_increase_mb': memory_increase,
            'vector_count': vector_count,
            'success': True
        }
        
    except Exception as e:
        print(f"转换失败: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

if __name__ == "__main__":
    print("STIL文件转换性能测试")
    print("流式输出优化版本")
    
    # 测试文件路径（您需要根据实际情况调整）
    test_files = [
        # 添加您的测试文件路径
        ("tests/stil_files/pattern_block/syn_ok_pattern_block_1.stil", "test_output_1.gasc"),
        # 如果有大文件，可以添加：
        # ("path/to/large_file.stil", "large_test_output.gasc"),
    ]
    
    results = []
    
    for test_file, output_file in test_files:
        result = test_file_conversion(test_file, output_file)
        results.append(result)
        
        # 清理输出文件
        if os.path.exists(output_file):
            os.remove(output_file)
        if os.path.exists(output_file + ".tmp"):
            os.remove(output_file + ".tmp")
    
    # 总结报告
    print(f"\n{'='*60}")
    print("性能测试总结")
    print(f"{'='*60}")
    
    successful_tests = [r for r in results if r.get('success', False)]
    
    if successful_tests:
        avg_speed = sum(r['file_size_mb']/r['total_time'] for r in successful_tests) / len(successful_tests)
        total_vectors = sum(r.get('vector_count', 0) for r in successful_tests)
        total_time = sum(r['total_time'] for r in successful_tests)
        
        print(f"成功测试: {len(successful_tests)}/{len(results)}")
        print(f"平均处理速度: {avg_speed:.2f} MB/秒")
        print(f"总向量处理数量: {total_vectors:,}")
        if total_time > 0 and total_vectors > 0:
            print(f"平均向量处理速度: {total_vectors/total_time:.0f} 向量/秒")
    else:
        print("没有成功的测试") 