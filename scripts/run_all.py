#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量运行所有提取脚本
统一的入口点，支持错误处理和进度报告
"""

import os
import sys
import time
from datetime import datetime
from typing import List, Tuple
from dataclasses import dataclass

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@dataclass
class TaskResult:
    """任务执行结果"""
    script: str
    success: bool
    output: str
    error: str
    duration: float


class BatchRunner:
    """批量运行器"""

    SCRIPTS = [
        ("generate_meta_index.py", "生成索引"),
        ("extract_bond_terms.py", "发行条款提取"),
        ("extract_fund_usage.py", "募集资金运用提取"),
        ("extract_issuer_profile.py", "发行人基本情况提取"),
        ("extract_business_analysis.py", "主营业务分析提取"),
        ("extract_financial_analysis.py", "财务分析提取"),
    ]

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.scripts_dir = os.path.join(self.base_dir, "scripts")
        self.results: List[TaskResult] = []

    def run_script(self, script_name: str) -> TaskResult:
        """运行单个脚本"""
        script_path = os.path.join(self.scripts_dir, script_name)
        start_time = time.time()

        if not os.path.exists(script_path):
            return TaskResult(
                script=script_name,
                success=False,
                output="",
                error=f"脚本不存在：{script_path}",
                duration=0
            )

        try:
            # 导入并运行主函数
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                script_name.replace('.py', ''),
                script_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, 'main'):
                module.main()
                return TaskResult(
                    script=script_name,
                    success=True,
                    output="执行成功",
                    error="",
                    duration=time.time() - start_time
                )
            else:
                return TaskResult(
                    script=script_name,
                    success=False,
                    output="",
                    error="脚本缺少 main() 函数",
                    duration=time.time() - start_time
                )

        except Exception as e:
            return TaskResult(
                script=script_name,
                success=False,
                output="",
                error=str(e),
                duration=time.time() - start_time
            )

    def run_all(self, skip_errors: bool = False) -> List[TaskResult]:
        """
        运行所有脚本

        Args:
            skip_errors: 是否跳过错误的脚本继续执行

        Returns:
            执行结果列表
        """
        print("=" * 60)
        print(f"批量处理开始：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        self.results = []

        for script_name, description in self.SCRIPTS:
            print(f"\n[{len(self.results) + 1}/{len(self.SCRIPTS)}] "
                  f"{description}: {script_name}")
            print("-" * 40)

            result = self.run_script(script_name)
            self.results.append(result)

            if result.success:
                print(f"✓ 成功 ({result.duration:.2f}s)")
            else:
                print(f"✗ 失败：{result.error}")
                if not skip_errors:
                    print("\n处理中止")
                    break

        # 打印汇总
        self._print_summary()

        return self.results

    def _print_summary(self):
        """打印执行摘要"""
        print("\n" + "=" * 60)
        print("执行摘要")
        print("=" * 60)

        success_count = sum(1 for r in self.results if r.success)
        total = len(self.results)
        total_duration = sum(r.duration for r in self.results)

        print(f"成功：{success_count}/{total}")
        print(f"总耗时：{total_duration:.2f}s")

        if success_count < total:
            print("\n失败的脚本:")
            for r in self.results:
                if not r.success:
                    print(f"  - {r.script}: {r.error}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="批量运行提取脚本")
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="跳过错误的脚本继续执行"
    )
    args = parser.parse_args()

    runner = BatchRunner()
    results = runner.run_all(skip_errors=args.skip_errors)

    # 返回错误码
    if all(r.success for r in results):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
