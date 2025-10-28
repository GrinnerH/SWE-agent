#!/usr/bin/env python3
"""
轨迹分析辅助脚本
从 SWE-agent 轨迹文件中提取关键信息，便于分析
"""

import json
import sys
from pathlib import Path

def load_trajectory(traj_file):
    """加载轨迹文件"""
    with open(traj_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def extract_key_steps(trajectory):
    """提取关键步骤"""
    key_steps = []

    for i, step in enumerate(trajectory['trajectory']):
        action = step.get('action', '')
        thought = step.get('thought', '')
        observation = step.get('observation', '')

        # 识别关键步骤
        is_key_step = False
        step_type = 'other'

        # PoC 创建
        if 'create' in action and 'testcase' in action:
            is_key_step = True
            step_type = 'poc_create'

        # PoC 修改
        elif 'change' in action and 'testcase' in action:
            is_key_step = True
            step_type = 'poc_modify'

        # 运行测试
        elif 'secb repro' in action or 'secb build' in action:
            is_key_step = True
            step_type = 'test'

        # 代码分析
        elif 'search_file' in action or 'search_dir' in action:
            if 'vmcode' in action or 'async' in action or 'property' in action.lower():
                is_key_step = True
                step_type = 'code_analysis'

        # 打开关键文件
        elif 'open' in action and ('njs_vmcode.c' in action or 'njs_async.c' in action):
            is_key_step = True
            step_type = 'code_review'

        if is_key_step:
            key_steps.append({
                'step_num': i,
                'type': step_type,
                'action': action[:200],  # 限制长度
                'thought': thought[:300] if thought else '',
                'observation_preview': observation[:300] if observation else '',
                'observation_full_length': len(observation)
            })

    return key_steps

def extract_poc_versions(trajectory):
    """提取所有 PoC 版本"""
    poc_versions = []

    for i, step in enumerate(trajectory['trajectory']):
        action = step.get('action', '')
        observation = step.get('observation', '')

        # 查找 PoC 文件内容
        if '/testcase/poc.js' in observation and 'lines total' in observation:
            # 提取文件内容
            lines = observation.split('\n')
            content_lines = []
            in_content = False

            for line in lines:
                if 'lines total' in line:
                    in_content = True
                    continue
                if in_content and line.strip() and not line.startswith('(Open file:'):
                    content_lines.append(line)

            if content_lines:
                poc_versions.append({
                    'step_num': i,
                    'content': '\n'.join(content_lines[:50])  # 前50行
                })

    return poc_versions

def extract_test_results(trajectory):
    """提取测试结果"""
    test_results = []

    for i, step in enumerate(trajectory['trajectory']):
        action = step.get('action', '')
        observation = step.get('observation', '')

        if 'secb repro' in action:
            # 检查是否有 sanitizer 错误
            has_segv = 'SEGV' in observation or 'AddressSanitizer' in observation
            has_crash = 'crash' in observation.lower() or 'abort' in observation.lower()
            output_length = len(observation)

            test_results.append({
                'step_num': i,
                'has_segv': has_segv,
                'has_crash': has_crash,
                'output_length': output_length,
                'output_preview': observation[:500]
            })

    return test_results

def analyze_iteration_pattern(trajectory):
    """分析迭代模式"""
    iterations = []
    current_iteration = []

    for i, step in enumerate(trajectory['trajectory']):
        action = step.get('action', '')
        thought = step.get('thought', '')

        current_iteration.append({
            'step': i,
            'action_type': action.split()[0] if action else 'unknown'
        })

        # 如果遇到 secb repro，说明一个迭代结束
        if 'secb repro' in action:
            iterations.append({
                'start_step': current_iteration[0]['step'] if current_iteration else i,
                'end_step': i,
                'num_steps': len(current_iteration),
                'actions': [s['action_type'] for s in current_iteration]
            })
            current_iteration = []

    return iterations

def generate_report(traj_file):
    """生成分析报告"""
    print(f"正在分析轨迹文件: {traj_file}")
    print("=" * 80)

    trajectory = load_trajectory(traj_file)
    total_steps = len(trajectory['trajectory'])

    print(f"\n📊 基本统计")
    print(f"总步骤数: {total_steps}")

    # 关键步骤
    key_steps = extract_key_steps(trajectory)
    print(f"\n🔑 关键步骤 ({len(key_steps)} 个)")
    print("-" * 80)
    for step in key_steps:
        print(f"\nStep {step['step_num']} [{step['type']}]")
        print(f"  Action: {step['action']}")
        if step['thought']:
            print(f"  Thought: {step['thought']}")
        print(f"  Observation length: {step['observation_full_length']} chars")

    # PoC 版本
    poc_versions = extract_poc_versions(trajectory)
    print(f"\n\n📝 PoC 版本历史 ({len(poc_versions)} 个版本)")
    print("-" * 80)
    for i, version in enumerate(poc_versions, 1):
        print(f"\n版本 {i} (Step {version['step_num']})")
        print("```javascript")
        print(version['content'])
        print("```")

    # 测试结果
    test_results = extract_test_results(trajectory)
    print(f"\n\n🧪 测试结果 ({len(test_results)} 次测试)")
    print("-" * 80)
    for result in test_results:
        print(f"\nStep {result['step_num']}")
        print(f"  SEGV检测: {'✅ 是' if result['has_segv'] else '❌ 否'}")
        print(f"  崩溃检测: {'✅ 是' if result['has_crash'] else '❌ 否'}")
        print(f"  输出长度: {result['output_length']} chars")
        print(f"  输出预览: {result['output_preview'][:200]}...")

    # 迭代模式
    iterations = analyze_iteration_pattern(trajectory)
    print(f"\n\n🔄 迭代模式分析 ({len(iterations)} 个迭代)")
    print("-" * 80)
    for i, iteration in enumerate(iterations, 1):
        print(f"\n迭代 {i}: Step {iteration['start_step']}-{iteration['end_step']} ({iteration['num_steps']} 步)")
        print(f"  操作序列: {' -> '.join(iteration['actions'][:10])}")

    # 最终状态
    print(f"\n\n📌 最终状态")
    print("-" * 80)
    last_step = trajectory['trajectory'][-1]
    print(f"最后步骤: {total_steps - 1}")
    print(f"最后动作: {last_step.get('action', 'N/A')[:200]}")
    print(f"最后思考: {last_step.get('thought', 'N/A')[:300]}")

    # 成功指标
    print(f"\n\n✅ 成功指标")
    print("-" * 80)
    has_successful_poc = any(r['has_segv'] or r['has_crash'] for r in test_results)
    print(f"生成成功的 PoC: {'✅ 是' if has_successful_poc else '❌ 否'}")
    print(f"PoC 版本数: {len(poc_versions)}")
    print(f"测试次数: {len(test_results)}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        traj_file = 'trajectories/grinner/secb_poc__deepseek/deepseek-chat__t-0.00__p-0.95__c-1.50___secb_poc_eval/njs.cve-2022-32414/njs.cve-2022-32414.traj'
    else:
        traj_file = sys.argv[1]

    generate_report(traj_file)
