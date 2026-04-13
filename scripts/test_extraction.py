#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试提取脚本"""

import fitz
import re
import os

# 切换到脚本所在目录
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pdf_path = 'raw/樟树市创业投资发展有限公司 2024 年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf'
print(f"Checking path: {os.path.exists(pdf_path)}")
print(f"raw dir: {os.listdir('raw')}")

if not os.path.exists(pdf_path):
    print(f"文件不存在：{pdf_path}")
    print("当前目录:", os.getcwd())
    print("raw 目录内容:", os.listdir('raw'))
else:
    doc = fitz.open(pdf_path)

    # 提取全文
    full_text = ''
    for page in doc:
        full_text += page.get_text()

    # 查找第三节范围
    start = full_text.find('第三节')
    end = full_text.find('第四节')
    if start > 0 and end > start:
        section3 = full_text[start:end]
        print('=== 第三节内容（前 3000 字）===')
        print(section3[:3000])
        print('\n\n=== 关键信息提取测试 ===')
        clean_text = section3.replace('\n', '')

        # 测试募集资金总额
        match = re.search(r'本期债券.*?不超过 [人民币]*\s*(\d+(?:\.\d+)?)\s*亿', clean_text)
        if match:
            print(f'募集资金总额：{match.group(1)} 亿元')

        # 测试资金用途
        match = re.search(r'募集资金.*?扣除发行费用后.*?拟 (.*?)(?:根据 | 二、| 三、| 四、)', clean_text)
        if match:
            print(f'资金用途：{match.group(1)[:200]}')

        # 测试偿还债务
        match = re.search(r'偿还.*?(\d+(?:\.\d+)?)\s*亿', clean_text)
        if match:
            print(f'偿还债务：{match.group(1)} 亿元')

        # 测试补充流动资金
        match = re.search(r'流动资金.*?(\d+(?:\.\d+)?)\s*亿', clean_text)
        if match:
            print(f'补充流动资金：{match.group(1)} 亿元')

    # 查找第四节范围
    start = full_text.find('第四节')
    end = full_text.find('第五节')
    if start > 0 and end > start:
        section4 = full_text[start:end]
        print('\n\n=== 第四节内容（前 3000 字）===')
        print(section4[:3000])
        print('\n\n=== 发行人信息提取测试 ===')
        clean_text = section4.replace('\n', '')

        # 测试发行人全称
        match = re.search(r'发行人全称 [为：:]?([^.。]+)', clean_text)
        if match:
            print(f'发行人全称：{match.group(1).strip()}')

        # 测试注册资本
        match = re.search(r'注册资本 [为：:]?\s*人民币\s*(\d+(?:\.\d+)?)\s*亿', clean_text)
        if match:
            print(f'注册资本：{match.group(1)} 亿元')

        # 测试成立日期
        match = re.search(r'成立日期 [为：:]?\s*(\d{4}年\d{1,2}月\d{1,2}日)', clean_text)
        if match:
            print(f'成立日期：{match.group(1)}')

        # 测试法定代表人
        match = re.search(r'法定代表人 [为：:]?([^\n。]+)', clean_text)
        if match:
            print(f'法定代表人：{match.group(1).strip()[:20]}')

        # 测试注册地址
        match = re.search(r'注册地址 [为：:]?([^\n。]+)', clean_text)
        if match:
            print(f'注册地址：{match.group(1).strip()[:50]}')
