#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare 数据同步脚本
从 Tushare 获取宏观经济数据和债券数据，同步到 Obsidian 知识库
"""

import tushare as ts
import os
import pandas as pd
from datetime import datetime
from pathlib import Path


class TushareDataSync:
    """Tushare 数据同步器"""

    def __init__(self, token: str = None):
        """初始化 Tushare API"""
        self.token = token or os.getenv('TUSHARE_TOKEN')
        if not self.token:
            raise ValueError("TUSHARE_TOKEN 未配置，请设置环境变量或传入 token 参数")

        ts.set_token(self.token)
        self.pro = ts.pro_api()
        self.output_dir = "knowledge/06-区域分析"

    def fetch_macro_data(self) -> dict:
        """获取宏观经济数据"""
        print("=== 获取宏观经济数据 ===\n")

        data = {}

        # 1. CPI 居民消费价格指数
        try:
            cpi = self.pro.query('cn_cpi')
            data['cpi'] = cpi.head(12)  # 最近 12 个月
            print(f"✓ CPI 数据 - {len(data['cpi'])}条")
        except Exception as e:
            print(f"✗ CPI 数据获取失败：{e}")

        # 2. PPI 工业生产者出厂价格指数
        try:
            ppi = self.pro.query('cn_ppi')
            data['ppi'] = ppi.head(12)
            print(f"✓ PPI 数据 - {len(data['ppi'])}条")
        except Exception as e:
            print(f"✗ PPI 数据获取失败：{e}")

        # 3. PMI 采购经理指数
        try:
            pmi = self.pro.query('cn_pmi')
            data['pmi'] = pmi.head(12)
            print(f"✓ PMI 数据 - {len(data['pmi'])}条")
        except Exception as e:
            print(f"✗ PMI 数据获取失败：{e}")

        # 4. GDP 国内生产总值
        try:
            gdp = self.pro.query('cn_gdp')
            data['gdp'] = gdp.head(8)  # 最近 8 个季度
            print(f"✓ GDP 数据 - {len(data['gdp'])}条")
        except Exception as e:
            print(f"✗ GDP 数据获取失败：{e}")

        # 5. 货币供应量
        try:
            m = self.pro.query('cn_m')
            data['money_supply'] = m.head(12)
            print(f"✓ 货币供应量数据 - {len(data['money_supply'])}条")
        except Exception as e:
            print(f"✗ 货币供应量数据获取失败：{e}")

        # 6. Shibor 利率
        try:
            shibor = self.pro.query('shibor')
            data['shibor'] = shibor.head(20)
            print(f"✓ Shibor 利率数据 - {len(data['shibor'])}条")
        except Exception as e:
            print(f"✗ Shibor 利率数据获取失败：{e}")

        # 7. LPR 贷款基础利率
        try:
            lpr = self.pro.query('shibor_lpr')
            data['lpr'] = lpr.head(12)
            print(f"✓ LPR 利率数据 - {len(data['lpr'])}条")
        except Exception as e:
            print(f"✗ LPR 利率数据获取失败：{e}")

        # 8. 社会融资规模
        try:
            sf = self.pro.query('sf_month')
            data['social_finance'] = sf.head(12)
            print(f"✓ 社会融资规模数据 - {len(data['social_finance'])}条")
        except Exception as e:
            print(f"✗ 社会融资规模数据获取失败：{e}")

        # 9. 国债收益率曲线
        try:
            yc = self.pro.query('yc_cb')
            # 按交易日期分组，取最新日期的完整曲线
            latest_date = yc['trade_date'].max()
            yc_latest = yc[yc['trade_date'] == latest_date]
            data['bond_yield'] = yc_latest
            print(f"✓ 国债收益率曲线 - 日期{latest_date}, {len(data['bond_yield'])}条")
        except Exception as e:
            print(f"✗ 国债收益率曲线获取失败：{e}")

        return data

    def fetch_bond_market_data(self) -> dict:
        """获取债券市场数据"""
        print("\n=== 获取债券市场数据 ===\n")

        data = {}

        # 1. 可转债基础信息
        try:
            cb_basic = self.pro.query('cb_basic')
            data['convertible_bonds'] = cb_basic
            print(f"✓ 可转债基础信息 - {len(data['convertible_bonds'])}条")
        except Exception as e:
            print(f"✗ 可转债基础信息获取失败：{e}")

        # 2. 债券回购日行情（银行间）
        try:
            repo = self.pro.query('repo_daily')
            # 取最新交易日
            latest_date = repo['trade_date'].max()
            repo_latest = repo[repo['trade_date'] == latest_date]
            data['repo_latest'] = repo_latest
            print(f"✓ 债券回购行情 - 日期{latest_date}, {len(data['repo_latest'])}条")
        except Exception as e:
            print(f"✗ 债券回购行情获取失败：{e}")

        return data

    def generate_macro_note(self, data: dict) -> str:
        """生成宏观经济分析笔记"""
        today = datetime.now().strftime('%Y-%m-%d')

        # CPI 表格
        cpi_table = ""
        if 'cpi' in data and len(data['cpi']) > 0:
            cpi_df = data['cpi'][['month', 'nt_yoy', 'cnt_yoy']].head(6)
            cpi_table = "| 月份 | 全国同比% | 城镇同比% |\n|------|----------|----------|\n"
            for _, row in cpi_df.iterrows():
                cpi_table += f"| {row['month']} | {row['nt_yoy']:.1f} | {row['cnt_yoy']:.1f} |\n"

        # PPI 表格
        ppi_table = ""
        if 'ppi' in data and len(data['ppi']) > 0:
            ppi_df = data['ppi'][['month', 'ppi_yoy', 'ppi_cg_yoy']].head(6)
            ppi_table = "| 月份 | PPI 同比% | 消费品同比% |\n|------|----------|------------|\n"
            for _, row in ppi_df.iterrows():
                ppi_table += f"| {row['month']} | {row['ppi_yoy']:.1f} | {row['ppi_cg_yoy']:.1f} |\n"

        # PMI 表格
        pmi_table = ""
        if 'pmi' in data and len(data['pmi']) > 0:
            pmi_df = data['pmi'][['MONTH', 'PMI010000', 'PMI010200', 'PMI010400', 'PMI010700']].head(6)
            pmi_table = "| 月份 | 制造业 PMI | 非制造业 PMI | 服务业 PMI | 建筑业 PMI |\n|------|-----------|-----------|-----------|----------|\n"
            for _, row in pmi_df.iterrows():
                pmi_table += f"| {row['MONTH']} | {row['PMI010000']:.1f} | {row['PMI010200']:.1f} | {row['PMI010400']:.1f} | {row['PMI010700']:.1f} |\n"

        # GDP 表格
        gdp_table = ""
        if 'gdp' in data and len(data['gdp']) > 0:
            gdp_df = data['gdp'][['quarter', 'gdp_yoy', 'pi_yoy', 'si_yoy', 'ti_yoy']].head(6)
            gdp_table = "| 季度 | GDP 同比% | 第一产业% | 第二产业% | 第三产业% |\n|------|----------|----------|----------|----------|\n"
            for _, row in gdp_df.iterrows():
                gdp_table += f"| {row['quarter']} | {row['gdp_yoy']:.1f} | {row['pi_yoy']:.1f} | {row['si_yoy']:.1f} | {row['ti_yoy']:.1f} |\n"

        # 货币供应量表格
        m_table = ""
        if 'money_supply' in data and len(data['money_supply']) > 0:
            m_df = data['money_supply'][['month', 'm0_yoy', 'm1_yoy', 'm2_yoy']].head(6)
            m_table = "| 月份 | M0 同比% | M1 同比% | M2 同比% |\n|------|---------|---------|---------|\n"
            for _, row in m_df.iterrows():
                m_table += f"| {row['month']} | {row['m0_yoy']:.1f} | {row['m1_yoy']:.1f} | {row['m2_yoy']:.1f} |\n"

        # Shibor 表格
        shibor_table = ""
        if 'shibor' in data and len(data['shibor']) > 0:
            shibor_df = data['shibor'][['date', 'on', '1w', '1m', '3m']].head(10)
            shibor_table = "| 日期 | 隔夜% | 1 周% | 1 月% | 3 月% |\n|------|------|------|------|------|\n"
            for _, row in shibor_df.iterrows():
                shibor_table += f"| {row['date']} | {row['on']:.3f} | {row['1w']:.3f} | {row['1m']:.4f} | {row['3m']:.4f} |\n"

        # LPR 表格
        lpr_table = ""
        if 'lpr' in data and len(data['lpr']) > 0:
            lpr_df = data['lpr'][['date', '1y', '5y']].head(6)
            lpr_table = "| 日期 | 1 年期% | 5 年期% |\n|------|--------|--------|\n"
            for _, row in lpr_df.iterrows():
                lpr_table += f"| {row['date']} | {row['1y']} | {row['5y']} |\n"

        # 社会融资表格
        sf_table = ""
        if 'social_finance' in data and len(data['social_finance']) > 0:
            sf_df = data['social_finance'][['month', 'inc_month', 'stk_endval']].head(6)
            sf_table = "| 月份 | 当月增量 (亿) | 存量规模 (万亿) |\n|------|------------|-------------|\n"
            for _, row in sf_df.iterrows():
                sf_table += f"| {row['month']} | {row['inc_month']/100:.0f} | {row['stk_endval']:.2f} |\n"

        # 国债收益率表格 - 只显示关键期限
        yield_table = ""
        if 'bond_yield' in data and len(data['bond_yield']) > 0:
            yield_df = data['bond_yield'][['curve_term', 'yield']].sort_values('curve_term')

            # 关键期限：3 月，6 月，1 年，2 年，3 年，5 年，7 年，10 年，30 年
            key_terms = [0.25, 0.5, 1, 2, 3, 5, 7, 10, 30]
            yield_table = "| 期限 | 收益率% | 期限 | 收益率% |\n|------|--------|------|--------|\n"

            # 每行显示两个期限
            rows = []
            for key_term in key_terms:
                # 找到最接近的期限
                closest = yield_df.iloc[(yield_df['curve_term'].astype(float) - key_term).abs().argsort()[:1]].iloc[0]
                term_label = f"{int(key_term*12)}月" if key_term < 1 else f"{key_term}年"
                rows.append((term_label, closest['yield']))

            # 两列显示
            for i in range(0, len(rows), 2):
                if i + 1 < len(rows):
                    yield_table += f"| {rows[i][0]} | {rows[i][1]:.2f} | {rows[i+1][0]} | {rows[i+1][1]:.2f} |\n"
                else:
                    yield_table += f"| {rows[i][0]} | {rows[i][1]:.2f} | - | - |\n"

        template = f"""---
