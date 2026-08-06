#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量运行所有提取脚本
统一的入口点，支持错误处理和进度报告

并行策略（task 47）：
    当本次处理的募集说明书数量多于 MAX_PARALLEL_FILES(3) 份时，采用
    ProcessPoolExecutor 并行处理，同一时刻最多 3 份募集说明书，各自在
    独立的子进程中跑完整个提取流水线，从而缩短整体处理时间。
    并行不改变任何提取逻辑：每个子进程内对单份 PDF 仍按原顺序依次运行
    5 个提取脚本（发行条款 -> 募集资金运用 -> 发行人基本情况 ->
    主营业务分析 -> 财务分析），生成的笔记与串行模式完全一致。
    索引生成与数据校验脚本不接受 --files，在全部募集说明书处理完成后
    由主进程整体运行一次。
    可通过 --no-parallel 强制回到旧的逐份串行模式（用于调试）。
"""

import os
import sys
import io
import contextlib
import time
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 并行处理时，同一时刻处理的募集说明书份数上限
MAX_PARALLEL_FILES = 3

# 需要按单份募集说明书逐个运行的提取脚本（顺序不可调整：
# 募集资金运用提取会读取发行条款提取生成的笔记进行交叉校验）。
# 生成索引与数据校验脚本不接受 --files，应在所有募集说明书处理完成后整体运行。
EXTRACT_SCRIPTS = [
    ("extract_bond_terms.py", "发行条款提取"),
    ("extract_fund_usage.py", "募集资金运用提取"),
    ("extract_issuer_profile.py", "发行人基本情况提取"),
    ("extract_business_analysis.py", "主营业务分析提取"),
    ("extract_financial_analysis.py", "财务分析提取"),
]


@dataclass
class TaskResult:
    """任务执行结果"""
    script: str
    success: bool
    output: str
    error: str
    duration: float


def _process_one_file(pdf_file: str, base_dir: str = None) -> dict:
    """
    在独立子进程中处理单份募集说明书：依次运行全部提取脚本。

    该函数在 ProcessPoolExecutor 的子进程中执行，每个子进程拥有独立的
    sys.argv 与内存，因此并发调用之间不存在共享状态冲突。
    返回可 pickle 的结果字典。
    """
    runner = BatchRunner(base_dir=base_dir, files=[pdf_file])
    results = []
    log_buf = io.StringIO()
    start = time.time()
    with contextlib.redirect_stdout(log_buf):
        for script_name, _ in EXTRACT_SCRIPTS:
            results.append(runner.run_script(script_name))
    duration = time.time() - start
    return {
        "file": pdf_file,
        "results": results,
        "log": log_buf.getvalue(),
        "duration": duration,
    }


class BatchRunner:
    """批量运行器"""

    SCRIPTS = [
        ("generate_meta_index.py", "生成索引"),
        ("extract_bond_terms.py", "发行条款提取"),
        ("extract_fund_usage.py", "募集资金运用提取"),
        ("extract_issuer_profile.py", "发行人基本情况提取"),
        ("extract_business_analysis.py", "主营业务分析提取"),
        ("extract_financial_analysis.py", "财务分析提取"),
        ("validator.py", "数据校验"),
    ]

    def __init__(self, base_dir: str = None, files: list = None):
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.scripts_dir = os.path.join(self.base_dir, "scripts")
        self.results: List[TaskResult] = []
        self.files = files  # 指定处理的PDF文件列表，None表示全部

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
            import argparse
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                script_name.replace('.py', ''),
                script_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, 'main'):
                # 构造 sys.argv 传入 --files 参数
                old_argv = sys.argv
                if self.files:
                    sys.argv = [script_name, "--files"] + self.files
                else:
                    sys.argv = [script_name]
                try:
                    module.main()
                finally:
                    sys.argv = old_argv
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

    def _resolve_pdf_files(self) -> Optional[List[str]]:
        """解析本次需要处理的 PDF 文件列表（不存在于 raw/ 下的会被过滤）"""
        raw_dir = os.path.join(self.base_dir, "raw")
        if self.files:
            pdf_files = [f for f in self.files if f.endswith(".pdf")]
            pdf_files = [f for f in pdf_files if os.path.exists(os.path.join(raw_dir, f))]
            return pdf_files
        if os.path.isdir(raw_dir):
            return [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]
        return None

    def run_all_auto(self, skip_errors: bool = False) -> List[TaskResult]:
        """
        自动选择串行 / 并行模式运行。

        处理的募集说明书数量 <= MAX_PARALLEL_FILES 时走原有串行逻辑；
        多于 3 份时并行处理（同一时刻最多 3 份）。
        """
        pdf_files = self._resolve_pdf_files()
        if pdf_files is None or len(pdf_files) <= MAX_PARALLEL_FILES:
            return self.run_all(skip_errors=skip_errors)
        return self._run_parallel(pdf_files, skip_errors=skip_errors)

    def _run_parallel(self, pdf_files: List[str], skip_errors: bool = False) -> List[TaskResult]:
        """
        并行处理多份募集说明书：每份 PDF 在独立子进程中跑完整个提取流水线，
        同一时刻最多 MAX_PARALLEL_FILES 份。

        注：与串行模式（遇到错误即中止）不同，并行模式会尽力处理完所有
        募集说明书，出错的文件单独报告，不中断其他文件的处理。
        """
        from concurrent.futures import ProcessPoolExecutor, as_completed

        wall_start = time.time()
        print("=" * 60)
        print(f"并行处理开始：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"共 {len(pdf_files)} 份募集说明书，"
              f"同一时刻最多处理 {MAX_PARALLEL_FILES} 份")
        print("=" * 60)

        self.results = []
        try:
            with ProcessPoolExecutor(max_workers=MAX_PARALLEL_FILES) as executor:
                future_to_file = {
                    executor.submit(_process_one_file, f, self.base_dir): f
                    for f in pdf_files
                }
                done = 0
                for future in as_completed(future_to_file):
                    pdf_file = future_to_file[future]
                    done += 1
                    try:
                        payload = future.result()
                    except Exception as e:
                        print(f"[{done}/{len(pdf_files)}] [FAIL] {pdf_file}: {e}")
                        continue

                    success = sum(1 for r in payload["results"] if r.success)
                    total = len(payload["results"])
                    mark = "OK" if success == total else "FAIL"
                    print(f"[{done}/{len(pdf_files)}] [{mark}] {pdf_file} "
                          f"({success}/{total} 个脚本成功, {payload['duration']:.2f}s)")
                    self.results.extend(payload["results"])
                    if success < total:
                        for r in payload["results"]:
                            if not r.success:
                                print(f"      - {r.script}: {r.error}")
                        # 打印该文件提取日志的最后若干行，便于定位失败原因
                        log_tail = [ln for ln in payload["log"].splitlines() if ln.strip()][-8:]
                        if log_tail:
                            print("      日志末尾：")
                            for ln in log_tail:
                                print(f"        {ln}")
        except Exception as e:
            print(f"\n[并行处理异常：{e}，已回退到串行模式]")
            return self.run_all(skip_errors=skip_errors)

        # 未指定 --files（处理 raw/ 下全部）时，串行模式会在最后生成索引并校验。
        # 并行模式需在全部募集说明书处理完成后，由主进程整体运行一次。
        if not self.files:
            for script_name, description in self.SCRIPTS:
                if script_name in ("generate_meta_index.py", "validator.py"):
                    print(f"\n运行 {description}: {script_name}")
                    self.results.append(self.run_script(script_name))

        self._print_summary(wall_clock=time.time() - wall_start)
        return self.results

    def run_all(self, skip_errors: bool = False) -> List[TaskResult]:
        """
        运行所有脚本（原串行逻辑）

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
            # 指定了 --files 时，跳过索引生成和校验（它们不接受 --files 参数）
            if self.files and script_name in ("generate_meta_index.py", "validator.py"):
                print(f"\n[{len(self.results) + 1}/{len(self.SCRIPTS)}] "
                      f"{description}: {script_name}")
                print("-" * 40)
                print(f"[SKIP] 指定 --files 时跳过")
                continue
            print(f"\n[{len(self.results) + 1}/{len(self.SCRIPTS)}] "
                  f"{description}: {script_name}")
            print("-" * 40)

            result = self.run_script(script_name)
            self.results.append(result)

            if result.success:
                print(f"[OK] 成功 ({result.duration:.2f}s)")
            else:
                print(f"[FAIL] 失败：{result.error}")
                if not skip_errors:
                    print("\n处理中止")
                    break

        # 打印汇总
        self._print_summary()

        return self.results

    def _print_summary(self, wall_clock: Optional[float] = None):
        """打印执行摘要"""
        print("\n" + "=" * 60)
        print("执行摘要")
        print("=" * 60)

        success_count = sum(1 for r in self.results if r.success)
        total = len(self.results)
        total_duration = sum(r.duration for r in self.results)

        print(f"成功：{success_count}/{total}")
        print(f"总耗时（脚本累计）：{total_duration:.2f}s")
        if wall_clock is not None:
            print(f"总耗时（墙钟时间）：{wall_clock:.2f}s")

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
    parser.add_argument(
        "--files", nargs="*", default=None,
        help="指定要处理的PDF文件名（多个用空格隔开），不指定则处理raw/下所有PDF"
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="禁用并行处理，逐份串行处理（用于调试）"
    )
    args = parser.parse_args()

    runner = BatchRunner(files=args.files)
    if args.no_parallel:
        results = runner.run_all(skip_errors=args.skip_errors)
    else:
        results = runner.run_all_auto(skip_errors=args.skip_errors)

    # 返回错误码
    if all(r.success for r in results):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