created: {today}
type: macro_economy
tags: [宏观经济，CPI, PPI, PMI, GDP, 利率]
---

# 宏观经济数据

## 数据更新时间
- 数据截至：{datetime.now().strftime('%Y年%m月')}
- 来源：Tushare Pro

## 价格指数

### CPI 居民消费价格指数

{cpi_table if cpi_table else "数据暂缺"}

### PPI 工业生产者出厂价格指数

{ppi_table if ppi_table else "数据暂缺"}

## 采购经理指数 PMI

{pmi_table if pmi_table else "数据暂缺"}

## 国民经济核算

### GDP 及产业增速

{gdp_table if gdp_table else "数据暂缺"}

## 货币供应

{m_table if m_table else "数据暂缺"}

## 利率水平

### Shibor 银行间拆借利率

{shibor_table if shibor_table else "数据暂缺"}

### LPR 贷款市场报价利率

{lpr_table if lpr_table else "数据暂缺"}

### 国债收益率曲线

{yield_table if yield_table else "数据暂缺"}

## 社会融资

{sf_table if sf_table else "数据暂缺"}

---
**数据来源**: Tushare Pro API
**更新日期**: {today}
"""

        output_path = os.path.join(self.output_dir, "宏观经济数据.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)

        return output_path

    def generate_bond_market_note(self, data: dict) -> str:
        """生成债券市场数据笔记"""
        today = datetime.now().strftime('%Y-%m-%d')

        # 可转债统计
        cb_summary = ""
        if 'convertible_bonds' in data and len(data['convertible_bonds']) > 0:
            cb_df = data['convertible_bonds']
            cb_summary = f"""
- 可转债总数：{len(cb_df)} 只
- 最新转债示例：{cb_df.iloc[0]['bond_short_name']} ({cb_df.iloc[0]['ts_code']})
"""

        # 债券回购利率
        repo_table = ""
        if 'repo_latest' in data and len(data['repo_latest']) > 0:
            repo_df = data['repo_latest'][['ts_code', 'repo_maturity', 'close', 'weight']].head(10)
            repo_table = "| 代码 | 品种 | 收盘价% | 加权% |\n|------|--------|--------|------|\n"
            for _, row in repo_df.iterrows():
                repo_table += f"| {row['ts_code']} | {row['repo_maturity']} | {row['close']:.3f} | {row['weight']:.3f} |\n"

        template = f"""---
created: {today}
type: bond_market
tags: [债券市场，可转债，回购利率，收益率]
---

# 债券市场数据

## 数据更新时间
- 数据截至：{datetime.now().strftime('%Y年%m月%d日')}
- 来源：Tushare Pro

## 可转债市场

{cb_summary if cb_summary else "数据暂缺"}

## 债券回购利率（最新交易日）

{repo_table if repo_table else "数据暂缺"}

## 国债收益率

详见：[[宏观经济数据]]

---
**数据来源**: Tushare Pro API
**更新日期**: {today}
"""

        output_path = os.path.join(self.output_dir, "债券市场数据.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)

        return output_path

    def sync_all(self):
        """执行全量同步"""
        print("=" * 60)
        print("Tushare 数据同步开始")
        print("=" * 60)
        print()

        # 获取数据
        macro_data = self.fetch_macro_data()
        bond_data = self.fetch_bond_market_data()

        print("\n=== 生成笔记 ===\n")

        # 生成笔记
        macro_file = self.generate_macro_note(macro_data)
        print(f"✓ 生成宏观经济笔记：{macro_file}")

        bond_file = self.generate_bond_market_note(bond_data)
        print(f"✓ 生成债券市场笔记：{bond_file}")

        print("\n" + "=" * 60)
        print("同步完成!")
        print("=" * 60)

        return macro_file, bond_file


def main():
    """主函数"""
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误：请设置 TUSHARE_TOKEN 环境变量")
        print("使用方法：export TUSHARE_TOKEN=your_token")
        return

    syncer = TushareDataSync(token)
    syncer.sync_all()


if __name__ == "__main__":
    main()
