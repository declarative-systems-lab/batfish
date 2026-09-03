#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可解释网络验证测试系统 - 用户研究版本
支持随机分组、计时、确认机制、不可退回的测试流程
"""

import base64
import os
import re
import random
from pathlib import Path
from io import BytesIO
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

OUTPUT_DIR = Path(__file__).resolve().parent / "generated"
INDEX_TEMPLATE = Path(__file__).resolve().parent / "templates" / "index.html"

def highlight_translation_text(text):
    """静态处理翻译文本，添加高亮标签（直接硬编码颜色和字体大小）"""
    if not text:
        return text
    highlighted = text
    
    # 高亮 permit / deny（不区分大小写）- 橙色，font-weight: 900
    highlighted = re.sub(r'\b(permit|deny)\b', r'<span style="color: #ff8800; font-weight: 900;">\1</span>', highlighted, flags=re.IGNORECASE)
    # 高亮 IPV4 地址 (格式: 数字.数字.数字.数字/数字 或 数字.数字.数字.数字) - 蓝色，font-weight: 900
    highlighted = re.sub(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)', r'<span style="color: #0080ff; font-weight: 900;">\1</span>', highlighted)
    # 高亮 community (格式: 数字:数字) - 蓝色，font-weight: 900
    highlighted = re.sub(r'(\d+:\d+)', r'<span style="color: #0080ff; font-weight: 900;">\1</span>', highlighted)
    # 高亮数字范围 (格式: 数字~数字 或 数字-数字) - 绿色，font-weight: 900
    highlighted = re.sub(r'(\d+)[~-](\d+)', r'<span style="color: #16a34a; font-weight: 900;">\1~\2</span>', highlighted)
    # 高亮特定句子中的数字 1 - 绿色，font-weight: 900
    # 匹配中文：AS-path 前置扩展，长度应为 数字
    highlighted = re.sub(r'(AS-path\s+前置扩展，长度应为\s+)(\d+)', r'\1<span style="color: #16a34a; font-weight: 900;">\2</span>', highlighted)
    # 匹配英文：AS-path prepend length = 数字
    highlighted = re.sub(r'(AS-path\s+prepend\s+length\s*=\s*)(\d+)', r'\1<span style="color: #16a34a; font-weight: 900;">\2</span>', highlighted, flags=re.IGNORECASE)
    # 高亮 community 中的 none（不区分大小写）- 橙色，font-weight: 900
    # 匹配 "none" 作为独立单词，通常在 community 上下文中
    highlighted = re.sub(r'\b(none)\b', r'<span style="color: #ff8800; font-weight: 900;">\1</span>', highlighted, flags=re.IGNORECASE)
    
    # 处理特定的两句，将它们变成斜体，并移除其中的 community 高亮
    # 匹配 "Community domain: {xxx}" 或 "Community 可选范围：{xxx}"
    def replace_community_domain(match):
        full_text = match.group(0)
        # 移除其中的 community 高亮标签（数字:数字 格式的高亮）
        full_text = re.sub(r'<span style="color: #0080ff; font-weight: 900;">(\d+:\d+)</span>', r'\1', full_text)
        # 将整句变成斜体
        return f'<em>{full_text}</em>'
    
    # 匹配 "Community domain: {xxx}" 或 "Community 可选范围：{xxx}"
    highlighted = re.sub(
        r'Community\s+domain:\s*\{[^}]+\}|Community\s+可选范围：\s*\{[^}]+\}',
        replace_community_domain,
        highlighted,
        flags=re.IGNORECASE
    )
    
    # 特殊处理1: 如果包含红色标题，将 <span style="color: red;"> 到第一个 <em> 或 >= 之间的所有高亮颜色改为红色
    # 对于每个 <span style="color: red;">，找到它后面第一个出现的 <em> 或 >=（哪个先出现就用哪个）
    if re.search(r'<span\s+style\s*=\s*["\']color:\s*red\s*;?\s*["\']', highlighted, re.IGNORECASE):
        def replace_between_red_and_target(match):
            prefix = match.group(1)  # <span style="color: red;"> 及其后的内容
            target = match.group(2)  # <em> 或 >= 或 &gt;=
            # 在 prefix 中替换所有高亮颜色为红色
            # 替换橙色 (#ff8800)、蓝色 (#0080ff)、绿色 (#16a34a) 为红色
            prefix = re.sub(r'color:\s*#ff8800', 'color: red', prefix)
            prefix = re.sub(r'color:\s*#0080ff', 'color: red', prefix)
            prefix = re.sub(r'color:\s*#16a34a', 'color: red', prefix)
            return prefix + target
        
        # 找到所有 <span style="color: red;"> 的位置
        red_span_pattern = r'<span\s+style\s*=\s*["\']color:\s*red\s*;?\s*["\']>'
        red_span_matches = list(re.finditer(red_span_pattern, highlighted, re.IGNORECASE))
        
        # 从后往前处理，避免位置偏移问题
        for red_span_match in reversed(red_span_matches):
            red_span_start = red_span_match.start()
            red_span_end = red_span_match.end()
            after_red_span = highlighted[red_span_end:]
            
            # 找到第一个 <em> 的位置
            em_match = re.search(r'<em>', after_red_span, re.IGNORECASE)
            em_pos = em_match.start() if em_match else None
            
            # 找到第一个 >= 或 &gt;= 的位置
            gte_match1 = re.search(r'&gt;=', after_red_span)
            gte_match2 = re.search(r'>=', after_red_span)
            gte_pos = None
            if gte_match1 and gte_match2:
                gte_pos = min(gte_match1.start(), gte_match2.start())
            elif gte_match1:
                gte_pos = gte_match1.start()
            elif gte_match2:
                gte_pos = gte_match2.start()
            
            # 选择更近的位置（<em> 或 >=）
            target_pos = None
            target_text = None
            if em_pos is not None and gte_pos is not None:
                if em_pos < gte_pos:
                    target_pos = em_pos
                    target_text = '<em>'
                else:
                    target_pos = gte_pos
                    target_text = gte_match1.group(0) if gte_match1 and gte_match1.start() == gte_pos else gte_match2.group(0)
            elif em_pos is not None:
                target_pos = em_pos
                target_text = '<em>'
            elif gte_pos is not None:
                target_pos = gte_pos
                target_text = gte_match1.group(0) if gte_match1 else gte_match2.group(0)
            
            # 如果找到了目标位置，处理中间的内容
            if target_pos is not None:
                prefix = highlighted[red_span_start:red_span_end + target_pos]
                # 在 prefix 中替换所有高亮颜色为红色
                prefix = re.sub(r'color:\s*#ff8800', 'color: red', prefix)
                prefix = re.sub(r'color:\s*#0080ff', 'color: red', prefix)
                prefix = re.sub(r'color:\s*#16a34a', 'color: red', prefix)
                # 替换原文本
                highlighted = highlighted[:red_span_start] + prefix + target_text + highlighted[red_span_end + target_pos + len(target_text):]
    
    # 特殊处理2: 在 <em>...</em> 之间的内容，移除所有高亮标签
    def remove_highlights_in_em(match):
        content = match.group(1)
        # 移除所有高亮 span 标签，保留内容
        # 匹配 <span style="...">内容</span> 并替换为 内容
        content = re.sub(r'<span\s+style\s*=[^>]*>([^<]*)</span>', r'\1', content)
        # 处理嵌套的情况，可能需要多次替换
        while re.search(r'<span\s+style\s*=[^>]*>', content):
            content = re.sub(r'<span\s+style\s*=[^>]*>([^<]*)</span>', r'\1', content)
        return f'<em>{content}</em>'
    
    # 匹配 <em>...</em> 并移除其中的高亮标签
    highlighted = re.sub(
        r'<em>(.*?)</em>',
        remove_highlights_in_em,
        highlighted,
        flags=re.DOTALL
    )
    
    return highlighted

def read_file_content(file_path):
    """读取文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # 转义JavaScript中的反引号
            content = content.replace('`', '\\`')
            return content
    except FileNotFoundError:
        print(f"警告: 文件 {file_path} 不存在")
        return ""

def read_answer_content(file_path):
    """读取答案文件内容，保留每行开头和结尾的空格"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 只移除文件末尾的空白字符（换行符等），保留开头和每行的原始格式
            content = content.rstrip()
            # 移除文件开头的空行（完全空白的行），但保留每行的行首空格
            lines = content.split('\n')
            # 从开头移除完全空白的行
            while lines and lines[0].strip() == '':
                lines.pop(0)
            # 从末尾移除完全空白的行
            while lines and lines[-1].strip() == '':
                lines.pop()
            content = '\n'.join(lines)
            # 转义JavaScript中的反引号
            content = content.replace('`', '\\`')
            return content
    except FileNotFoundError:
        print(f"警告: 文件 {file_path} 不存在")
        return ""

def encode_image_to_base64(image_path, max_width=1000, quality=70):
    """将图片编码为Base64，并压缩以减小文件大小
    
    Args:
        image_path: 图片文件路径
        max_width: 最大宽度（像素），超过此宽度会按比例缩放
        quality: JPEG质量（1-100），仅对JPEG格式有效，PNG会使用optimize=True
    """
    if not image_path:
        return ""
    
    try:
        if PIL_AVAILABLE:
            # 使用 PIL 压缩图片
            with open(image_path, 'rb') as img_file:
                img = Image.open(img_file)
                
                # 如果是 RGBA 模式，转换为 RGB（JPEG 不支持透明度）
                if img.mode in ('RGBA', 'LA', 'P'):
                    # 创建白色背景
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 按比例缩放（如果宽度超过 max_width）
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    # 兼容不同版本的 PIL
                    try:
                        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                    except AttributeError:
                        img = img.resize((max_width, new_height), Image.LANCZOS)
                
                # 压缩并编码为 base64
                output = BytesIO()
                # 使用 JPEG 格式以获得更好的压缩率
                img.save(output, format='JPEG', quality=quality, optimize=True)
                img_data = output.getvalue()
                base64_data = base64.b64encode(img_data).decode('utf-8')
                return f"data:image/jpeg;base64,{base64_data}"
        else:
            # 如果没有 PIL，使用原始方法（不压缩）
            with open(image_path, 'rb') as img_file:
                img_data = img_file.read()
                base64_data = base64.b64encode(img_data).decode('utf-8')
                # 根据文件扩展名判断格式
                ext = os.path.splitext(image_path)[1].lower()
                mime_type = 'image/png' if ext == '.png' else 'image/jpeg'
                return f"data:{mime_type};base64,{base64_data}"
    except FileNotFoundError:
        print(f"警告: 图片文件 {image_path} 不存在")
        return ""
    except Exception as e:
        print(f"警告: 处理图片 {image_path} 时出错: {e}")
        # 如果压缩失败，尝试不压缩的方式
        try:
            with open(image_path, 'rb') as img_file:
                img_data = img_file.read()
                base64_data = base64.b64encode(img_data).decode('utf-8')
                ext = os.path.splitext(image_path)[1].lower()
                mime_type = 'image/png' if ext == '.png' else 'image/jpeg'
                return f"data:{mime_type};base64,{base64_data}"
        except Exception as e2:
            print(f"警告: 无法读取图片 {image_path}: {e2}")
            return ""

def resolve_topology_image_path(question_dir, mini=False):
    """拓扑图路径：优先 SVG，其次 PNG"""
    base_name = '0_network-topology-mini' if mini else '0_network-topology'
    for ext in ('.svg', '.png'):
        path = f'{question_dir}/{base_name}{ext}'
        if os.path.isfile(path):
            return path
    return f'{question_dir}/{base_name}.png'

def encode_topology_image(image_path, max_width=1000, quality=70):
    """拓扑图编码：SVG 保持矢量清晰，位图仍走 JPEG 压缩"""
    if not image_path:
        return ""
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.svg':
        try:
            with open(image_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            base64_data = base64.b64encode(svg_content.encode('utf-8')).decode('utf-8')
            return f"data:image/svg+xml;base64,{base64_data}"
        except FileNotFoundError:
            print(f"警告: SVG 文件 {image_path} 不存在")
            return ""
        except Exception as e:
            print(f"警告: 读取 SVG {image_path} 时出错: {e}")
            return ""
    return encode_image_to_base64(image_path, max_width, quality)


def categorize_config_terms(highlight_terms):
    """将配置术语按类型分类"""
    route_maps = []
    prefix_lists = []
    community_lists = []
    other_terms = []
    
    for term in highlight_terms:
        term = term.strip()
        if not term:
            continue
            
        # 路由策略模式：R1_IN_FROM_ISP1, R2_OUT_TO_R3 等
        if re.match(r'R\d+_(IN|OUT)_(FROM|TO)_\w+', term):
            route_maps.append(term)
        # 前缀列表模式：isp1_network, private_ips, network_10_0_0_0 等
        elif re.match(r'(default_ips|private_ips|isp\d+_network|other_network|network_\d+_\d+_\d+_\d+)', term):
            prefix_lists.append(term)
        # 社区列表模式：纯数字
        elif re.match(r'^\d+$', term):
            community_lists.append(term)
        else:
            other_terms.append(term)
    
    return {
        'route_maps': route_maps,
        'prefix_lists': prefix_lists,
        'community_lists': community_lists,
        'other_terms': other_terms
    }

def parse_coursera_questions(coursera_content):
    """解析 coursera 格式的问题文件"""
    questions = []
    current_question = None
    current_option = None
    in_config_block = False
    in_option_block = False
    in_note_block = False
    config_lines = []
    option_lines = []
    note_lines = []
    
    lines = coursera_content.split('\n')
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        original_line = line
        
        # 检测新问题开始
        if stripped.startswith('question') and ':' in stripped:
            # 保存前一个问题
            if current_question is not None:
                if current_option is not None:
                    # 只去掉末尾的空白，保留开头的空格
                    option_content = '\n'.join(option_lines)
                    # 去掉末尾的空白行和空格
                    while option_content and (option_content[-1] == '\n' or option_content[-1] == ' ' or option_content[-1] == '\t'):
                        option_content = option_content[:-1]
                    # 去掉开头的空行（完全空白的行），但保留行首空格
                    lines = option_content.split('\n')
                    while lines and lines[0].strip() == '':
                        lines.pop(0)
                    current_question['options'].append({
                        'num': current_option['num'],
                        'correct': current_option['correct'],
                        'text': '\n'.join(lines),
                        'is_diff': current_option.get('is_diff', False)
                    })
                questions.append(current_question)
            
            # 开始新问题
            question_num = stripped.split(':')[0].replace('question', '').strip()
            question_text = stripped.split(':', 1)[1].strip() if ':' in stripped else ''
            current_question = {
                'num': question_num,
                'text': question_text,
                'config': '',
                'note': None,
                'options': []
            }
            current_option = None
            in_config_block = False
            in_option_block = False
            in_note_block = False
            config_lines = []
            option_lines = []
            note_lines = []
        
        # 检测 note 代码块开始
        elif stripped == '```note':
            in_note_block = True
            note_lines = []
        # 检测 note 代码块结束
        elif in_note_block and stripped == '```':
            in_note_block = False
            if current_question:
                # 保留原始格式（包括缩进和换行）
                note_content = '\n'.join(note_lines)
                # 去掉末尾的空白行和空格
                while note_content and (note_content[-1] == '\n' or note_content[-1] == ' ' or note_content[-1] == '\t'):
                    note_content = note_content[:-1]
                # 去掉开头的空行（完全空白的行），但保留行首空格
                lines = note_content.split('\n')
                while lines and lines[0].strip() == '':
                    lines.pop(0)
                if lines:
                    current_question['note'] = '\n'.join(lines)
        
        # 检测配置代码块开始
        elif stripped == '```config' and not in_note_block:
            in_config_block = True
            config_lines = []
        # 检测配置代码块结束
        elif in_config_block and stripped == '```':
            in_config_block = False
            if current_question:
                # 只去掉末尾的空白，保留开头的空格和空行
                config_content = '\n'.join(config_lines)
                # 去掉末尾的空白行和空格
                while config_content and (config_content[-1] == '\n' or config_content[-1] == ' ' or config_content[-1] == '\t'):
                    config_content = config_content[:-1]
                # 去掉开头的空行（完全空白的行），但保留行首空格
                lines = config_content.split('\n')
                while lines and lines[0].strip() == '':
                    lines.pop(0)
                current_question['config'] = '\n'.join(lines)
        # 配置代码块内容
        elif in_config_block:
            config_lines.append(original_line)  # 保留原始格式（包括缩进）
        # note 代码块内容
        elif in_note_block:
            note_lines.append(original_line)  # 保留原始格式（包括缩进和换行）
        
        # 检测选项
        elif stripped.startswith('option') and ':' in stripped and not in_config_block and not in_note_block:
            # 保存前一个选项
            if current_option is not None:
                # 只去掉末尾的空白，保留开头的空格
                option_content = '\n'.join(option_lines)
                # 去掉末尾的空白行和空格
                while option_content and (option_content[-1] == '\n' or option_content[-1] == ' ' or option_content[-1] == '\t'):
                    option_content = option_content[:-1]
                # 去掉开头的空行（完全空白的行），但保留行首空格
                lines = option_content.split('\n')
                while lines and lines[0].strip() == '':
                    lines.pop(0)
                current_question['options'].append({
                    'num': current_option['num'],
                    'correct': current_option['correct'],
                    'text': '\n'.join(lines),
                    'is_diff': current_option.get('is_diff', False)
                })
            
            # 解析新选项
            option_num = stripped.split(':')[0].strip()
            option_text = stripped.split(':', 1)[1].strip() if ':' in stripped else ''
            is_correct = '[yes]' in option_text
            current_option = {
                'num': option_num,
                'correct': is_correct,
                'is_diff': False  # 标记是否为 diff 格式
            }
            in_option_block = False  # 先设置为 False，等待代码块开始
            option_lines = []
        
        # 选项代码块：检测到 ``` 或 ```diff 且当前有选项
        elif current_option is not None and (stripped == '```' or stripped.startswith('```')) and not in_config_block:
            if not in_option_block:
                # 开始选项代码块（可能是 ``` 或 ```diff 等）
                in_option_block = True
                option_lines = []
                # 记录是否为 diff 格式
                if stripped.startswith('```diff'):
                    current_option['is_diff'] = True
            else:
                # 结束选项代码块
                in_option_block = False
        # 选项代码块内容
        elif in_option_block and current_option is not None:
            option_lines.append(original_line)  # 保留原始格式
        
        # 问题文本（在配置块之前，且不在选项块中）
        elif current_question and not in_config_block and not in_option_block and not in_note_block and not stripped.startswith('option') and stripped and not stripped.startswith('```'):
            if not current_question['text']:
                current_question['text'] = stripped
            else:
                current_question['text'] += ' ' + stripped
    
    # 保存最后一个问题和选项
    if current_question is not None:
        if current_option is not None and option_lines:
            # 只去掉末尾的空白，保留开头的空格
            option_content = '\n'.join(option_lines)
            # 去掉末尾的空白行和空格
            while option_content and (option_content[-1] == '\n' or option_content[-1] == ' ' or option_content[-1] == '\t'):
                option_content = option_content[:-1]
            # 去掉开头的空行（完全空白的行），但保留行首空格
            lines = option_content.split('\n')
            while lines and lines[0].strip() == '':
                lines.pop(0)
            current_question['options'].append({
                'num': current_option['num'],
                'correct': current_option['correct'],
                'text': '\n'.join(lines),
                'is_diff': current_option.get('is_diff', False)
            })
        # 如果最后一个问题还有未保存的配置
        if in_config_block and config_lines:
            config_content = '\n'.join(config_lines)
            # 只去掉末尾的空白，保留开头的空格
            while config_content and (config_content[-1] == '\n' or config_content[-1] == ' ' or config_content[-1] == '\t'):
                config_content = config_content[:-1]
            # 去掉开头的空行（完全空白的行），但保留行首空格
            lines = config_content.split('\n')
            while lines and lines[0].strip() == '':
                lines.pop(0)
            current_question['config'] = '\n'.join(lines)
        # 如果最后一个问题还有未保存的 note
        if in_note_block and note_lines:
            note_content = '\n'.join(note_lines)
            # 去掉末尾的空白行和空格
            while note_content and (note_content[-1] == '\n' or note_content[-1] == ' ' or note_content[-1] == '\t'):
                note_content = note_content[:-1]
            # 去掉开头的空行（完全空白的行），但保留行首空格
            lines = note_content.split('\n')
            while lines and lines[0].strip() == '':
                lines.pop(0)
            if lines:
                current_question['note'] = '\n'.join(lines)
        questions.append(current_question)
    
    return questions

def load_coursera_question_data(language='en'):
    """加载 coursera 问题数据，返回 JavaScript 对象字面量字符串"""
    coursera_dir = 'question_coursera'
    
    if language == 'zh':
        file_path = f'{coursera_dir}/question_coursera01_zh.txt'
    else:
        file_path = f'{coursera_dir}/question_coursera01.txt'
    
    # 直接读取文件
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except FileNotFoundError:
        content = ""
    
    questions = parse_coursera_questions(content)
    
    # 加载默认的 subspec 文件（用于非 question6 的问题）
    config_subspec_content = read_file_content(f'{coursera_dir}/config_level_subspecs.txt')
    line_subspec_content = read_file_content(f'{coursera_dir}/line_level_subspecs.txt')
    # 根据语言加载语义概括文件
    if language == 'zh':
        config_subspec_trans_content = highlight_translation_text(read_file_content(f'{coursera_dir}/config_level_subspecs_trans_zh.txt'))
        line_subspec_trans_content = highlight_translation_text(read_file_content(f'{coursera_dir}/line_level_subspecs_trans_zh.txt'))
    else:
        config_subspec_trans_content = highlight_translation_text(read_file_content(f'{coursera_dir}/config_level_subspecs_trans.txt'))
        line_subspec_trans_content = highlight_translation_text(read_file_content(f'{coursera_dir}/line_level_subspecs_trans.txt'))
    
    # 为 question6 加载单独的子规约文件
    question6_subspec_dir = f'{coursera_dir}/question6_subspecs'
    question6_config_subspec_content = read_file_content(f'{question6_subspec_dir}/config_level_subspecs.txt')
    question6_line_subspec_content = read_file_content(f'{question6_subspec_dir}/line_level_subspecs.txt')
    if language == 'zh':
        question6_config_subspec_trans_content = highlight_translation_text(read_file_content(f'{question6_subspec_dir}/config_level_subspecs_trans_zh.txt'))
        question6_line_subspec_trans_content = highlight_translation_text(read_file_content(f'{question6_subspec_dir}/line_level_subspecs_trans_zh.txt'))
    else:
        question6_config_subspec_trans_content = highlight_translation_text(read_file_content(f'{question6_subspec_dir}/config_level_subspecs_trans.txt'))
        question6_line_subspec_trans_content = highlight_translation_text(read_file_content(f'{question6_subspec_dir}/line_level_subspecs_trans.txt'))
    
    # 为每个问题添加子规约内容（如果该问题有单独的子规约）
    for question in questions:
        if question.get('num') == '6':
            # question6 使用单独的子规约
            question['configSubspecContent'] = question6_config_subspec_content or ''
            question['lineSubspecContent'] = question6_line_subspec_content or ''
            question['configSubspecTransContent'] = question6_config_subspec_trans_content or ''
            question['lineSubspecTransContent'] = question6_line_subspec_trans_content or ''
        else:
            # 其他问题使用默认的子规约（在全局变量中）
            question['configSubspecContent'] = None  # None 表示使用全局的
            question['lineSubspecContent'] = None
            question['configSubspecTransContent'] = None
            question['lineSubspecTransContent'] = None
    
    # 转换为 JavaScript 对象字面量，而不是 JSON
    # 这样可以避免 JSON 转义的问题
    def format_js_value(value):
        """将 Python 值格式化为 JavaScript 值"""
        if isinstance(value, str):
            # 转义字符串中的特殊字符
            value = value.replace('\\', '\\\\')  # 反斜杠
            value = value.replace('`', '\\`')    # 反引号
            value = value.replace('$', '\\$')    # 美元符号（模板字符串中）
            value = value.replace('\n', '\\n')   # 换行
            value = value.replace('\r', '\\r')   # 回车
            value = value.replace('\t', '\\t')   # 制表符
            value = value.replace('"', '\\"')    # 双引号
            return f'"{value}"'
        elif isinstance(value, bool):
            return 'true' if value else 'false'
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, list):
            items = [format_js_value(item) for item in value]
            return '[' + ', '.join(items) + ']'
        elif isinstance(value, dict):
            items = [f'{format_js_key(k)}: {format_js_value(v)}' for k, v in value.items()]
            return '{' + ', '.join(items) + '}'
        else:
            return 'null'
    
    def format_js_key(key):
        """格式化 JavaScript 对象键"""
        if isinstance(key, str) and key.isidentifier():
            return key
        else:
            return f'"{key}"'
    
    # 格式化整个对象
    result = {
        'questions': questions,
        'configSubspecContent': config_subspec_content or '',
        'lineSubspecContent': line_subspec_content or '',
        'configSubspecTransContent': config_subspec_trans_content or '',
        'lineSubspecTransContent': line_subspec_trans_content or ''
    }
    
    js_obj = format_js_value(result)
    return js_obj

def parse_config_with_subspecs(config_content, config_subspec_content, line_subspec_content, config_subspec_trans_content=None, line_subspec_trans_content=None, show_subspecs=True, highlight_terms=None, language='en'):
    """解析配置文件，提取subspec信息"""
    # 解析config-level subspec数据
    config_subspec_data = {}
    lines = config_subspec_content.split('\n')
    current_var = None
    
    for line in lines:
        if line.startswith('Config Variable:'):
            current_var = line.split('Config Variable: ')[1].strip()
        elif line.strip().startswith('1.') and current_var:
            subspec = line.strip()[2:].strip()
            config_subspec_data[current_var] = subspec
    
    # 解析line-level subspec数据
    line_subspec_data = {}
    line_subspec_names = set()  # 存储所有line-level subspec名称，包括empty的
    lines = line_subspec_content.split('\n')
    current_line_group = None
    
    for line in lines:
        if line.startswith('Line Group:'):
            current_line_group = line.split('Line Group: ')[1].strip()
            # 将所有line group名称添加到集合中，无论内容是否为empty
            if current_line_group:
                line_subspec_names.add(current_line_group)
        elif line.strip().startswith('1.') and current_line_group:
            subspec = line.strip()[2:].strip()
            line_subspec_data[current_line_group] = subspec
    
    # 解析转换后的config-level subspec数据
    config_subspec_trans_data = {}
    if config_subspec_trans_content:
        lines = config_subspec_trans_content.split('\n')
        current_var = None
        
        for line in lines:
            if line.startswith('Config Variable:'):
                current_var = line.split('Config Variable: ')[1].strip()
            elif line.strip().startswith('1.') and current_var:
                subspec_trans = line.strip()[2:].strip()
                config_subspec_trans_data[current_var] = subspec_trans
    
    # 解析转换后的line-level subspec数据
    line_subspec_trans_data = {}
    if line_subspec_trans_content:
        lines = line_subspec_trans_content.split('\n')
        current_line_group = None
        
        for line in lines:
            if line.startswith('Line Group:'):
                current_line_group = line.split('Line Group: ')[1].strip()
            elif line.strip().startswith('1.') and current_line_group:
                subspec_trans = line.strip()[2:].strip()
                line_subspec_trans_data[current_line_group] = subspec_trans
    
    # 合并两种subspec数据
    subspec_data = {**config_subspec_data, **line_subspec_data}
    
    # 分类高亮术语
    categorized_terms = categorize_config_terms(highlight_terms) if highlight_terms else None
    
    # 处理配置内容
    processed_lines = []
    for line in config_content.split('\n'):
        if '[' in line and '](' in line:
            # 处理包含subspec的行
            processed_line = process_config_line(line, subspec_data, config_subspec_data, line_subspec_data, line_subspec_names, show_subspecs, categorized_terms, config_subspec_trans_data, line_subspec_trans_data, language)
            processed_lines.append(processed_line)
        else:
            # 即使没有subspec，也要应用分类高亮
            if categorized_terms:
                processed_line = apply_categorized_highlighting(line, categorized_terms)
                processed_lines.append(processed_line)
            else:
                processed_lines.append(line)
    
    return processed_lines, line_subspec_names

def apply_number_highlighting(line):
    """应用数字高亮到配置行"""
    processed_line = line
    
    # 避免高亮已经被subspec标记的内容
    # 使用更健壮的subspec保护机制
    subspec_placeholders = {}
    placeholder_counter = 0
    
    # 使用回调函数来替换subspec，确保每个subspec都有唯一占位符
    def replace_subspec(match):
        nonlocal placeholder_counter
        placeholder = f"__SUBSPEC_PLACEHOLDER_{placeholder_counter}__"
        subspec_placeholders[placeholder] = match.group(0)
        placeholder_counter += 1
        return placeholder
    
    # 替换所有subspec为占位符
    subspec_pattern = r'<span class="[^"]*" data-subspec="[^"]*" data-subspec-name="[^"]*">.*?</span>'
    processed_line = re.sub(subspec_pattern, replace_subspec, processed_line)
    
    # 数字高亮模式 - 只在非subspec区域应用
    # 1. seq xxx - 序列号
    processed_line = re.sub(r'\bseq\s+(\d+)\b', r'seq <span class="highlight-number">\1</span>', processed_line)
    
    # 2. ge xxx, le xxx, eq xxx - 长度操作符
    processed_line = re.sub(r'\b(ge|le|eq)\s+(\d+)\b', r'\1 <span class="highlight-number">\2</span>', processed_line)
    
    # 3. x.x.x.x/x - IP地址/掩码中的数字
    processed_line = re.sub(r'\b(\d+\.\d+\.\d+\.\d+)/(\d+)\b', r'<span class="highlight-number">\1</span>/<span class="highlight-number">\2</span>', processed_line)
    
    # 4. xxx:xxx - 社区值中的数字
    processed_line = re.sub(r'\b(\d+):(\d+)\b', r'<span class="highlight-number">\1</span>:<span class="highlight-number">\2</span>', processed_line)
    
    # 5. permit xxx, deny xxx - 操作符后的数字
    processed_line = re.sub(r'\b(permit|deny)\s+(\d+)\b', r'\1 <span class="highlight-number">\2</span>', processed_line)
    
    # 恢复subspec标记的内容
    for placeholder, original in subspec_placeholders.items():
        processed_line = processed_line.replace(placeholder, original)
    
    return processed_line

def apply_categorized_highlighting(line, categorized_terms):
    """应用分类高亮到配置行"""
    processed_line = line
    
    # 路由策略 - 蓝色高亮
    for term in categorized_terms['route_maps']:
        if term.strip():
            highlight_pattern = r'\b' + re.escape(term.strip()) + r'\b'
            processed_line = re.sub(highlight_pattern, f'<span class="highlight-route-map">{term.strip()}</span>', processed_line, flags=re.IGNORECASE)
    
    # 前缀列表 - 绿色高亮
    for term in categorized_terms['prefix_lists']:
        if term.strip():
            highlight_pattern = r'\b' + re.escape(term.strip()) + r'\b'
            processed_line = re.sub(highlight_pattern, f'<span class="highlight-prefix-list">{term.strip()}</span>', processed_line, flags=re.IGNORECASE)
    
    # 社区列表 - 橙色高亮
    for term in categorized_terms['community_lists']:
        if term.strip():
            highlight_pattern = r'\b' + re.escape(term.strip()) + r'\b'
            processed_line = re.sub(highlight_pattern, f'<span class="highlight-community-list">{term.strip()}</span>', processed_line, flags=re.IGNORECASE)
    
    # 其他术语 - 黄色高亮（保持原有样式）
    for term in categorized_terms['other_terms']:
        if term.strip():
            highlight_pattern = r'\b' + re.escape(term.strip()) + r'\b'
            processed_line = re.sub(highlight_pattern, f'<span class="highlight-term">{term.strip()}</span>', processed_line, flags=re.IGNORECASE)
    
    # 应用数字高亮（在分类高亮之后，确保优先级）
    processed_line = apply_number_highlighting(processed_line)
    
    return processed_line

def format_subspec_for_display(subspec_text, subspec_name, config_subspec_data, line_subspec_data, config_subspec_trans_data=None, line_subspec_trans_data=None, is_missing=False, language='en'):
    """格式化subspec文本，使其更易读"""
    # 如果 subspec 不存在，显示 "none" 和 "No subspec found"
    if is_missing:
        if language == 'zh':
            return '没有找到子规约<br>─────────────────────<br>none'
        else:
            return 'No subspec found<br>─────────────────────<br>none'
    
    if subspec_text == 'No subspec found' or subspec_text == 'empty':
        return f'<div class="tooltip-header">配置字段说明</div><div class="tooltip-simple">无特殊约束条件</div>'
    
    # 处理subspec文本中的变量名替换
    processed_subspec = subspec_text
    
    # 判断是config-level还是line-level subspec
    if subspec_name in config_subspec_data:
        # Config-level: 将 Config_xxx 替换为 VAR，但对 ip/mask 字段特殊处理
        def replace_config_level_var(match):
            full_var = match.group(0)
            # 检查是否以 __ip 或 __mask 结尾
            if full_var.endswith('__ip'):
                return 'VAR_IP'
            elif full_var.endswith('__mask'):
                return 'VAR_MASK'
            else:
                return 'VAR'
        
        processed_subspec = re.sub(r'Config_[a-zA-Z0-9_]+', replace_config_level_var, processed_subspec)
        field_name = 'VAR'
        subspec_type = 'Field-Level'
    else:
        # Line-level: 将 Config_xxx_Line_..._xxx 保留最后一个 _xxx 并转换为 VAR_XXX
        def replace_line_level_var(match):
            full_var = match.group(0)
            # 提取最后一个下划线后的部分
            parts = full_var.split('_')
            if len(parts) > 1:
                last_part = parts[-1].upper()
                return f'VAR_{last_part}'
            return 'VAR'
        
        processed_subspec = re.sub(r'Config_[a-zA-Z0-9_]+', replace_line_level_var, processed_subspec)
        field_name = 'VAR_XXX'
        subspec_type = 'Line-Level'
    
    # 获取转换后的subspec
    subspec_trans = None
    if subspec_name in config_subspec_data and config_subspec_trans_data and subspec_name in config_subspec_trans_data:
        subspec_trans = config_subspec_trans_data[subspec_name]
    elif subspec_name in line_subspec_data and line_subspec_trans_data and subspec_name in line_subspec_trans_data:
        subspec_trans = line_subspec_trans_data[subspec_name]
    
    # 根据subspec内容提供更详细的说明
    if 'true' in processed_subspec.lower():
        if subspec_trans:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">✅ 启用此配置项</div>
                       <div class="tooltip-translated">{subspec_trans}</div>
                       <div class="tooltip-separator">─────────────────────</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
        else:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">✅ 启用此配置项</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
    elif 'false' in processed_subspec.lower():
        if subspec_trans:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">❌ 禁用此配置项</div>
                       <div class="tooltip-translated">{subspec_trans}</div>
                       <div class="tooltip-separator">─────────────────────</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
        else:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">❌ 禁用此配置项</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
    elif '=' in processed_subspec and '#' in processed_subspec:
        # 处理数值约束
        if 'extract' in processed_subspec:
            if subspec_trans:
                return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                           <div class="tooltip-simple">🌐 IP地址/网络前缀配置</div>
                           <div class="tooltip-detail">指定特定的IP地址或网络范围</div>
                           <div class="tooltip-translated">{subspec_trans}</div>
                           <div class="tooltip-separator">─────────────────────</div>
                           <div class="tooltip-formula">{processed_subspec}</div>'''
            else:
                return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                           <div class="tooltip-simple">🌐 IP地址/网络前缀配置</div>
                           <div class="tooltip-detail">指定特定的IP地址或网络范围</div>
                           <div class="tooltip-formula">{processed_subspec}</div>'''
        else:
            if subspec_trans:
                return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                           <div class="tooltip-simple">🔢 数值配置约束</div>
                           <div class="tooltip-detail">设置特定的数值参数</div>
                           <div class="tooltip-translated">{subspec_trans}</div>
                           <div class="tooltip-separator">─────────────────────</div>
                           <div class="tooltip-formula">{processed_subspec}</div>'''
            else:
                return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                           <div class="tooltip-simple">🔢 数值配置约束</div>
                           <div class="tooltip-detail">设置特定的数值参数</div>
                           <div class="tooltip-formula">{processed_subspec}</div>'''
    elif '>=' in processed_subspec or '<=' in processed_subspec:
        if subspec_trans:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">📏 范围约束条件</div>
                       <div class="tooltip-detail">设置数值范围限制</div>
                       <div class="tooltip-translated">{subspec_trans}</div>
                       <div class="tooltip-separator">─────────────────────</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
        else:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">📏 范围约束条件</div>
                       <div class="tooltip-detail">设置数值范围限制</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
    elif 'not' in processed_subspec.lower():
        if subspec_trans:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">🚫 排除条件</div>
                       <div class="tooltip-detail">排除特定的配置项</div>
                       <div class="tooltip-translated">{subspec_trans}</div>
                       <div class="tooltip-separator">─────────────────────</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
        else:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">🚫 排除条件</div>
                       <div class="tooltip-detail">排除特定的配置项</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
    else:
        if subspec_trans:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">⚙️ 配置约束条件</div>
                       <div class="tooltip-detail">应用特定的配置规则</div>
                       <div class="tooltip-translated">{subspec_trans}</div>
                       <div class="tooltip-separator">─────────────────────</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''
        else:
            return f'''<div class="tooltip-header">{subspec_type} 配置字段: {field_name}</div>
                       <div class="tooltip-simple">⚙️ 配置约束条件</div>
                       <div class="tooltip-detail">应用特定的配置规则</div>
                       <div class="tooltip-formula">{processed_subspec}</div>'''

def process_line_number(line):
    """处理行号，将行号部分用深灰色样式包裹"""
    # 匹配行号模式：开头可能有空格，然后是数字，再是至少一个空格，然后是内容
    # 例如：` 1 !!!` 或 `10 route-map`
    pattern = r'^(\s*)(\d+)(\s+)(.*)$'
    match = re.match(pattern, line)
    if match:
        leading_spaces = match.group(1)
        line_number = match.group(2)
        trailing_spaces = match.group(3)
        content = match.group(4)
        return f'{leading_spaces}<span class="config-line-number">{line_number}</span>{trailing_spaces}{content}'
    return line

def process_config_line(line, subspec_data, config_subspec_data, line_subspec_data, line_subspec_names, show_subspecs=True, categorized_terms=None, config_subspec_trans_data=None, line_subspec_trans_data=None, language='en'):
    """处理单行配置，将[name](subspec_name)转换为可交互的HTML，并支持分类高亮"""
    # 首先处理行号
    processed_line = process_line_number(line)
    
    if not show_subspecs:
        # 不显示subspec，直接移除标注
        pattern = r'\[([^\]]+)\]\([^)]+\)'
        processed_line = re.sub(pattern, r'\1', processed_line)
    else:
        # 使用正则表达式匹配 [name](subspec_name) 模式
        pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        
        def replace_match(match):
            field_name = match.group(1)
            subspec_name = match.group(2)
            # 检查 subspec_name 是否真的存在于 subspec_data 中
            is_missing = subspec_name not in subspec_data
            if is_missing:
                subspec = 'empty'
            else:
                subspec = subspec_data.get(subspec_name, 'empty')
            
            formatted_subspec = format_subspec_for_display(subspec, subspec_name, config_subspec_data, line_subspec_data, config_subspec_trans_data, line_subspec_trans_data, is_missing=is_missing, language=language)
            
            # 判断是 line-level 还是 config-level subspec
            css_class = "config-field"
            is_empty = (subspec == 'empty')
            
            if subspec_name in line_subspec_names:
                css_class += " line-level"
            
            if is_missing:
                # 如果 subspec 根本不存在，使用 missing-subspec 类（亮黄色）
                css_class += " missing-subspec"
            elif is_empty:
                # 如果 subspec 存在但值为 'empty'，使用 empty-subspec 类
                css_class += " empty-subspec"
            
            return f'<span class="{css_class}" data-subspec="{formatted_subspec}" data-subspec-name="{subspec_name}">{field_name}</span>'
        
        processed_line = re.sub(pattern, replace_match, processed_line)
    
    # 应用分类高亮
    if categorized_terms:
        processed_line = apply_categorized_highlighting(processed_line, categorized_terms)
    
    return processed_line

def process_config_references(text):
    """处理配置引用，将 @@ R1 Configuration 2,4 @@ 或 @@ Configuration 2,4 @@ 转换为可交互元素"""
    import re
    
    # 支持两种格式：
    # 1. @@ R1 Configuration 2,4 @@ (带路由器前缀)
    # 2. @@ Configuration 2,4 @@ (不带路由器前缀)
    
    # 先处理带路由器前缀的
    pattern_with_router = r'@@\s+(R\d+)\s+Configuration\s+(\d+(?:,\d+)*)\s+@@'
    def replace_with_router(match):
        router = match.group(1)  # R1
        line_range = match.group(2)  # 2,4
        return f'<span class="config-reference" data-router="{router}" data-lines="{line_range}" data-original-title="Click to highlight {router} Configuration lines {line_range}">@@ {router} Configuration {line_range} @@</span>'
    
    text = re.sub(pattern_with_router, replace_with_router, text)
    
    # 再处理不带路由器前缀的
    pattern_without_router = r'@@\s+Configuration\s+(\d+(?:,\d+)*)\s+@@'
    def replace_without_router(match):
        line_range = match.group(1)  # 2,4
        return f'<span class="config-reference" data-lines="{line_range}" data-original-title="Click to highlight Configuration lines {line_range}">@@ Configuration {line_range} @@</span>'
    
    text = re.sub(pattern_without_router, replace_without_router, text)
    
    return text

def parse_questions(question_content):
    """解析问题内容，支持新的格式"""
    lines = question_content.split('\n')
    question_text = ""
    options = []
    note_content = None
    current_option_num = None
    current_option_correct = None
    current_diff = []
    in_note_block = False
    note_lines = []
    
    for line in lines:
        original_line = line
        line = line.strip()
        if not line:
            if in_note_block:
                note_lines.append('')
            continue
            
        if line.startswith('```note'):
            # 开始 note 代码块
            in_note_block = True
            note_lines = []
        elif line.startswith('```') and in_note_block:
            # note 代码块结束
            in_note_block = False
            if note_lines:
                note_content = '\n'.join(note_lines)
        elif in_note_block:
            # note 内容
            note_lines.append(original_line)  # 保留原始格式（包括缩进和换行）
        elif line.startswith('option') and ':' in line:
            # 处理选项
            if current_option_num is not None:
                # 保存前一个选项
                option_text = '\n'.join(current_diff)
                # 处理配置引用
                option_text = process_config_references(option_text)
                option_id = f"option{current_option_num}"
                option_value = f"option_{current_option_num}"
                options.append({
                        'id': option_id,
                        'value': option_value,
                        'text': option_text,
                        'correct': current_option_correct
                    })
            
            # 解析新选项
            parts = line.split(':')
            if len(parts) >= 2:
                option_num = parts[0].strip()
                is_correct = '[yes]' in parts[1]
                current_option_num = option_num
                current_option_correct = is_correct
                current_diff = []
        elif line.startswith('```diff'):
            current_diff = []
        elif line.startswith('```'):
            # diff块结束
            pass
        elif line.startswith('-') or line.startswith('+'):
            # diff内容
            current_diff.append(line)
        elif not line.startswith('option') and not line.startswith('```') and not in_note_block:
            # 问题描述
            if not question_text:
                question_text = line
    
    # 处理最后一个选项
    if current_option_num is not None:
        option_text = '\n'.join(current_diff)
        # 处理配置引用
        option_text = process_config_references(option_text)
        option_id = f"option{current_option_num}"
        option_value = f"option_{current_option_num}"
        options.append({
            'id': option_id,
            'value': option_value,
            'text': option_text,
            'correct': current_option_correct
        })
    
    return question_text, options, note_content

def load_question_data(question_num, language='en'):
    """加载指定问题的数据"""
    # 映射索引到实际的文件夹名称
    # question_num 0 对应 question0 (warm-up/qualification testing)
    # question_num 1-4 对应 question1-question4
    if question_num == 0:
        question_dir = "question0"
    elif question_num == 1:
        question_dir = "question1"
    elif question_num == 2:
        question_dir = "question2"
    elif question_num == 3:
        question_dir = "question3"
    elif question_num == 4:
        question_dir = "question4"
    else:
        question_dir = f"question{question_num}"
    
    if language == 'zh':
        spec_content = read_file_content(f'{question_dir}/2_specification_zh.txt')
        question_content = read_file_content(f'{question_dir}/4_question_zh.txt')
        answer_content = read_answer_content(f'{question_dir}/9_answer_zh.txt')
    else:
        spec_content = read_file_content(f'{question_dir}/2_specification.txt')
        question_content = read_file_content(f'{question_dir}/4_question.txt')
        answer_content = read_answer_content(f'{question_dir}/9_answer.txt')
    
    # 收集所有配置文件
    config_contents = []
    routers = ['r1', 'r2', 'r3']
    for router in routers:
        config_file = f'{question_dir}/3_configuration_{router}.txt'
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if content:  # 只添加非空内容
                    # 只移除文件末尾的空白字符（换行符等），保留开头和每行的原始格式
                    content = content.rstrip()
                    # 移除文件开头的空行（完全空白的行），但保留每行的行首空格
                    lines = content.split('\n')
                    # 从开头移除完全空白的行
                    while lines and lines[0].strip() == '':
                        lines.pop(0)
                    content = '\n'.join(lines)
                    content = content.replace('`', '\\`')
                    config_contents.append((router.upper(), content))
        except FileNotFoundError:
            continue
    
    if not config_contents:
        print(f"警告: 问题{question_num}没有找到配置文件")
        config_content = ""
    else:
        # 为每个路由器配置添加分隔符，保持独立
        config_parts = []
        for router, content in config_contents:
            # 只移除末尾的空白行，保留开头和每行的原始格式（包括行首空格）
            lines = content.split('\n')
            # 从末尾移除完全空白的行
            while lines and lines[-1].strip() == '':
                lines.pop()
            content_trimmed = '\n'.join(lines)
            # 移除开头的 <br>&nbsp; 标签（如果有的话）
            if content_trimmed.startswith('<br>&nbsp;'):
                content_trimmed = content_trimmed.replace('<br>&nbsp;', ' ', 1)  # 只替换第一个
            # 标题后直接接内容，不要空行
            config_parts.append(f"=== {router} CONFIG ===\\n{content_trimmed}")
        # 多个路由器配置之间用两个换行分隔
        config_content = "\\n\\n".join(config_parts)
    
    # question0 (warm-up) 不提供 subspecs
    if question_num == 0:
        config_subspec_content = ""
        line_subspec_content = ""
        config_subspec_trans_content = ""
        line_subspec_trans_content = ""
    else:
        config_subspec_content = read_file_content(f'{question_dir}/3_field_level_subspecs.txt')
        line_subspec_content = read_file_content(f'{question_dir}/3_line_level_subspecs.txt')
        if language == 'zh':
            config_subspec_trans_content = highlight_translation_text(read_file_content(f'{question_dir}/3_field_level_subspecs_trans_zh.txt'))
            line_subspec_trans_content = highlight_translation_text(read_file_content(f'{question_dir}/3_line_level_subspecs_trans_zh.txt'))
        else:
            config_subspec_trans_content = highlight_translation_text(read_file_content(f'{question_dir}/3_field_level_subspecs_trans.txt'))
            line_subspec_trans_content = highlight_translation_text(read_file_content(f'{question_dir}/3_line_level_subspecs_trans.txt'))
    highlight_content = read_file_content(f'{question_dir}/3_highlight.txt')
    
    image_path = resolve_topology_image_path(question_dir, mini=False)
    image_mini_path = resolve_topology_image_path(question_dir, mini=True)
    
    return spec_content, config_content, question_content, answer_content, config_subspec_content, line_subspec_content, config_subspec_trans_content, line_subspec_trans_content, highlight_content, image_path, image_mini_path

def generate_userstudy_html():
    """生成测试HTML文件"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(
        INDEX_TEMPLATE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    
    # 介绍内容已移除
    
    # 生成HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Explainable Network Verification Test - User Study</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Times New Roman', Times, serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            font-size: 16px;
            font-weight: 525;
        }}

        .container {{
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }}

        .header {{
            text-align: center;
            margin-bottom: 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            position: relative;
        }}

        .header-controls {{
            display: none;
        }}

        .language-switcher {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
        }}

        .fixed-bar-toggle-btn {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: rgba(255, 255, 255, 0.2);
            border: 2px solid rgba(255, 255, 255, 0.3);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
            font-weight: bold;
            white-space: nowrap;
        }}

        .fixed-bar-toggle-btn:hover {{
            background: rgba(255, 255, 255, 0.3);
        }}

        .fixed-bar-toggle-btn.active {{
            background: white;
            color: #667eea;
            border-color: white;
        }}

        .fixed-bar-toggle-btn.active:hover {{
            background: white;
        }}

        .lang-btn {{
            background: rgba(255, 255, 255, 0.2);
            border: 2px solid rgba(255, 255, 255, 0.3);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
            font-weight: bold;
        }}

        .lang-btn:hover {{
            background: rgba(255, 255, 255, 0.3);
        }}

        .lang-btn.active {{
            background: white;
            color: #667eea;
            border-color: white;
        }}

        .lang-btn.active:hover {{
            background: white;
        }}

        .header h1 {{
            font-size: 2.2em;
            margin-bottom: 10px;
        }}


        .progress-bar {{
            background: white;
            margin-bottom: 30px;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }}

        .progress-info {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}

        .progress-text {{
            font-size: 1.1em;
            font-weight: bold;
            color: #667eea;
        }}

        .timer {{
            font-size: 1.1em;
            font-weight: bold;
            color: #e74c3c;
        }}

        .progress-bar-fill {{
            width: 100%;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
        }}

        .progress-bar-progress {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            border-radius: 4px;
            transition: width 0.3s ease;
        }}

        .section {{
            background: white;
            margin-bottom: 20px;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }}

        /* Four-panel layout for questions */
        .question-layout {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            grid-template-rows: auto auto;
            gap: 20px;
            margin-bottom: 30px;
        }}

        .panel-topology {{
            grid-column: 1;
            grid-row: 1;
        }}

        .panel-specification {{
            grid-column: 2;
            grid-row: 1;
        }}

        .panel-config {{
            grid-column: 1;
            grid-row: 2;
        }}

        .panel-questions {{
            grid-column: 2;
            grid-row: 2;
        }}

        /* Responsive adjustments */
        @media (max-width: 1200px) {{
            .question-layout {{
                grid-template-columns: 1fr;
                grid-template-rows: auto auto auto auto;
            }}
            
            .panel-topology {{
                grid-column: 1;
                grid-row: 1;
            }}
            
            .panel-specification {{
                grid-column: 1;
                grid-row: 2;
            }}
            
            .panel-config {{
                grid-column: 1;
                grid-row: 3;
            }}
            
            .panel-questions {{
                grid-column: 1;
                grid-row: 4;
            }}
        }}

        .section h2 {{
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.5em;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }}

        .topology-image {{
            text-align: center;
            margin: 10px 0;
            overflow: visible;
        }}

        .topology-image img {{
            width: 100%;
            max-width: 100%;
            height: auto;
            border-radius: 0;
            display: block;
            margin: 0 auto;
        }}

        @media (prefers-color-scheme: dark) {{
            .topology-image,
            .fixed-topology-mini {{
                background: #1e1e1e;
                border-radius: 6px;
                padding: 6px;
            }}

            .topology-image img,
            .fixed-topology-mini img {{
                filter: invert(0.92) hue-rotate(180deg);
            }}
        }}

        .specification {{
            background: #f8f9fa;
            padding: 20px;
            border-left: 4px solid #667eea;
            border-radius: 5px;
            font-size: 1.1em;
            line-height: 1.7;
        }}

        .specification-text {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
        }}

        /* Fixed top bar for topology and specification when scrolled */
        .fixed-top-bar {{
            position: fixed;
            top: 0;
            left: 50%;
            right: 0;
            background: white;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
            z-index: 999;
            opacity: 0;
            visibility: hidden;
            transform: translateY(-100%);
            transition: opacity 0.3s ease, transform 0.3s ease, visibility 0.3s ease;
            padding: 8px 20px;
            border-bottom: 2px solid #667eea;
            border-left: 2px solid #667eea;
        }}

        .fixed-top-bar.visible {{
            opacity: 1;
            visibility: visible;
            transform: translateY(0);
        }}

        .fixed-top-bar.hidden {{
            display: none;
        }}

        .fixed-top-bar-content {{
            max-width: 100%;
            width: 100%;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
            align-items: center;
            justify-content: center;
        }}

        .fixed-topology-mini {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 0;
            max-width: 100%;
            width: 100%;
        }}

        .fixed-topology-mini img {{
            width: 100%;
            max-width: 100%;
            height: auto;
            border-radius: 0;
            box-shadow: none;
            object-fit: contain;
        }}

        .fixed-spec-first-line {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
            max-width: 800px;
            width: 100%;
            word-wrap: break-word;
            overflow-wrap: break-word;
            white-space: normal;
            hyphens: auto;
            text-align: left;
        }}

        .fixed-spec-first-line b {{
            color: #667eea;
            font-weight: bold;
        }}

        .fixed-question-instruction {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
            max-width: 800px;
            width: 100%;
            word-wrap: break-word;
            overflow-wrap: break-word;
            white-space: normal;
            hyphens: auto;
            text-align: left;
            margin-top: 4px;
        }}

        .fixed-question-instruction b {{
            color: #667eea;
            font-weight: bold;
        }}

        /* 如果 b 标签内已经有颜色样式（通过 style 属性），则不覆盖 */
        .fixed-question-instruction b[style*="color"] {{
            color: inherit;
        }}

        @media (max-width: 1200px) {{
            .fixed-top-bar {{
                left: 0;
                right: 0;
            }}
            
            .fixed-top-bar-content {{
                max-width: 100%;
                gap: 8px;
            }}
            
            .fixed-topology-mini img {{
                max-width: 100%;
            }}
            
            .fixed-spec-first-line {{
                max-width: 600px;
                font-size: 16px;
                line-height: 1.4;
            }}
            
            .fixed-question-instruction {{
                max-width: 600px;
                font-size: 16px;
                line-height: 1.4;
            }}
        }}

        @media (max-width: 768px) {{
            .fixed-top-bar {{
                padding: 6px 12px;
                left: 0;
                right: 0;
            }}
            
            .fixed-top-bar-content {{
                gap: 6px;
            }}
            
            .fixed-topology-mini img {{
                max-width: 100%;
            }}
            
            .fixed-spec-first-line {{
                max-width: 100%;
                font-size: 15px;
                line-height: 1.3;
            }}
            
            .fixed-question-instruction {{
                max-width: 100%;
                font-size: 15px;
                line-height: 1.3;
            }}
        }}










        /* Collapsible sections */










        .config-container {{
            background: white;
            color: #222;
            padding: 20px;
            border-radius: 8px;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525; /* Default for Safari/Firefox */
            line-height: 1.5;
            overflow-x: auto;
            border: 1px solid #e9ecef;
        }}
        
        /* Chrome/Edge/Other specific font-weight for config container */
        .browser-chrome .config-container,
        .browser-edge .config-container,
        .browser-other .config-container {{
            font-weight: 600 !important;
        }}

        .config-line {{
            margin: 5px 0;
            position: relative;
            white-space: pre;
            display: block;
        }}

        .config-field {{
            background: #B8DCF9;
            color: #000;
            padding: 1px 2px;
            border-radius: 2px;
            cursor: pointer;
            transition: background-color 0.3s ease, box-shadow 0.3s ease;
            position: relative;
            font-weight: 525; /* Default for Safari/Firefox - 与配置文本相同粗细 */
            display: inline; /* 确保是 inline 元素，不增加额外宽度 */
            box-sizing: content-box; /* 确保 padding 不影响布局计算 */
        }}
        
        /* Chrome/Edge/Other specific font-weight */
        .browser-chrome .config-field,
        .browser-edge .config-field,
        .browser-other .config-field {{
            font-weight: 600 !important;
        }}

        /* 所有 config-field 悬停时统一为灰色 */
        .config-field:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }}

        /* Config field showing tooltip - 灰色高亮显示正在显示 tooltip 的字段 */
        .config-field-showing-tooltip {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        .config-field.line-level.config-field-showing-tooltip {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 确保在 diff 内容中，显示 tooltip 的 config-field 也使用白色字体 */
        .diff-removed .config-field-showing-tooltip,
        .diff-added .config-field-showing-tooltip {{
            color: #fff !important;
        }}

        .diff-removed .config-field-showing-tooltip *,
        .diff-added .config-field-showing-tooltip * {{
            color: #fff !important;
        }}

        /* Line-level subspec 淡紫色高亮样式 */
        .config-field.line-level {{
            background: #E2C0E8;
            color: #000;
            font-weight: 525; /* Default for Safari/Firefox - 与配置文本相同粗细 */
            padding: 1px 2px; /* 与 config-field 保持一致 */
            border-radius: 2px;
        }}

        /* Missing subspec (not found in subspec files) 亮黄色 */
        .config-field.missing-subspec {{
            background: rgba(255, 255, 0, 0.85);
        }}

        /* Missing line-level subspec 亮黄色 */
        .config-field.line-level.missing-subspec {{
            background: rgba(255, 255, 0, 0.85);
        }}

        /* Empty field-level subspec 更淡的蓝色 */
        .config-field.empty-subspec {{
            background: rgba(220, 240, 255, 0.5);
        }}

        /* Empty line-level subspec 更淡的紫色 */
        .config-field.line-level.empty-subspec {{
            background: rgba(240, 220, 250, 0.5);
        }}

        /* Chrome/Edge/Other specific font-weight for line-level */
        .browser-chrome .config-field.line-level,
        .browser-edge .config-field.line-level,
        .browser-other .config-field.line-level {{
            font-weight: 600 !important;
        }}

        /* 所有 config-field 悬停时统一为灰色 */
        .config-field.line-level:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }}

        /* Missing subspec hover 效果 - 统一为灰色 */
        .config-field.missing-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* Missing line-level subspec hover 效果 - 统一为灰色 */
        .config-field.line-level.missing-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* Empty field-level subspec hover 效果 - 统一为灰色 */
        .config-field.empty-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* Empty line-level subspec hover 效果 - 统一为灰色 */
        .config-field.line-level.empty-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 确保 diff 区域中的 config-field 悬停时也是灰色 */
        .diff-added .config-field:hover,
        .diff-removed .config-field:hover,
        .config-line-highlighted .config-field:hover,
        .config-line-highlighted-added .config-field:hover,
        .config-line-highlighted-removed .config-field:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 确保选项区域中的 config-field 悬停时也是灰色 */
        .option-diff-content .config-field:hover,
        .option-text-content .config-field:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 空的 symbolic spacer，只增加宽度，不设置背景颜色 */
        .config-field-empty-spacer {{
            padding: 1px 2px;
            border-radius: 2px;
            display: inline;
            box-sizing: content-box;
        }}

        .highlight-term {{
            background: #ffeb3b;
            color: #333;
            padding: 1px 3px;
            border-radius: 2px;
            font-weight: 525; /* Default for Safari/Firefox */
            box-shadow: 0 1px 2px rgba(255, 235, 59, 0.3);
        }}

        /* 分类高亮样式 */
        .highlight-route-map {{
            color: #e65100 !important;
            font-weight: 600 !important; /* Default for Safari/Firefox */
        }}

        .highlight-prefix-list {{
            color: #1565c0 !important;
            font-weight: 600 !important; /* Default for Safari/Firefox */
        }}

        .highlight-community-list {{
            color: #2e7d32 !important;
            font-weight: 600 !important; /* Default for Safari/Firefox */
        }}

        .highlight-number {{
            color: #8B4513 !important; /* 棕色 */
            font-weight: 525 !important; /* Default for Safari/Firefox */
            background: rgba(139, 69, 19, 0.05); /* 更淡的棕色半透明背景 */
            padding: 1px 2px;
            border-radius: 2px;
        }}
        
        /* Chrome/Edge/Other specific font-weight for highlights */
        .browser-chrome .highlight-term,
        .browser-edge .highlight-term,
        .browser-other .highlight-term {{
            font-weight: 600 !important;
        }}
        
        .browser-chrome .highlight-route-map,
        .browser-edge .highlight-route-map,
        .browser-other .highlight-route-map,
        .browser-chrome .highlight-prefix-list,
        .browser-edge .highlight-prefix-list,
        .browser-other .highlight-prefix-list,
        .browser-chrome .highlight-community-list,
        .browser-edge .highlight-community-list,
        .browser-other .highlight-community-list {{
            font-weight: 700 !important;
        }}
        
        .browser-chrome .highlight-number,
        .browser-edge .highlight-number,
        .browser-other .highlight-number {{
            font-weight: 600 !important;
        }}

        /* 配置元素图例 */
        .config-legend {{
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
            font-size: 14px;
        }}

        .config-legend h4 {{
            margin: 0 0 10px 0;
            color: #667eea;
            font-size: 16px;
        }}

        .legend-items {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .legend-color {{
            width: 16px;
            height: 16px;
            border-radius: 3px;
            border: 1px solid #ddd;
        }}

        .legend-color.route-map {{
            background: transparent;
            border: 2px solid #e65100;
        }}

        .legend-color.prefix-list {{
            background: transparent;
            border: 2px solid #1565c0;
        }}

        .legend-color.community-list {{
            background: transparent;
            border: 2px solid #2e7d32;
        }}

        .legend-color.other {{
            background: #ffeb3b;
        }}

        .legend-color.config-level {{
            background: #B8DCF9;
        }}

        .legend-color.line-level {{
            background: #E2C0E8;
        }}


        .legend-color.number {{
            background: #1976d2;
        }}

        .tooltip {{
            position: fixed;
            background: #eeeeee;
            color: #9e9e9e;
            padding: 16px 20px;
            border-radius: 10px;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 14px;
            font-weight: 600;
            max-width: 550px;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            word-wrap: break-word;
            line-height: 1.5;
            border: 1px solid #9e9e9e;
            transform: translateZ(0);
            backface-visibility: hidden;
        }}

        .tooltip-header {{
            font-weight: bold;
            color: #000 !important;
            margin-bottom: 8px;
            font-size: 14px;
            border-bottom: 1px solid #9e9e9e;
            padding-bottom: 6px;
        }}

        .tooltip-content {{
            font-family: 'Courier New', monospace;
            background: rgba(0, 0, 0, 0.05);
            padding: 10px;
            border-radius: 6px;
            margin-top: 8px;
            border-left: 3px solid #9e9e9e;
        }}

        .tooltip-simple {{
            color: #000 !important;
            font-style: italic;
        }}

        .tooltip-type {{
            color: #9e9e9e;
            font-size: 12px;
            margin: 4px 0;
            font-style: italic;
        }}

        .tooltip-detail {{
            color: #000 !important;
            font-size: 11px;
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px solid #9e9e9e;
        }}

        .tooltip-formula {{
            color: #9e9e9e;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            margin-top: 8px;
            padding-top: 8px;
        }}

        .tooltip-translated {{
            color: #000 !important;
            font-size: 13px;
            margin-top: 6px;
            line-height: 1.4;
        }}

        .tooltip .tooltip-translated .highlight-action,
        .tooltip-translated .highlight-action {{
            color: #0080ff !important;
            font-weight: 900 !important;
        }}

        .tooltip .tooltip-translated .highlight-network,
        .tooltip-translated .highlight-network {{
            color: #ff8800 !important;
            font-weight: 900 !important;
        }}

        .tooltip .tooltip-translated .highlight-range,
        .tooltip-translated .highlight-range {{
            color: #16a34a !important;
            font-weight: 900 !important;
        }}

        .tooltip-separator {{
            color: #999;
            margin: 8px 0;
            font-size: 12px;
        }}

        .tooltip.show {{
            opacity: 1;
            visibility: visible;
        }}

        .tooltip::after {{
            content: '';
            position: absolute;
            top: var(--arrow-top, 100%);
            left: var(--arrow-left, 20px);
            border-width: 6px;
            border-style: solid;
            border-color: var(--arrow-border, #9e9e9e transparent transparent transparent);
            transform: translateX(-50%);
        }}

        .questions {{
            background: transparent;
            padding: 20px;
            border-radius: 8px;
        }}

        .question-text {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            margin-bottom: 20px;
            line-height: 1.4;
            color: #333;
        }}

        .question-instruction {{
            background: #e3f2fd;
            border: 2px solid #2196f3;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 20px;
            font-size: 1.05em;
            color: #1976d2;
            text-align: left;
        }}
        
        /* Note 样式 - 淡灰色 */
        .question-instruction.note-instruction {{
            background: #f5f5f5;
            border: 1px solid #9e9e9e;
            color: #666;
        }}

        .question-instruction .instruction-line {{
            display: block;
            margin-bottom: 4px;
        }}

        .question-instruction .instruction-line:last-child {{
            margin-bottom: 0;
        }}

        .user-notes {{
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}

        .user-notes h4 {{
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.2em;
            font-weight: bold;
        }}

        .user-notes textarea {{
            width: 100%;
            min-height: 120px;
            height: 120px;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-family: 'Times New Roman', Times, serif;
            font-size: 16px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
            resize: vertical;
            box-sizing: border-box;
        }}

        .user-notes textarea:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.1);
        }}

        .question-options {{
            margin-top: 20px;
        }}


        .option-item {{
            display: flex;
            align-items: center;
            margin: 15px 0;
            padding: 15px;
            background: white;
            border-radius: 8px;
            border: 2px solid #e9ecef;
            transition: all 0.3s ease;
        }}

        .option-item input[type="checkbox"] {{
            margin-right: 15px;
            transform: scale(1.2);
            accent-color: #667eea;
            cursor: pointer;
        }}

        .option-item input[type="checkbox"]:hover {{
            transform: scale(1.3);
        }}

        .option-item .option-content-wrapper {{
            flex: 1;
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
        }}

        .btn-container {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 30px;
            width: 100%;
        }}

        .btn-container .btn {{
            width: 100%;
            flex: 1;
        }}

        .start-screen .btn-container {{
            max-width: 900px;
            margin-left: auto;
            margin-right: auto;
        }}

        .btn {{
            padding: 15px 30px;
            font-size: 1.1em;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            border: none;
            font-weight: bold;
        }}

        .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}

        .btn-primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}

        .btn-secondary {{
            background: #6c757d;
            color: white;
        }}

        .btn-secondary:hover {{
            background: #5a6268;
            transform: translateY(-2px);
        }}

        .btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none !important;
        }}

        .modal {{
            display: none;
            position: fixed;
            z-index: 2000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
        }}

        .modal-content {{
            background-color: white;
            margin: 15% auto;
            padding: 30px;
            border-radius: 10px;
            width: 90%;
            max-width: 500px;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }}

        .modal h3 {{
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.5em;
        }}

        .modal p {{
            margin-bottom: 25px;
            line-height: 1.6;
        }}

        .modal-buttons {{
            display: flex;
            justify-content: center;
            gap: 15px;
        }}

        .start-screen {{
            text-align: center;
            padding: 50px 20px;
        }}

        .start-screen h2 {{
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 20px;
        }}

        .start-screen p {{
            font-size: 1.2em;
            margin-bottom: 30px;
            color: #666;
            line-height: 1.8;
            font-weight: 525;
        }}

        .start-info {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin: 30px auto;
            max-width: 900px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            text-align: left;
            font-weight: 525;
        }}

        .start-info h3 {{
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.3em;
        }}

        .start-info ul {{
            list-style: none;
            padding: 0;
        }}

        .start-info li {{
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
            display: flex;
            align-items: center;
        }}

        .start-info li:last-child {{
            border-bottom: none;
        }}

        .start-info li::before {{
            content: "✓";
            color: #27ae60;
            font-weight: bold;
            margin-right: 10px;
            font-size: 1.2em;
        }}

        /* Group info styles */
        .group-info {{
            margin: 20px 0;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 12px;
            border: 2px solid #e9ecef;
        }}

        .group-info-top {{
            margin: 20px 0 30px 0;
            text-align: center;
        }}

        .group-assignment {{
            text-align: center;
        }}

        .group-assignment h3 {{
            margin: 0 0 20px 0;
            color: #495057;
            font-size: 22px;
            font-weight: 600;
            line-height: 1.4;
        }}

        .group-badge {{
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 16px;
            color: white;
            margin: 0 5px;
        }}

        .group-badge.group-a {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}

        .group-badge.group-b {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }}

        .subspec-info {{
            margin-top: 20px;
            text-align: center;
            font-size: 20px;
            font-weight: 600;
            color: #333;
            line-height: 1.6;
        }}

        .subspec-info strong {{
            color: #495057;
            font-weight: 700;
            font-size: 22px;
        }}

        .subspec-with {{
            color: #28a745;
            font-weight: 600;
            font-size: 18px;
        }}

        .subspec-without {{
            color: #dc3545;
            font-weight: 600;
            font-size: 18px;
        }}

        .qualification-note {{
            margin-top: 10px;
            font-size: 22px;
            color: #6c757d;
            font-style: italic;
        }}

        /* 介绍页面样式已移除 */

        /* 可折叠配置区块样式 */
        .config-collapsible {{
            margin: 5px 0;
            border: 1px solid #9e9e9e;
            border-radius: 8px;
            overflow: hidden;
        }}

        .config-header {{
            background: #f8f9fa;
            padding: 8px 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            transition: background-color 0.3s ease;
            border-bottom: 1px solid #9e9e9e;
        }}

        .config-header:hover {{
            background: #e9ecef;
        }}

        .config-caret {{
            margin-right: 10px;
            transition: transform 0.3s ease;
            font-size: 14px;
            color: #666;
        }}

        .config-caret.expanded {{
            transform: rotate(90deg);
        }}

        .config-title {{
            font-weight: bold;
            font-size: 1.1em;
            color: #333;
        }}

        .config-content {{
            background: white;
            padding: 15px 10px;
            display: none;
            border-top: 1px solid #9e9e9e;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525; /* Default for Safari/Firefox */
            line-height: 1.5;
            color: #222;
            white-space: pre-wrap;
            word-wrap: break-word;
            overflow-wrap: break-word;
            max-width: 100%;
            overflow-x: auto;
            text-align: left;
        }}
        
        /* Chrome/Edge/Other specific font-weight for config content */
        .browser-chrome .config-content,
        .browser-edge .config-content,
        .browser-other .config-content {{
            font-weight: 600 !important;
        }}

        .config-content.expanded {{
            display: block;
        }}

        .config-text {{
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525; /* Default for Safari/Firefox */
            line-height: 1.5;
            color: #222;
            white-space: pre-wrap;
            word-wrap: break-word;
            overflow-wrap: break-word;
            background: white;
            padding: 15px;
            border-radius: 4px;
            border: 1px solid #9e9e9e;
            max-width: 100%;
            overflow-x: auto;
        }}
        
        /* Chrome/Edge/Other specific font-weight for config text */
        .browser-chrome .config-text,
        .browser-edge .config-text,
        .browser-other .config-text {{
            font-weight: 600 !important;
        }}

        /* Diff格式颜色高亮 */
        .diff-line {{
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525; /* Default for Safari/Firefox - 统一使用 config-font 样式 */
            line-height: 1.5;
            white-space: pre-wrap;
        }}
        
        /* Chrome/Edge/Other specific font-weight for diff line */
        .browser-chrome .diff-line,
        .browser-edge .diff-line,
        .browser-other .diff-line {{
            font-weight: 600 !important;
        }}

        .diff-removed {{
            color: #C73E3E !important;
        }}

        .diff-removed * {{
            color: #C73E3E !important;
        }}

        .diff-added {{
            color: #388E3C !important;
        }}

        .diff-added * {{
            color: #388E3C !important;
        }}

        /* 在 diff 背景下加深子规约颜色（仅配置显示区域） */
        /* 必须在 .diff-added * 和 .diff-removed * 之后定义，以确保优先级正确 */
        /* 深色子规约（.subspec-with）在 diff 背景下加深，保持深绿色调，与浅色有明显区分 */
        .diff-added .subspec-with,
        .diff-removed .subspec-with,
        .config-line-highlighted .subspec-with,
        .config-line-highlighted-added .subspec-with,
        .config-line-highlighted-removed .subspec-with {{
            color: #155724 !important; /* 从 #28a745 明显加深，深绿色，与浅色子规约有明显区分 */
            font-weight: 700 !important; /* 增加字体粗细以增强对比 */
        }}

        /* 浅色子规约（.subspec-without）在 diff 背景下极深加深，特别强调，与深色有明显区分 */
        .diff-added .subspec-without,
        .diff-removed .subspec-without,
        .config-line-highlighted .subspec-without,
        .config-line-highlighted-added .subspec-without,
        .config-line-highlighted-removed .subspec-without {{
            color: #721c24 !important; /* 从 #dc3545 极深加深，深红色，与深绿色有明显区分 */
            font-weight: 700 !important; /* 增加字体粗细以增强对比 */
        }}

        /* 排除选项框中的子规约，保持原色 */
        .option-diff-content .diff-added .subspec-with,
        .option-diff-content .diff-removed .subspec-with,
        .option-diff-content .config-line-highlighted .subspec-with,
        .option-diff-content .config-line-highlighted-added .subspec-with,
        .option-diff-content .config-line-highlighted-removed .subspec-with {{
            color: #28a745 !important; /* 恢复原色 */
            font-weight: 600 !important; /* 恢复原字体粗细 */
        }}

        .option-diff-content .diff-added .subspec-without,
        .option-diff-content .diff-removed .subspec-without,
        .option-diff-content .config-line-highlighted .subspec-without,
        .option-diff-content .config-line-highlighted-added .subspec-without,
        .option-diff-content .config-line-highlighted-removed .subspec-without {{
            color: #dc3545 !important; /* 恢复原色 */
            font-weight: 600 !important; /* 恢复原字体粗细 */
        }}

        /* 在 diff-added 和 diff-removed 背景下加深子规约颜色 */
        /* Field-level subspec 在 diff 背景下加深 */
        .diff-added .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .diff-removed .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .config-line-highlighted .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .config-line-highlighted-added .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .config-line-highlighted-removed .config-field:not(.line-level):not(.empty-subspec):not(:hover) {{
            background: #8FC5E8 !important; /* 从 #B8DCF9 加深 */
        }}

        /* Line-level subspec 在 diff 背景下加深 */
        .diff-added .config-field.line-level:not(.empty-subspec):not(:hover),
        .diff-removed .config-field.line-level:not(.empty-subspec):not(:hover),
        .config-line-highlighted .config-field.line-level:not(.empty-subspec):not(:hover),
        .config-line-highlighted-added .config-field.line-level:not(.empty-subspec):not(:hover),
        .config-line-highlighted-removed .config-field.line-level:not(.empty-subspec):not(:hover) {{
            background: #C99DD4 !important; /* 从 #E2C0E8 加深 */
        }}

        /* Empty field-level subspec 在 diff 背景下明显加深（但仍保持浅色以区分） */
        .diff-added .config-field.empty-subspec:not(.line-level):not(:hover),
        .diff-removed .config-field.empty-subspec:not(.line-level):not(:hover),
        .config-line-highlighted .config-field.empty-subspec:not(.line-level):not(:hover),
        .config-line-highlighted-added .config-field.empty-subspec:not(.line-level):not(:hover),
        .config-line-highlighted-removed .config-field.empty-subspec:not(.line-level):not(:hover) {{
            background: rgba(180, 220, 255, 0.75) !important; /* 从 rgba(220, 240, 255, 0.5) 加深 */
        }}

        /* Empty line-level subspec 在 diff 背景下明显加深（但仍保持浅色以区分） */
        .diff-added .config-field.line-level.empty-subspec:not(:hover),
        .diff-removed .config-field.line-level.empty-subspec:not(:hover),
        .config-line-highlighted .config-field.line-level.empty-subspec:not(:hover),
        .config-line-highlighted-added .config-field.line-level.empty-subspec:not(:hover),
        .config-line-highlighted-removed .config-field.line-level.empty-subspec:not(:hover) {{
            background: rgba(220, 200, 240, 0.75) !important; /* 从 rgba(240, 220, 250, 0.5) 加深 */
        }}

        /* 排除选项框中的子规约，保持原色 */
        .option-diff-content .diff-added .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .option-diff-content .config-line-highlighted .config-field:not(.line-level):not(.empty-subspec):not(:hover) {{
            background: #B8DCF9 !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的子规约高亮，与配置中（-）一致，使用加深的背景色 */
        .option-diff-content .diff-removed .config-field:not(.line-level):not(.empty-subspec):not(:hover) {{
            background: #8FC5E8 !important; /* 与配置中（-）一致，从 #B8DCF9 加深 */
        }}

        .option-diff-content .diff-added .config-field.line-level:not(.empty-subspec):not(:hover),
        .option-diff-content .config-line-highlighted .config-field.line-level:not(.empty-subspec):not(:hover) {{
            background: #E2C0E8 !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的 line-level 子规约高亮，与配置中（-）一致 */
        .option-diff-content .diff-removed .config-field.line-level:not(.empty-subspec):not(:hover) {{
            background: #C99DD4 !important; /* 与配置中（-）一致，从 #E2C0E8 加深 */
        }}

        .option-diff-content .diff-added .config-field.empty-subspec:not(.line-level):not(:hover),
        .option-diff-content .config-line-highlighted .config-field.empty-subspec:not(.line-level):not(:hover) {{
            background: rgba(220, 240, 255, 0.5) !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的 empty field-level 子规约高亮，与配置中（-）一致 */
        .option-diff-content .diff-removed .config-field.empty-subspec:not(.line-level):not(:hover) {{
            background: rgba(180, 220, 255, 0.75) !important; /* 与配置中（-）一致，从 rgba(220, 240, 255, 0.5) 加深 */
        }}

        .option-diff-content .diff-added .config-field.line-level.empty-subspec:not(:hover),
        .option-diff-content .config-line-highlighted .config-field.line-level.empty-subspec:not(:hover) {{
            background: rgba(240, 220, 250, 0.5) !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的 empty line-level 子规约高亮，与配置中（-）一致 */
        .option-diff-content .diff-removed .config-field.line-level.empty-subspec:not(:hover) {{
            background: rgba(220, 200, 240, 0.75) !important; /* 与配置中（-）一致，从 rgba(240, 220, 250, 0.5) 加深 */
        }}

        .diff-context {{
            color: #000;
        }}

        .diff-header {{
            background-color: #f8f9fa;
            border-left: 3px solid #007bff;
            padding-left: 8px;
            font-weight: 600;
        }}

        .diff-router {{
            color: #8b4513;
            font-weight: bold;
            background-color: #f5f5dc;
            padding: 2px 4px;
            border-radius: 3px;
        }}

        .diff-line-numbers {{
            color: #8b4513;
            font-weight: bold;
            background-color: #f5f5dc;
            padding: 2px 4px;
            border-radius: 3px;
        }}

        /* 通用配置字体样式 - 统一 Core Configuration Fragment 和 Maintenance Task */
        .config-font {{
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525; /* Default for Safari/Firefox */
            line-height: 1.5;
            color: #222;
        }}
        
        /* Chrome/Edge/Other specific font-weight for config font */
        .browser-chrome .config-font,
        .browser-edge .config-font,
        .browser-other .config-font {{
            font-weight: 600 !important;
        }}

        .option-diff-content {{
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525; /* Default for Safari/Firefox - 统一使用 config-font 样式 */
            line-height: 1.5;
            background: white;
            border: 1px solid #9e9e9e;
            border-radius: 4px;
            padding: 10px;
            margin: 5px 0;
            color: #222;
        }}
        
        /* Chrome/Edge/Other specific font-weight for option diff content */
        .browser-chrome .option-diff-content,
        .browser-edge .option-diff-content,
        .browser-other .option-diff-content {{
            font-weight: 600 !important;
        }}

        /* 配置引用样式 - 类似IDE的跳转链接 */
        .config-reference {{
            color: #0066cc;
            cursor: pointer;
            text-decoration: underline;
            text-decoration-style: dotted;
            transition: all 0.2s ease;
            font-weight: 525; /* Default for Safari/Firefox - 与配置文本相同粗细 */
        }}
        
        /* Chrome/Edge/Other specific font-weight for config reference */
        /* Chrome/Edge only supports 100-900 in steps of 100, so 525 will be rounded to 500 */
        .browser-chrome .config-reference,
        .browser-edge .config-reference,
        .browser-other .config-reference {{
            font-weight: 525 !important;
        }}

        .config-reference:hover {{
            color: #004499;
            text-decoration-style: solid;
            text-decoration-thickness: 2px;
        }}

        .config-reference:active {{
            transform: translateY(0);
            box-shadow: 0 1px 2px rgba(0, 102, 204, 0.3);
        }}

        /* 配置行号样式 - 灰色，与配置文本相同粗细，在 macOS 上也能正确显示 */
        .config-line-number {{
            color: #666;
            font-weight: normal;
        }}

        /* 配置行样式 - 增加上下间距 */
        .config-line {{
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.5 !important;
            display: block; /* 让span表现为块级元素，每行独立 */
            white-space: pre; /* 保留所有空格，包括多个连续空格 */
        }}
        

        /* 配置行高亮样式 */
        .config-line-highlighted {{
            background-color: #fff3cd !important;
            border-left: 4px solid #ffc107 !important;
            padding-left: 8px !important;
            margin: 0 !important;
            animation: highlight-pulse 0.5s ease-in-out;
        }}

        .config-line-highlighted-removed {{
            background-color: #ffebee !important;
            border-left: 4px solid #d32f2f !important;
            padding-left: 8px !important;
            margin: 0 !important;
            animation: highlight-pulse-removed 0.5s ease-in-out;
        }}

        .config-line-highlighted-added {{
            background-color: #e8f5e9 !important;
            border-left: 4px solid #388e3c !important;
            padding-left: 8px !important;
            margin: 0 !important;
        }}

        .config-line-added-display {{
            background-color: #e8f5e9 !important;
            border-left: 4px solid #388e3c !important;
            padding-left: 8px !important;
            margin: 0 !important;
            opacity: 0.9;
        }}

        @keyframes highlight-pulse {{
            0% {{ background-color: #fff3cd; }}
            50% {{ background-color: #ffeaa7; }}
            100% {{ background-color: #fff3cd; }}
        }}

        @keyframes highlight-pulse-removed {{
            0% {{ background-color: #ffebee; }}
            50% {{ background-color: #ffcdd2; }}
            100% {{ background-color: #ffebee; }}
        }}

        /* 配置区域滚动到高亮行的样式 */
        .config-section {{
            scroll-margin-top: 20px;
        }}


        .completion-screen {{
            padding: 30px 20px;
        }}

        .completion-header {{
            text-align: center;
            margin-bottom: 30px;
        }}

        .completion-header h1 {{
            color: #667eea;
            font-size: 2.2em;
            margin-bottom: 20px;
            font-weight: bold;
        }}

        .completion-layout {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
            max-width: 1600px;
            margin-left: auto;
            margin-right: auto;
            align-items: stretch;
        }}

        .completion-left-column {{
            display: flex;
            flex-direction: column;
            gap: 20px;
            height: 100%;
        }}

        .completion-right-column {{
            display: flex;
            flex-direction: column;
            gap: 20px;
            height: 100%;
        }}
        
        .completion-right-column .completion-card:last-child {{
            flex: 1;
            display: flex;
            flex-direction: column;
        }}
        
        .completion-right-column .completion-card:last-child .survey-question:last-of-type {{
            flex: 1;
            display: flex;
            flex-direction: column;
        }}
        
        .completion-right-column .completion-card:last-child .survey-question:last-of-type textarea {{
            flex: 1;
            min-height: 100px;
        }}

        .completion-description {{
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
        }}

        .completion-description h2 {{
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 20px;
            font-weight: 600;
        }}

        .completion-description p {{
            font-size: 1.1em;
            margin-bottom: 15px;
            color: #5a6c7d;
            line-height: 1.5;
            max-width: 1000px;
            margin-left: auto;
            margin-right: auto;
        }}
        
        .completion-description p:last-child {{
            margin-bottom: 0;
        }}

        .completion-text {{
            font-size: 22px !important;
            line-height: 1.4 !important;
            color: #495057 !important;
            font-weight: 600 !important;
            max-width: 1400px !important;
            margin: 0 auto !important;
            text-align: center !important;
        }}

        .completion-text strong {{
            font-weight: bold !important;
        }}
        
        .completion-text em {{
            font-style: italic !important;
            font-weight: normal !important;
            font-size: 22px !important;
            color: #6c757d !important;
            margin-top: 10px !important;
        }}

        .completion-text span {{
            color: #667eea !important;
            font-weight: bold !important;
            text-decoration: underline !important;
        }}

        .completion-card .survey-question {{
            text-align: left;
            margin-bottom: 15px;
            padding: 15px;
            background: rgba(248, 249, 250, 0.6);
            border-radius: 12px;
            transition: all 0.2s ease;
        }}

        .completion-card .survey-question:hover {{
            background: rgba(248, 249, 250, 0.9);
            /* 移除移动效果，保持专业外观 */
            transform: none;
        }}

        .completion-card .survey-question label {{
            text-align: left;
            display: block;
            margin-bottom: 12px;
            font-weight: 600;
            color: #2c3e50;
            font-size: 1.05em;
            line-height: 1.4;
        }}

        .completion-card .survey-question textarea {{
            text-align: left;
            width: 100%;
            padding: 16px;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            resize: vertical;
            min-height: 100px;
            box-sizing: border-box;
            transition: all 0.2s ease;
            background: rgba(255, 255, 255, 0.9);
        }}

        .completion-card .survey-question textarea:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            background: white;
        }}

        .completion-card table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        }}

        .completion-card table th,
        .completion-card table td {{
            padding: 16px 20px;
            text-align: left;
            border-bottom: 1px solid #e9ecef;
        }}

        .completion-card table th {{
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            font-weight: 600;
            color: #2c3e50;
            width: 35%;
            font-size: 0.95em;
            letter-spacing: 0.3px;
        }}

        .completion-card table td {{
            color: #5a6c7d;
            font-weight: 500;
            background: rgba(255, 255, 255, 0.8);
        }}

        .completion-card table tr:hover td {{
            background: rgba(102, 126, 234, 0.05);
        }}

        .completion-card table tr:last-child th,
        .completion-card table tr:last-child td {{
            border-bottom: none;
        }}

        .answer-navigation {{
            margin-top: 25px;
            text-align: center;
        }}

        .answer-navigation .btn {{
            padding: 14px 28px;
            font-size: 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
            letter-spacing: 0.5px;
        }}

        .answer-navigation .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }}

        .answer-navigation .btn:hover {{
            background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}

        /* Answer page styles */
        .answer-page {{
            display: none;
        }}

        .answer-page.active {{
            display: block;
        }}

        .answer-explanation {{
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
        }}
        .answer-explanation .explanation-content, .answer-explanation .explanation-code, .answer-slide .explanation-content {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
            white-space: pre-wrap; /* 保留空格和换行 */
        }}

        .answer-explanation h4 {{
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.2em;
            font-weight: bold;
        }}

        /* 答案解析页面的选项样式 - 保持可点击 */
        .answer-page .option-item {{
            display: flex;
            align-items: center;
            margin: 15px 0;
            padding: 15px;
            background: white;
            border-radius: 8px;
            border: 2px solid #e9ecef;
            transition: all 0.3s ease;
        }}

        .answer-page .option-item:hover {{
            border-color: #667eea;
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.1);
        }}

        .answer-page .option-item label {{
            flex: 1;
            cursor: pointer;
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
        }}

        .answer-option-checkmark {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 22px;
            height: 22px;
            margin-right: 12px;
            text-align: center;
            font-weight: bold;
            font-size: 14px;
            border-radius: 4px;
            line-height: 1;
            flex-shrink: 0;
        }}

        .answer-option-checkmark.correct {{
            background: #4caf50;
            color: white;
        }}

        .answer-option-checkmark.incorrect {{
            background: #f44336;
            color: white;
        }}

        .answer-option-checkmark.correct::before {{
            content: "✓";
            font-size: 16px;
            font-weight: 700;
            line-height: 1;
        }}

        .answer-option-checkmark.incorrect::before {{
            content: "✗";
            font-size: 16px;
            font-weight: 700;
            line-height: 1;
        }}

        .answer-navigation-controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 30px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }}

        .answer-navigation-container {{
            background: white;
            margin-bottom: 30px;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }}

        .answer-navigation-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}

        .answer-nav-buttons {{
            display: flex;
            gap: 15px;
        }}

        .answer-nav-buttons .btn {{
            min-width: 160px;
            width: 160px;
            padding: 10px 20px;
            font-size: 14px;
            font-weight: 600;
            border-radius: 6px;
            transition: all 0.3s ease;
            border: none;
            cursor: pointer;
            text-align: center;
        }}

        .answer-nav-buttons .btn-secondary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}

        .answer-nav-buttons .btn-secondary:hover {{
            background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}

        .answer-nav-buttons .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}

        .answer-nav-buttons .btn-primary:hover {{
            background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}


        .answer-counter {{
            font-size: 1.1em;
            font-weight: bold;
            color: #667eea;
            text-align: right;
        }}

        .answer-counter span {{
            color: #667eea;
        }}

        .answer-progress-row {{
            width: 100%;
        }}

        .answer-progress-row .progress-bar-fill {{
            width: 100%;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
        }}

        .answer-progress-row .progress-bar-progress {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            border-radius: 4px;
            transition: width 0.3s ease;
        }}

        .completion-card {{
            background: linear-gradient(145deg, #ffffff 0%, #f8f9fa 100%);
            border-radius: 16px;
            padding: 28px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(0, 0, 0, 0.04);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.8);
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease;
            display: flex;
            flex-direction: column;
            height: fit-content;
        }}


        .completion-card:hover {{
            /* 移除移动效果，保持专业外观 */
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.12), 0 4px 12px rgba(0, 0, 0, 0.06);
        }}

        .completion-card h3 {{
            color: #2c3e50;
            font-size: 1.4em;
            margin-bottom: 20px;
            font-weight: 600;
            letter-spacing: 0.5px;
            position: relative;
        }}


        .completion-card p {{
            color: #5a6c7d;
            font-size: 1em;
            line-height: 1.6;
        }}

        @media (max-width: 1200px) {{
            .completion-layout {{
                grid-template-columns: 1fr;
                gap: 25px;
                max-width: 100%;
            }}
        }}
        
        @media (max-width: 768px) {{
            .completion-layout {{
                grid-template-columns: 1fr;
                gap: 25px;
                max-width: 100%;
            }}
            
            .completion-right-column {{
                gap: 25px;
            }}
            
            .completion-description {{
                padding: 15px;
                margin-bottom: 25px;
            }}
            
            .completion-description h2 {{
                font-size: 2.2em;
            }}
            
            .completion-card {{
                padding: 20px;
            }}
            
            .completion-card h3 {{
                font-size: 1.2em;
            }}
            
            .sus-question {{
                padding: 12px;
                margin-bottom: 15px;
            }}
            
            .completion-card .survey-question {{
                padding: 15px;
                margin-bottom: 20px;
            }}
        }}

        .results-table {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }}

        .results-table table {{
            width: 100%;
            border-collapse: collapse;
        }}

        .results-table th,
        .results-table td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e9ecef;
        }}

        .results-table th {{
            background: #f8f9fa;
            font-weight: bold;
            color: #667eea;
        }}


        .error-message {{
            text-align: center;
            padding: 40px;
            background: #fff5f5;
            border: 2px solid #f56565;
            border-radius: 10px;
            margin: 20px 0;
        }}

        .error-message h3 {{
            color: #e53e3e;
            margin-bottom: 15px;
        }}

        .error-message p {{
            color: #666;
            margin-bottom: 20px;
        }}

        .error-message button {{
            padding: 10px 20px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
        }}

        .error-message button:hover {{
            background: #5a6fd8;
        }}

        .survey-section {{
            margin-top: 40px;
            padding: 30px;
            background: #f8f9fa;
            border-radius: 15px;
            border: 2px solid #e9ecef;
        }}

        .survey-section h3 {{
            color: #667eea;
            margin-bottom: 25px;
            font-size: 1.5em;
            text-align: center;
        }}

        .survey-form {{
            max-width: 600px;
            margin: 0 auto;
        }}

        .survey-question {{
            margin-bottom: 30px;
        }}

        .survey-question label {{
            display: block;
            margin-bottom: 10px;
            font-weight: bold;
            color: #333;
            font-size: 1.1em;
        }}

        .survey-question textarea {{
            width: 100%;
            padding: 15px;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            resize: vertical;
            min-height: 100px;
            box-sizing: border-box;
        }}

        .survey-question textarea:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}

        /* SUS Questionnaire Styles */
        .sus-scale-legend {{
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border: 1px solid #dee2e6;
            border-radius: 12px;
            padding: 16px 12px;
            margin-bottom: 20px;
            text-align: center;
            width: 100%;
            max-width: 100%;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        }}

        .sus-scale-legend .sus-likert-labels {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            column-gap: 8px;
            margin-bottom: 10px;
            padding: 0;
            width: 100%;
        }}

        .sus-scale-legend .sus-likert-labels span {{
            font-size: 0.9em;
            color: #666;
            text-align: center;
            font-weight: 500;
            line-height: 1.2;
            white-space: nowrap;
        }}

        .sus-scale-legend .sus-likert-scale {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            column-gap: 8px;
            align-items: center;
            padding: 0;
            width: 100%;
            max-width: none;
            margin: 0;
        }}

        .sus-scale-legend .sus-likert-option {{
            display: flex;
            justify-content: center;
            align-items: center;
            min-width: 0;
        }}

        .sus-scale-legend .scale-number {{
            font-size: 0.9em;
            color: white;
            font-weight: 600;
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 50%;
            box-shadow: 0 2px 6px rgba(102, 126, 234, 0.3);
            transition: all 0.2s ease;
        }}

        .sus-scale-legend .scale-number:hover {{
            /* 移除缩放效果，保持专业外观 */
            transform: none;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }}

        .sus-question {{
            margin-bottom: 12px;
            text-align: left;
            padding: 12px;
            background: rgba(248, 249, 250, 0.6);
            border-radius: 10px;
            transition: all 0.2s ease;
        }}

        .sus-question:hover {{
            background: rgba(248, 249, 250, 0.9);
            /* 移除移动效果，保持专业外观 */
            transform: none;
        }}

        .sus-question label {{
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #2c3e50;
            font-size: 1.0em;
            line-height: 1.3;
        }}

        .sus-likert-scale {{
            display: flex;
            justify-content: flex-end;
            flex-wrap: nowrap;
            align-items: center;
            margin-top: 8px;
            padding: 0 20px;
            max-width: 800px;
            margin-left: auto;
            margin-right: auto;
            gap: 15px;
        }}

        .sus-likert-option {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            flex: 1;
            min-width: 80px;
        }}

        .sus-likert-option input[type="radio"] {{
            margin-bottom: 3px;
            width: 20px;
            height: 20px;
            cursor: pointer;
            accent-color: #667eea;
            transition: all 0.2s ease;
        }}

        .sus-likert-option input[type="radio"]:hover {{
            /* 移除缩放效果，保持专业外观 */
            transform: none;
        }}

        .sus-likert-option label {{
            font-size: 0.8em;
            color: #666;
            text-align: center;
            margin-bottom: 0;
            font-weight: normal;
            line-height: 1.1;
            white-space: nowrap;
        }}

        /* SUS Tooltip Styles */
        .sus-likert-option {{
            position: relative;
        }}

        .sus-likert-option .sus-tooltip {{
            visibility: hidden;
            width: 120px;
            background-color: #333;
            color: #fff;
            text-align: center;
            border-radius: 6px;
            padding: 8px 12px;
            position: absolute;
            z-index: 1;
            top: 125%;
            left: 50%;
            margin-left: -60px;
            opacity: 0;
            transition: opacity 0.3s;
            font-size: 0.8em;
            font-weight: 600;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        }}

        .sus-likert-option .sus-tooltip::after {{
            content: "";
            position: absolute;
            bottom: 100%;
            left: 50%;
            margin-left: -5px;
            border-width: 5px;
            border-style: solid;
            border-color: transparent transparent #333 transparent;
        }}

        .sus-likert-option:hover .sus-tooltip {{
            visibility: visible;
            opacity: 1;
        }}

        .sus-likert-labels {{
            display: flex;
            justify-content: space-between;
            flex-wrap: nowrap;
            margin-bottom: 8px;
            padding: 0 20px;
        }}

        .sus-likert-labels span {{
            font-size: 0.8em;
            color: #888;
            text-align: center;
            flex: 1;
            white-space: nowrap;
        }}

        /* 星级评分样式已移除 */

        .submit-survey-btn {{
            display: block;
            width: 220px;
            margin: 20px auto 0;
            padding: 16px 32px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }}

        .submit-survey-btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
            background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
        }}

        .submit-survey-btn:disabled {{
            background: #ccc;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }}

        .completion-buttons {{
            display: flex;
            gap: 15px;
            justify-content: space-between;
            margin: 20px 0 0 0;
            flex-wrap: nowrap;
        }}

        .completion-buttons .btn {{
            flex: 1;
            min-width: 0;
            max-width: none;
            padding: 16px 20px;
            font-size: 16px;
            font-weight: 600;
            border-radius: 10px;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            white-space: nowrap;
        }}

        .completion-buttons .submit-survey-btn {{
            margin: 0;
        }}

        /* 隐藏Netlify表单但保持其功能 */
        .netlify-form-hidden {{
            position: absolute;
            left: -9999px;
            top: -9999px;
            visibility: hidden;
        }}

        .survey-complete {{
            margin-top: 40px;
            padding: 40px;
            background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
            border-radius: 20px;
            border: 3px solid #28a745;
            text-align: center;
            box-shadow: 0 10px 30px rgba(40, 167, 69, 0.2);
        }}

        .complete-icon {{
            font-size: 4em;
            margin-bottom: 20px;
        }}

        .survey-complete h3 {{
            color: #28a745;
            margin-bottom: 15px;
            font-size: 2em;
        }}

        .survey-complete p {{
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
            line-height: 1.6;
        }}

        .complete-summary {{
            background: white;
            padding: 25px;
            border-radius: 15px;
            margin: 30px 0;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}

        .complete-summary h4 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 1.3em;
        }}

        .summary-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }}

        .summary-item:last-child {{
            border-bottom: none;
        }}

        .summary-item span {{
            color: #666;
            font-size: 1.1em;
        }}

        .summary-item strong {{
            color: #333;
            font-size: 1.2em;
        }}

        .complete-actions {{
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-top: 30px;
        }}

        .action-btn {{
            padding: 15px 30px;
            border: none;
            border-radius: 25px;
            font-size: 1.1em;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            min-width: 200px;
        }}

        .action-btn.primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}

        .action-btn.primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }}

        .action-btn.secondary {{
            background: #f8f9fa;
            color: #666;
            border: 2px solid #e9ecef;
        }}

        .action-btn.secondary:hover {{
            background: #e9ecef;
            color: #333;
        }}

        .download-complete {{
            margin-top: 40px;
            padding: 40px;
            background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
            border-radius: 20px;
            border: 3px solid #28a745;
            text-align: center;
            box-shadow: 0 10px 30px rgba(40, 167, 69, 0.2);
        }}

        .download-complete .complete-icon {{
            font-size: 4em;
            margin-bottom: 20px;
        }}

        .download-complete h3 {{
            color: #28a745;
            margin-bottom: 15px;
            font-size: 2em;
        }}

        .download-complete p {{
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
            line-height: 1.6;
        }}

        .download-complete .complete-actions {{
            display: flex;
            justify-content: center;
            margin-top: 30px;
        }}

        @media (max-width: 768px) {{
            .complete-actions {{
                flex-direction: column;
                align-items: center;
            }}
            
            .action-btn {{
                width: 100%;
                max-width: 300px;
            }}

            body {{
                overflow-x: hidden;
            }}

            .container {{
                padding: 10px;
                max-width: 100%;
            }}
            
            .header {{
                padding: 16px 12px;
            }}

            .header h1 {{
                font-size: 1.35em;
                line-height: 1.35;
                margin-top: 8px;
            }}

            .header-controls {{
                display: none;
            }}

            .language-switcher {{
                bottom: 12px;
                right: 12px;
            }}

            .fixed-bar-toggle-btn {{
                bottom: 12px;
                right: 12px;
                font-size: 12px;
                padding: 6px 12px;
            }}

            .lang-btn {{
                font-size: 12px;
                padding: 6px 12px;
            }}
            
            .section {{
                padding: 12px;
            }}

            .section h2 {{
                font-size: 1.2em;
            }}

            .question-layout {{
                gap: 12px;
            }}

            .question-layout > * {{
                min-width: 0;
                width: 100%;
            }}

            .specification {{
                padding: 14px;
            }}

            .config-container,
            .config-content,
            .config-text {{
                font-size: 13px;
                padding: 12px;
                -webkit-overflow-scrolling: touch;
            }}

            .progress-info {{
                flex-direction: column;
                gap: 10px;
                align-items: flex-start;
            }}

            .timer {{
                font-size: 0.95em;
                line-height: 1.4;
            }}

            .btn-container {{
                flex-direction: column;
                align-items: stretch;
            }}

            .btn-container .btn {{
                width: 100%;
            }}

            .sus-scale-legend {{
                padding: 12px 8px;
            }}

            .sus-scale-legend .sus-likert-labels,
            .sus-scale-legend .sus-likert-scale {{
                column-gap: 4px;
            }}

            .sus-scale-legend .sus-likert-labels span {{
                font-size: 0.82em;
            }}

            .sus-likert-scale {{
                gap: 8px;
                padding: 0 8px;
                max-width: 100%;
                flex-wrap: nowrap;
            }}

            .sus-likert-option {{
                min-width: 0;
                flex: 1;
            }}

            .sus-likert-labels {{
                padding: 0 8px;
                flex-wrap: nowrap;
            }}

            .completion-buttons {{
                flex-direction: row;
                flex-wrap: nowrap;
                justify-content: space-between;
                gap: 10px;
            }}

            .completion-buttons .btn,
            .submit-survey-btn {{
                flex: 1;
                min-width: 0;
                max-width: none;
                width: auto;
                padding: 16px 12px;
                font-size: 16px;
            }}

            .answer-navigation-row {{
                flex-wrap: nowrap;
                align-items: center;
                gap: 8px;
            }}

            .answer-nav-buttons {{
                flex-direction: row;
                justify-content: flex-start;
                width: auto;
                flex: 1;
                min-width: 0;
                gap: 8px;
            }}

            .answer-nav-buttons .btn {{
                width: auto;
                min-width: 0;
                flex: 0 0 auto;
                max-width: none;
                padding: 10px 12px;
                font-size: 14px;
                white-space: nowrap;
            }}

            .answer-counter {{
                width: auto;
                flex: 0 0 auto;
                text-align: right;
                font-size: 1.1em;
                white-space: nowrap;
            }}
        }}
    </style>
</head>
<body>
    <!-- Netlify表单配置 -->
    <form name="user-study-results" netlify netlify-honeypot="bot-field" action="/" method="POST" class="netlify-form-hidden">
        <input type="hidden" name="form-name" value="user-study-results">
        <input type="hidden" name="timestamp">
        <input type="hidden" name="userGroup">
        <input type="hidden" name="language">
        <input type="hidden" name="userNumber">
        <input type="hidden" name="totalTime">
        <input type="hidden" name="score">
        <input type="hidden" name="totalQuestions">
        <input type="hidden" name="questionTimes">
        <input type="hidden" name="answers">
        <input type="hidden" name="userNotes">
        <input type="hidden" name="questionCorrectness">
        <input type="hidden" name="surveyQ1">
        <input type="hidden" name="surveyQ2">
        <input type="hidden" name="susTotalScore">
        <input type="hidden" name="susScores">
        <input type="hidden" name="bot-field">
    </form>
    <!-- Fixed top bar for topology and specification -->
    <div class="fixed-top-bar" id="fixedTopBar">
        <div class="fixed-top-bar-content">
            <div class="fixed-topology-mini" id="fixedTopologyMini"></div>
            <div class="fixed-spec-first-line" id="fixedSpecFirstLine"></div>
            <div class="fixed-question-instruction" id="fixedQuestionInstruction"></div>
        </div>
    </div>
    <div class="container">
        <div class="header">
            <div class="language-switcher">
                <button class="lang-btn active" id="lang-en" onclick="switchLanguage('en')">English</button>
                <button class="lang-btn" id="lang-zh" onclick="switchLanguage('zh')">中文</button>
            </div>
            <button class="fixed-bar-toggle-btn active" id="fixedBarToggleBtn" onclick="toggleFixedBar()">
                <span id="fixedBarToggleText">Show Fixed Bar</span>
            </button>
            <h1 id="header-title">Explainable Network Verification via Localized Subspecification - User Study</h1>
            </div>
            

        <!-- 进度条 -->
        <div class="progress-bar">
            <div class="progress-info">
                <div class="progress-text" id="progress-text">Question <span id="currentQuestion">1</span> / 5</div>
                <div class="timer" id="timer-text"><span id="totalTimeLabel">Total Time</span>: <span id="totalTimer">00:00</span> | <span id="currentQuestionLabel">Current Question</span>: <span id="questionTimer">00:00</span></div>
            </div>
            <div class="progress-bar-fill">
                <div class="progress-bar-progress" id="progressBar" style="width: 20%"></div>
            </div>
        </div>

        <!-- 测试内容区域 -->
        <div id="testContent">
            <!-- 动态生成的内容 -->
        </div>
    </div>

        <!-- Confirmation Modal -->
    <div id="confirmModal" class="modal">
        <div class="modal-content">
                <h3 id="confirm-title">Confirm Selection</h3>
                <p id="confirm-text">Please confirm your selection. You cannot go back after confirmation, please choose carefully.</p>
            <div class="modal-buttons">
                    <button class="btn btn-secondary" onclick="closeConfirmModal()" id="confirm-cancel">Cancel</button>
                    <button class="btn btn-primary" onclick="confirmSelection()" id="confirm-confirm">Confirm Selection</button>
            </div>
        </div>
    </div>

        <!-- Validation Modal -->
    <div id="validationModal" class="modal">
        <div class="modal-content">
                <h3 id="validation-title">⚠️ Selection Required</h3>
                <p id="validation-text">Please select exactly one option before proceeding to the next question.</p>
            <div class="modal-buttons">
                    <button class="btn btn-primary" onclick="closeValidationModal()" id="validation-ok">OK</button>
            </div>
        </div>
    </div>

        <!-- SUS Validation Modal -->
    <div id="susValidationModal" class="modal">
        <div class="modal-content">
                <h3 id="sus-validation-title">⚠️ SUS Questions Required</h3>
                <p id="sus-validation-text">Please answer all 10 System Usability Scale questions before completing the survey.</p>
            <div class="modal-buttons">
                    <button class="btn btn-primary" onclick="closeSusValidationModal()" id="sus-validation-ok">OK</button>
            </div>
        </div>
    </div>

        <!-- Refresh/Back Confirmation Modal -->
    <div id="refreshBackModal" class="modal">
        <div class="modal-content">
                <h3 id="refresh-back-title">⚠️ Refresh Page?</h3>
                <p id="refresh-back-text">Are you sure you want to refresh the page? Your progress will be lost.</p>
            <div class="modal-buttons">
                    <button class="btn btn-secondary" onclick="closeRefreshBackModal()" id="refresh-back-cancel">Cancel</button>
                    <button class="btn btn-primary" onclick="confirmRefresh()" id="refresh-back-confirm">Confirm</button>
            </div>
        </div>
    </div>

    <script>
        // Global variables
        let currentQuestionIndex = -1; // -1 for start screen
        // 介绍页面已移除
        let userGroup = Math.random() < 0.5 ? 'A' : 'B'; // Random grouping
        let userNumber = ''; // 4-digit participant ID
        let startTime = null;
        let questionStartTime = null;
        let questionTimes = [];
        let totalTime = 0;
        let answers = [];
        let userNotes = [];
        let testCompleted = false;
        let isOnCompletionScreen = false;
        let currentSlide = 0; // Current slide position
        let currentLanguage = 'en'; // Current language - will be auto-detected
        let fixedBarEnabled = true; // Fixed bar visibility state (default: enabled)

        // Get userNumber from URL parameter or localStorage
        function getParticipantId() {{
            // First check URL parameter
            const urlParams = new URLSearchParams(window.location.search);
            const urlUserNumber = urlParams.get('userNumber');
            if (urlUserNumber && urlUserNumber.length === 4) {{
                userNumber = urlUserNumber;
                localStorage.setItem('userNumber', userNumber);
                return userNumber;
            }}
            
            // Then check localStorage (set by index.html)
            const savedUserNumber = localStorage.getItem('userNumber');
            if (savedUserNumber && savedUserNumber.length === 4) {{
                userNumber = savedUserNumber;
                return userNumber;
            }}
            
            return '';
        }}

        // Auto-detect language from URL parameter or localStorage
        function detectLanguage() {{
            // First check URL parameter
            const urlParams = new URLSearchParams(window.location.search);
            const urlLang = urlParams.get('lang');
            if (urlLang && (urlLang === 'en' || urlLang === 'zh')) {{
                currentLanguage = urlLang;
                return currentLanguage;
            }}
            
            // Then check localStorage (set by index.html)
            const savedLanguage = localStorage.getItem('selectedLanguage');
            if (savedLanguage && (savedLanguage === 'en' || savedLanguage === 'zh')) {{
                currentLanguage = savedLanguage;
                return currentLanguage;
            }}
            
            // Default to English
            return currentLanguage;
        }}

        // Text constants for different languages
        const textConstants = {{
            'en': {{
            'title': 'Explainable Network Verification via Localized Subspecification - User Study',
                'progress': 'Question',
                'totalTime': 'Total Time',
                'currentTime': 'Current Question',
                'networkTopology': 'Network Topology',
                'networkSpec': 'Verified Network Specification (Confirmed Global Routing Policy)',
                'networkSpecQuestion0': 'Network Description',
                'coreConfig': 'Core Configuration Fragment',
                'coreConfigWithSubspecs': 'Core Configuration Fragment (with subspecs annotations)',
                'maintenanceTask': 'Maintenance Task',
                'maintenanceTaskQuestion0': 'Test Task',
                'questionNote1': 'When modifying multiple configuration fields, refer to the line-level subspec!',
                'questionNote2': 'When removing an entire configuration line, refer to the <span style="color: red;">empty</span> line-level subspec!',
                'userNotes': 'Question Notes',
                'userNotesPlaceholder': 'Record any thoughts, observations, or notes about this question...',
                'nextQuestion': 'Next Question',
                'confirmTitle': 'Confirm Selection',
                'confirmText': 'You cannot go back to the previous question after confirming your selection, please choose carefully.',
                'cancel': 'Cancel',
                'confirm': 'Confirm Selection',
                'completionTitle': '🎉 Test Completed!',
                'completionText': '<strong>Thank you for participating in this user study on explainable network verification via subspecifications.</strong><br><em>You can click the "VIEW ANSWER EXPLANATIONS" button to see our provided answers with subspecs.</em><br><em>You need to complete the System Usability Scale (SUS), then click the "COMPLETE" button to submit your responses.</em>',
                'testResults': 'Test Results',
                'testGroup': 'Test Group',
                'totalTimeLabel': 'Total Time',
                'questionTimes': 'Question Times',
                'dataRecorded': 'Your test data has been recorded and will be used for research analysis.',
                'correct': 'Correct',
                'incorrect': 'Incorrect',
                'score': 'Score',
                'correctAnswers': 'Correct Answers',
                'totalQuestions': 'Total Questions',
                'welcome': 'Welcome to the user study',
                'welcomeDesc': '',
                'instructions': 'Test Instructions',
                'instruction1': 'You will be presented with five questions (including one warm-up question).<br> Please read each question carefully and select all correct options.',
                'instruction2': 'You cannot go back to the previous question after confirming your selection, please choose carefully.',
                'instruction3': 'You may quit the user study at any time during the session.',
                'startTest': 'Enter',
                'validationTitle': '⚠️ Selection Required',
                'validationText': 'Please select exactly one option before proceeding to the next question.',
                'ok': 'OK',
                'assignedTo': 'You are assigned to',
                'group': 'Group',
                'withSubspecs': 'WITH subspecs (Questions:',
                'withoutSubspecs': 'WITHOUT subspecs (Questions:',
                'showFixedBar': 'Show Fixed Bar',
                'hideFixedBar': 'Hide Fixed Bar',
                
                'survey': 'Survey',
                'surveyQuestion1': 'When using or testing routing protocols and doing network verification, what challenges have you run into?',
                'surveyQuestion1Placeholder': 'Please describe the challenges you encountered...',
                'surveyQuestion2': 'Do you think our tool is helpful for protocol testing and network verification? If yes, could you describe how?',
                'surveyQuestion2Placeholder': 'Please describe how our tool is helpful...',
                'sus': 'System Usability Scale',
                'susQuestion1': 'I think that I would like to use this system frequently.',
                'susQuestion2': 'I found the system unnecessarily complex.',
                'susQuestion3': 'I thought the system was easy to use.',
                'susQuestion4': 'I think that I would need the support of a technical person to be able to use this system.',
                'susQuestion5': 'I found the various functions in this system were well integrated.',
                'susQuestion6': 'I thought there was too much inconsistency in this system.',
                'susQuestion7': 'I would imagine that most people would learn to use this system very quickly.',
                'susQuestion8': 'I found the system very cumbersome to use.',
                'susQuestion9': 'I felt very confident using the system.',
                'susQuestion10': 'I needed to learn a lot of things before I could get going with this system.',
                'stronglyDisagree': 'Strongly Disagree',
                'disagree': 'Disagree',
                'neutral': 'Neutral',
                'agree': 'Agree',
                'stronglyAgree': 'Strongly Agree',
                'complete': 'Complete',
                'submitted': 'Submitted ✓',
                'submissionFailed': 'Submission Failed',
                'susValidationTitle': '⚠️ SUS Questions Required',
                'susValidationText': 'Please answer all 10 System Usability Scale questions before completing the survey.',
                'fieldLevelSubspecs': 'field-level subspecs',
                'lineLevelSubspecs': 'line-level subspecs',
                'viewAnswerExplanations': 'View Answer Explanations',
                'nextAnswer': 'Next Answer',
                'previousAnswer': 'Previous Answer',
                'backToResults': 'Back to Results',
                'correctAnswersInstruction': 'Correct options are shown below with ✓ and incorrect options with ✗.',
                'answerExplanation': 'Answer Explanation',
                'totalTimeLabel': 'Total Time',
                'currentQuestionLabel': 'Current Question',
                'answerCounter': 'Answer',
                'of': 'of',
                'checkButton': 'CHECK',
                'courseraIncorrect': '✗ You have selected some incorrect options.',
                'courseraIncomplete': '⚠ Please select all correct options.',
                'courseraCorrect': '✓ All correct! Well done!',
                'courseraQuestions1': 'Coursera Questions 1',
                'courseraQuestions2': 'Coursera Questions 2',
                'questionLabel': 'Question',
                'refreshTitle': '⚠️ Refresh Page?',
                'refreshText': 'Are you sure you want to refresh the page? Your progress will be lost.',
                'backTitle': '⚠️ Go Back?',
                'backText': 'Are you sure you want to go back? Your progress will be lost.'
            }},
            'zh': {{
                'title': '基于局部子规约的可解释网络验证 - 用户研究',
                'progress': '问题',
                'totalTime': '总时间',
                'currentTime': '当前问题',
                'networkTopology': '网络拓扑',
                'networkSpec': '已验证的网络规约（已确认的全局路由策略）',
                'networkSpecQuestion0': '网络描述',
                'coreConfig': '核心配置片段',
                'coreConfigWithSubspecs': '核心配置片段（带子规约提示注释）',
                'maintenanceTask': '维护任务',
                'maintenanceTaskQuestion0': '测试任务',
                'questionNote1': '修改一行中的多个配置域时，请参考配置行子规约！',
                'questionNote2': '删除整行配置行时，请参考<span style="color: red;">空的</span>配置行子规约！',
                'userNotes': '问题笔记',
                'userNotesPlaceholder': '记录您对此问题的任何想法、观察或笔记...',
                'nextQuestion': '下一题',
                'confirmTitle': '确认选择',
                'confirmText': '您确认选择后，就无法返回到上一题了。请仔细选择。',
                'cancel': '取消',
                'confirm': '确认选择',
                'completionTitle': '🎉 测试完成！',
                'completionText': '<strong>感谢您参与基于子规约的可解释网络验证用户研究。</strong><br><em>您可以点击"查看答案解析"按钮，查看我们提供的解答及其子规约说明。</em><br><em>您需要完成系统可用性量表（SUS），然后点击"完成"按钮提交您的回答。</em>',
                'testResults': '测试结果',
                'testGroup': '测试组别',
                'totalTimeLabel': '总时间',
                'questionTimes': '各题用时',
                'dataRecorded': '您的测试数据已被记录，将用于研究分析。',
                'correct': '正确',
                'incorrect': '错误',
                'score': '得分',
                'correctAnswers': '正确答案',
                'totalQuestions': '总题数',
                'welcome': '欢迎参与本次用户研究',
                'welcomeDesc': '',
                'instructions': '测试说明',
                'instruction1': '您将看到五个问题（包括一个热身问题）。<br>请仔细阅读每个问题，并选择所有正确的选项。',
                'instruction2': '您确认选择后，就无法返回到上一题了。请仔细选择。',
                'instruction3': '您在中间可以随时退出本次用户研究。',
                'startTest': '开始',
                'validationTitle': '⚠️ 需要选择',
                'validationText': '请选择一个选项后再继续下一题。',
                'ok': '确定',
                'assignedTo': '您被分配到',
                'group': '组',
                'withSubspecs': '带子规约提示（问题：',
                'withoutSubspecs': '不带子规约提示（问题：',
                'showFixedBar': '显示固定栏',
                'hideFixedBar': '隐藏固定栏',
                
                'survey': '问卷调查',
                'surveyQuestion1': '在使用或测试路由协议以及进行网络验证时，您遇到了哪些挑战？',
                'surveyQuestion1Placeholder': '请描述您遇到的挑战...',
                'surveyQuestion2': '您认为我们的工具对协议测试和网络验证有帮助吗？如果有，请描述它是如何帮助的？',
                'surveyQuestion2Placeholder': '请描述我们的工具是如何帮助的...',
                'sus': '系统可用性量表',
                'susQuestion1': '我认为我会经常使用这个系统。',
                'susQuestion2': '我发现这个系统过于复杂。',
                'susQuestion3': '我认为这个系统易于使用。',
                'susQuestion4': '我认为我需要技术支持人员的帮助才能使用这个系统。',
                'susQuestion5': '我发现这个系统中的各种功能整合得很好。',
                'susQuestion6': '我认为这个系统存在太多不一致的地方。',
                'susQuestion7': '我想大多数人会很快学会使用这个系统。',
                'susQuestion8': '我发现这个系统使用起来非常麻烦。',
                'susQuestion9': '我对使用这个系统感到非常自信。',
                'susQuestion10': '在使用这个系统之前，我需要学习很多东西。',
                'stronglyDisagree': '强烈不同意',
                'disagree': '不同意',
                'neutral': '中性',
                'agree': '同意',
                'stronglyAgree': '强烈同意',
                'complete': '完成',
                'submitted': '已提交 ✓',
                'submissionFailed': '提交失败',
                'susValidationTitle': '⚠️ 需要完成SUS问题',
                'susValidationText': '请完成所有10个系统可用性量表问题后再提交调查。',
                'fieldLevelSubspecs': '配置域子规约',
                'lineLevelSubspecs': '配置行子规约',
                'viewAnswerExplanations': '查看答案解析',
                'nextAnswer': '下一答案',
                'previousAnswer': '上一答案',
                'backToResults': '返回结果',
                'correctAnswersInstruction': '正确选项如下所示，用 ✓ 标记，错误选项用 ✗ 标记。',
                'answerExplanation': '答案解析',
                'totalTimeLabel': '总时间',
                'currentQuestionLabel': '当前问题',
                'answerCounter': '答案',
                'of': '共',
                'checkButton': '确认',
                'courseraIncorrect': '✗ 您选择了一些不正确的选项。',
                'courseraIncomplete': '⚠ 请选择所有正确的选项。',
                'courseraCorrect': '✓ 全部正确！做得好！',
                'courseraQuestions1': 'Coursera 问题 1',
                'courseraQuestions2': 'Coursera 问题 2',
                'questionLabel': '问题',
                'refreshTitle': '⚠️ 刷新页面？',
                'refreshText': '您确定要刷新页面吗？您的进度将会丢失。',
                'backTitle': '⚠️ 返回？',
                'backText': '您确定要返回吗？您的进度将会丢失。'
            }}
        }};

        // Current texts object (will be updated when language changes)
        let texts = textConstants[currentLanguage];
        
        // Group configuration: 
        // question0 (warm-up, index 0): no subspecs for both groups
        // question1-question4 (index 1-4): depends on group
        const groupConfig = {{
            'A': [false, false, true, false, true],  // question0, question1-4: A pattern
            'B': [false, true, false, true, false]   // question0, question1-4: B pattern
        }};

        // Correct answer configuration
        const correctAnswers = [
            ['option_1'], // Question 0 (question0 warm-up): first option is correct
            ['option_3'], // Question 1: third option is correct
            ['option_3'], // Question 2: third option is correct
            ['option_3'], // Question 3: third option is correct
            ['option_3']  // Question 4: third option is correct
        ];

        // Question data - will be loaded dynamically based on language
        let questions = [];

        // 介绍内容已移除

        // Question data for both languages
        // Coursera data removed - now in separate coursera_en.html and coursera_zh.html files
        
        // Pre-encode topology SVGs (question0 / question1-2 / question3-4 各一份，mini 与 full 内容相同)
        const question0Topology = `{encode_topology_image(resolve_topology_image_path('question0'))}`;
        const question1Topology = `{encode_topology_image(resolve_topology_image_path('question1'))}`;
        const question3Topology = `{encode_topology_image(resolve_topology_image_path('question3'))}`;
        const questionImages = {{
            'en': [
                question0Topology,
                question1Topology,
                question1Topology,
                question3Topology,
                question3Topology
            ],
            'zh': [
                question0Topology,
                question1Topology,
                question1Topology,
                question3Topology,
                question3Topology
            ]
        }};
        
        const questionData = {{
            'en': [
                {{
                spec: `{load_question_data(0, 'en')[0]}`,
                config: `{load_question_data(0, 'en')[1]}`,
                question: `{load_question_data(0, 'en')[2]}`,
                answer: `{load_question_data(0, 'en')[3]}`,
                configSubspec: `{load_question_data(0, 'en')[4]}`,
                lineSubspec: `{load_question_data(0, 'en')[5]}`,
                configSubspecTrans: `{load_question_data(0, 'en')[6]}`,
                lineSubspecTrans: `{load_question_data(0, 'en')[7]}`,
                routemapSubspecTrans: ``,
                highlight: `{load_question_data(0, 'en')[8]}`,
                image: questionImages.en[0],
                imageMini: questionImages.en[0]
                }},
                {{
                spec: `{load_question_data(1, 'en')[0]}`,
                config: `{load_question_data(1, 'en')[1]}`,
                question: `{load_question_data(1, 'en')[2]}`,
                answer: `{load_question_data(1, 'en')[3]}`,
                configSubspec: `{load_question_data(1, 'en')[4]}`,
                lineSubspec: `{load_question_data(1, 'en')[5]}`,
                configSubspecTrans: `{load_question_data(1, 'en')[6]}`,
                lineSubspecTrans: `{load_question_data(1, 'en')[7]}`,
                routemapSubspecTrans: ``,
                highlight: `{load_question_data(1, 'en')[8]}`,
                image: questionImages.en[1],
                imageMini: questionImages.en[1]
                }},
                {{
                spec: `{load_question_data(2, 'en')[0]}`,
                config: `{load_question_data(2, 'en')[1]}`,
                question: `{load_question_data(2, 'en')[2]}`,
                answer: `{load_question_data(2, 'en')[3]}`,
                configSubspec: `{load_question_data(2, 'en')[4]}`,
                lineSubspec: `{load_question_data(2, 'en')[5]}`,
                configSubspecTrans: `{load_question_data(2, 'en')[6]}`,
                lineSubspecTrans: `{load_question_data(2, 'en')[7]}`,
                routemapSubspecTrans: ``,
                highlight: `{load_question_data(2, 'en')[8]}`,
                image: questionImages.en[2],
                imageMini: questionImages.en[2]
                }},
                {{
                spec: `{load_question_data(3, 'en')[0]}`,
                config: `{load_question_data(3, 'en')[1]}`,
                question: `{load_question_data(3, 'en')[2]}`,
                answer: `{load_question_data(3, 'en')[3]}`,
                configSubspec: `{load_question_data(3, 'en')[4]}`,
                lineSubspec: `{load_question_data(3, 'en')[5]}`,
                configSubspecTrans: `{load_question_data(3, 'en')[6]}`,
                lineSubspecTrans: `{load_question_data(3, 'en')[7]}`,
                routemapSubspecTrans: ``,
                highlight: `{load_question_data(3, 'en')[8]}`,
                image: questionImages.en[3],
                imageMini: questionImages.en[3]
                }},
                {{
                spec: `{load_question_data(4, 'en')[0]}`,
                config: `{load_question_data(4, 'en')[1]}`,
                question: `{load_question_data(4, 'en')[2]}`,
                answer: `{load_question_data(4, 'en')[3]}`,
                configSubspec: `{load_question_data(4, 'en')[4]}`,
                lineSubspec: `{load_question_data(4, 'en')[5]}`,
                configSubspecTrans: `{load_question_data(4, 'en')[6]}`,
                lineSubspecTrans: `{load_question_data(4, 'en')[7]}`,
                routemapSubspecTrans: ``,
                highlight: `{load_question_data(4, 'en')[8]}`,
                image: questionImages.en[4],
                imageMini: questionImages.en[4]
            }}
            ],
            'zh': [
                {{
                    spec: `{load_question_data(0, 'zh')[0]}`,
                    config: `{load_question_data(0, 'zh')[1]}`,
                    question: `{load_question_data(0, 'zh')[2]}`,
                    answer: `{load_question_data(0, 'zh')[3]}`,
                    configSubspec: `{load_question_data(0, 'zh')[4]}`,
                    lineSubspec: `{load_question_data(0, 'zh')[5]}`,
                    configSubspecTrans: `{load_question_data(0, 'zh')[6]}`,
                    lineSubspecTrans: `{load_question_data(0, 'zh')[7]}`,
                    routemapSubspecTrans: ``,
                    highlight: `{load_question_data(0, 'zh')[8]}`,
                    image: questionImages.zh[0],
                    imageMini: questionImages.zh[0]
                }},
                {{
                    spec: `{load_question_data(1, 'zh')[0]}`,
                    config: `{load_question_data(1, 'zh')[1]}`,
                    question: `{load_question_data(1, 'zh')[2]}`,
                    answer: `{load_question_data(1, 'zh')[3]}`,
                    configSubspec: `{load_question_data(1, 'zh')[4]}`,
                    lineSubspec: `{load_question_data(1, 'zh')[5]}`,
                    configSubspecTrans: `{load_question_data(1, 'zh')[6]}`,
                    lineSubspecTrans: `{load_question_data(1, 'zh')[7]}`,
                    routemapSubspecTrans: ``,
                    highlight: `{load_question_data(1, 'zh')[8]}`,
                    image: questionImages.zh[1],
                    imageMini: questionImages.zh[1]
                }},
                {{
                    spec: `{load_question_data(2, 'zh')[0]}`,
                    config: `{load_question_data(2, 'zh')[1]}`,
                    question: `{load_question_data(2, 'zh')[2]}`,
                    answer: `{load_question_data(2, 'zh')[3]}`,
                    configSubspec: `{load_question_data(2, 'zh')[4]}`,
                    lineSubspec: `{load_question_data(2, 'zh')[5]}`,
                    configSubspecTrans: `{load_question_data(2, 'zh')[6]}`,
                    lineSubspecTrans: `{load_question_data(2, 'zh')[7]}`,
                    routemapSubspecTrans: ``,
                    highlight: `{load_question_data(2, 'zh')[8]}`,
                    image: questionImages.zh[2],
                    imageMini: questionImages.zh[2]
                }},
                {{
                    spec: `{load_question_data(3, 'zh')[0]}`,
                    config: `{load_question_data(3, 'zh')[1]}`,
                    question: `{load_question_data(3, 'zh')[2]}`,
                    answer: `{load_question_data(3, 'zh')[3]}`,
                    configSubspec: `{load_question_data(3, 'zh')[4]}`,
                    lineSubspec: `{load_question_data(3, 'zh')[5]}`,
                    configSubspecTrans: `{load_question_data(3, 'zh')[6]}`,
                    lineSubspecTrans: `{load_question_data(3, 'zh')[7]}`,
                    routemapSubspecTrans: ``,
                    highlight: `{load_question_data(3, 'zh')[8]}`,
                    image: questionImages.zh[3],
                    imageMini: questionImages.zh[3]
                }},
                {{
                    spec: `{load_question_data(4, 'zh')[0]}`,
                    config: `{load_question_data(4, 'zh')[1]}`,
                    question: `{load_question_data(4, 'zh')[2]}`,
                    answer: `{load_question_data(4, 'zh')[3]}`,
                    configSubspec: `{load_question_data(4, 'zh')[4]}`,
                    lineSubspec: `{load_question_data(4, 'zh')[5]}`,
                    configSubspecTrans: `{load_question_data(4, 'zh')[6]}`,
                    lineSubspecTrans: `{load_question_data(4, 'zh')[7]}`,
                    routemapSubspecTrans: ``,
                    highlight: `{load_question_data(4, 'zh')[8]}`,
                    image: questionImages.zh[4],
                    imageMini: questionImages.zh[4]
                }}
            ],
            // Coursera data removed - now in separate files
        }};

        // Load question data for current language
        function loadQuestionsForLanguage(language) {{
            questions = questionData[language] || questionData['en'];
        }}

        // Switch language function
        function switchLanguage(language) {{
            currentLanguage = language;
            texts = textConstants[language];
            
            // Update language buttons
            document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.remove('active'));
            document.getElementById(`lang-${{language}}`).classList.add('active');
            
            // Reload questions for new language
            loadQuestionsForLanguage(language);
            
            // Update UI texts
            updateUITexts();
            
            // Update config reference tooltips
            updateConfigReferenceTooltips();
            
            // If we're on start screen, refresh it
            if (currentQuestionIndex === -1) {{
                showStartScreen();
            }} else if (isOnCompletionScreen) {{
                // If we're on completion screen, just update texts without restarting
                updateUITexts();
            }} else {{
                // If we're in the middle of a test, refresh current question
                showQuestion(currentQuestionIndex);
            }}
        }}

        // Update UI texts
        function updateUITexts() {{
            document.getElementById('header-title').textContent = texts.title;
            
            // Update fixed bar toggle button text
            const toggleText = document.getElementById('fixedBarToggleText');
            if (toggleText) {{
                toggleText.textContent = fixedBarEnabled ? texts.hideFixedBar : texts.showFixedBar;
            }}
            
            // Only update progress bar texts if not on start screen
            if (currentQuestionIndex >= 0) {{
                document.getElementById('progress-text').innerHTML = `${{texts.progress}} <span id="currentQuestion">${{currentQuestionIndex + 1}}</span> / 5`;
                document.getElementById('timer-text').innerHTML = `${{texts.totalTime}}: <span id="totalTimer">00:00</span> | ${{texts.currentTime}}: <span id="questionTimer">00:00</span>`;
            }}
            
            // Update modal texts
            document.getElementById('confirm-title').textContent = texts.confirmTitle;
            document.getElementById('confirm-text').textContent = texts.confirmText;
            document.getElementById('confirm-cancel').textContent = texts.cancel;
            document.getElementById('confirm-confirm').textContent = texts.confirm;
            
            // Update validation modal texts
            document.getElementById('validation-title').textContent = texts.validationTitle;
            document.getElementById('validation-text').textContent = texts.validationText;
            document.getElementById('validation-ok').textContent = texts.ok;
            
            // Update SUS validation modal texts
            document.getElementById('sus-validation-title').textContent = texts.susValidationTitle;
            document.getElementById('sus-validation-text').textContent = texts.susValidationText;
            document.getElementById('sus-validation-ok').textContent = texts.ok;
            
            // Update refresh/back confirmation modal texts
            // Note: Title and text are updated dynamically in showRefreshBackModal based on action
            const refreshBackCancel = document.getElementById('refresh-back-cancel');
            const refreshBackConfirm = document.getElementById('refresh-back-confirm');
            if (refreshBackCancel) refreshBackCancel.textContent = texts.cancel;
            if (refreshBackConfirm) refreshBackConfirm.textContent = texts.confirm;
            
            // Update SUS texts if they exist
            const susTitle = document.getElementById('susTitle');
            const susQuestionLabels = [
                document.getElementById('susQuestion1Label'),
                document.getElementById('susQuestion2Label'),
                document.getElementById('susQuestion3Label'),
                document.getElementById('susQuestion4Label'),
                document.getElementById('susQuestion5Label'),
                document.getElementById('susQuestion6Label'),
                document.getElementById('susQuestion7Label'),
                document.getElementById('susQuestion8Label'),
                document.getElementById('susQuestion9Label'),
                document.getElementById('susQuestion10Label')
            ];
            const susQuestions = [
                texts.susQuestion1, texts.susQuestion2, texts.susQuestion3, texts.susQuestion4, texts.susQuestion5,
                texts.susQuestion6, texts.susQuestion7, texts.susQuestion8, texts.susQuestion9, texts.susQuestion10
            ];
            
            if (susTitle) susTitle.textContent = texts.sus;
            susQuestionLabels.forEach((label, index) => {{
                if (label) label.textContent = (index + 1) + '. ' + susQuestions[index];
            }});
            
            // Update Likert scale labels (only in the legend section)
            const legendLikertLabels = document.querySelectorAll('.sus-scale-legend .sus-likert-labels span');
            const likertTexts = [texts.stronglyDisagree, texts.disagree, texts.neutral, texts.agree, texts.stronglyAgree];
            legendLikertLabels.forEach((label, index) => {{
                if (index < likertTexts.length) label.textContent = likertTexts[index];
            }});
            
            // Update survey texts if they exist
            const surveyTitle = document.getElementById('surveyTitle');
            const surveyQuestion1Label = document.getElementById('surveyQuestion1Label');
            const surveyQuestion2Label = document.getElementById('surveyQuestion2Label');
            const surveyQ1 = document.getElementById('surveyQ1');
            const surveyQ2 = document.getElementById('surveyQ2');
            const completeBtn = document.getElementById('completeBtn');
            
            if (surveyTitle) surveyTitle.textContent = texts.survey;
            if (surveyQuestion1Label) surveyQuestion1Label.textContent = '1. ' + texts.surveyQuestion1;
            if (surveyQuestion2Label) surveyQuestion2Label.textContent = '2. ' + texts.surveyQuestion2;
            if (surveyQ1) surveyQ1.placeholder = texts.surveyQuestion1Placeholder;
            if (surveyQ2) surveyQ2.placeholder = texts.surveyQuestion2Placeholder;
            if (completeBtn) completeBtn.textContent = texts.complete;
            
            // Update timer labels
            const totalTimeLabel = document.getElementById('totalTimeLabel');
            const currentQuestionLabel = document.getElementById('currentQuestionLabel');
            if (totalTimeLabel) totalTimeLabel.textContent = texts.totalTimeLabel;
            if (currentQuestionLabel) currentQuestionLabel.textContent = texts.currentQuestionLabel;
        }}

        // Show start screen
        function showStartScreen() {{
            const startHtml = `
                <div class="start-screen">
                    <h2>${{texts.welcome}}</h2>
                    
                    <div id="groupInfo" class="group-info-top">
                        <!-- Group assignment and subspec info will be displayed here -->
                    </div>
                    
                    <div class="start-info">
                        <h3>${{texts.instructions}}</h3>
                        <ul>
                            <li>${{texts.instruction1}}</li>
                            <li>${{texts.instruction2}}</li>
                            <li>${{texts.instruction3}}</li>
                        </ul>
                    </div>
                    
                    <div class="btn-container">
                        <button class="btn btn-primary" onclick="startTest()">${{texts.startTest}}</button>
                    </div>
                </div>
            `;
            
            document.getElementById('testContent').innerHTML = startHtml;
            document.querySelector('.progress-bar').style.display = 'none';
            
            // Hide fixed top bar on start screen
            const fixedTopBar = document.getElementById('fixedTopBar');
            const container = document.querySelector('.container');
            if (fixedTopBar) {{
                fixedTopBar.classList.remove('visible');
            }}
            if (container) {{
                container.style.paddingTop = '';
            }}
            
            // Show language switcher on start screen
            showLanguageSwitcher();
            
            // Hide fixed bar toggle button on start screen
            toggleFixedBarButton(false);
            
            // Update group info after the HTML is inserted
            setTimeout(() => {{
                updateStartScreenWithGroupInfo();
            }}, 100);
        }}



        // Hide language switcher
        function hideLanguageSwitcher() {{
            const languageSwitcher = document.querySelector('.language-switcher');
            if (languageSwitcher) {{
                languageSwitcher.style.display = 'none';
            }}
        }}

        // Show language switcher
        function showLanguageSwitcher() {{
            const languageSwitcher = document.querySelector('.language-switcher');
            if (languageSwitcher) {{
                languageSwitcher.style.display = 'flex';
            }}
        }}

        // Start test
        function startTest() {{
            isOnCompletionScreen = false;
            startTime = Date.now();
            questionStartTime = Date.now();
            
            // Hide language switcher once test starts
            hideLanguageSwitcher();
            
            document.querySelector('.progress-bar').style.display = 'block';
            showQuestion(0);
            startTimer();
        }}
        
        // Update start screen with group information
        function updateStartScreenWithGroupInfo() {{
            const groupInfo = document.getElementById('groupInfo');
            if (groupInfo) {{
                // Get subspec configuration for this group
                const subspecConfig = groupConfig[userGroup];
                const questionsWithSubspecs = [];
                const questionsWithoutSubspecs = [];
                
                subspecConfig.forEach((showSubspec, index) => {{
                    if (showSubspec) {{
                        questionsWithSubspecs.push(index + 1);
                    }} else {{
                        questionsWithoutSubspecs.push(index + 1);
                    }}
                }});
                
                let subspecInfo = '';
                if (questionsWithSubspecs.length > 0) {{
                    subspecInfo += '<span class="subspec-with">' + texts.withSubspecs + ' ' + questionsWithSubspecs.join(', ') + ')</span>';
                }}
                if (questionsWithoutSubspecs.length > 0) {{
                    if (subspecInfo) subspecInfo += ' | ';
                    subspecInfo += '<span class="subspec-without">' + texts.withoutSubspecs + ' ' + questionsWithoutSubspecs.join(', ') + ')</span>';
                }}
                
                groupInfo.innerHTML = 
                    '<div class="group-assignment">' +
                        '<h3>' + texts.assignedTo + ' <span class="group-badge group-' + userGroup.toLowerCase() + '">' + texts.group + ' ' + userGroup + '</span> | ' + subspecInfo + '</h3>' +
                    '</div>';
            }}
        }}

        // 介绍页面函数已移除

        // 格式化介绍内容
        // 格式化介绍内容函数已移除

        // 生成配置图例
        function generateConfigLegend(categorizedTerms, showSubspecs = true) {{
            return `
                <div class="config-legend">
                    <div class="legend-items">
                        <div class="legend-item">
                            <div class="legend-color route-map"></div>
                            <span>route-maps</span>
                        </div>
                        <div class="legend-item">
                            <div class="legend-color prefix-list"></div>
                            <span>prefix-lists</span>
                        </div>
                        <div class="legend-item">
                            <div class="legend-color community-list"></div>
                            <span>community-lists</span>
                        </div>
                        ${{showSubspecs ? `
                        <div class="legend-item">
                            <div class="legend-color line-level"></div>
                            <span>${{texts.lineLevelSubspecs}}</span>
                        </div>
                        <div class="legend-item">
                            <div class="legend-color config-level"></div>
                            <span>${{texts.fieldLevelSubspecs}}</span>
                        </div>
                        ` : ''}}
                    </div>
                </div>
            `;
        }}

        // 生成可折叠的配置区块
        function generateCollapsibleConfigs(configContent, configSubspecContent, lineSubspecContent, showSubspecs, highlightContent, configSubspecTransContent, lineSubspecTransContent) {{
            // 解析配置内容，分离不同路由器的配置
            const configs = parseConfigSections(configContent);
            
            // 生成配置图例
            const highlightTerms = highlightContent ? highlightContent.split('\\n').filter(term => term.trim()) : [];
            const categorizedTerms = categorizeConfigTerms(highlightTerms);
            const legend = generateConfigLegend(categorizedTerms, showSubspecs);
            
            const configBlocks = configs.map((config, index) => {{
                const routerName = config.router || `Router ${{index + 1}}`;
                const processedLines = processConfig(config.content, configSubspecContent, lineSubspecContent, showSubspecs, highlightContent, configSubspecTransContent, lineSubspecTransContent);
                const configId = `config-${{index}}`;
                
                return `
                    <div class="config-collapsible config-section" data-router="${{routerName}}">
                        <div class="config-header" onclick="toggleConfig('${{configId}}')">
                            <span class="config-caret" id="caret-${{configId}}">▶</span>
                            <span class="config-title">${{routerName}}</span>
                        </div>
                        <div class="config-content" id="${{configId}}">${{processedLines.map((line, lineIndex) => `<span class="config-line" data-line="${{lineIndex + 1}}">${{line}}</span>`).join('')}}</div>
                    </div>
                `;
            }}).join('');
            
            return legend + configBlocks;
        }}

        // 解析配置内容，分离不同路由器的配置
        function parseConfigSections(configContent) {{
            const lines = configContent.split('\\n');
            const configs = [];
            let currentConfig = null;
            
            for (let i = 0; i < lines.length; i++) {{
                const line = lines[i];
                // 检查是否是路由器配置分隔符
                if (line.includes('=== ') && line.includes(' CONFIG ===')) {{
                    // 保存之前的配置
                    if (currentConfig) {{
                        configs.push(currentConfig);
                    }}
                    
                    // 提取路由器名称
                    const routerMatch = line.match(/=== (.*?) CONFIG ===/);
                    const routerName = routerMatch ? routerMatch[1].trim() : `Router ${{configs.length + 1}}`;
                    
                    // 开始新的配置
                    currentConfig = {{
                        router: routerName,
                        content: ''
                    }};
                    
                    // 跳过标题后的空行（包括只包含空格的行）
                    let nextIndex = i + 1;
                    while (nextIndex < lines.length && lines[nextIndex].trim() === '') {{
                        nextIndex++;
                    }}
                    i = nextIndex - 1; // 循环会自动+1，所以这里-1
                    continue;
                }} else if (currentConfig) {{
                    // 添加到当前配置
                    // 如果配置内容为空且当前行是空行，跳过
                    if (currentConfig.content === '' && line.trim() === '') {{
                        continue;
                    }}
                    // 添加行到配置内容
                    if (currentConfig.content === '') {{
                        currentConfig.content = line;
                    }} else {{
                        currentConfig.content += '\\n' + line;
                    }}
                }} else {{
                    // 如果没有找到路由器标题，创建默认配置
                    if (configs.length === 0) {{
                        currentConfig = {{
                            router: 'Router 1',
                            content: line
                        }};
                    }} else {{
                        if (configs[configs.length - 1].content === '') {{
                            configs[configs.length - 1].content = line;
                        }} else {{
                            configs[configs.length - 1].content += '\\n' + line;
                        }}
                    }}
                }}
            }}
            
            // 添加最后一个配置
            if (currentConfig) {{
                configs.push(currentConfig);
            }}
            
            // 移除每个配置内容开头和结尾的空白行（包括只包含空格的行）
            for (const config of configs) {{
                if (config.content) {{
                    // 按行分割，移除只包含空白字符的行
                    const lines = config.content.split('\\n');
                    
                    // 找到第一个非空行的索引
                    let firstNonEmpty = 0;
                    for (let i = 0; i < lines.length; i++) {{
                        if (lines[i].trim() !== '') {{
                            firstNonEmpty = i;
                            break;
                        }}
                    }}
                    
                    // 找到最后一个非空行的索引
                    let lastNonEmpty = lines.length - 1;
                    for (let i = lines.length - 1; i >= 0; i--) {{
                        if (lines[i].trim() !== '') {{
                            lastNonEmpty = i;
                            break;
                        }}
                    }}
                    
                    // 重新组合，只保留非空行之间的内容
                    if (firstNonEmpty <= lastNonEmpty) {{
                        config.content = lines.slice(firstNonEmpty, lastNonEmpty + 1).join('\\n');
                    }} else {{
                        config.content = '';
                    }}
                }}
            }}
            
            return configs;
        }}

        // 切换配置显示/隐藏
        function toggleConfig(configId) {{
            const content = document.getElementById(configId);
            const caret = document.getElementById('caret-' + configId);
            
            if (content.classList.contains('expanded')) {{
                content.classList.remove('expanded');
                caret.classList.remove('expanded');
            }} else {{
                content.classList.add('expanded');
                caret.classList.add('expanded');
            }}
        }}

        // 格式化diff内容，添加颜色高亮
        // 处理配置引用，将 @@ R1 Configuration 2,4 @@ 或 @@ Configuration 2,4 @@ 转换为可交互元素
        function processConfigReferences(text) {{
            // 支持两种格式：
            // 1. @@ R1 Configuration 2,4 @@ (带路由器前缀)
            // 2. @@ Configuration 2,4 @@ (不带路由器前缀)
            const patternWithRouter = /@@\s+(R\d+)\s+Configuration\s+(\d+(?:,\d+)*)\s+@@/g;
            const patternWithoutRouter = /@@\s+Configuration\s+(\d+(?:,\d+)*)\s+@@/g;
            
            // 根据当前语言设置提示文本
            const isChinese = currentLanguage === 'zh';
            
            // 先处理带路由器前缀的
            text = text.replace(patternWithRouter, (match, router, lineRange) => {{
                const title = isChinese ? 
                    `点击高亮 ${{router}} 配置行 ${{lineRange}}` : 
                    `Click to highlight ${{router}} Configuration lines ${{lineRange}}`;
                return `<span class="config-reference" data-router="${{router}}" data-lines="${{lineRange}}" title="${{title}}">@@ ${{router}} Configuration ${{lineRange}} @@</span>`;
            }});
            
            // 再处理不带路由器前缀的
            text = text.replace(patternWithoutRouter, (match, lineRange) => {{
                const title = isChinese ? 
                    `点击高亮配置行 ${{lineRange}}` : 
                    `Click to highlight Configuration lines ${{lineRange}}`;
                return `<span class="config-reference" data-lines="${{lineRange}}" title="${{title}}">@@ Configuration ${{lineRange}} @@</span>`;
            }});
            
            return text;
        }}

        // 解析 subspec 数据（用于 options）
        function parseSubspecData(configSubspecContent, lineSubspecContent, configSubspecTransContent, lineSubspecTransContent) {{
            const configSubspecData = {{}};
            const configLines = (configSubspecContent || '').split('\\n');
            let currentVar = null;
            
            for (const line of configLines) {{
                if (line.startsWith('Config Variable:')) {{
                    currentVar = line.split('Config Variable: ')[1].trim();
                }} else if (line.trim().startsWith('1.') && currentVar) {{
                    const subspec = line.trim().substring(2).trim();
                    configSubspecData[currentVar] = subspec;
                }}
            }}
            
            const lineSubspecData = {{}};
            const lineSubspecNames = new Set();
            const lineLines = (lineSubspecContent || '').split('\\n');
            let currentLineGroup = null;
            
            for (const line of lineLines) {{
                if (line.startsWith('Line Group:')) {{
                    currentLineGroup = line.split('Line Group: ')[1].trim();
                    if (currentLineGroup) {{
                        lineSubspecNames.add(currentLineGroup);
                    }}
                }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                    const subspec = line.trim().substring(2).trim();
                    lineSubspecData[currentLineGroup] = subspec;
                }}
            }}
            
            const configSubspecTransData = {{}};
            if (configSubspecTransContent) {{
                const configTransLines = configSubspecTransContent.split('\\n');
                let currentVar = null;
                
                for (const line of configTransLines) {{
                    if (line.startsWith('Config Variable:')) {{
                        currentVar = line.split('Config Variable: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentVar) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        configSubspecTransData[currentVar] = subspecTrans;
                    }}
                }}
            }}
            
            const lineSubspecTransData = {{}};
            if (lineSubspecTransContent) {{
                const lineTransLines = lineSubspecTransContent.split('\\n');
                let currentLineGroup = null;
                
                for (const line of lineTransLines) {{
                    if (line.startsWith('Line Group:')) {{
                        currentLineGroup = line.split('Line Group: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        lineSubspecTransData[currentLineGroup] = subspecTrans;
                    }}
                }}
            }}
            
            const subspecData = {{...configSubspecData, ...lineSubspecData}};
            
            return {{
                subspecData,
                configSubspecData,
                lineSubspecData,
                lineSubspecNames,
                configSubspecTransData,
                lineSubspecTransData
            }};
        }}

        // 处理 options 文本，支持配置引用和 subspec
        // 只处理 [text](subspec) 格式，不处理单纯的 []
        function processOptionText(text, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs, configSubspecTransData, lineSubspecTransData) {{
            // HTML 转义函数，用于转义 HTML 属性值中的特殊字符
            function escapeHtmlForAttribute(html) {{
                if (!html) return '';
                return html
                    .replace(/&/g, '&amp;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
            }}
            
            // 先处理配置引用
            let processed = processConfigReferences(text);
            
            // 如果显示 subspec 且有 subspec 数据，处理 subspec
            // 使用更智能的方法处理嵌套方括号，如 [[400:100]](...)
            if (showSubspecs && subspecData && text.includes('[') && text.includes('](')) {{
                // 从右到左查找所有 ]( 位置，然后向前查找匹配的 [
                let result = processed;
                let lastIndex = result.length;
                
                // 从右到左查找所有 ]( 模式
                while (true) {{
                    const bracketParenIndex = result.lastIndexOf('](', lastIndex);
                    if (bracketParenIndex === -1) break;
                    
                    // 从 ]( 位置向前查找匹配的 [
                    let bracketCount = 0;
                    let startIndex = -1;
                    for (let i = bracketParenIndex; i >= 0; i--) {{
                        if (result[i] === ']') {{
                            bracketCount++;
                        }} else if (result[i] === '[') {{
                            bracketCount--;
                            if (bracketCount === 0) {{
                                startIndex = i;
                                break;
                            }}
                        }}
                    }}
                    
                    if (startIndex !== -1) {{
                        // 查找匹配的 )
                        let parenCount = 0;
                        let endIndex = -1;
                        for (let i = bracketParenIndex + 1; i < result.length; i++) {{
                            if (result[i] === '(') {{
                                parenCount++;
                            }} else if (result[i] === ')') {{
                                parenCount--;
                                if (parenCount === 0) {{
                                    endIndex = i;
                                    break;
                                }}
                            }}
                        }}
                        
                        if (endIndex !== -1) {{
                            const fieldName = result.substring(startIndex + 1, bracketParenIndex);
                            const subspecName = result.substring(bracketParenIndex + 2, endIndex);
                            
                            // 处理 subspec
                            // 检查 subspecName 是否真的存在于 subspecData 中
                            const isMissing = !(subspecName in subspecData);
                            const subspec = isMissing ? 'empty' : (subspecData[subspecName] || 'empty');
                            let displaySubspec;
                            
                            // 判断是config-level还是line-level subspec
                            if (subspecName in configSubspecData) {{
                                // Config-level: 将 Config_xxx 替换为 VAR，但对 ip/mask 字段特殊处理
                                displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                                    // 检查是否以 __ip 或 __mask 结尾
                                    if (match.endsWith('__ip')) {{
                                        return 'VAR_IP';
                                    }} else if (match.endsWith('__mask')) {{
                                        return 'VAR_MASK';
                                    }} else {{
                                        return 'VAR';
                                    }}
                                }});
                            }} else {{
                                // Line-level: 将 Config_xxx_Line_..._xxx 保留最后一个 _xxx 并转换为 VAR_XXX
                                displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                                    const parts = match.split('_');
                                    if (parts.length > 1) {{
                                        const lastPart = parts[parts.length - 1].toUpperCase();
                                        return `VAR_${{lastPart}}`;
                                    }}
                                    return 'VAR';
                                }});
                            }}
                            
                            // 获取转换后的subspec
                            let subspecTrans = null;
                            if (subspecName in configSubspecData && configSubspecTransData && subspecName in configSubspecTransData) {{
                                subspecTrans = configSubspecTransData[subspecName];
                            }} else if (subspecName in lineSubspecData && lineSubspecTransData && subspecName in lineSubspecTransData) {{
                                subspecTrans = lineSubspecTransData[subspecName];
                            }}
                            
                            // 构建完整的tooltip内容
                            let tooltipContent;
                            if (isMissing) {{
                                // 如果 subspec 不存在，显示 "none" 和 "No subspec found"
                                const missingText = currentLanguage === 'zh' ? '没有找到子规约' : 'No subspec found';
                                tooltipContent = '<div class="tooltip-translated">' + missingText + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">none</div>';
                            }} else {{
                                if (subspecTrans) {{
                                    // 翻译文本已经在 Python 中静态处理，添加了高亮标签
                                    tooltipContent = '<div class="tooltip-translated">' + subspecTrans + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">' + displaySubspec + '</div>';
                                }} else {{
                                    tooltipContent = '<div class="tooltip-formula">' + displaySubspec + '</div>';
                                }}
                            }}
                            
                            // 转义 tooltipContent 以便安全地插入到 HTML 属性中
                            const escapedTooltipContent = escapeHtmlForAttribute(tooltipContent);
                            
                            // 判断是 line-level 还是 config-level subspec
                            let cssClass = "config-field";
                            let isEmpty = (subspec === 'empty');
                            
                            if (lineSubspecNames && lineSubspecNames.has(subspecName)) {{
                                cssClass += " line-level";
                            }}
                            
                            if (isMissing) {{
                                // 如果 subspec 根本不存在，使用 missing-subspec 类（亮黄色）
                                cssClass += " missing-subspec";
                            }} else if (isEmpty) {{
                                // 如果 subspec 存在但值为 'empty'，使用 empty-subspec 类
                                cssClass += " empty-subspec";
                            }}
                            
                            const replacement = `<span class="${{cssClass}}" data-subspec="${{escapedTooltipContent}}" data-subspec-name="${{subspecName}}">${{fieldName}}</span>`;
                            result = result.substring(0, startIndex) + replacement + result.substring(endIndex + 1);
                            lastIndex = startIndex - 1;
                            continue;
                        }}
                    }}
                    
                    lastIndex = bracketParenIndex - 1;
                }}
                
                processed = result;
            }} else if (!showSubspecs && text.includes('[') && text.includes('](')) {{
                // 不显示subspec，直接移除标注
                // 使用同样的方法处理嵌套方括号
                let result = processed;
                let lastIndex = result.length;
                
                while (true) {{
                    const bracketParenIndex = result.lastIndexOf('](', lastIndex);
                    if (bracketParenIndex === -1) break;
                    
                    // 从 ]( 位置向前查找匹配的 [
                    let bracketCount = 0;
                    let startIndex = -1;
                    for (let i = bracketParenIndex; i >= 0; i--) {{
                        if (result[i] === ']') {{
                            bracketCount++;
                        }} else if (result[i] === '[') {{
                            bracketCount--;
                            if (bracketCount === 0) {{
                                startIndex = i;
                                break;
                            }}
                        }}
                    }}
                    
                    if (startIndex !== -1) {{
                        // 查找匹配的 )
                        let parenCount = 0;
                        let endIndex = -1;
                        for (let i = bracketParenIndex + 1; i < result.length; i++) {{
                            if (result[i] === '(') {{
                                parenCount++;
                            }} else if (result[i] === ')') {{
                                parenCount--;
                                if (parenCount === 0) {{
                                    endIndex = i;
                                    break;
                                }}
                            }}
                        }}
                        
                        if (endIndex !== -1) {{
                            const fieldName = result.substring(startIndex + 1, bracketParenIndex);
                            result = result.substring(0, startIndex) + fieldName + result.substring(endIndex + 1);
                            lastIndex = startIndex - 1;
                            continue;
                        }}
                    }}
                    
                    lastIndex = bracketParenIndex - 1;
                }}
                
                processed = result;
            }}
            
            // 处理空的 symbolic [config]<> 格式
            // 如果显示 subspec，则增加宽度但不设置背景颜色
            // 如果不显示 subspec，则直接移除
            if (text.includes('[') && text.includes(']<>')) {{
                let result = processed;
                let lastIndex = result.length;
                
                // 从右到左查找所有 ]<> 位置
                while (true) {{
                    const bracketAngleIndex = result.lastIndexOf(']<>', lastIndex);
                    if (bracketAngleIndex === -1) break;
                    
                    // 从 ]<> 位置向前查找匹配的 [
                    let bracketCount = 0;
                    let startIndex = -1;
                    for (let i = bracketAngleIndex; i >= 0; i--) {{
                        if (result[i] === ']') {{
                            bracketCount++;
                        }} else if (result[i] === '[') {{
                            bracketCount--;
                            if (bracketCount === 0) {{
                                startIndex = i;
                                break;
                            }}
                        }}
                    }}
                    
                    if (startIndex !== -1) {{
                        const fieldName = result.substring(startIndex + 1, bracketAngleIndex);
                        if (showSubspecs) {{
                            // 显示 subspec：创建一个空的 span，只增加宽度，不设置背景颜色
                            const replacement = `<span class="config-field-empty-spacer">${{fieldName}}</span>`;
                            result = result.substring(0, startIndex) + replacement + result.substring(bracketAngleIndex + 3);
                        }} else {{
                            // 不显示 subspec：直接移除 [config]<>，只保留内容
                            result = result.substring(0, startIndex) + fieldName + result.substring(bracketAngleIndex + 3);
                        }}
                        lastIndex = startIndex - 1;
                        continue;
                    }}
                    
                    lastIndex = bracketAngleIndex - 1;
                }}
                
                processed = result;
            }}
            
            // 处理 [[Config_X]<>] 或 [[Config_X](Config_X_xxx)] 格式，加上 [] 突出强调
            // 匹配 [[...]<>] 或 [[...](...)] 格式（双重方括号）
            processed = processed.replace(/\[\[([^\]]+)\](\<\>|\([^)]+\))\]/g, (match, innerContent, suffix) => {{
                // 在外层加上 [] 突出强调
                return `<span style="font-weight: bold; color: #0066cc;">[</span>${{innerContent}}${{suffix}}<span style="font-weight: bold; color: #0066cc;">]</span>`;
            }});
            
            return processed;
        }}

        function formatDiffContent(diffLines, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs, configSubspecTransData, lineSubspecTransData) {{
            if (typeof diffLines === 'string') {{
                diffLines = diffLines.split('\\n');
            }}
            
            // 如果没有提供 subspec 数据，使用默认处理（向后兼容）
            const hasSubspecData = subspecData && configSubspecData && lineSubspecData && lineSubspecNames;
            
            return diffLines.map(line => {{
                const trimmedLine = line.trim();
                let processedLine = line;
                
                // 处理 subspec 和配置引用
                if (hasSubspecData) {{
                    processedLine = processOptionText(line, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs !== undefined ? showSubspecs : true, configSubspecTransData, lineSubspecTransData);
                }} else {{
                    processedLine = processConfigReferences(line);
                }}
                
                if (trimmedLine.startsWith('-')) {{
                    // 删除的行 - 红色
                    return `<div class="diff-line diff-removed">${{processedLine}}</div>`;
                }} else if (trimmedLine.startsWith('+')) {{
                    // 添加的行 - 绿色
                    return `<div class="diff-line diff-added">${{processedLine}}</div>`;
                }} else if (trimmedLine.startsWith('@@') && trimmedLine.includes('Configuration')) {{
                    // diff提示行 - 转换为可交互的配置引用
                    return `<div class="diff-line diff-context">${{processedLine}}</div>`;
                }} else {{
                    // 普通行 - 默认颜色
                    return `<div class="diff-line diff-context">${{processedLine}}</div>`;
                }}
            }}).join('');
        }}

        // 开始实际测试
        function startActualTest() {{
            document.getElementById('testContent').style.display = 'block';
            showStartScreen();
        }}


        // Initialize test
        function initTest() {{
            // Auto-detect language from URL parameter or localStorage first
            detectLanguage();
            
            // Get participant ID (userNumber) from URL parameter or localStorage
            getParticipantId();
            
            // Update texts based on detected language
            texts = textConstants[currentLanguage];
            
            // Load initial questions for current language
            loadQuestionsForLanguage(currentLanguage);
            
            // Update language button states
            document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.remove('active'));
            const activeBtn = document.getElementById(`lang-${{currentLanguage}}`);
            if (activeBtn) {{
                activeBtn.classList.add('active');
            }}
            
            // Initialize fixed bar state after texts are loaded
            initFixedBarState();
            
            // Show start screen first, then update UI texts
            showStartScreen(); // Show start screen first
            updateUITexts(); // Initialize UI texts after start screen is shown
        }}

        // Show question
        function showQuestion(index) {{
            const questionIndex = index;
            
            if (questionIndex >= questions.length) {{
                showCompletionScreen();
                return;
            }}

            currentQuestionIndex = questionIndex;
            const question = questions[questionIndex];
            // 调整 groupConfig 索引
            const showSubspecs = groupConfig[userGroup][questionIndex];
            
            // 重置 bit-map 状态
            resetConfigReferenceBitMap();
            
            // 更新进度（总共 5 个问题：question0 + question1-4）
            document.getElementById('currentQuestion').textContent = questionIndex + 1;
            document.getElementById('progressBar').style.width = ((questionIndex + 1) / 5) * 100 + '%';
            
            try {{
                // 生成问题HTML
                const questionHtml = generateQuestionHTML(question, showSubspecs);
                document.getElementById('testContent').innerHTML = questionHtml;
                
                // Hide language switcher during questions
                hideLanguageSwitcher();
                
                // Show fixed bar toggle button on question pages
                toggleFixedBarButton(true);
                
                // Reset fixed bar state to enabled (default state for each question page)
                resetFixedBarState();
                
                // 重置题目计时
                questionStartTime = Date.now();
                document.getElementById('questionTimer').textContent = '00:00';
            }} catch (error) {{
                console.error('显示问题时出错:', error, question);
                // 显示错误信息
                document.getElementById('testContent').innerHTML = `
                    <div class="error-message">
                        <h3>加载问题失败</h3>
                        <p>问题 ${{index + 1}} 加载时出现错误，请刷新页面重试。</p>
                        <button onclick="location.reload()">刷新页面</button>
                    </div>
                `;
            }}
            
            // 添加事件监听器
            addQuestionEventListeners();
            
            // 更新配置引用的提示文本
            updateConfigReferenceTooltips();
            
            // 更新固定工具栏内容
            updateFixedTopBar(question);
            
            // 初始化滚动检测
            initScrollDetection();
            
            // 滚动到页面顶部
            window.scrollTo(0, 0);
        }}
        
        // Coursera functions removed - now in separate coursera_en.html and coursera_zh.html files
        
        // Generate question HTML
        function generateQuestionHTML(question, showSubspecs) {{
            const processedConfig = processConfig(question.config, question.configSubspec, question.lineSubspec, showSubspecs, question.highlight, question.configSubspecTrans, question.lineSubspecTrans);
            const questionData = parseQuestion(question.question);
            
            // 解析 subspec 数据用于处理 options
            const subspecParsed = parseSubspecData(question.configSubspec, question.lineSubspec, question.configSubspecTrans, question.lineSubspecTrans);
            
            // 处理 options 文本，支持 subspec
            const processedOptions = questionData.options.map(option => {{
                // 检查是否是 diff 格式（包含 - 或 + 开头的行）
                const lines = option.text.split('\\n');
                const isDiff = lines.some(line => line.trim().startsWith('-') || line.trim().startsWith('+'));
                
                if (isDiff) {{
                    // diff 格式：使用 formatDiffContent
                    const processedText = formatDiffContent(lines, subspecParsed.subspecData, subspecParsed.configSubspecData, subspecParsed.lineSubspecData, subspecParsed.lineSubspecNames, showSubspecs, subspecParsed.configSubspecTransData, subspecParsed.lineSubspecTransData);
                    return {{...option, text: processedText}};
                }} else {{
                    // 普通文本：使用 processOptionText
                    const processedText = processOptionText(option.text, subspecParsed.subspecData, subspecParsed.configSubspecData, subspecParsed.lineSubspecData, subspecParsed.lineSubspecNames, showSubspecs, subspecParsed.configSubspecTransData, subspecParsed.lineSubspecTransData);
                    return {{...option, text: processedText}};
                }}
            }});
            
            return `
                <!-- Four-panel layout -->
                <div class="question-layout">
                    <!-- Top-left: Network Topology -->
                    <div class="section panel-topology">
                        <h2>${{texts.networkTopology}}</h2>
                    <div class="topology-image">
                            <img src="${{questionImages[currentLanguage][currentQuestionIndex]}}" alt="${{texts.networkTopology}}" />
                    </div>
                </div>

                    <!-- Top-right: Network Specification -->
                    <div class="section panel-specification">
                        <h2>${{currentQuestionIndex === 0 ? texts.networkSpecQuestion0 : texts.networkSpec}}</h2>
                        <div class="specification-text">
                        ${{question.spec}}
                    </div>
                </div>

                    <!-- Bottom-left: Configuration Display -->
                    <div class="section panel-config">
                        <h2>${{showSubspecs ? texts.coreConfigWithSubspecs : texts.coreConfig}}</h2>
                        ${{generateCollapsibleConfigs(question.config, question.configSubspec, question.lineSubspec, showSubspecs, question.highlight, question.configSubspecTrans, question.lineSubspecTrans)}}
                </div>

                    <!-- Bottom-right: Question Section -->
                    <div class="section panel-questions">
                        <h2>${{texts.maintenanceTask}}</h2>
                        <div class="question-text">
                            ${{questionData.text}}
                        </div>
                        
                        ${{questionData.note ? `<div class="question-instruction note-instruction">
                            <div class="instruction-line">${{questionData.note}}</div>
                        </div>` : ''}}
                        
                        ${{showSubspecs ? `<div class="question-instruction">
                            <div class="instruction-line">📋 ${{texts.questionNote1}}</div>
                            <div class="instruction-line">📋 ${{texts.questionNote2}}</div>
                        </div>` : ''}}
                        
                        <div class="question-options">
                            ${{processedOptions.map((option, i) => `
                                <div class="option-item">
                                    <input type="checkbox" id="${{option.id}}" name="options" value="${{option.value}}">
                                    <div class="option-content-wrapper">
                                        <div class="option-diff-content">${{option.text}}</div>
                                    </div>
                                </div>
                            `).join('')}}
                        </div>
                        
                        <!-- User Notes Section -->
                        <div class="user-notes">
                            <h4>${{texts.userNotes}}</h4>
                            <textarea id="userNotes${{currentQuestionIndex}}" placeholder="${{texts.userNotesPlaceholder}}"></textarea>
                        </div>
                        
                        <div class="btn-container">
                            <button class="btn btn-primary" onclick="nextQuestion()" id="nextBtn">${{texts.nextQuestion}}</button>
                        </div>
                    </div>
                </div>
            `;
        }}

        // 分类配置术语
        function categorizeConfigTerms(highlightTerms) {{
            const routeMaps = [];
            const prefixLists = [];
            const communityLists = [];
            const otherTerms = [];
            
            for (const term of highlightTerms) {{
                const trimmedTerm = term.trim();
                if (!trimmedTerm) continue;
                
                // 路由策略模式：R1_IN_FROM_ISP1, R2_OUT_TO_R3 等
                if (/R\\d+_(IN|OUT)_(FROM|TO)_\\w+/.test(trimmedTerm)) {{
                    routeMaps.push(trimmedTerm);
                }}
                // 前缀列表模式：isp1_network, private_ips, network_10_0_0_0 等
                else if (/(default_ips|isp\\d+_network|other_network|private_ips|network_\\d+_\\d+_\\d+_\\d+)/.test(trimmedTerm)) {{
                    prefixLists.push(trimmedTerm);
                }}
                // 社区列表模式：纯数字
                else if (/^\\d+$/.test(trimmedTerm)) {{
                    communityLists.push(trimmedTerm);
                }}
                else {{
                    otherTerms.push(trimmedTerm);
                }}
            }}
            
            return {{
                routeMaps: routeMaps,
                prefixLists: prefixLists,
                communityLists: communityLists,
                otherTerms: otherTerms
            }};
        }}

        // 应用数字高亮
        function applyNumberHighlighting(line) {{
            let processedLine = line;
            
            // 避免高亮已经被subspec标记的内容
            // 使用更健壮的subspec保护机制
            const subspecPlaceholders = {{}};
            let placeholderCounter = 0;
            
            // 使用回调函数来替换subspec，确保每个subspec都有唯一占位符
            const subspecPattern = /<span class="[^"]*" data-subspec="[^"]*" data-subspec-name="[^"]*">.*?<\/span>/g;
            processedLine = processedLine.replace(subspecPattern, (match) => {{
                const placeholder = `__SUBSPEC_PLACEHOLDER_${{placeholderCounter}}__`;
                subspecPlaceholders[placeholder] = match;
                placeholderCounter++;
                return placeholder;
            }});
            
            // 数字高亮模式 - 只在非subspec区域应用
            // 1. seq xxx - 序列号（保留原始空格数量）
            processedLine = processedLine.replace(/\\bseq(\\s+)(\\d+)\\b/g, (match, spaces, number) => {{
                return `seq${{spaces}}<span class="highlight-number">${{number}}</span>`;
            }});
            
            // 2. ge xxx, le xxx, eq xxx - 长度操作符（保留原始空格数量）
            processedLine = processedLine.replace(/\\b(ge|le|eq)(\\s+)(\\d+)\\b/g, (match, op, spaces, number) => {{
                return `${{op}}${{spaces}}<span class="highlight-number">${{number}}</span>`;
            }});
            
            // 3. x.x.x.x/x - IP地址/掩码中的数字
            processedLine = processedLine.replace(/\\b(\\d+\\.\\d+\\.\\d+\\.\\d+)\\/(\\d+)\\b/g, '<span class="highlight-number">$1</span>/<span class="highlight-number">$2</span>');
            
            // 4. xxx:xxx - 社区值中的数字
            processedLine = processedLine.replace(/\\b(\\d+):(\\d+)\\b/g, '<span class="highlight-number">$1</span>:<span class="highlight-number">$2</span>');
            
            // 5. permit xxx, deny xxx - 操作符后的数字（保留原始空格数量）
            processedLine = processedLine.replace(/\\b(permit|deny)(\\s+)(\\d+)\\b/g, (match, op, spaces, number) => {{
                return `${{op}}${{spaces}}<span class="highlight-number">${{number}}</span>`;
            }});
            
            // 恢复subspec标记的内容
            for (const [placeholder, original] of Object.entries(subspecPlaceholders)) {{
                processedLine = processedLine.replace(placeholder, original);
            }}
            
            return processedLine;
        }}

        // 应用分类高亮
        function applyCategorizedHighlighting(line, categorizedTerms) {{
            let processedLine = line;
            
            // 路由策略 - 蓝色高亮
            for (const term of categorizedTerms.routeMaps) {{
                if (term.trim()) {{
                    const highlightPattern = new RegExp('\\\\b' + term.trim().replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'gi');
                    processedLine = processedLine.replace(highlightPattern, `<span class="highlight-route-map">${{term.trim()}}</span>`);
                }}
            }}
            
            // 前缀列表 - 绿色高亮
            for (const term of categorizedTerms.prefixLists) {{
                if (term.trim()) {{
                    const highlightPattern = new RegExp('\\\\b' + term.trim().replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'gi');
                    processedLine = processedLine.replace(highlightPattern, `<span class="highlight-prefix-list">${{term.trim()}}</span>`);
                }}
            }}
            
            // 社区列表 - 橙色高亮
            for (const term of categorizedTerms.communityLists) {{
                if (term.trim()) {{
                    const highlightPattern = new RegExp('\\\\b' + term.trim().replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'gi');
                    processedLine = processedLine.replace(highlightPattern, `<span class="highlight-community-list">${{term.trim()}}</span>`);
                }}
            }}
            
            // 其他术语 - 黄色高亮（保持原有样式）
            for (const term of categorizedTerms.otherTerms) {{
                if (term.trim()) {{
                    const highlightPattern = new RegExp('\\\\b' + term.trim().replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'gi');
                    processedLine = processedLine.replace(highlightPattern, `<span class="highlight-term">${{term.trim()}}</span>`);
                }}
            }}
            
            // 应用数字高亮（在分类高亮之后，确保优先级）
            processedLine = applyNumberHighlighting(processedLine);
            
            return processedLine;
        }}

        // 处理配置
        function processConfig(configContent, configSubspecContent, lineSubspecContent, showSubspecs, highlightContent, configSubspecTransContent, lineSubspecTransContent) {{
            // 解析config-level subspec数据
            const configSubspecData = {{}};
            const configLines = configSubspecContent.split('\\n');
            let currentVar = null;
            
            for (const line of configLines) {{
                if (line.startsWith('Config Variable:')) {{
                    currentVar = line.split('Config Variable: ')[1].trim();
                }} else if (line.trim().startsWith('1.') && currentVar) {{
                    const subspec = line.trim().substring(2).trim();
                    configSubspecData[currentVar] = subspec;
                }}
            }}
            
            // 解析line-level subspec数据
            const lineSubspecData = {{}};
            const lineSubspecNames = new Set(); // 存储所有line-level subspec名称，包括empty的
            const lineLines = lineSubspecContent.split('\\n');
            let currentLineGroup = null;
            
            for (const line of lineLines) {{
                if (line.startsWith('Line Group:')) {{
                    currentLineGroup = line.split('Line Group: ')[1].trim();
                    // 将所有line group名称添加到集合中，无论内容是否为empty
                    if (currentLineGroup) {{
                        lineSubspecNames.add(currentLineGroup);
                    }}
                }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                    const subspec = line.trim().substring(2).trim();
                    lineSubspecData[currentLineGroup] = subspec;
                }}
            }}
            
            // 解析转换后的config-level subspec数据
            const configSubspecTransData = {{}};
            if (configSubspecTransContent) {{
                const configTransLines = configSubspecTransContent.split('\\n');
                let currentVar = null;
                
                for (const line of configTransLines) {{
                    if (line.startsWith('Config Variable:')) {{
                        currentVar = line.split('Config Variable: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentVar) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        configSubspecTransData[currentVar] = subspecTrans;
                    }}
                }}
            }}
            
            // 解析转换后的line-level subspec数据
            const lineSubspecTransData = {{}};
            if (lineSubspecTransContent) {{
                const lineTransLines = lineSubspecTransContent.split('\\n');
                let currentLineGroup = null;
                
                for (const line of lineTransLines) {{
                    if (line.startsWith('Line Group:')) {{
                        currentLineGroup = line.split('Line Group: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        lineSubspecTransData[currentLineGroup] = subspecTrans;
                    }}
                }}
            }}
            
            // 合并两种subspec数据
            const subspecData = {{...configSubspecData, ...lineSubspecData}};
            
            // 解析并分类高亮术语
            const highlightTerms = highlightContent ? highlightContent.split('\\n').filter(term => term.trim()) : [];
            const categorizedTerms = categorizeConfigTerms(highlightTerms);
            
            // 处理配置内容，过滤掉空白行
            const processedLines = [];
            const lines = configContent.split('\\n');
            
            // 找到第一个非空行的索引
            let firstNonEmptyIndex = 0;
            for (let i = 0; i < lines.length; i++) {{
                if (lines[i].trim() !== '') {{
                    firstNonEmptyIndex = i;
                    break;
                }}
            }}
            
            // 找到最后一个非空行的索引
            let lastNonEmptyIndex = lines.length - 1;
            for (let i = lines.length - 1; i >= 0; i--) {{
                if (lines[i].trim() !== '') {{
                    lastNonEmptyIndex = i;
                    break;
                }}
            }}
            
            // 只处理非空行范围内的内容
            for (let i = firstNonEmptyIndex; i <= lastNonEmptyIndex; i++) {{
                const line = lines[i];
                // 跳过空行和只包含空白字符的行
                if (line.trim() === '') {{
                    continue;
                }}
                if (line.includes('[') && line.includes('](')) {{
                    const processedLine = processConfigLine(line, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs, categorizedTerms, configSubspecTransData, lineSubspecTransData);
                    processedLines.push(processedLine);
                }} else {{
                    // 即使没有subspec，也要应用分类高亮
                    // 首先处理行号
                    let processedLine = processLineNumber(line);
                    processedLine = applyCategorizedHighlighting(processedLine, categorizedTerms);
                    processedLines.push(processedLine);
                }}
            }}
            
            return processedLines;
        }}

        // 处理行号，将行号部分用深灰色样式包裹
        function processLineNumber(line) {{
            // 匹配行号模式：开头可能有空格，然后是数字，再是至少一个空格，然后是内容
            // 例如：` 1 !!!` 或 `10 route-map`
            const pattern = /^(\\s*)(\\d+)(\\s+)(.*)$/;
            const match = line.match(pattern);
            if (match) {{
                const leadingSpaces = match[1];
                const lineNumber = match[2];
                const trailingSpaces = match[3];
                const content = match[4];
                return `${{leadingSpaces}}<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{content}}`;
            }}
            return line;
        }}

        // 处理配置行
        function processConfigLine(line, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs, categorizedTerms, configSubspecTransData, lineSubspecTransData) {{
            // HTML 转义函数，用于转义 HTML 属性值中的特殊字符
            function escapeHtmlForAttribute(html) {{
                if (!html) return '';
                return html
                    .replace(/&/g, '&amp;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
            }}
            
            // 首先处理行号
            let processedLine = processLineNumber(line);
            
            if (!showSubspecs) {{
                // 不显示subspec，直接移除标注
                processedLine = processedLine.replace(/\\[([^\\]]+)\\]\\([^)]+\\)/g, '$1');
            }} else {{
                // 显示subspec
                processedLine = processedLine.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, (match, fieldName, subspecName) => {{
                    // 检查 subspecName 是否真的存在于 subspecData 中
                    const isMissing = !(subspecName in subspecData);
                    const subspec = isMissing ? 'empty' : (subspecData[subspecName] || 'empty');
                    let displaySubspec;
                    
                    if (subspecName in configSubspecData) {{
                        // Config-level: 将 Config_xxx 替换为 VAR，但对 ip/mask 字段特殊处理
                        displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                            // 检查是否以 __ip 或 __mask 结尾
                            if (match.endsWith('__ip')) {{
                                return 'VAR_IP';
                            }} else if (match.endsWith('__mask')) {{
                                return 'VAR_MASK';
                            }} else {{
                                return 'VAR';
                            }}
                        }});
                    }} else {{
                        // Line-level: 将 Config_xxx_Line_..._xxx 保留最后一个 _xxx 并转换为 VAR_XXX
                        displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                            const parts = match.split('_');
                            if (parts.length > 1) {{
                                const lastPart = parts[parts.length - 1].toUpperCase();
                                return `VAR_${{lastPart}}`;
                            }}
                            return 'VAR';
                        }});
                    }}
                    
                    // 获取转换后的subspec
                    let subspecTrans = null;
                    if (subspecName in configSubspecData && configSubspecTransData && subspecName in configSubspecTransData) {{
                        subspecTrans = configSubspecTransData[subspecName];
                    }} else if (subspecName in lineSubspecData && lineSubspecTransData && subspecName in lineSubspecTransData) {{
                        subspecTrans = lineSubspecTransData[subspecName];
                    }}
                    
                    // 构建完整的tooltip内容
                    let tooltipContent;
                    if (isMissing) {{
                        // 如果 subspec 不存在，显示 "none" 和 "No subspec found"
                        const missingText = currentLanguage === 'zh' ? '没有找到子规约' : 'No subspec found';
                        tooltipContent = '<div class="tooltip-translated">' + missingText + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">none</div>';
                    }} else {{
                        if (subspecTrans) {{
                            // 翻译文本已经在 Python 中静态处理，添加了高亮标签
                            tooltipContent = '<div class="tooltip-translated">' + subspecTrans + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">' + displaySubspec + '</div>';
                        }} else {{
                            tooltipContent = '<div class="tooltip-formula">' + displaySubspec + '</div>';
                        }}
                    }}
                    
                    // 转义 tooltipContent 以便安全地插入到 HTML 属性中
                    const escapedTooltipContent = escapeHtmlForAttribute(tooltipContent);
                    
                    // 判断是 line-level 还是 config-level subspec
                    let cssClass = "config-field";
                    let isEmpty = (subspec === 'empty');
                    
                    if (lineSubspecNames.has(subspecName)) {{
                        cssClass += " line-level";
                    }}
                    
                    if (isMissing) {{
                        // 如果 subspec 根本不存在，使用 missing-subspec 类（亮黄色）
                        cssClass += " missing-subspec";
                    }} else if (isEmpty) {{
                        // 如果 subspec 存在但值为 'empty'，使用 empty-subspec 类
                        cssClass += " empty-subspec";
                    }}
                    
                    return `<span class="${{cssClass}}" data-subspec="${{escapedTooltipContent}}" data-subspec-name="${{subspecName}}">${{fieldName}}</span>`;
                }});
            }}
            
            // 应用分类高亮
            if (categorizedTerms) {{
                processedLine = applyCategorizedHighlighting(processedLine, categorizedTerms);
            }}
            
            return processedLine;
        }}

        // 解析问题
        function parseQuestion(questionContent) {{
            try {{
                const lines = questionContent.split('\\n');
                let questionText = "";
                const options = [];
                let noteContent = null;
                let currentOption = null;
                let currentDiff = [];
                let inNoteBlock = false;
                const noteLines = [];
                
                for (const line of lines) {{
                    const originalLine = line;
                    const trimmedLine = line.trim();
                    
                    if (trimmedLine.startsWith('```note')) {{
                        // 开始 note 代码块
                        inNoteBlock = true;
                        noteLines.length = 0;
                    }} else if (trimmedLine.startsWith('```') && inNoteBlock) {{
                        // note 代码块结束
                        inNoteBlock = false;
                        if (noteLines.length > 0) {{
                            noteContent = noteLines.join('\\n');
                        }}
                    }} else if (inNoteBlock) {{
                        // note 内容（保留原始格式）
                        noteLines.push(originalLine);
                    }} else if (!trimmedLine) {{
                        continue;
                    }} else if (trimmedLine.startsWith('option') && trimmedLine.includes(':')) {{
                        // 处理选项
                        if (currentOption !== null) {{
                            // 保存前一个选项
                            const optionText = formatDiffContent(currentDiff);
                            const optionId = `option${{options.length + 1}}`;
                            const optionValue = `option_${{options.length + 1}}`;
                            options.push({{
                                id: optionId,
                                value: optionValue,
                                text: optionText,
                                correct: currentOption === 'yes'
                            }});
                        }}
                        
                        // 解析新选项
                        const parts = trimmedLine.split(':');
                        if (parts.length >= 2) {{
                            const isCorrect = parts[1].includes('[yes]');
                            currentOption = isCorrect ? 'yes' : 'no';
                            currentDiff = [];
                        }}
                    }} else if (trimmedLine.startsWith('```diff')) {{
                        currentDiff = [];
                    }} else if (trimmedLine.startsWith('```')) {{
                        // 代码块结束
                    }} else if (trimmedLine.startsWith('-') || trimmedLine.startsWith('+')) {{
                        // diff内容
                        currentDiff.push(line);
                    }} else if (currentOption !== null && !trimmedLine.startsWith('option') && !trimmedLine.startsWith('```')) {{
                        // 在选项解析过程中，添加普通代码内容
                        currentDiff.push(line);
                    }} else if (!trimmedLine.startsWith('option') && !trimmedLine.startsWith('```')) {{
                        // 问题描述
                        if (!questionText) {{
                            questionText = trimmedLine;
                        }}
                    }}
                }}
                
                // 处理最后一个选项
                if (currentOption !== null) {{
                    const optionText = formatDiffContent(currentDiff);
                    const optionId = `option${{options.length + 1}}`;
                    const optionValue = `option_${{options.length + 1}}`;
                    options.push({{
                        id: optionId,
                        value: optionValue,
                        text: optionText,
                        correct: currentOption === 'yes'
                    }});
                }}
                
                // 验证解析结果
                if (!questionText) {{
                    console.error('解析问题文本失败:', questionContent);
                    questionText = '问题解析失败';
                }}
                
                if (options.length === 0) {{
                    console.error('解析选项失败:', questionContent);
                    // 添加默认选项
                    for (let i = 1; i <= 3; i++) {{
                        options.push({{
                            id: `option${{i}}`,
                            value: `option_${{i}}`,
                            text: `选项 ${{i}} 解析失败`,
                            correct: i === 3 // 默认第三个选项正确
                        }});
                    }}
                }}
                
                return {{ text: questionText, options, note: noteContent }};
            }} catch (error) {{
                console.error('解析问题内容时出错:', error, questionContent);
                // 返回默认内容
                return {{
                    text: '问题解析失败',
                    options: [
                        {{ id: 'option1', value: 'option_1', text: '选项1解析失败', correct: false }},
                        {{ id: 'option2', value: 'option_2', text: '选项2解析失败', correct: false }},
                        {{ id: 'option3', value: 'option_3', text: '选项3解析失败', correct: true }}
                    ]
                }};
            }}
        }}

        // 添加问题事件监听器
        function addQuestionEventListeners() {{
            // 添加subspec tooltip事件
            // 先清理之前的事件，然后重新绑定
            removeHoverEvents();
            addHoverEvents();
            
            // 添加配置引用点击事件
            addConfigReferenceListeners();
            
            // 添加选项变化监听
            const checkboxes = document.querySelectorAll('input[name="options"]');
            const nextBtn = document.getElementById('nextBtn');
            
            checkboxes.forEach(checkbox => {{
                checkbox.addEventListener('change', () => {{
                    // Allow proceeding even with no selections (some questions may have no correct answers)
                    nextBtn.disabled = false;
                }});
            }});
        }}

        // Bit-map 机制：跟踪每个配置引用的状态
        let configReferenceBitMap = new Map(); // key: "router-lines", value: {{optionId, isActive}}
        let currentActiveOption = null; // 当前激活的选项ID
        
        // 生成配置引用的唯一标识（包含选项ID）
        function getConfigRefId(router, lines, optionId) {{
            return `${{optionId}}-${{router}}-${{lines}}`;
        }}
        
        // 获取配置引用所在的选项ID
        function getOptionId(element) {{
            const option = element.closest('.option-item, .answer-option');
            if (option) {{
                // 首先尝试从 input 元素获取 id
                const input = option.querySelector('input[type="checkbox"]');
                if (input && input.id) {{
                    return input.id;
                }}
                
                // 然后尝试使用 option 元素的 id 属性
                if (option.id) {{
                    return option.id;
                }}
                
                // 如果没有 id，使用 data-option-id 属性
                if (option.getAttribute('data-option-id')) {{
                    return option.getAttribute('data-option-id');
                }}
                
                // 最后使用类名
                return option.className;
            }}
            return null;
        }}
        
        // 检查配置引用是否已激活
        function isConfigRefActive(router, lines, optionId) {{
            const refId = getConfigRefId(router, lines, optionId);
            return configReferenceBitMap.has(refId) && configReferenceBitMap.get(refId).isActive;
        }}
        
        // 激活配置引用
        function activateConfigRef(router, lines, optionId) {{
            const refId = getConfigRefId(router, lines, optionId);
            configReferenceBitMap.set(refId, {{ optionId, isActive: true }});
        }}
        
        // 停用配置引用
        function deactivateConfigRef(router, lines, optionId) {{
            const refId = getConfigRefId(router, lines, optionId);
            if (configReferenceBitMap.has(refId)) {{
                configReferenceBitMap.delete(refId);
            }}
        }}
        
        // 清除指定选项的所有配置引用
        function clearOptionConfigRefs(optionId, containerElement) {{
            const refsToRemove = [];
            // 先收集所有需要清除的配置引用信息
            for (let [refId, data] of configReferenceBitMap) {{
                if (data.optionId === optionId) {{
                    refsToRemove.push(refId);
                }}
            }}
            // 先停用所有配置引用（从 Map 中删除），这样 clearConfigLinesHighlight 就不会保留它们的高亮
            refsToRemove.forEach(refId => {{
                configReferenceBitMap.delete(refId);
            }});
            // 然后清除所有对应的高亮（使用 forceClear = true 强制清除，忽略其他选项的配置引用）
            refsToRemove.forEach(refId => {{
                const parts = refId.split('-');
                const router = parts[1];
                const lines = parts[2];
                // 如果提供了 containerElement，使用它；否则在整个文档中清除
                // forceClear = true 表示强制清除，即使与其他选项的配置引用重叠
                clearConfigLinesHighlight(router, lines, containerElement || null, true);
            }});
        }}
        
        // 清除所有配置引用
        function clearAllConfigRefs() {{
            configReferenceBitMap.clear();
            clearAllHighlights();
        }}
        
        // 清除特定配置行的高亮
        function clearConfigLinesHighlight(router, lineRange, containerElement, forceClear = false) {{
            const [startLine, endLine] = lineRange.split(',').map(num => parseInt(num.trim()));
            // 如果提供了 containerElement，在该容器内查找；否则在整个文档中查找
            const searchContainer = containerElement || document;
            const configSection = searchContainer.querySelector(`.config-section[data-router="${{router}}"]`);
            if (!configSection) return;
            
            // 收集所有其他激活的配置引用（同一个 router，同一个 optionId）
            // 注意：当前配置引用已经在调用此函数之前被 deactivateConfigRef 移除了
            // 如果 forceClear 为 true，则忽略其他激活的配置引用，强制清除
            const otherActiveRefs = [];
            if (!forceClear) {{
                for (let [refId, data] of configReferenceBitMap) {{
                    if (data.isActive) {{
                        const parts = refId.split('-');
                        const refRouter = parts[1];
                        const refLines = parts[2];
                        const refOptionId = data.optionId;
                        // 检查是否是同一个 router（如果 router 为 null，则匹配所有 router）
                        if (refRouter === router || (!router && refRouter)) {{
                            otherActiveRefs.push({{router: refRouter, lines: refLines, optionId: refOptionId}});
                        }}
                    }}
                }}
            }}
            
            // 辅助函数：检查行号是否在其他激活的配置引用的范围内
            function isLineInOtherActiveRefs(lineNum) {{
                if (forceClear) {{
                    // 强制清除模式：忽略其他激活的配置引用
                    return false;
                }}
                for (const ref of otherActiveRefs) {{
                    const [refStartLine, refEndLine] = ref.lines.split(',').map(num => parseInt(num.trim()));
                    if (lineNum >= refStartLine && lineNum <= refEndLine) {{
                        return true;
                    }}
                }}
                return false;
            }}
            
            const configLines = configSection.querySelectorAll('.config-line');
            configLines.forEach((line) => {{
                // 尝试从行内容中提取实际行号
                const lineNumberSpan = line.querySelector('.config-line-number');
                let actualLineNumber = null;
                if (lineNumberSpan) {{
                    actualLineNumber = parseInt(lineNumberSpan.textContent.trim());
                }} else {{
                    actualLineNumber = parseInt(line.getAttribute('data-line'));
                }}
                
                if (actualLineNumber && actualLineNumber >= startLine && actualLineNumber <= endLine) {{
                    // 检查该行是否还在其他激活的配置引用的范围内
                    if (!isLineInOtherActiveRefs(actualLineNumber)) {{
                        // 该行不在其他激活的配置引用的范围内，可以清除高亮
                        line.classList.remove('config-line-highlighted');
                        line.classList.remove('config-line-highlighted-removed');
                        line.classList.remove('config-line-highlighted-added');
                        
                        // 恢复原始内容（如果之前保存过）
                        if (line.hasAttribute('data-original-html')) {{
                            line.innerHTML = line.getAttribute('data-original-html');
                            line.removeAttribute('data-original-html');
                        }}
                    }}
                    // 如果该行还在其他激活的配置引用的范围内，保留高亮（不做任何操作）
                }}
            }});
            
            // 也检查diff行
            const diffLines = configSection.querySelectorAll('.diff-line');
            diffLines.forEach((line, index) => {{
                const lineNumber = index + 1;
                if (lineNumber >= startLine && lineNumber <= endLine) {{
                    // 检查该行是否还在其他激活的配置引用的范围内
                    if (!isLineInOtherActiveRefs(lineNumber)) {{
                        // 该行不在其他激活的配置引用的范围内，可以清除高亮
                        line.classList.remove('config-line-highlighted');
                        line.classList.remove('config-line-highlighted-removed');
                        line.classList.remove('config-line-highlighted-added');
                        
                        // 恢复原始内容（如果之前保存过）
                        if (line.hasAttribute('data-original-html')) {{
                            line.innerHTML = line.getAttribute('data-original-html');
                            line.removeAttribute('data-original-html');
                        }}
                    }}
                    // 如果该行还在其他激活的配置引用的范围内，保留高亮（不做任何操作）
                }}
            }});
            
            // 移除新增行显示（只移除不在其他激活的配置引用的范围内的新增行）
            // 注意：我们需要检查新增行对应的原始行号是否在其他激活的配置引用范围内
            configSection.querySelectorAll('.config-line-added-display').forEach(el => {{
                const lineNum = parseInt(el.getAttribute('data-line'));
                if (lineNum && lineNum >= startLine && lineNum <= endLine) {{
                    // 检查该行是否还在其他激活的配置引用的范围内
                    if (!isLineInOtherActiveRefs(lineNum)) {{
                        // 该行不在其他激活的配置引用的范围内，可以删除
                        el.remove();
                    }}
                }}
            }});
            
            // 注意：不再重新应用其他激活的配置引用的高亮
            // 每个配置引用独立管理自己的高亮状态，互不影响
            // 如果行在其他激活的配置引用范围内，我们已经保留了它们的高亮状态
        }}
        
        // 展开多个设备的配置下拉栏（智能优化版本）
        function expandMultipleDeviceConfigs(routers, containerElement) {{
            const uniqueRouters = [...new Set(routers)];
            // 如果提供了 containerElement，在该容器内查找；否则在整个文档中查找
            const searchContainer = containerElement || document;
            
            // 检查哪些设备配置已经展开
            const alreadyExpandedRouters = [];
            const needToExpandRouters = [];
            
            uniqueRouters.forEach(router => {{
                const targetSection = searchContainer.querySelector(`.config-section[data-router="${{router}}"]`);
                if (targetSection) {{
                    const targetContent = targetSection.querySelector('.config-content');
                    if (targetContent && targetContent.classList.contains('expanded')) {{
                        alreadyExpandedRouters.push(router);
                    }} else {{
                        needToExpandRouters.push(router);
                    }}
                }}
            }});
            
            // 如果所有需要的设备都已经展开，检查是否有其他设备需要关闭
            if (needToExpandRouters.length === 0) {{
                // 关闭所有不在目标列表中的已展开设备
                searchContainer.querySelectorAll('.config-content.expanded').forEach(content => {{
                    const configSection = content.closest('.config-section');
                    if (configSection) {{
                        const router = configSection.getAttribute('data-router');
                        if (router && !uniqueRouters.includes(router)) {{
                            // 直接操作 DOM，不依赖 toggleConfig
                            content.classList.remove('expanded');
                            const configId = content.id;
                            const caret = document.getElementById('caret-' + configId);
                            if (caret) {{
                                caret.classList.remove('expanded');
                            }}
                        }}
                    }}
                }});
                return;
            }}
            
            // 关闭所有不在目标列表中的已展开设备
            searchContainer.querySelectorAll('.config-content.expanded').forEach(content => {{
                const configSection = content.closest('.config-section');
                if (configSection) {{
                    const router = configSection.getAttribute('data-router');
                    if (router && !uniqueRouters.includes(router)) {{
                        // 直接操作 DOM，不依赖 toggleConfig
                        content.classList.remove('expanded');
                        const configId = content.id;
                        const caret = document.getElementById('caret-' + configId);
                        if (caret) {{
                            caret.classList.remove('expanded');
                        }}
                    }}
                }}
            }});
            
            // 展开需要的设备
            needToExpandRouters.forEach(router => {{
                expandSingleDeviceConfig(router, containerElement);
            }});
        }}
        
        // 展开单个设备配置（不关闭其他配置）
        function expandSingleDeviceConfig(targetRouter, containerElement) {{
            // 如果提供了 containerElement，在该容器内查找；否则在整个文档中查找
            const searchContainer = containerElement || document;
            const targetSection = searchContainer.querySelector(`.config-section[data-router="${{targetRouter}}"]`);
            if (targetSection) {{
                const targetContent = targetSection.querySelector('.config-content');
                if (targetContent) {{
                    // 直接操作 DOM，不依赖 toggleConfig（因为 toggleConfig 使用 getElementById，可能在解析页面中找不到）
                    if (!targetContent.classList.contains('expanded')) {{
                        targetContent.classList.add('expanded');
                    const configId = targetContent.id;
                        const caret = document.getElementById('caret-' + configId);
                        if (caret) {{
                            caret.classList.add('expanded');
                        }}
                    }}
                }}
            }}
        }}
        
        // 更新配置引用的提示文本
        function updateConfigReferenceTooltips() {{
            const configReferences = document.querySelectorAll('.config-reference');
            configReferences.forEach(ref => {{
                const router = ref.getAttribute('data-router');
                const lines = ref.getAttribute('data-lines');
                const optionId = getOptionId(ref);
                const isActive = isConfigRefActive(router, lines, optionId);
                
                // 根据当前语言和状态设置提示文本
                const isChinese = currentLanguage === 'zh';
                if (router) {{
                    // 带路由器前缀的情况
                if (isActive) {{
                    const title = isChinese ? 
                        `点击清除 ${{router}} 配置行 ${{lines}} 的高亮` : 
                        `Click to clear the highlight of ${{router}} Configuration lines ${{lines}}`;
                    ref.setAttribute('title', title);
                }} else {{
                    const title = isChinese ? 
                        `点击高亮 ${{router}} 配置行 ${{lines}}` : 
                        `Click to highlight ${{router}} Configuration lines ${{lines}}`;
                        ref.setAttribute('title', title);
                    }}
                }} else if (lines) {{
                    // 不带路由器前缀的情况
                    const title = isChinese ? 
                        `点击高亮配置行 ${{lines}}` : 
                        `Click to highlight Configuration lines ${{lines}}`;
                    ref.setAttribute('title', title);
                }}
            }});
        }}
        

        // 添加配置引用事件监听器 - 基于 bit-map 机制
        function addConfigReferenceListeners() {{
            const configReferences = document.querySelectorAll('.config-reference');
            
            configReferences.forEach(ref => {{
                ref.addEventListener('click', function(e) {{
                    e.preventDefault();
                    e.stopPropagation();
                    
                    const router = this.getAttribute('data-router');
                    const lines = this.getAttribute('data-lines');
                    const currentOptionId = getOptionId(this);
                    
                    // 检查当前配置引用是否已激活
                    const isCurrentlyActive = isConfigRefActive(router, lines, currentOptionId);
                    
                    if (isCurrentlyActive) {{
                        // 场景1: 当前配置引用已激活，点击则关闭
                        deactivateConfigRef(router, lines, currentOptionId);
                        clearConfigLinesHighlight(router, lines, null);
                        
                        // 检查当前选项是否还有其他激活的配置引用
                        const hasOtherActiveRefs = Array.from(configReferenceBitMap.values())
                            .some(data => data.optionId === currentOptionId && data.isActive);
                        
                        if (!hasOtherActiveRefs) {{
                            currentActiveOption = null;
                        }}
                    }} else {{
                        // 场景2: 当前配置引用未激活
                        if (currentActiveOption && currentActiveOption !== currentOptionId) {{
                            // 场景2a: 当前有其他选项激活，先清除其他选项的所有配置引用
                            clearOptionConfigRefs(currentActiveOption, null);
                        }}
                        
                        // 激活当前配置引用
                        activateConfigRef(router, lines, currentOptionId);
                        currentActiveOption = currentOptionId;
                        
                        // 高亮配置行（传入选项ID以便检查diff内容，containerElement 为 null 表示在整个文档中查找）
                        highlightConfigLines(router, lines, currentOptionId, null);
                        
                        // 收集当前选项所有激活的配置引用，用于展开多个设备
                        const activeRefs = Array.from(configReferenceBitMap.entries())
                            .filter(([refId, data]) => data.optionId === currentOptionId && data.isActive)
                            .map(([refId, data]) => refId.split('-')[1]); // 提取router
                        
                        // 展开所有相关设备的配置下拉栏（containerElement 为 null 表示在整个文档中查找）
                        expandMultipleDeviceConfigs(activeRefs, null);
                        
                        // 滚动到当前配置区域
                        // 在问题界面中，containerElement 为 null，表示在整个文档中查找
                        scrollToConfigSection(router, null);
                    }}
                    
                    // 更新所有配置引用的提示文本
                    updateConfigReferenceTooltips();
                }});
            }});
        }}

        // 高亮配置行
        function highlightConfigLines(router, lineRange, optionId, containerElement) {{
            // 解析行号范围
            const [startLine, endLine] = lineRange.split(',').map(num => parseInt(num.trim()));
            
            // 查找对应的配置区域
            // 如果提供了 containerElement，在该容器内查找；否则在整个文档中查找
            const searchContainer = containerElement || document;
            const configSection = searchContainer.querySelector(`.config-section[data-router="${{router}}"]`);
            if (!configSection) {{
                return;
            }}
            
            // 查找选项的 diff 内容，检查是否有 - 或 + 标记
            const diffInfo = {{}}; // key: lineNumber, value: 'removed' | 'added' | null
            const addedLinesInfo = []; // 存储新增行的信息
            let removedLines = []; // 存储删除行的信息，用于匹配新增行和替换内容（在函数作用域内初始化）
            
            if (optionId) {{
                const optionElement = document.getElementById(optionId)?.closest('.option-item, .answer-option');
                if (optionElement) {{
                    const diffContent = optionElement.querySelector('.option-diff-content');
                    if (diffContent) {{
                        const diffLines = Array.from(diffContent.querySelectorAll('.diff-line'));
                        let configRefIndex = -1;
                        
                        // 找到配置引用所在的行
                        for (let i = 0; i < diffLines.length; i++) {{
                            const lineText = diffLines[i].textContent || diffLines[i].innerText;
                            const trimmedText = lineText.trim();
                            
                            // 检查是否包含配置引用
                            const configRefPattern = router ? 
                                new RegExp(`${{router}}\\\\s+Configuration\\\\s+${{lineRange}}`) :
                                new RegExp(`Configuration\\\\s+${{lineRange}}`);
                            
                            if (configRefPattern.test(trimmedText)) {{
                                configRefIndex = i;
                                break;
                            }}
                        }}
                        
                        // 如果找到配置引用，检查后续行的标记
                        if (configRefIndex >= 0) {{
                            let currentLineNum = startLine;
                            
                            for (let i = configRefIndex + 1; i < diffLines.length; i++) {{
                                const diffLine = diffLines[i];
                                // 获取文本内容用于检测标记
                                const lineText = diffLine.textContent || diffLine.innerText;
                                const trimmedText = lineText.trim();
                                // 获取 HTML 内容用于保留格式（包括 [[Config_X](Config_X_xxx)]）
                                // diffLine 是 <div class="diff-line diff-removed">内容</div> 格式
                                // 我们需要提取 <div> 内的内容，而不是整个 <div>
                                let lineHTML = diffLine.innerHTML || '';
                                // 如果 lineHTML 包含 <div> 标签，尝试提取内部内容
                                // 但通常 diffLine.innerHTML 已经是内部内容了，不需要额外处理
                                            
                                // 检查是否是删除行或新增行（通过类名）
                                const isRemoved = diffLine.classList && diffLine.classList.contains('diff-removed');
                                const isAdded = diffLine.classList && diffLine.classList.contains('diff-added');
                                            
                                // 如果遇到下一个配置引用，停止
                                if (trimmedText.startsWith('@@') && trimmedText.includes('Configuration')) {{
                                    break;
                                }}
                                
                                // 如果遇到 <br> 标签，停止（这是配置块的结束标记）
                                if (trimmedText === '<br>' || trimmedText.includes('<br>')) {{
                                    break;
                                }}
                                
                                // 跳过空行
                                if (trimmedText === '') {{
                                    continue;
                                }}
                                
                                // 检查行的标记（优先使用类名，如果没有则使用文本内容）
                                if (isRemoved || trimmedText.startsWith('-')) {{
                                    // 处理所有删除行，不限制在 j,k 范围内（因为配置块到 <br> 或结束）
                                    if (currentLineNum >= startLine && currentLineNum <= endLine) {{
                                        diffInfo[currentLineNum] = 'removed';
                                        // 提取删除行的内容（保留 HTML 格式，包括 [] 和 [[Config_X](Config_X_xxx)]）
                                        let removedContent = '';
                                        // 优先使用 lineHTML，因为它包含完整的 HTML 结构（包括 .config-field 元素）
                                        if (lineHTML && lineHTML.trim().length > 0) {{
                                            // 如果 HTML 中包含 .config-field，说明已经处理过，直接使用
                                            if (lineHTML.includes('config-field') || lineHTML.includes('data-subspec')) {{
                                                // HTML 已经包含完整的结构，直接使用（可能需要去除开头的 - 号）
                                                if (lineHTML.trim().startsWith('-')) {{
                                                    removedContent = lineHTML.trim().substring(1).trim();
                                                }} else {{
                                                    removedContent = lineHTML.trim();
                                                }}
                                            }} else if (lineHTML.includes('-')) {{
                                                // HTML 中包含 - 号，尝试提取 - 号后的内容
                                                const minusMatch = lineHTML.match(/[-]\\s*(.+)/);
                                                if (minusMatch) {{
                                                    removedContent = minusMatch[1].trim();
                                                }} else {{
                                                    const minusIndex = lineHTML.indexOf('-');
                                                    removedContent = lineHTML.substring(minusIndex + 1).trim();
                                                }}
                                            }} else {{
                                                // HTML 中没有 - 号，直接使用
                                                removedContent = lineHTML.trim();
                                            }}
                                        }} else {{
                                            // 如果 HTML 为空，使用文本内容（去除 - 号）
                                            removedContent = trimmedText.substring(1).trim();
                                        }}
                                        // 存储删除行信息，用于后续匹配新增行和替换内容
                                        removedLines.push({{lineNum: currentLineNum, content: removedContent}});
                                    }}
                                    currentLineNum++;
                                }} else if (isAdded || trimmedText.startsWith('+')) {{
                                    // 新增行：找到对应的删除行（通常是最近的删除行）
                                    // 提取新增行的内容（保留 HTML 格式，包括 [[Config_X](Config_X_xxx)]）
                                    let addedContent = '';
                                    // 优先使用 lineHTML，因为它包含完整的 HTML 结构（包括 .config-field 元素）
                                    if (lineHTML && lineHTML.trim().length > 0) {{
                                        // 如果 HTML 中包含 .config-field，说明已经处理过，直接使用
                                        if (lineHTML.includes('config-field') || lineHTML.includes('data-subspec')) {{
                                            // HTML 已经包含完整的结构，直接使用（可能需要去除开头的 + 号）
                                            if (lineHTML.trim().startsWith('+')) {{
                                                addedContent = lineHTML.trim().substring(1).trim();
                                            }} else {{
                                                addedContent = lineHTML.trim();
                                            }}
                                        }} else if (lineHTML.includes('+')) {{
                                            // HTML 中包含 + 号，尝试提取 + 号后的内容
                                            const plusMatch = lineHTML.match(/[+]\\s*(.+)/);
                                            if (plusMatch) {{
                                                addedContent = plusMatch[1].trim();
                                            }} else {{
                                                const plusIndex = lineHTML.indexOf('+');
                                                addedContent = lineHTML.substring(plusIndex + 1).trim();
                                            }}
                                        }} else {{
                                            // HTML 中没有 + 号，直接使用
                                            addedContent = lineHTML.trim();
                                        }}
                                    }} else {{
                                        // 如果 HTML 为空，使用文本内容（去除 + 号）
                                        addedContent = trimmedText.substring(1).trim();
                                    }}
                                    // 如果最近有删除行，将新增行关联到该删除行
                                    // 对于多个 + 行，每个 + 行应该关联到对应的 - 行（按顺序）
                                    if (removedLines.length > 0) {{
                                        // 计算这个 + 行应该关联到哪个 - 行
                                        // 如果这是第一个 + 行，关联到第一个 - 行；如果是第二个 + 行，关联到第二个 - 行，以此类推
                                        // 使用 addedLinesInfo 的长度来确定这是第几个 + 行
                                        const addedLineIndex = addedLinesInfo.length;
                                        let targetRemovedLineIndex = addedLineIndex;
                                        // 如果 + 行数量超过 - 行数量，则最后一个 + 行关联到最后一个 - 行
                                        if (targetRemovedLineIndex >= removedLines.length) {{
                                            targetRemovedLineIndex = removedLines.length - 1;
                                        }}
                                        const targetRemovedLine = removedLines[targetRemovedLineIndex];
                                        const removedLineNum = targetRemovedLine.lineNum;
                                        addedLinesInfo.push({{lineNum: removedLineNum, content: addedContent}});
                                    }} else {{
                                        // 如果没有删除行，仍然记录新增行信息（但需要确保行号在范围内）
                                        if (currentLineNum >= startLine && currentLineNum <= endLine) {{
                                            diffInfo[currentLineNum] = 'added';
                                            addedLinesInfo.push({{lineNum: currentLineNum, content: addedContent}});
                                        }}
                                    }}
                                    // 新增行不增加行号计数（因为它不在原始配置中）
                                }} else if (trimmedText && !trimmedText.startsWith('@@')) {{
                                    // 普通行，继续计数
                                    currentLineNum++;
                                }}
                            }}
                        }}
                    }}
                }}
            }}
            
            // 确保配置区域已展开（如果配置内容是隐藏的，先展开它）
            const configContent = configSection.querySelector('.config-content');
            if (configContent && !configContent.classList.contains('expanded')) {{
                // 直接操作 DOM，不依赖 toggleConfig（因为 toggleConfig 使用 getElementById，可能在解析页面中找不到）
                configContent.classList.add('expanded');
                const configId = configContent.id;
                if (configId) {{
                    const caret = document.getElementById('caret-' + configId);
                    if (caret) {{
                        caret.classList.add('expanded');
                    }}
                }}
            }}
            
            // 查找配置行并应用高亮
            const configLines = configSection.querySelectorAll('.config-line');
            let highlightedCount = 0;
            
            // 创建一个映射：实际行号 -> DOM 元素
            const lineNumberToElement = new Map();
            
            // 第一步：收集所有 diff 行，计算最大行号位数
            const diffLineNumbers = [];
            configLines.forEach((line) => {{
                const lineNumberSpan = line.querySelector('.config-line-number');
                if (lineNumberSpan) {{
                    const actualLineNumber = parseInt(lineNumberSpan.textContent.trim());
                    if (!isNaN(actualLineNumber)) {{
                        lineNumberToElement.set(actualLineNumber, line);
                        // 检查是否是 diff 行
                        if (actualLineNumber >= startLine && actualLineNumber <= endLine) {{
                            if (diffInfo[actualLineNumber] === 'removed' || diffInfo[actualLineNumber] === 'added') {{
                                diffLineNumbers.push(actualLineNumber);
                            }}
                        }}
                    }}
                }}
            }});
            
            // 计算最大行号位数
            let maxDigits = 0;
            if (diffLineNumbers.length > 0) {{
                const maxLineNumber = Math.max(...diffLineNumbers);
                maxDigits = maxLineNumber.toString().length;
            }}
            
            // 第二步：处理所有行，在添加 - 或 + 号时直接添加对齐空格
            configLines.forEach((line) => {{
                // 尝试从行内容中提取实际行号
                const lineNumberSpan = line.querySelector('.config-line-number');
                let actualLineNumber = null;
                if (lineNumberSpan) {{
                    actualLineNumber = parseInt(lineNumberSpan.textContent.trim());
                }} else {{
                    // 如果没有行号 span，使用 data-line 作为后备
                    actualLineNumber = parseInt(line.getAttribute('data-line'));
                }}
                
                if (actualLineNumber) {{
                    lineNumberToElement.set(actualLineNumber, line);
                    
                    if (actualLineNumber >= startLine && actualLineNumber <= endLine) {{
                        // 检查行是否已经被其他配置引用高亮（通过检查是否有高亮类）
                        const isAlreadyHighlighted = line.classList.contains('config-line-highlighted') || 
                                                     line.classList.contains('config-line-highlighted-removed') || 
                                                     line.classList.contains('config-line-highlighted-added');
                        const currentHTML = line.innerHTML;
                        const hasMinusSign = currentHTML.trim().startsWith('-');
                        const hasPlusSign = currentHTML.trim().startsWith('+');
                        
                        // 根据 diff 信息决定高亮颜色
                        if (diffInfo[actualLineNumber] === 'removed') {{
                            line.classList.add('config-line-highlighted-removed');
                            // 如果行已经被其他配置引用高亮，并且已经有 - 号或 + 号，则不再修改内容
                            // 这样可以避免覆盖其他配置引用已经设置的内容
                            if (isAlreadyHighlighted && (hasMinusSign || hasPlusSign)) {{
                                // 只添加高亮类，不修改内容
                            }} else {{
                                // 用 diff 中的内容替换配置行的内容（保留 HTML 格式，包括 []）
                                const removedLineInfo = removedLines && removedLines.length > 0 ? removedLines.find(r => r.lineNum === actualLineNumber) : null;
                                if (removedLineInfo) {{
                                    // 保存原始内容（如果还没有保存）
                                    if (!line.hasAttribute('data-original-html')) {{
                                        line.setAttribute('data-original-html', line.innerHTML);
                                    }}
                                    
                                    // 保留行号部分，只替换内容部分，并在行号前添加 - 号
                                    const lineNumberSpan = line.querySelector('.config-line-number');
                                    if (lineNumberSpan) {{
                                        const removedLineHTML = line.innerHTML;
                                        const lineNumberMatch = removedLineHTML.match(/^(\\s*)<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                        if (lineNumberMatch) {{
                                            const lineNumber = lineNumberMatch[2];
                                            const trailingSpaces = lineNumberMatch[3];
                                            // 在行号前添加 - 号，并添加对齐空格
                                            const numberDigits = lineNumber.length;
                                            const paddingSpaces = maxDigits > 0 ? ' '.repeat(maxDigits - numberDigits) : '';
                                            line.innerHTML = `-${{paddingSpaces}}<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{removedLineInfo.content}}`;
                                        }} else {{
                                            // 如果无法匹配，使用简单格式，在行号前添加 - 号，并添加对齐空格
                                            const lineNumber = lineNumberSpan.textContent.trim();
                                            const numberDigits = lineNumber.length;
                                            const paddingSpaces = maxDigits > 0 ? ' '.repeat(maxDigits - numberDigits) : '';
                                            line.innerHTML = `-${{paddingSpaces}}<span class="config-line-number">${{lineNumber}}</span> ${{removedLineInfo.content}}`;
                                        }}
                                    }}
                                }} else {{
                                    // 如果没有 removedLineInfo，仍然需要添加 - 号
                                    const lineNumberSpan = line.querySelector('.config-line-number');
                                    if (lineNumberSpan) {{
                                        // 检查是否已经有 - 号
                                        if (!hasMinusSign) {{
                                            // 保存原始内容（如果还没有保存）
                                            if (!line.hasAttribute('data-original-html')) {{
                                                line.setAttribute('data-original-html', currentHTML);
                                            }}
                                            // 在行号前添加 - 号
                                            const lineNumberMatch = currentHTML.match(/^(\\s*)<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                            if (lineNumberMatch) {{
                                                const leadingSpaces = lineNumberMatch[1];
                                                const lineNumber = lineNumberMatch[2];
                                                const trailingSpaces = lineNumberMatch[3];
                                                const contentAfter = currentHTML.substring(lineNumberMatch[0].length);
                                                line.innerHTML = `${{leadingSpaces}}-<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{contentAfter}}`;
                                            }} else {{
                                                // 简单格式
                                                const lineNumber = lineNumberSpan.textContent.trim();
                                                const contentAfter = currentHTML.replace(/<span class="config-line-number">.*?<\\/span>\\s*/, '');
                                                line.innerHTML = `-<span class="config-line-number">${{lineNumber}}</span> ${{contentAfter}}`;
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }} else if (diffInfo[actualLineNumber] === 'added') {{
                            line.classList.add('config-line-highlighted-added');
                            // 如果行已经被其他配置引用高亮，并且已经有 + 号或 - 号，则不再修改内容
                            // 这样可以避免覆盖其他配置引用已经设置的内容
                            if (isAlreadyHighlighted && (hasPlusSign || hasMinusSign)) {{
                                // 只添加高亮类，不修改内容
                            }} else {{
                                // 在行号前添加 + 号
                                const lineNumberSpan = line.querySelector('.config-line-number');
                                if (lineNumberSpan) {{
                                    // 检查是否已经有 + 号
                                    if (!hasPlusSign) {{
                                        // 保存原始内容（如果还没有保存）
                                        if (!line.hasAttribute('data-original-html')) {{
                                            line.setAttribute('data-original-html', currentHTML);
                                        }}
                                        // 在行号前添加 + 号，去掉前导空格（更紧凑）
                                        const lineNumberMatch = currentHTML.match(/^(\\s*)<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                        if (lineNumberMatch) {{
                                            const lineNumber = lineNumberMatch[2];
                                            const trailingSpaces = lineNumberMatch[3];
                                            const contentAfter = currentHTML.substring(lineNumberMatch[0].length);
                                            // 在行号前添加 + 号，并添加对齐空格
                                            const numberDigits = lineNumber.length;
                                            const paddingSpaces = maxDigits > 0 ? ' '.repeat(maxDigits - numberDigits) : '';
                                            line.innerHTML = `+${{paddingSpaces}}<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{contentAfter}}`;
                                        }} else {{
                                            // 简单格式，在行号前添加 + 号，并添加对齐空格
                                            const lineNumber = lineNumberSpan.textContent.trim();
                                            const contentAfter = currentHTML.replace(/<span class="config-line-number">.*?<\\/span>\\s*/, '');
                                            const numberDigits = lineNumber.length;
                                            const paddingSpaces = maxDigits > 0 ? ' '.repeat(maxDigits - numberDigits) : '';
                                            line.innerHTML = `+${{paddingSpaces}}<span class="config-line-number">${{lineNumber}}</span> ${{contentAfter}}`;
                                        }}
                                    }}
                                }}
                            }}
                        }} else {{
                    line.classList.add('config-line-highlighted');
                        }}
                        
                    highlightedCount++;
                    }}
                }}
            }});
            
            // 注意：对齐已经在添加 - 或 + 号时完成，不需要额外的对齐函数
            
            // 如果有新增行，在对应的删除行后显示
            // 先显示所有删除行，再显示所有新增行（按行号排序）
            if (addedLinesInfo.length > 0) {{
                
                // 按行号分组新增行
                const addedLinesByRemovedLineNum = new Map();
                addedLinesInfo.forEach((addedInfo) => {{
                    if (!addedLinesByRemovedLineNum.has(addedInfo.lineNum)) {{
                        addedLinesByRemovedLineNum.set(addedInfo.lineNum, []);
                    }}
                    addedLinesByRemovedLineNum.get(addedInfo.lineNum).push(addedInfo);
                }});
                
                // 获取所有删除行的行号，按行号排序
                const removedLineNums = removedLines && removedLines.length > 0 ? Array.from(removedLines.map(r => r.lineNum)).sort((a, b) => a - b) : [];
                
                // 找到最后一个删除行的位置，所有新增行将插入到它之后
                let lastRemovedLine = null;
                if (removedLineNums.length > 0) {{
                    const lastRemovedLineNum = removedLineNums[removedLineNums.length - 1];
                    lastRemovedLine = lineNumberToElement.get(lastRemovedLineNum);
                    if (!lastRemovedLine || diffInfo[lastRemovedLineNum] !== 'removed') {{
                        // 如果最后一个删除行不存在，尝试找到最后一个有效的删除行
                        for (let i = removedLineNums.length - 1; i >= 0; i--) {{
                            const lineNum = removedLineNums[i];
                            const line = lineNumberToElement.get(lineNum);
                            if (line && diffInfo[lineNum] === 'removed') {{
                                lastRemovedLine = line;
                                break;
                            }}
                        }}
                    }}
                }}
                
                // 如果找到了最后一个删除行，将所有新增行插入到它之后
                if (lastRemovedLine) {{
                    let insertAfter = lastRemovedLine;
                    
                    // 按删除行行号顺序，依次插入所有新增行
                    removedLineNums.forEach((removedLineNum) => {{
                        const addedLinesForThisRemoved = addedLinesByRemovedLineNum.get(removedLineNum) || [];
                        if (addedLinesForThisRemoved.length > 0) {{
                            // 使用行号映射找到对应的删除行（用于获取行号格式）
                            const targetRemovedLine = lineNumberToElement.get(removedLineNum);
                            
                            // 验证这确实是删除行
                            if (targetRemovedLine && diffInfo[removedLineNum] === 'removed') {{
                                // 为这个删除行的所有新增行创建元素
                                addedLinesForThisRemoved.forEach((addedInfo, index) => {{
                                    // 创建新增行元素
                                    const addedLine = document.createElement('span');
                                    addedLine.className = 'config-line config-line-added-display';
                                    addedLine.setAttribute('data-line', removedLineNum);
                                    
                                    // 构建内容：行号 + 内容
                                    // 需要保持与删除行相同的行号格式（去掉前导空格，更紧凑）
                                    const lineNumberSpan = targetRemovedLine.querySelector('.config-line-number');
                                    if (lineNumberSpan) {{
                                        // 优先从原始 HTML 中提取格式（如果保存了），否则从当前 HTML 中提取
                                        let removedLineHTML = targetRemovedLine.getAttribute('data-original-html') || targetRemovedLine.innerHTML;
                                        // 查找行号前后的空格（考虑可能包含 - 或 + 号的情况）
                                        // 匹配格式：前导空格 + 可选的 - 或 + 号 + 行号 span + 后置空格
                                        const lineNumberMatch = removedLineHTML.match(/^(\\s*)(?:[-+]\\s*)?<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                        if (lineNumberMatch) {{
                                            const lineNumber = lineNumberMatch[2];
                                            const trailingSpaces = lineNumberMatch[3];
                                            // 使用相同的格式，但内容使用新增行的内容（保留 HTML 格式，包括 [[Config_X](Config_X_xxx)]），并在行号前添加 + 号，添加对齐空格
                                            const numberDigits = lineNumber.length;
                                            const paddingSpaces = maxDigits > 0 ? ' '.repeat(maxDigits - numberDigits) : '';
                                            addedLine.innerHTML = `+${{paddingSpaces}}<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{addedInfo.content}}`;
                                        }} else {{
                                            // 如果无法匹配，使用简单格式，在行号前添加 + 号，添加对齐空格
                                            const lineNumber = lineNumberSpan.textContent.trim();
                                            const numberDigits = lineNumber.length;
                                            const paddingSpaces = maxDigits > 0 ? ' '.repeat(maxDigits - numberDigits) : '';
                                            addedLine.innerHTML = `+${{paddingSpaces}}<span class="config-line-number">${{lineNumber}}</span> ${{addedInfo.content}}`;
                                        }}
                                    }} else {{
                                        // 如果没有行号，使用 removedLineNum，在行号前添加 + 号，添加对齐空格
                                        const numberDigits = removedLineNum.toString().length;
                                        const paddingSpaces = maxDigits > 0 ? ' '.repeat(maxDigits - numberDigits) : '';
                                        addedLine.innerHTML = `+${{paddingSpaces}}<span class="config-line-number">${{removedLineNum}}</span> ${{addedInfo.content}}`;
                                    }}
                                    
                                    // 插入到 insertAfter 之后
                                    const parent = insertAfter.parentNode;
                                    if (parent) {{
                                        parent.insertBefore(addedLine, insertAfter.nextSibling);
                                        // 为新插入的 .config-field 元素添加事件监听器
                                        attachSubspecTooltipsToElement(addedLine);
                                        // 更新 insertAfter 为刚插入的行，以便下一个新增行插入到它之后
                                        insertAfter = addedLine;
                                    }}
                                }});
                            }}
                        }}
                    }});
                }}
                
                // 注意：对齐已经在创建新增行时完成，不需要再次对齐
            }}
            
            // 如果没有找到配置行，尝试在diff行中查找
            if (highlightedCount === 0) {{
                const diffLines = configSection.querySelectorAll('.diff-line');
                diffLines.forEach((line, index) => {{
                    const lineNumber = index + 1;
                    if (lineNumber >= startLine && lineNumber <= endLine) {{
                        // 检查是否是删除行或新增行
                        if (line.classList.contains('diff-removed')) {{
                            line.classList.add('config-line-highlighted-removed');
                            // 在内容前添加 - 号（如果还没有）
                            const lineText = line.textContent || line.innerText;
                            if (!lineText.trim().startsWith('-')) {{
                                // 保存原始内容（如果还没有保存）
                                if (!line.hasAttribute('data-original-html')) {{
                                    line.setAttribute('data-original-html', line.innerHTML);
                                }}
                                const currentHTML = line.innerHTML;
                                line.innerHTML = `-${{currentHTML}}`;
                            }}
                        }} else if (line.classList.contains('diff-added')) {{
                            line.classList.add('config-line-highlighted-added');
                            // 在内容前添加 + 号（如果还没有）
                            const lineText = line.textContent || line.innerText;
                            if (!lineText.trim().startsWith('+')) {{
                                // 保存原始内容（如果还没有保存）
                                if (!line.hasAttribute('data-original-html')) {{
                                    line.setAttribute('data-original-html', line.innerHTML);
                                }}
                                const currentHTML = line.innerHTML;
                                line.innerHTML = `+${{currentHTML}}`;
                            }}
                        }} else {{
                        line.classList.add('config-line-highlighted');
                        }}
                        highlightedCount++;
                    }}
                }});
            }}
        }}

        // 清除所有高亮
        function clearAllHighlights() {{
            // 清除所有高亮类
            document.querySelectorAll('.config-line-highlighted').forEach(el => {{
                el.classList.remove('config-line-highlighted');
            }});
            document.querySelectorAll('.config-line-highlighted-removed').forEach(el => {{
                el.classList.remove('config-line-highlighted-removed');
            }});
            document.querySelectorAll('.config-line-highlighted-added').forEach(el => {{
                el.classList.remove('config-line-highlighted-added');
            }});
            
            // 恢复所有行的原始内容（如果之前保存过）
            document.querySelectorAll('.config-line[data-original-html]').forEach(line => {{
                line.innerHTML = line.getAttribute('data-original-html');
                line.removeAttribute('data-original-html');
            }});
            
            // 移除新增行显示
            document.querySelectorAll('.config-line-added-display').forEach(el => {{
                el.remove();
            }});
        }}
        
        // 重置 bit-map 状态（在切换问题时调用）
        function resetConfigReferenceBitMap() {{
            configReferenceBitMap.clear();
            currentActiveOption = null;
            clearAllHighlights();
        }}

        // 自动展开目标配置，关闭其他配置
        function expandTargetConfig(targetRouter) {{
            // 关闭所有配置（使用原有的toggleConfig函数）
            document.querySelectorAll('.config-content').forEach(content => {{
                if (content.classList.contains('expanded')) {{
                    const configId = content.id;
                    toggleConfig(configId);
                }}
            }});
            
            // 展开目标配置（使用原有的toggleConfig函数）
            const targetSection = document.querySelector(`.config-section[data-router="${{targetRouter}}"]`);
            if (targetSection) {{
                const targetContent = targetSection.querySelector('.config-content');
                if (targetContent && !targetContent.classList.contains('expanded')) {{
                    const configId = targetContent.id;
                    toggleConfig(configId);
                }}
            }}
        }}

        // 滚动到配置区域
        function scrollToConfigSection(router, containerElement) {{
            // 如果提供了 containerElement，在该容器内查找；否则在整个文档中查找
            const searchContainer = containerElement || document;
            const configSection = searchContainer.querySelector(`.config-section[data-router="${{router}}"]`);
            if (configSection) {{
                configSection.scrollIntoView({{
                    behavior: 'smooth',
                    block: 'center'
                }});
            }}
        }}

        // 添加鼠标悬停事件
        // Global tooltip management
        let globalTooltip = null;
        let hoverEventsInitialized = false;

        // 使用事件委托处理所有 .config-field 的悬停事件（包括动态插入的元素）
        function setupSubspecTooltipDelegation() {{
            // Create a single global tooltip if it doesn't exist
            if (!globalTooltip) {{
                globalTooltip = document.createElement('div');
                globalTooltip.className = 'tooltip';
                document.body.appendChild(globalTooltip);
            }}
            
            // 如果已经设置过事件委托，不再重复设置
            if (hoverEventsInitialized) {{
                return;
            }}
            
            // 在 document 上使用事件委托，监听所有 .config-field 的鼠标事件
            document.addEventListener('mouseover', (e) => {{
                // 检查事件目标是否是 .config-field 或其子元素
                const field = e.target.closest('.config-field');
                if (!field) return;
                
                // 移除之前所有字段的高亮
                document.querySelectorAll('.config-field-showing-tooltip').forEach(f => {{
                    f.classList.remove('config-field-showing-tooltip');
                }});
                
                // 为当前字段添加灰色高亮
                field.classList.add('config-field-showing-tooltip');
                
                const subspec = field.getAttribute('data-subspec');
                
                // Always hide tooltip first to ensure clean state
                globalTooltip.classList.remove('show');
                globalTooltip.style.display = 'none';
                globalTooltip.style.visibility = 'hidden';
                globalTooltip.style.opacity = '0';
                
                // If no subspec, don't show tooltip
                if (!subspec) return;
                
                // Set content and force reflow
                globalTooltip.innerHTML = subspec;
                globalTooltip.style.display = 'block';
                
                // Use requestAnimationFrame to ensure Safari completes layout before positioning
                requestAnimationFrame(() => {{
                        // Get field position and dimensions
                        const fieldRect = field.getBoundingClientRect();
                        const tooltipHeight = globalTooltip.offsetHeight;
                        
                        // Get actual tooltip width after content is set
                        const tooltipWidth = globalTooltip.offsetWidth;
                        const maxTooltipWidth = 550;
                        
                        // Calculate tooltip position relative to the field
                        // Center tooltip horizontally over the field
                        let left = fieldRect.left + (fieldRect.width / 2) - (tooltipWidth / 2);
                        // Position tooltip above the field with consistent spacing
                        let top = fieldRect.top - tooltipHeight - 20;
                        
                        // Calculate arrow position (center of the field)
                        const arrowLeft = fieldRect.left + (fieldRect.width / 2);
                        
                        // Ensure tooltip stays within viewport bounds horizontally
                        if (left < 10) {{
                            left = 10;
                        }} else if (left + tooltipWidth > window.innerWidth - 10) {{
                            left = window.innerWidth - tooltipWidth - 10;
                        }}
                        
                        // Adjust vertical position if tooltip would go off-screen
                        let arrowPosition = 'bottom'; // Default: arrow points down from tooltip
                        if (top < 10) {{
                            // Tooltip goes below the field
                            top = fieldRect.bottom + 20;
                            arrowPosition = 'top'; // Arrow points up from tooltip
                        }}
                        
                        // Set arrow position and style
                        if (arrowPosition === 'top') {{
                            // Tooltip is below the field: arrow should be above the tooltip and point up
                            globalTooltip.style.setProperty('--arrow-top', '-12px');
                            // Bottom border colored → triangle points up
                            globalTooltip.style.setProperty('--arrow-border', 'transparent transparent #9e9e9e transparent');
                        }} else {{
                            // Arrow at bottom of tooltip, pointing down
                            globalTooltip.style.setProperty('--arrow-top', '100%');
                            globalTooltip.style.setProperty('--arrow-border', '#9e9e9e transparent transparent transparent');
                        }}
                        
                        // Calculate arrow horizontal position relative to tooltip
                        // Use actual tooltip width for accurate positioning
                        const arrowOffset = arrowLeft - left;
                        const minArrowPos = 20;
                        const maxArrowPos = tooltipWidth - 20;
                        globalTooltip.style.setProperty('--arrow-left', Math.max(minArrowPos, Math.min(maxArrowPos, arrowOffset)) + 'px');
                        
                        // Set final position and show tooltip immediately
                        globalTooltip.style.left = left + 'px';
                        globalTooltip.style.top = top + 'px';
                        globalTooltip.style.visibility = 'visible';
                        globalTooltip.style.opacity = '1';
                        globalTooltip.classList.add('show');
                    }});
            }});
            
            // 添加点击事件，复制 subspec 翻译内容到剪贴板
            document.addEventListener('click', (e) => {{
                // 检查事件目标是否是 .config-field 或其子元素
                const field = e.target.closest('.config-field');
                if (!field) return;
                
                // 阻止默认行为
                e.preventDefault();
                e.stopPropagation();
                
                const subspec = field.getAttribute('data-subspec');
                if (!subspec) return;
                
                // 创建一个临时 div 来解析 HTML 内容
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = subspec;
                
                // 查找 tooltip-translated 元素
                const translatedElement = tempDiv.querySelector('.tooltip-translated');
                if (!translatedElement) {{
                    // 如果没有 tooltip-translated，尝试获取所有文本内容
                    const allText = tempDiv.innerText || tempDiv.textContent || '';
                    if (allText.trim()) {{
                        copyToClipboard(allText.trim());
                    }}
                    return;
                }}
                
                // 获取翻译文本（去除 HTML 标签，保留文本内容）
                const translatedText = translatedElement.innerText || translatedElement.textContent || '';
                
                if (translatedText.trim()) {{
                    copyToClipboard(translatedText.trim());
                }}
            }});
            
            // 复制到剪贴板的辅助函数
            function copyToClipboard(text) {{
                // 优先使用现代 Clipboard API（支持 HTTPS 和 localhost）
                // 兼容性：Chrome 66+, Firefox 63+, Safari 13.1+, Edge 79+
                if (navigator.clipboard && navigator.clipboard.writeText) {{
                    // 检查是否在安全上下文中（HTTPS 或 localhost）
                    const isSecureContext = window.isSecureContext || location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
                    if (isSecureContext) {{
                        navigator.clipboard.writeText(text).then(() => {{
                            showCopyFeedback();
                        }}).catch(err => {{
                            console.error('复制失败:', err);
                            // 降级到传统方法
                            fallbackCopyToClipboard(text);
                        }});
                        return;
                    }}
                }}
                // 降级到传统方法（支持所有浏览器，包括旧版本）
                fallbackCopyToClipboard(text);
            }}
            
            // 降级复制方法（兼容所有浏览器和操作系统）
            function fallbackCopyToClipboard(text) {{
                const textArea = document.createElement('textarea');
                textArea.value = text;
                // 设置样式，确保元素不可见但可选中
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                textArea.style.top = '-999999px';
                textArea.style.opacity = '0';
                textArea.style.pointerEvents = 'none';
                // 设置 readonly 以防止 iOS Safari 弹出键盘
                textArea.setAttribute('readonly', '');
                document.body.appendChild(textArea);
                
                // 对于 iOS Safari，需要特殊处理
                if (/iPad|iPhone|iPod/.test(navigator.userAgent)) {{
                    const range = document.createRange();
                    range.selectNodeContents(textArea);
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    textArea.setSelectionRange(0, 999999);
                }} else {{
                    textArea.focus();
                    textArea.select();
                }}
                
                try {{
                    const successful = document.execCommand('copy');
                    if (successful) {{
                        showCopyFeedback();
                    }} else {{
                        console.error('复制命令执行失败');
                    }}
                }} catch (err) {{
                    console.error('复制失败:', err);
                }}
                
                document.body.removeChild(textArea);
            }}
            
            // 显示复制反馈
            function showCopyFeedback() {{
                // 创建或获取反馈元素
                let feedback = document.getElementById('copy-feedback');
                if (!feedback) {{
                    feedback = document.createElement('div');
                    feedback.id = 'copy-feedback';
                    feedback.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #4caf50; color: white; padding: 10px 20px; border-radius: 4px; z-index: 10000; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); transition: opacity 0.3s ease;';
                    document.body.appendChild(feedback);
                }}
                
                // 获取当前语言：优先从 window.currentLanguage，其次从 texts 对象，最后从 URL 参数
                let currentLanguage = 'en';
                if (typeof window !== 'undefined' && window.currentLanguage) {{
                    currentLanguage = window.currentLanguage;
                }} else if (typeof texts !== 'undefined' && texts) {{
                    // 通过检查 texts 对象的内容来判断语言
                    const langBtn = document.querySelector('.lang-btn.active');
                    if (langBtn) {{
                        const langId = langBtn.id;
                        if (langId && langId.includes('zh')) {{
                            currentLanguage = 'zh';
                        }}
                    }}
                }} else {{
                    // 从 URL 参数获取
                    const urlParams = new URLSearchParams(window.location.search);
                    const urlLang = urlParams.get('lang');
                    if (urlLang === 'zh') {{
                        currentLanguage = 'zh';
                    }}
                }}
                
                feedback.textContent = currentLanguage === 'zh' ? '已复制到剪贴板' : 'Copied to clipboard';
                feedback.style.display = 'block';
                feedback.style.opacity = '1';
                
                // 2秒后淡出
                setTimeout(() => {{
                    feedback.style.opacity = '0';
                    setTimeout(() => {{
                        feedback.style.display = 'none';
                    }}, 300);
                }}, 2000);
            }}
            
            document.addEventListener('mouseout', (e) => {{
                // 检查事件目标是否是 .config-field 或其子元素
                const field = e.target.closest('.config-field');
                if (!field) return;
                
                // 检查鼠标是否移动到另一个 .config-field
                const relatedField = e.relatedTarget?.closest('.config-field');
                if (relatedField) return; // 如果移动到另一个 field，不隐藏 tooltip
                
                // 移除灰色高亮
                field.classList.remove('config-field-showing-tooltip');
                
                globalTooltip.classList.remove('show');
                globalTooltip.style.display = 'none';
                globalTooltip.style.visibility = 'hidden';
                globalTooltip.style.opacity = '0';
            }});
            
            hoverEventsInitialized = true;
        }}
        
        // 为特定元素内的 .config-field 添加事件监听器（已废弃，改用事件委托）
        function attachSubspecTooltipsToElement(element) {{
            // 不再需要单独绑定，事件委托已经处理了所有元素
            // 但为了向后兼容，保留这个函数（空实现）
        }}

        function addHoverEvents() {{
            // 使用事件委托而不是直接绑定
            setupSubspecTooltipDelegation();
        }}
        
        // 保留旧的直接绑定代码作为备份（已废弃）
        function addHoverEventsOld() {{
            // Only initialize once to prevent duplicate event listeners
            if (hoverEventsInitialized) {{
                return;
            }}
            
            // Create a single global tooltip
            if (!globalTooltip) {{
                globalTooltip = document.createElement('div');
                globalTooltip.className = 'tooltip';
                document.body.appendChild(globalTooltip);
            }}
            
            const fields = document.querySelectorAll('.config-field');
            
            fields.forEach(field => {{
                // Check if this field already has event listeners
                if (field.hasAttribute('data-hover-initialized')) {{
                    return;
                }}
                
                field.addEventListener('mouseenter', (e) => {{
                    const subspec = field.getAttribute('data-subspec');
                    
                    // Always hide tooltip first to ensure clean state
                    globalTooltip.classList.remove('show');
                    globalTooltip.style.display = 'none';
                    globalTooltip.style.visibility = 'hidden';
                    globalTooltip.style.opacity = '0';
                    
                    // If no subspec, don't show tooltip
                    if (!subspec) return;
                    
                    // Set content and force reflow
                    globalTooltip.innerHTML = subspec;
                    globalTooltip.style.display = 'block';
                    
                    // Use requestAnimationFrame to ensure Safari completes layout before positioning
                    requestAnimationFrame(() => {{
                        // Get field position and dimensions
                        const fieldRect = field.getBoundingClientRect();
                        const tooltipHeight = globalTooltip.offsetHeight;
                        
                        // Get actual tooltip width after content is set
                        const tooltipWidth = globalTooltip.offsetWidth;
                        const maxTooltipWidth = 550;
                        
                        // Calculate tooltip position relative to the field
                        // Center tooltip horizontally over the field
                        let left = fieldRect.left + (fieldRect.width / 2) - (tooltipWidth / 2);
                        // Position tooltip above the field with consistent spacing
                        let top = fieldRect.top - tooltipHeight - 20;
                        
                        // Calculate arrow position (center of the field)
                        const arrowLeft = fieldRect.left + (fieldRect.width / 2);
                        
                        // Ensure tooltip stays within viewport bounds horizontally
                        if (left < 10) {{
                            left = 10;
                        }} else if (left + tooltipWidth > window.innerWidth - 10) {{
                            left = window.innerWidth - tooltipWidth - 10;
                        }}
                        
                        // Adjust vertical position if tooltip would go off-screen
                        let arrowPosition = 'bottom'; // Default: arrow points down from tooltip
                        if (top < 10) {{
                            // Tooltip goes below the field
                            top = fieldRect.bottom + 20;
                            arrowPosition = 'top'; // Arrow points up from tooltip
                        }}
                        
                        // Set arrow position and style
                        if (arrowPosition === 'top') {{
                            // Tooltip is below the field: arrow should be above the tooltip and point up
                            globalTooltip.style.setProperty('--arrow-top', '-12px');
                            // Bottom border colored → triangle points up
                            globalTooltip.style.setProperty('--arrow-border', 'transparent transparent #9e9e9e transparent');
                        }} else {{
                            // Arrow at bottom of tooltip, pointing down
                            globalTooltip.style.setProperty('--arrow-top', '100%');
                            globalTooltip.style.setProperty('--arrow-border', '#9e9e9e transparent transparent transparent');
                        }}
                        
                        // Calculate arrow horizontal position relative to tooltip
                        // Use actual tooltip width for accurate positioning
                        const arrowOffset = arrowLeft - left;
                        const minArrowPos = 20;
                        const maxArrowPos = tooltipWidth - 20;
                        globalTooltip.style.setProperty('--arrow-left', Math.max(minArrowPos, Math.min(maxArrowPos, arrowOffset)) + 'px');
                        
                        // Set final position and show tooltip immediately
                        globalTooltip.style.left = left + 'px';
                        globalTooltip.style.top = top + 'px';
                        globalTooltip.style.visibility = 'visible';
                        globalTooltip.style.opacity = '1';
                        globalTooltip.classList.add('show');
                    }});
                }});
                
                field.addEventListener('mouseleave', (e) => {{
                    // Always hide tooltip when leaving a field
                    // The mouseenter event of the next field will handle showing the new tooltip
                    globalTooltip.classList.remove('show');
                    globalTooltip.style.display = 'none';
                    globalTooltip.style.visibility = 'hidden';
                    globalTooltip.style.opacity = '0';
                }});
                
                // Mark this field as initialized
                field.setAttribute('data-hover-initialized', 'true');
            }});
            
            hoverEventsInitialized = true;
        }}

        function removeHoverEvents() {{
            // Remove all existing tooltips
            const existingTooltips = document.querySelectorAll('.tooltip');
            existingTooltips.forEach(tooltip => {{
                if (tooltip !== globalTooltip) {{
                    tooltip.remove();
                }}
            }});
            
            // Reset initialization flag
            hoverEventsInitialized = false;
            
            // Remove initialization markers from fields
            const fields = document.querySelectorAll('.config-field[data-hover-initialized]');
            fields.forEach(field => {{
                field.removeAttribute('data-hover-initialized');
            }});
        }}

        // Check if answer is correct
        function checkAnswer(selectedOptions, questionIndex) {{
            // 添加防护性检查
            if (!questions || questionIndex < 0 || questionIndex >= questions.length) {{
                console.error('Invalid question index:', questionIndex, 'Questions length:', questions ? questions.length : 'undefined');
                return false;
            }}
            
            const question = questions[questionIndex];
            if (!question || !question.question) {{
                console.error('Invalid question object at index:', questionIndex, question);
                return false;
            }}
            
            const questionData = parseQuestion(question.question);
            if (!questionData || !questionData.options) {{
                console.error('Invalid question data for index:', questionIndex);
                return false;
            }}
            
            // 检查选中的选项是否都是正确的
            for (const option of questionData.options) {{
                const isSelected = selectedOptions.includes(option.value);
                const shouldBeSelected = option.correct;
                
                if (isSelected !== shouldBeSelected) {{
                    return false;
                }}
            }}
            
            return true;
        }}

        // 格式化解析内容，使用 note-instruction 的格式（每行一个 instruction-line）
        function formatExplanation(explanation) {{
            if (!explanation) return '';
            
            // 将内容按行分割
            let lines = explanation.split('\\n');
            
            // 只移除开头和末尾的空白行，保留中间的空白行（用于排版）
            while (lines.length > 0 && lines[0].trim() === '') {{
                lines.shift();
            }}
            while (lines.length > 0 && lines[lines.length - 1].trim() === '') {{
                lines.pop();
            }}
            
            if (lines.length === 0) return '';
            
            let result = '';
            let inCodeBlock = false;
            let codeBlockContent = '';
            
            for (let i = 0; i < lines.length; i++) {{
                const line = lines[i];
                
                if (line.trim() === '```') {{
                    if (inCodeBlock) {{
                        // 结束代码块，将代码块内容作为一个 instruction-line
                        result += `<div class="instruction-line"><pre style="margin: 0; padding: 0; background: transparent; border: none; font-family: 'Consolas', 'Monaco', 'Courier New', monospace; white-space: pre-wrap;">${{codeBlockContent}}</pre></div>`;
                        codeBlockContent = '';
                        inCodeBlock = false;
                    }} else {{
                        inCodeBlock = true;
                    }}
                }} else if (inCodeBlock) {{
                    codeBlockContent += (codeBlockContent ? '\\n' : '') + line;
                }} else if (line.trim() === '') {{
                    // 空行，跳过（不添加任何内容）
                    continue;
                }} else {{
                    // 处理加粗文本 **text**，每行作为一个 instruction-line
                    let processedLine = line.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                    // 处理配置引用 @@ Rx Configuration j,k @@ 或 @@ Configuration j,k @@
                    processedLine = processConfigReferences(processedLine);
                    result += `<div class="instruction-line">${{processedLine}}</div>`;
                }}
            }}
            
            // 如果代码块没有正确关闭，手动关闭
            if (inCodeBlock && codeBlockContent) {{
                result += `<div class="instruction-line"><pre style="margin: 0; padding: 0; background: transparent; border: none; font-family: 'Consolas', 'Monaco', 'Courier New', monospace; white-space: pre-wrap;">${{codeBlockContent}}</pre></div>`;
            }}
            
            return result;
        }}

        // 下一题
        function nextQuestion() {{
            // 检查选项选择（仅对 question 0 要求必须选择恰好 1 个选项）
            // question 0 是单选题，必须选择恰好 1 个选项
            // question 1-4 可以选择 0 个选项
            if (currentQuestionIndex === 0) {{
            const checkboxes = document.querySelectorAll('input[name="options"]:checked');
                if (checkboxes.length === 0 || checkboxes.length > 1) {{
                document.getElementById('validationModal').style.display = 'block';
                return;
                }}
            }}
            
            // 防止重复点击
            const nextBtn = document.getElementById('nextBtn');
            if (nextBtn.disabled) {{
                return; // 如果按钮已经被禁用，直接返回
            }}
            
            // 禁用按钮防止重复点击
            nextBtn.disabled = true;
            
            // 显示确认模态框（不在这里记录答案，等确认后再记录）
            document.getElementById('confirmModal').style.display = 'block';
        }}

        // 确认选择
        function confirmSelection() {{
            // 记录当前题目用时
            const questionTime = Date.now() - questionStartTime;
            questionTimes.push(questionTime);
            
            // 记录答案
            const checkboxes = document.querySelectorAll('input[name="options"]:checked');
            const selectedOptions = Array.from(checkboxes).map(cb => cb.value);
            answers.push(selectedOptions);
            
            // 记录用户笔记
            const notesTextarea = document.getElementById(`userNotes${{currentQuestionIndex}}`);
            const userNote = notesTextarea ? notesTextarea.value.trim() : '';
            userNotes.push(userNote);
            
            closeConfirmModal();
            
            // 清除固定工具栏内容，并滚动到页面顶部
            clearFixedTopBar();
            window.scrollTo(0, 0);
            
            // 延迟一小段时间确保清除完成后再显示下一题
            setTimeout(() => {{
                showQuestion(currentQuestionIndex + 1);
            }}, 100);
        }}

        // 关闭确认模态框
        function closeConfirmModal() {{
            document.getElementById('confirmModal').style.display = 'none';
            // 恢复按钮状态，允许用户重新点击
            const nextBtn = document.getElementById('nextBtn');
            if (nextBtn) {{
                nextBtn.disabled = false;
            }}
        }}

        // 关闭验证模态框
        function closeValidationModal() {{
            document.getElementById('validationModal').style.display = 'none';
        }}

        // 关闭SUS验证模态框
        function closeSusValidationModal() {{
            document.getElementById('susValidationModal').style.display = 'none';
        }}

        // Refresh/Back Confirmation Modal functions
        let pendingRefreshBackAction = null; // 'refresh' or 'back'
        let isNavigatingAway = false; // Flag to track if user confirmed navigation
        
        function showRefreshBackModal(action) {{
            pendingRefreshBackAction = action;
            const modal = document.getElementById('refreshBackModal');
            const title = document.getElementById('refresh-back-title');
            const text = document.getElementById('refresh-back-text');
            
            // Update text based on action and current language
            if (action === 'refresh') {{
                title.textContent = texts.refreshTitle;
                text.textContent = texts.refreshText;
            }} else if (action === 'back') {{
                title.textContent = texts.backTitle;
                text.textContent = texts.backText;
            }}
            
            // Show modal without scrolling to top
            // Save current scroll position
            const scrollY = window.scrollY || window.pageYOffset;
            
            modal.style.display = 'block';
            
            // Restore scroll position after showing modal
            // Use requestAnimationFrame to ensure DOM is updated
            requestAnimationFrame(() => {{
                window.scrollTo(0, scrollY);
            }});
        }}
        
        function closeRefreshBackModal() {{
            document.getElementById('refreshBackModal').style.display = 'none';
            pendingRefreshBackAction = null;
        }}
        
        // Handle refresh confirmation from modal
        function confirmRefresh() {{
            isNavigatingAway = true;
            closeRefreshBackModal();
            
            // Remove beforeunload listener to allow refresh
            window.removeEventListener('beforeunload', handleBeforeUnload);
            
            // Small delay to ensure listener is removed and modal is closed before reload
            setTimeout(() => {{
                window.location.reload();
            }}, 100);
        }}
        
        // Handle keyboard shortcuts for refresh (F5, Ctrl+R, Ctrl+Shift+R)
        function handleKeyDown(e) {{
            // Only intercept if test is in progress (including SUS page on completion screen)
            if (currentQuestionIndex >= 0 && !testCompleted && !isNavigatingAway) {{
                // F5 key
                if (e.key === 'F5' || e.keyCode === 116) {{
                    e.preventDefault();
                    showRefreshBackModal('refresh');
                    return false;
                }}
                
                // Ctrl+R or Ctrl+Shift+R (Cmd+R on Mac)
                if ((e.ctrlKey || e.metaKey) && e.key === 'r') {{
                    e.preventDefault();
                    showRefreshBackModal('refresh');
                    return false;
                }}
                
                // Ctrl+Shift+R (Cmd+Shift+R on Mac) - hard refresh
                if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'R') {{
                    e.preventDefault();
                    showRefreshBackModal('refresh');
                    return false;
                }}
            }}
        }}
        
        // Note: We completely removed handleBeforeUnload function
        // Setting returnValue in beforeunload would show browser's default dialog
        // We rely entirely on keyboard interception (handleKeyDown) to show our custom modal
        // This ensures NO browser default dialog will appear
        
        // Handle page refresh via browser refresh button (beforeunload event)
        // 
        // TECHNICAL EXPLANATION: Why refresh and back buttons behave differently:
        // 
        // 1. Back button (popstate event):
        //    - Part of browser History API, fully controllable
        //    - We can use history.pushState() to prevent navigation
        //    - Event is synchronous, can show modal immediately
        //    - Result: Perfect control, no browser dialog
        //
        // 2. Refresh button (beforeunload event):
        //    - Part of browser security mechanism
        //    - Browser restricts this to prevent malicious sites from trapping users
        //    - Even with returnValue, browser may show default dialog (security policy)
        //    - Cannot fully prevent refresh without browser dialog
        //    - Result: Limited control, may show browser dialog
        //
        // We try to minimize browser dialog by:
        // 1. Showing our custom modal immediately
        // 2. Using history.pushState to try to prevent navigation
        // 3. Only setting returnValue as last resort
        function handleBeforeUnload(e) {{
            // Only intercept if test is in progress and user hasn't confirmed navigation
            // Include SUS page on completion screen (isOnCompletionScreen check removed)
            if (currentQuestionIndex >= 0 && !testCompleted && !isNavigatingAway) {{
                // Try to use history.pushState to prevent navigation (like we do for back button)
                // This might work in some cases to prevent refresh
                try {{
                    window.history.pushState(null, '', window.location.href);
                }} catch(err) {{
                    // Ignore errors
                }}
                
                // Show our custom modal immediately (synchronously)
                showRefreshBackModal('refresh');
                
                // Set returnValue to prevent the refresh
                // This is REQUIRED to actually stop the page from refreshing
                // Note: Due to browser security, this may also trigger browser's default dialog
                // But our custom modal will appear too, giving user choice
                e.preventDefault();
                e.returnValue = ''; // Empty string - browser will show its own message
                return ''; // Also return empty string for older browsers
            }}
        }}
        
        // Handle browser back button (popstate event)
        function handlePopState(e) {{
            // Only prevent back navigation if test is in progress and user hasn't confirmed navigation
            // Include SUS page on completion screen (isOnCompletionScreen check removed)
            if (currentQuestionIndex >= 0 && !testCompleted && !isNavigatingAway) {{
                // Push current state back to prevent navigation
                window.history.pushState(null, '', window.location.href);
                // Show confirmation modal
                showRefreshBackModal('back');
            }}
        }}

        // Global variables for answer pages
        let currentAnswerPageIndex = 0;
        let answerPagesVisible = false;

        // Generate answer pages HTML
        function generateAnswerPages() {{
            return questions.map((question, index) => {{
                const questionData = parseQuestion(question.question);
                const userAnswer = answers[index] || [];
                const isCorrect = checkAnswer(userAnswer, index);
                
                // Parse correct answers from question text
                const correctAnswers = parseCorrectAnswers(question.question);
                
                // Use the same logic as generateQuestionHTML but with answer-specific modifications
                // First answer (question0) doesn't show subspecs, others do
                const showSubspecs = index > 0;
                
                // 解析 subspec 数据用于处理 options
                const subspecParsed = parseSubspecData(question.configSubspec, question.lineSubspec, question.configSubspecTrans, question.lineSubspecTrans);
                
                // 处理 options 文本，支持 subspec
                const processedOptions = questionData.options.map(option => {{
                    // 检查是否是 diff 格式（包含 - 或 + 开头的行）
                    const lines = option.text.split('\\n');
                    const isDiff = lines.some(line => line.trim().startsWith('-') || line.trim().startsWith('+'));
                    
                    if (isDiff) {{
                        // diff 格式：使用 formatDiffContent
                        const processedText = formatDiffContent(lines, subspecParsed.subspecData, subspecParsed.configSubspecData, subspecParsed.lineSubspecData, subspecParsed.lineSubspecNames, showSubspecs, subspecParsed.configSubspecTransData, subspecParsed.lineSubspecTransData);
                        return {{...option, text: processedText}};
                    }} else {{
                        // 普通文本：使用 processOptionText
                        const processedText = processOptionText(option.text, subspecParsed.subspecData, subspecParsed.configSubspecData, subspecParsed.lineSubspecData, subspecParsed.lineSubspecNames, showSubspecs, subspecParsed.configSubspecTransData, subspecParsed.lineSubspecTransData);
                        return {{...option, text: processedText}};
                    }}
                }});
                
                return `
                    <div class="answer-page" id="answerPage${{index}}">
                        <!-- Answer Navigation and Progress Container -->
                        <div class="answer-navigation-container">
                            <!-- First Row: Navigation and Status -->
                            <div class="answer-navigation-row">
                                <div class="answer-nav-buttons">
                                    <button class="btn btn-secondary" onclick="previousAnswerPage()" id="prevAnswerBtn${{index}}">
                                        ${{index === 0 ? texts.backToResults : texts.previousAnswer}}
                                    </button>
                                    <button class="btn btn-primary" onclick="nextAnswerPage()" id="nextAnswerBtn${{index}}">
                                        ${{index === questions.length - 1 ? texts.backToResults : texts.nextAnswer}}
                                    </button>
                                </div>
                                <div class="answer-counter">${{texts.answerCounter}} <span>${{index + 1}}</span> ${{texts.of}} ${{questions.length}}</div>
                            </div>
                            
                            <!-- Second Row: Progress Bar -->
                            <div class="answer-progress-row">
                                <div class="progress-bar-fill">
                                    <div class="progress-bar-progress" style="width: ${{((index + 1) / questions.length) * 100}}%"></div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Four-panel layout (copied from generateQuestionHTML) -->
                        <div class="question-layout">
                            <!-- Top-left: Network Topology -->
                            <div class="section panel-topology">
                                <h2>${{texts.networkTopology}}</h2>
                                <div class="topology-image">
                                    <img src="${{questionImages[currentLanguage][index]}}" alt="${{texts.networkTopology}}" />
                                </div>
                            </div>

                            <!-- Top-right: Network Specification -->
                            <div class="section panel-specification">
                                <h2>${{index === 0 ? texts.networkSpecQuestion0 : texts.networkSpec}}</h2>
                                <div class="specification-text">
                                    ${{question.spec}}
                                </div>
                            </div>

                            <!-- Bottom-left: Configuration Display -->
                            <div class="section panel-config">
                                <h2>${{showSubspecs ? texts.coreConfigWithSubspecs : texts.coreConfig}}</h2>
                                ${{generateCollapsibleConfigsForAnswer(question.config, question.configSubspec, question.lineSubspec, showSubspecs, question.highlight, index, question.configSubspecTrans, question.lineSubspecTrans)}}
                            </div>

                            <!-- Bottom-right: Question Section -->
                            <div class="section panel-questions">
                                <h2>${{index === 0 ? texts.maintenanceTaskQuestion0 : texts.maintenanceTask}}</h2>
                                <div class="question-text">
                                    ${{questionData.text}}
                                </div>
                                
                                ${{questionData.note ? `<div class="question-instruction note-instruction">
                                    <div class="instruction-line">${{questionData.note}}</div>
                                </div>` : ''}}
                                
                                ${{showSubspecs ? `<div class="question-instruction">
                                    <div class="instruction-line">📋 ${{texts.questionNote1}}</div>
                                    <div class="instruction-line">📋 ${{texts.questionNote2}}</div>
                                </div>` : ''}}
                                
                                    <div class="question-instruction">
                                        <strong>📋</strong> ${{texts.correctAnswersInstruction}}
                                    </div>
                                
                                <div class="question-options">
                                    ${{processedOptions.map((option, i) => {{
                                        const isSelected = userAnswer.includes(option.value);
                                        const isCorrectOption = correctAnswers.includes(option.value);
                                        // 为解析页面的选项生成唯一 ID
                                        const optionId = `answer-${{index}}-option-${{i}}`;
                                        return `
                                            <div class="option-item ${{isSelected ? 'selected' : ''}} ${{isCorrectOption ? 'correct' : 'incorrect'}}" id="${{optionId}}" data-option-id="${{optionId}}">
                                                <span class="answer-option-checkmark ${{isCorrectOption ? 'correct' : 'incorrect'}}"></span>
                                                <label>
                                                    <div class="option-diff-content">${{option.text}}</div>
                                                </label>
                                            </div>
                                        `;
                                    }}).join('')}}
                                </div>
                                
                                <!-- Answer Explanation -->
                                <div class="question-instruction note-instruction">
                                    <div class="instruction-line" style="font-weight: bold; margin-bottom: 8px; color: #667eea;">${{texts.answerExplanation}}</div>
                                    ${{formatExplanation(question.answer)}}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }}).join('');
        }}

        // Generate collapsible configs for answer pages with unique IDs
        function generateCollapsibleConfigsForAnswer(configContent, configSubspecContent, lineSubspecContent, showSubspecs, highlightContent, answerPageIndex, configSubspecTransContent, lineSubspecTransContent) {{
            // Parse config content, separate different router configs
            const configs = parseConfigSections(configContent);
            
            // Generate config legend for answer pages
            const highlightTerms = highlightContent ? highlightContent.split('\\n').filter(term => term.trim()) : [];
            const categorizedTerms = categorizeConfigTerms(highlightTerms);
            const legend = generateConfigLegend(categorizedTerms, showSubspecs);
            
            const configBlocks = configs.map((config, index) => {{
                const routerName = config.router || `Router ${{index + 1}}`;
                const processedLines = processConfig(config.content, configSubspecContent, lineSubspecContent, showSubspecs, highlightContent, configSubspecTransContent, lineSubspecTransContent);
                // Generate unique ID for each answer page
                const configId = `answer-config-${{answerPageIndex}}-${{index}}`;
                
                return `
                    <div class="config-collapsible config-section" data-router="${{routerName}}">
                        <div class="config-header" onclick="toggleConfig('${{configId}}')">
                            <span class="config-caret" id="caret-${{configId}}">▶</span>
                            <span class="config-title">${{routerName}}</span>
                        </div>
                        <div class="config-content" id="${{configId}}">${{processedLines.map((line, lineIndex) => `<span class="config-line" data-line="${{lineIndex + 1}}">${{line}}</span>`).join('')}}</div>
                    </div>
                `;
            }}).join('');
            
            return legend + configBlocks;
        }}

        // Parse correct answers from question text
        function parseCorrectAnswers(questionText) {{
            const correctAnswers = [];
            const lines = questionText.split('\\n');
            
            for (const line of lines) {{
                if (line.includes('[yes]')) {{
                    const match = line.match(/option(\\d+):\\s*\\[yes\\]/);
                    if (match) {{
                        // Convert option1, option2, option3 to option_1, option_2, option_3
                        const optionNum = match[1];
                        correctAnswers.push(`option_${{optionNum}}`);
                    }}
                }}
            }}
            
            return correctAnswers;
        }}

        // Show answer pages
        function showAnswerPages() {{
            // Hide the entire completion screen
            document.querySelector('.completion-screen').style.display = 'none';
            document.getElementById('answerPagesContainer').style.display = 'block';
            answerPagesVisible = true;
            // 重置 completion screen 状态，允许在答案解释页面显示固定窗口
            isOnCompletionScreen = false;
            currentAnswerPageIndex = 0;
            
            // Show fixed bar toggle button on answer pages
            toggleFixedBarButton(true);
            
            // Reset fixed bar state to enabled (default state for answer pages)
            resetFixedBarState();
            
            showAnswerPage(0);
            
            // 滚动到页面顶部
            window.scrollTo(0, 0);
        }}

        // Show specific answer page
        function showAnswerPage(index) {{
            // Hide all answer pages
            document.querySelectorAll('.answer-page').forEach(page => {{
                page.classList.remove('active');
            }});
            
            // Show current answer page
            const currentPage = document.getElementById(`answerPage${{index}}`);
            if (currentPage) {{
                currentPage.classList.add('active');
            }}
            
            // Update navigation buttons for current page
            const prevBtn = document.getElementById(`prevAnswerBtn${{index}}`);
            const nextBtn = document.getElementById(`nextAnswerBtn${{index}}`);
            
            if (prevBtn) {{
                prevBtn.textContent = index === 0 ? texts.backToResults : texts.previousAnswer;
            }}
            if (nextBtn) {{
                nextBtn.textContent = index === questions.length - 1 ? texts.backToResults : texts.nextAnswer;
            }}
            
            // Add event listeners for answer page (especially for config dropdowns)
            addAnswerPageEventListeners();
            
            // Update fixed top bar for answer page
            if (questions && index >= 0 && index < questions.length) {{
                const question = questions[index];
                updateFixedTopBar(question);
            }}
            
            // Initialize scroll detection for answer page
            initScrollDetection();
            
            // Update config reference tooltips for answer page
            updateConfigReferenceTooltips();
            
            // 滚动到页面顶部
            window.scrollTo(0, 0);
        }}

        // Navigate to previous answer page
        function previousAnswerPage() {{
            if (currentAnswerPageIndex > 0) {{
                currentAnswerPageIndex--;
                showAnswerPage(currentAnswerPageIndex);
            }} else {{
                // Go back to completion screen
                hideAnswerPages();
            }}
        }}

        // Navigate to next answer page
        function nextAnswerPage() {{
            if (currentAnswerPageIndex < questions.length - 1) {{
                currentAnswerPageIndex++;
                showAnswerPage(currentAnswerPageIndex);
            }} else {{
                // Go back to completion screen
                hideAnswerPages();
            }}
        }}

        // Add event listeners for answer pages
        function addAnswerPageEventListeners() {{
            // Clean up previous events before adding new ones
            removeHoverEvents();
            // Add subspec tooltip events (always show subspecs in answer pages)
            addHoverEvents();
            
            // 使用与问题界面相同的配置引用处理逻辑（基于 bit-map 机制）
            // 但需要限制在当前的答案页面容器内
            const configReferences = document.querySelectorAll('.config-reference');
            
            configReferences.forEach(ref => {{
                // Remove existing listeners to avoid duplicates
                const newRef = ref.cloneNode(true);
                ref.parentNode.replaceChild(newRef, ref);
                
                newRef.addEventListener('click', function(e) {{
                    e.preventDefault();
                    e.stopPropagation();
                    
                    const router = this.getAttribute('data-router');
                    const lines = this.getAttribute('data-lines');
                    if (!lines) return;
                    
                    const currentOptionId = getOptionId(this);
                    
                    // 找到当前答案页面容器（如果存在）
                    const answerPage = this.closest('.answer-page');
                    const containerElement = answerPage || null;
                    
                    // 检查当前配置引用是否已激活
                    const isCurrentlyActive = isConfigRefActive(router, lines, currentOptionId);
                    
                    if (isCurrentlyActive) {{
                        // 场景1: 当前配置引用已激活，点击则关闭
                        deactivateConfigRef(router, lines, currentOptionId);
                        clearConfigLinesHighlight(router, lines, containerElement);
                        
                        // 检查当前选项是否还有其他激活的配置引用
                        const hasOtherActiveRefs = Array.from(configReferenceBitMap.values())
                            .some(data => data.optionId === currentOptionId && data.isActive);
                        
                        if (!hasOtherActiveRefs) {{
                            currentActiveOption = null;
                        }}
                    }} else {{
                        // 场景2: 当前配置引用未激活
                        if (currentActiveOption && currentActiveOption !== currentOptionId) {{
                            // 场景2a: 当前有其他选项激活，先清除其他选项的所有配置引用
                            // 在解析页面中，需要在整个文档中清除（因为可能在不同的答案页面中）
                            clearOptionConfigRefs(currentActiveOption, null);
                            // 同时清除所有高亮（确保完全清除，包括所有答案页面中的高亮）
                            clearAllHighlights();
                        }}
                        
                        // 激活当前配置引用
                        activateConfigRef(router, lines, currentOptionId);
                        currentActiveOption = currentOptionId;
                        
                        // 收集当前选项所有激活的配置引用，用于展开多个设备
                        if (router) {{
                            const activeRefs = Array.from(configReferenceBitMap.entries())
                                .filter(([refId, data]) => data.optionId === currentOptionId && data.isActive)
                                .map(([refId, data]) => refId.split('-')[1]); // 提取router
                            
                            // 先展开所有相关设备的配置下拉栏（与问题界面一致：只展开目标设备，关闭其他设备）
                            // 这必须在 highlightConfigLines 之前调用，确保配置区域已展开
                            expandMultipleDeviceConfigs(activeRefs, containerElement);
                        }} else {{
                            // For references without router, expand all config sections
                            const searchContainer = containerElement || document;
                            searchContainer.querySelectorAll('.config-section').forEach(section => {{
                                const sectionRouter = section.getAttribute('data-router');
                                if (sectionRouter) {{
                                    expandSingleDeviceConfig(sectionRouter, containerElement);
                                }}
                            }});
                        }}
                        
                        // 高亮配置行（传入选项ID以便检查diff内容，以及容器元素）
                        // 注意：highlightConfigLines 内部也会检查并展开配置区域，但这里已经提前展开了
                        highlightConfigLines(router, lines, currentOptionId, containerElement);
                        
                        // 滚动到当前配置区域（与问题界面一致）
                        // 在解析页面中，传入容器元素以确保滚动到正确的配置区域
                        if (router) {{
                            scrollToConfigSection(router, containerElement);
                        }}
                    }}
                    
                    // Update tooltip
                    updateConfigReferenceTooltips();
                }});
            }});
        }}

        // Hide answer pages and show completion screen
        function hideAnswerPages() {{
            // Hide fixed bar toggle button when returning to completion screen
            toggleFixedBarButton(false);
            document.querySelector('.completion-screen').style.display = 'block';
            document.getElementById('answerPagesContainer').style.display = 'none';
            answerPagesVisible = false;
            
            // 确保在completion页面时固定窗口被隐藏
            isOnCompletionScreen = true;
            
            // 清除固定工具栏内容，并滚动到页面顶部
            clearFixedTopBar();
            
            // 触发可见性检查，确保固定窗口被隐藏
            if (typeof checkTopologyAndSpecVisibility === 'function') {{
                checkTopologyAndSpecVisibility();
            }}
            
            window.scrollTo(0, 0);
        }}

        // Show completion screen
        function showCompletionScreen() {{
            // 清除固定工具栏内容，并滚动到页面顶部
            clearFixedTopBar();
            window.scrollTo(0, 0);
            
            // Hide fixed bar toggle button on completion screen
            toggleFixedBarButton(false);
            
            isOnCompletionScreen = true;
            totalTime = Date.now() - startTime;
            
            // 计算得分
            let correctCount = 0;
            const questionResults = answers.map((answer, index) => {{
                const isCorrect = checkAnswer(answer, index);
                if (isCorrect) correctCount++;
                return {{
                    question: index + 1,
                    correct: isCorrect,
                    time: formatTime(questionTimes[index])
                }};
            }});
            
            const score = correctCount;
            const totalQuestions = answers.length;
            
            // Generate answer slides
            const answerSlides = questions.map((question, index) => {{
                const questionData = parseQuestion(question.question);
                const userAnswer = answers[index] || [];
                const isCorrect = checkAnswer(userAnswer, index);
                
                // 解析 subspec 数据用于处理 options
                // First answer (question0) doesn't show subspecs, others do
                const showSubspecs = index > 0;
                const subspecParsed = parseSubspecData(question.configSubspec, question.lineSubspec, question.configSubspecTrans, question.lineSubspecTrans);
                
                // 处理 options 文本，支持 subspec
                const processedOptions = questionData.options.map(option => {{
                    // 检查是否是 diff 格式（包含 - 或 + 开头的行）
                    const lines = option.text.split('\\n');
                    const isDiff = lines.some(line => line.trim().startsWith('-') || line.trim().startsWith('+'));
                    
                    if (isDiff) {{
                        // diff 格式：使用 formatDiffContent
                        const processedText = formatDiffContent(lines, subspecParsed.subspecData, subspecParsed.configSubspecData, subspecParsed.lineSubspecData, subspecParsed.lineSubspecNames, showSubspecs, subspecParsed.configSubspecTransData, subspecParsed.lineSubspecTransData);
                        return {{...option, text: processedText}};
                    }} else {{
                        // 普通文本：使用 processOptionText
                        const processedText = processOptionText(option.text, subspecParsed.subspecData, subspecParsed.configSubspecData, subspecParsed.lineSubspecData, subspecParsed.lineSubspecNames, showSubspecs, subspecParsed.configSubspecTransData, subspecParsed.lineSubspecTransData);
                        return {{...option, text: processedText}};
                    }}
                }});
                
                return `
                    <div class="answer-slide">
                        <div class="slide-header">
                            <div class="slide-title">Question ${{index + 1}}</div>
                            <div class="slide-status ${{isCorrect ? 'correct' : 'incorrect'}}">
                                ${{isCorrect ? 'Correct' : 'Incorrect'}}
                            </div>
                        </div>
                        <div class="slide-content">
                            <h4>${{questionData.text}}</h4>
                        </div>
                        <div class="answer-options">
                            ${{processedOptions.map((option, optIndex) => {{
                                const isSelected = userAnswer.includes(option.value);
                                const isCorrectOption = option.correct;
                                return `
                                    <div class="answer-option ${{isSelected ? 'selected' : ''}} ${{isCorrectOption ? 'correct' : 'incorrect'}}">
                                        <div class="option-diff-content">${{option.text}}</div>
                                    </div>
                                `;
                            }}).join('')}}
                        </div>
                        <div class="question-instruction note-instruction" style="margin-top: 20px;">
                            <div class="instruction-line" style="font-weight: bold; margin-bottom: 8px; color: #667eea;">Explanation</div>
                            ${{formatExplanation(question.answer)}}
                        </div>
                    </div>
                `;
            }}).join('');
            
            const completionHtml = `
                <div class="completion-screen">
                    <div class="completion-description">
                        <h2>${{texts.completionTitle}}</h2>
                        <p class="completion-text">${{texts.completionText}}</p>
                    </div>
                    
                    <div class="completion-layout">
                        <div class="completion-left-column">
                            <div class="completion-card">
                                <h3 id="susTitle">${{texts.sus}}</h3>
                            
                            <!-- SUS Scale Legend (shown once at the top) -->
                            <div class="sus-scale-legend">
                                <div class="sus-likert-labels">
                                    <span>${{texts.stronglyDisagree}}</span>
                                    <span>${{texts.disagree}}</span>
                                    <span>${{texts.neutral}}</span>
                                    <span>${{texts.agree}}</span>
                                    <span>${{texts.stronglyAgree}}</span>
                                </div>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <span class="scale-number">1</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <span class="scale-number">2</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <span class="scale-number">3</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <span class="scale-number">4</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <span class="scale-number">5</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion1Label">1. ${{texts.susQuestion1}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus1" value="1" id="sus1_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus1" value="2" id="sus1_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus1" value="3" id="sus1_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus1" value="4" id="sus1_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus1" value="5" id="sus1_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion2Label">2. ${{texts.susQuestion2}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus2" value="1" id="sus2_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus2" value="2" id="sus2_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus2" value="3" id="sus2_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus2" value="4" id="sus2_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus2" value="5" id="sus2_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion3Label">3. ${{texts.susQuestion3}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus3" value="1" id="sus3_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus3" value="2" id="sus3_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus3" value="3" id="sus3_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus3" value="4" id="sus3_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus3" value="5" id="sus3_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion4Label">4. ${{texts.susQuestion4}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus4" value="1" id="sus4_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus4" value="2" id="sus4_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus4" value="3" id="sus4_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus4" value="4" id="sus4_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus4" value="5" id="sus4_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion5Label">5. ${{texts.susQuestion5}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus5" value="1" id="sus5_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus5" value="2" id="sus5_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus5" value="3" id="sus5_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus5" value="4" id="sus5_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus5" value="5" id="sus5_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion6Label">6. ${{texts.susQuestion6}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus6" value="1" id="sus6_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus6" value="2" id="sus6_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus6" value="3" id="sus6_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus6" value="4" id="sus6_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus6" value="5" id="sus6_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion7Label">7. ${{texts.susQuestion7}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus7" value="1" id="sus7_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus7" value="2" id="sus7_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus7" value="3" id="sus7_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus7" value="4" id="sus7_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus7" value="5" id="sus7_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion8Label">8. ${{texts.susQuestion8}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus8" value="1" id="sus8_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus8" value="2" id="sus8_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus8" value="3" id="sus8_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus8" value="4" id="sus8_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus8" value="5" id="sus8_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion9Label">9. ${{texts.susQuestion9}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus9" value="1" id="sus9_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus9" value="2" id="sus9_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus9" value="3" id="sus9_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus9" value="4" id="sus9_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus9" value="5" id="sus9_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="sus-question">
                                <label id="susQuestion10Label">10. ${{texts.susQuestion10}}</label>
                                <div class="sus-likert-scale">
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus10" value="1" id="sus10_1">
                                        <span class="sus-tooltip">${{texts.stronglyDisagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus10" value="2" id="sus10_2">
                                        <span class="sus-tooltip">${{texts.disagree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus10" value="3" id="sus10_3">
                                        <span class="sus-tooltip">${{texts.neutral}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus10" value="4" id="sus10_4">
                                        <span class="sus-tooltip">${{texts.agree}}</span>
                                    </div>
                                    <div class="sus-likert-option">
                                        <input type="radio" name="sus10" value="5" id="sus10_5">
                                        <span class="sus-tooltip">${{texts.stronglyAgree}}</span>
                                    </div>
                                </div>
                            </div>
                            </div>
                        </div>
                    
                        <div class="completion-right-column">
                            <div class="completion-card">
                                <h3 id="surveyTitle">${{texts.survey}}</h3>
                            <div class="survey-question">
                                <label id="surveyQuestion1Label">1. ${{texts.surveyQuestion1}}</label>
                                <textarea id="surveyQ1" placeholder="${{texts.surveyQuestion1Placeholder}}" rows="3"></textarea>
                            </div>
                            
                            <div class="survey-question">
                                <label id="surveyQuestion2Label">2. ${{texts.surveyQuestion2}}</label>
                                <textarea id="surveyQ2" placeholder="${{texts.surveyQuestion2Placeholder}}" rows="3"></textarea>
                            </div>
                            
                            <div class="completion-buttons">
                                <button class="btn btn-primary" onclick="showAnswerPages()">${{texts.viewAnswerExplanations}}</button>
                                <button class="submit-survey-btn" onclick="submitSurvey()" id="completeBtn">${{texts.complete}}</button>
                            </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Answer Pages Container (outside completion screen) -->
                <div id="answerPagesContainer" style="display: none;">
                    ${{generateAnswerPages()}}
                </div>
            `;
            
            document.getElementById('testContent').innerHTML = completionHtml;
            document.querySelector('.progress-bar').style.display = 'none';
            
            // 确保固定工具栏已清除（已在函数开始时调用 clearFixedTopBar()，这里再次确保）
            clearFixedTopBar();
            
            // Hide language switcher on completion screen
            hideLanguageSwitcher();
            
            // 初始化问卷调查
            // initSurvey(); // 已移除星级评分功能
            
            // 滚动到页面顶部
            window.scrollTo(0, 0);
        }}


        // 问卷调查功能
        // 星级评分功能已移除

        // Calculate SUS score based on Wikipedia formula
        function calculateSUSScore(susData) {{
            // SUS formula from Wikipedia: 2.5 * (20 + sum of odd questions - sum of even questions)
            // Odd questions (1,3,5,7,9): use raw score
            // Even questions (2,4,6,8,10): use raw score
            
            let oddSum = 0;
            let evenSum = 0;
            
            for (let i = 1; i <= 10; i++) {{
                const score = susData[`question${{i}}`];
                if (score !== null && score !== undefined) {{
                    if (i % 2 === 1) {{ // Odd questions (1,3,5,7,9)
                        oddSum += score;
                    }} else {{ // Even questions (2,4,6,8,10)
                        evenSum += score;
                    }}
                }}
            }}
            
            const susScore = 2.5 * (20 + oddSum - evenSum);
            return Math.round(susScore * 100) / 100; // Round to 2 decimal places
        }}

        function submitSurvey() {{
            const surveyQ1 = document.getElementById('surveyQ1').value.trim();
            const surveyQ2 = document.getElementById('surveyQ2').value.trim();
            const submitBtn = document.querySelector('.submit-survey-btn');
            
            // Collect SUS data
            const susData = {{}};
            let allSusAnswered = true;
            for (let i = 1; i <= 10; i++) {{
                const selectedOption = document.querySelector(`input[name="sus${{i}}"]:checked`);
                susData[`question${{i}}`] = selectedOption ? parseInt(selectedOption.value) : null;
                if (!selectedOption) {{
                    allSusAnswered = false;
                }}
            }}
            
            // Validate SUS questions - all must be answered
            if (!allSusAnswered) {{
                document.getElementById('susValidationModal').style.display = 'block';
                return;
            }}
            
            // Calculate SUS score
            const susScore = calculateSUSScore(susData);
            
            // 调查问题现在是可选的，不需要验证
            
            // 星级评分已移除，无需验证
            
            // Disable button to prevent duplicate submission
            submitBtn.disabled = true;
            submitBtn.textContent = 'Completed';
            
            // Collect all test data
            const testData = {{
                timestamp: new Date().toISOString(),
                userGroup: userGroup,
                language: currentLanguage,
                userNumber: userNumber,
                totalTime: formatTime(totalTime),
                score: answers.filter((answer, index) => checkAnswer(answer, index)).length,
                totalQuestions: answers.length,
                questionTimes: questionTimes.map(time => formatTime(time)),
                answers: answers,
                userNotes: userNotes,
                questionCorrectness: answers.map((answer, index) => checkAnswer(answer, index)),
                sus: {{
                    scores: susData,
                    totalScore: susScore
                }},
                survey: {{
                    question1: surveyQ1,
                    question2: surveyQ2
                }}
            }};
            
            // 提交到Netlify表单
            submitToNetlify(testData);
        }}

        // Netlify表单提交函数
        function submitToNetlify(testData) {{
            try {{
                // 获取隐藏表单
                const form = document.querySelector('form[name="user-study-results"]');
                if (!form) {{
                    console.error('找不到Netlify表单');
                    showSubmissionError(testData);
                    return;
                }}

                // 填充表单字段
                form.querySelector('input[name="timestamp"]').value = testData.timestamp;
                form.querySelector('input[name="userGroup"]').value = testData.userGroup;
                form.querySelector('input[name="language"]').value = testData.language;
                form.querySelector('input[name="userNumber"]').value = testData.userNumber || '';
                form.querySelector('input[name="totalTime"]').value = testData.totalTime || '0';
                form.querySelector('input[name="score"]').value = testData.score || '0';
                form.querySelector('input[name="totalQuestions"]').value = testData.totalQuestions || '0';
                form.querySelector('input[name="questionTimes"]').value = JSON.stringify(testData.questionTimes || []);
                form.querySelector('input[name="answers"]').value = JSON.stringify(testData.answers || []);
                form.querySelector('input[name="userNotes"]').value = JSON.stringify(testData.userNotes || []);
                form.querySelector('input[name="questionCorrectness"]').value = JSON.stringify(testData.questionCorrectness || []);
                form.querySelector('input[name="surveyQ1"]').value = testData.survey.question1 || '';
                form.querySelector('input[name="surveyQ2"]').value = testData.survey.question2 || '';
                form.querySelector('input[name="susTotalScore"]').value = testData.sus.totalScore || '0';
                form.querySelector('input[name="susScores"]').value = JSON.stringify(testData.sus.scores || {{}});
                form.querySelector('input[name="bot-field"]').value = '';

                // 使用AJAX提交避免页面跳转
                const formData = new FormData(form);

                fetch('/', {{
                    method: 'POST',
                    body: formData
                }})
                .then(response => {{
                    if (response.ok) {{
                        showSubmissionSuccess();
                    }} else {{
                        console.error('提交失败:', response.status, response.statusText);
                        showSubmissionError(testData);
                    }}
                }})
                .catch(error => {{
                    console.error('提交错误:', error);
                    showSubmissionError(testData);
                }});
            }} catch (err) {{
                console.error('Netlify提交发生异常:', err);
                showSubmissionError(testData);
            }}
        }}

        function showSubmissionSuccess() {{
            // 禁用提交按钮并显示成功状态
            const submitBtn = document.querySelector('.submit-survey-btn');
            submitBtn.disabled = true;
            submitBtn.textContent = texts.submitted;
            submitBtn.style.background = '#28a745';
            submitBtn.style.cursor = 'not-allowed';
            
            // 显示简单的成功消息
            const surveySection = document.querySelector('.survey-section');
            if (surveySection) {{
                const successMsg = document.createElement('div');
                successMsg.className = 'submission-status success';
                successMsg.innerHTML = `
                    <div style="text-align: center; padding: 20px; background: #d4edda; border: 1px solid #c3e6cb; border-radius: 8px; margin-top: 20px;">
                        <h4 style="color: #155724; margin: 0;">✅ 数据已成功提交</h4>
                        <p style="color: #155724; margin: 10px 0 0 0;">感谢您的参与！</p>
                    </div>
                `;
                surveySection.appendChild(successMsg);
            }}
        }}

        // 下载数据到本地文件
        function downloadDataAsFile(testData) {{
            try {{
                // 将数据转换为 JSON 字符串
                const jsonData = JSON.stringify(testData, null, 2);
                
                // 创建 Blob 对象
                const blob = new Blob([jsonData], {{ type: 'application/json' }});
                
                // 创建下载链接
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                
                // 生成文件名（包含时间戳和用户编号）
                const timestamp = testData.timestamp || new Date().toISOString();
                const userNumber = testData.userNumber || 'unknown';
                const filename = `user-study-data-${{userNumber}}-${{timestamp.replace(/[:.]/g, '-')}}.json`;
                a.download = filename;
                
                // 触发下载
                document.body.appendChild(a);
                a.click();
                
                // 清理
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }} catch (err) {{
                console.error('下载数据失败:', err);
            }}
        }}
        
        function showSubmissionError(testData) {{
            // 禁用提交按钮并显示错误状态
            const submitBtn = document.querySelector('.submit-survey-btn');
            submitBtn.disabled = true;
            submitBtn.textContent = texts.submissionFailed;
            submitBtn.style.background = '#dc3545';
            submitBtn.style.cursor = 'not-allowed';
            
            // 如果提供了 testData，自动下载到本地
            if (testData) {{
                downloadDataAsFile(testData);
            }}
            
            // 显示简单的错误消息
            const surveySection = document.querySelector('.survey-section');
            if (surveySection) {{
                const errorMsg = document.createElement('div');
                errorMsg.className = 'submission-status error';
                const downloadMsg = testData ? '<p style="color: #721c24; margin: 10px 0 0 0;">数据已自动保存到本地文件</p>' : '';
                errorMsg.innerHTML = `
                    <div style="text-align: center; padding: 20px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 8px; margin-top: 20px;">
                        <h4 style="color: #721c24; margin: 0;">❌ 提交失败</h4>
                        <p style="color: #721c24; margin: 10px 0 0 0;">请检查网络连接后重试</p>
                        ${{downloadMsg}}
                    </div>
                `;
                surveySection.appendChild(errorMsg);
            }}
        }}

        function showSurveyComplete(testData) {{
            // 停止计时器
            stopTimer();
            
            // 生成并下载表单文件
            generateAndDownloadForm(testData);
            
            // 恢复按钮状态
            const submitBtn = document.querySelector('.submit-survey-btn');
            submitBtn.textContent = 'Complete';
            submitBtn.disabled = false;
            submitBtn.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
            
            // 显示完成提示
            showDownloadComplete();
        }}

        function generateAndDownloadForm(testData) {{
            // 生成表单内容
            const formContent = generateFormContent(testData);
            
            // 创建并下载文件
            const blob = new Blob([formContent], {{ type: 'text/plain;charset=utf-8' }});
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `Network_Verification_Test_Results_Group_${{testData.userGroup}}_${{new Date().toISOString().split('T')[0]}}.txt`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
            
            // 显示完成提示
            showDownloadComplete();
        }}

        function generateFormContent(testData) {{
            let content = '';
            
            // Form title
            content += '='.repeat(50) + '\\n';
            content += 'Explainable Network Verification via Localized Subspecification - User Study\\n';
            content += '='.repeat(50) + '\\n\\n';
            
            // Test time
            content += 'Test Time: ' + new Date().toLocaleString() + '\\n\\n';
            
            // Test basic information
            content += 'Test Basic Information\\n';
            content += '-'.repeat(30) + '\\n';
            content += 'Test Group: Group ' + testData.userGroup + '\\n';
            content += 'Test Language: English\\n';
            content += 'Total Time: ' + testData.totalTime + '\\n';
            content += 'Score: ' + testData.score + '/' + testData.totalQuestions + '\\n\\n';
            
            // Question time details
            content += 'Question Time Details\\n';
            content += '-'.repeat(30) + '\\n';
            testData.questionTimes.forEach((time, index) => {{
                content += 'Question ' + (index + 1) + ': ' + time + '\\n';
            }});
            content += '\\n';
            
            // User answers
            content += 'User Answers\\n';
            content += '-'.repeat(30) + '\\n';
            testData.answers.forEach((answer, index) => {{
                content += 'Question ' + (index + 1) + ': ' + answer.join(', ') + '\\n';
            }});
            content += '\\n';
            
            // User notes
            content += 'User Notes\\n';
            content += '-'.repeat(30) + '\\n';
            testData.userNotes.forEach((note, index) => {{
                content += 'Question ' + (index + 1) + ': ' + (note || '(no notes)') + '\\n';
            }});
            content += '\\n';
            
            // Question correctness
            content += 'Question Correctness\\n';
            content += '-'.repeat(30) + '\\n';
            testData.questionCorrectness.forEach((isCorrect, index) => {{
                content += 'Question ' + (index + 1) + ': ' + (isCorrect ? 'Correct' : 'Incorrect') + '\\n';
            }});
            content += '\\n';
            
            // SUS
            content += 'System Usability Scale (SUS)\\n';
            content += '-'.repeat(30) + '\\n';
            content += 'Total Score: ' + testData.sus.totalScore + '\\n';
            for (let i = 1; i <= 10; i++) {{
                content += 'Question ' + i + ': ' + (testData.sus.scores['question' + i] || 'Not answered') + '\\n';
            }}
            content += '\\n';
            
            // Survey
            content += texts.survey + '\\n';
            content += '-'.repeat(30) + '\\n';
            content += 'Question 1: ' + texts.surveyQuestion1 + '\\n';
            content += 'Answer: ' + testData.survey.question1 + '\\n\\n';
            
            content += 'Question 2: ' + texts.surveyQuestion2 + '\\n';
            content += 'Answer: ' + testData.survey.question2 + '\\n\\n';
            
            // 星级评分已移除
            
            // Bottom note
            content += '='.repeat(50) + '\\n';
            content += 'Please send this file to the researchers\\n';
            content += '='.repeat(50) + '\\n';
            
            return content;
        }}

        function showDownloadComplete() {{
            // Show download complete message
            const completeHtml = `
                <div class="download-complete">
                    <div class="complete-icon">✅</div>
                    <h3>Test Completed!</h3>
                    <p>The form file has been downloaded to your device. Please send the file to the researchers.</p>
                    
                    <div class="complete-actions">
                        <button class="action-btn secondary" onclick="location.reload()">Restart Test</button>
                    </div>
                </div>
            `;
            
            // Hide survey section and show completion message
            const surveySection = document.querySelector('.survey-section');
            surveySection.style.display = 'none';
            surveySection.insertAdjacentHTML('afterend', completeHtml);
        }}


        // 计时器
        let timerInterval = null;
        
        function startTimer() {{
            // 清除之前的计时器
            if (timerInterval) {{
                clearInterval(timerInterval);
            }}
            
            timerInterval = setInterval(() => {{
                if (startTime) {{
                    const totalElapsed = Date.now() - startTime;
                    document.getElementById('totalTimer').textContent = formatTime(totalElapsed);
                }}
                
                if (questionStartTime) {{
                    const questionElapsed = Date.now() - questionStartTime;
                    document.getElementById('questionTimer').textContent = formatTime(questionElapsed);
                }}
            }}, 1000);
        }}
        
        function stopTimer() {{
            if (timerInterval) {{
                clearInterval(timerInterval);
                timerInterval = null;
            }}
        }}

        // 格式化时间
        function formatTime(milliseconds) {{
            const seconds = Math.floor(milliseconds / 1000);
            const minutes = Math.floor(seconds / 60);
            const remainingSeconds = seconds % 60;
            return `${{minutes.toString().padStart(2, '0')}}:${{remainingSeconds.toString().padStart(2, '0')}}`;
        }}

        // 浏览器检测和字体粗细调整
        function detectBrowserAndAdjustFontWeight() {{
            const userAgent = navigator.userAgent.toLowerCase();
            const body = document.body;
            
            // 移除之前的浏览器类
            body.classList.remove('browser-chrome', 'browser-edge', 'browser-safari', 'browser-firefox', 'browser-other');
            
            // 简化的Safari检测
            const isSafari = userAgent.includes('safari') && !userAgent.includes('chrome');
            const isFirefox = userAgent.includes('firefox');
            const isChrome = userAgent.includes('chrome') || userAgent.includes('edg');
            
            if (isSafari) {{
                body.classList.add('browser-safari');
            }} else if (isFirefox) {{
                body.classList.add('browser-firefox');
            }} else if (isChrome) {{
                body.classList.add('browser-chrome');
            }} else {{
                body.classList.add('browser-other');
            }}
        }}
        
        // 提取规约第一句话（第一个<b>标签及其后面的内容，直到第一个<br>或</em>）
        function extractSpecFirstLine(specHtml) {{
            if (!specHtml) return '';
            
            // 创建一个临时div来解析HTML
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = specHtml;
            
            // 查找第一个<b>标签
            const firstBold = tempDiv.querySelector('b');
            if (!firstBold) {{
                // 如果没有<b>标签，返回第一段文本（最多150字符）
                const text = tempDiv.textContent || tempDiv.innerText || '';
                const firstLine = text.split(/\\n|\\r/)[0].trim();
                return firstLine.substring(0, 150) + (firstLine.length > 150 ? '...' : '');
            }}
            
            // 获取<b>标签的内容
            let result = '<b>' + firstBold.textContent + '</b>';
            
            // 获取<b>标签后面的内容，直到遇到<br>或</em>或段落结束
            let currentNode = firstBold.nextSibling;
            let textAfter = '';
            let foundBreak = false;
            
            while (currentNode && !foundBreak && textAfter.length < 200) {{
                if (currentNode.nodeType === Node.TEXT_NODE) {{
                    let text = currentNode.textContent || '';
                    // 检查文本中是否有换行符
                    if (text.includes('\\n') || text.includes('\\r')) {{
                        text = text.split(/\\n|\\r/)[0];
                        textAfter += text;
                        foundBreak = true;
                    }} else {{
                        textAfter += text;
                    }}
                }} else if (currentNode.nodeType === Node.ELEMENT_NODE) {{
                    const tagName = currentNode.tagName;
                    if (tagName === 'BR') {{
                        foundBreak = true;
                    }} else if (tagName === 'EM' || tagName === 'I') {{
                        // 对于<em>标签，我们包含其内容但然后停止
                        textAfter += currentNode.textContent;
                        foundBreak = true;
                    }} else if (tagName === 'B' || tagName === 'STRONG') {{
                        // 遇到新的加粗标签，停止
                        foundBreak = true;
                    }} else {{
                        // 其他标签，包含其文本内容
                        textAfter += currentNode.textContent || '';
                    }}
                }}
                if (!foundBreak) {{
                    currentNode = currentNode.nextSibling;
                }}
            }}
            
            // 清理文本，移除多余的空白
            textAfter = textAfter.trim();
            // 限制长度
            if (textAfter.length > 200) {{
                textAfter = textAfter.substring(0, 197) + '...';
            }}
            
            return result + (textAfter ? ' ' + textAfter : '');
        }}
        
        // 清除固定工具栏内容
        function clearFixedTopBar() {{
            const fixedTopBar = document.getElementById('fixedTopBar');
            const fixedTopologyMini = document.getElementById('fixedTopologyMini');
            const fixedSpecFirstLine = document.getElementById('fixedSpecFirstLine');
            const fixedQuestionInstruction = document.getElementById('fixedQuestionInstruction');
            
            if (fixedTopBar) {{
                fixedTopBar.classList.remove('visible');
            }}
            if (fixedTopologyMini) {{
                fixedTopologyMini.innerHTML = '';
            }}
            if (fixedSpecFirstLine) {{
                fixedSpecFirstLine.innerHTML = '';
            }}
            if (fixedQuestionInstruction) {{
                fixedQuestionInstruction.innerHTML = '';
            }}
            
            // 重置容器 padding
            const container = document.querySelector('.container');
            if (container) {{
                container.style.paddingTop = '';
            }}
        }}
        
        // 更新固定工具栏内容
        function updateFixedTopBar(question) {{
            const fixedTopBar = document.getElementById('fixedTopBar');
            const fixedTopologyMini = document.getElementById('fixedTopologyMini');
            const fixedSpecFirstLine = document.getElementById('fixedSpecFirstLine');
            const fixedQuestionInstruction = document.getElementById('fixedQuestionInstruction');
            
            if (!fixedTopBar || !fixedTopologyMini || !fixedSpecFirstLine || !question) return;
            
            // 使用 mini 版本的图片（用于固定工具栏）- 直接从 questionImages 获取，避免重复
            const questionIndex = questions.indexOf(question);
            let imgSrc = questionImages[currentLanguage] && questionIndex >= 0 ? questionImages[currentLanguage][questionIndex] : '';
            const specText = question.spec || '';
            
            // 如果image路径存在，直接使用
            if (imgSrc) {{
                fixedTopologyMini.innerHTML = `<img src="${{imgSrc}}" alt="Topology" />`;
            }} else {{
                fixedTopologyMini.innerHTML = '';
            }}
            
            // 更新规约文本（使用和home button相同的方式）
            // 使用和home button相同的逻辑：取第一行，支持HTML标签
            const firstLine = specText.split('\\n')[0];
            fixedSpecFirstLine.innerHTML = firstLine || '';
            
            // 提取问题第一句话中 <br><br> 后面的那句话
            if (fixedQuestionInstruction && question.question) {{
                const questionText = question.question;
                const firstLine = questionText.split('\\n')[0];
                
                // question0 (questionIndex === 0) 特殊处理：显示整行，删除 <br><br>
                if (questionIndex === 0) {{
                    const instructionText = firstLine.replace(/<br><br>/g, ' ').trim();
                    fixedQuestionInstruction.innerHTML = instructionText || '';
                }} else {{
                    // 其他问题：只显示 <br><br> 后面的内容
                    const brIndex = firstLine.indexOf('<br><br>');
                    if (brIndex !== -1) {{
                        const instructionText = firstLine.substring(brIndex + 8).trim();
                        fixedQuestionInstruction.innerHTML = instructionText || '';
                    }} else {{
                        fixedQuestionInstruction.innerHTML = '';
                    }}
                }}
            }}
        }}
        
        // 控制固定栏切换按钮的显示/隐藏
        function toggleFixedBarButton(show) {{
            const toggleBtn = document.getElementById('fixedBarToggleBtn');
            if (toggleBtn) {{
                if (show) {{
                    toggleBtn.style.display = '';
                }} else {{
                    toggleBtn.style.display = 'none';
                }}
            }}
        }}
        
        // 重置固定栏状态为启用（每个页面进入时默认状态）
        function resetFixedBarState() {{
            fixedBarEnabled = true;
            
            const fixedTopBar = document.getElementById('fixedTopBar');
            const toggleBtn = document.getElementById('fixedBarToggleBtn');
            const toggleText = document.getElementById('fixedBarToggleText');
            
            if (fixedTopBar) {{
                fixedTopBar.classList.remove('hidden');
            }}
            
            if (toggleBtn && toggleText && texts) {{
                toggleBtn.classList.add('active');
                toggleText.textContent = texts.hideFixedBar;
            }}
            
            // 清除固定工具栏内容（内容会在 updateFixedTopBar 中更新）
            clearFixedTopBar();
            
            // 触发可见性检查，确保固定栏在合适的时候显示
            setTimeout(() => {{
                if (typeof checkTopologyAndSpecVisibility === 'function') {{
                    checkTopologyAndSpecVisibility();
                }}
            }}, 100);
        }}
        
        // 切换固定栏显示/隐藏
        function toggleFixedBar() {{
            fixedBarEnabled = !fixedBarEnabled;
            // 不再保存到 localStorage，每个页面独立控制
            
            const fixedTopBar = document.getElementById('fixedTopBar');
            const toggleBtn = document.getElementById('fixedBarToggleBtn');
            const toggleText = document.getElementById('fixedBarToggleText');
            
            if (fixedTopBar) {{
                if (fixedBarEnabled) {{
                    fixedTopBar.classList.remove('hidden');
                }} else {{
                    fixedTopBar.classList.add('hidden');
                    fixedTopBar.classList.remove('visible');
                }}
            }}
            
            // 更新按钮状态（无论 fixedTopBar 是否存在）
            if (toggleBtn && toggleText && texts) {{
                if (fixedBarEnabled) {{
                    toggleBtn.classList.add('active');
                    toggleText.textContent = texts.hideFixedBar;
                }} else {{
                    toggleBtn.classList.remove('active');
                    toggleText.textContent = texts.showFixedBar;
                }}
            }}
            
            // 重新检查可见性
            checkTopologyAndSpecVisibility();
        }}
        
        // 初始化固定栏状态
        function initFixedBarState() {{
            // 不再从 localStorage 读取，每个页面独立控制
            fixedBarEnabled = true;
            
            const fixedTopBar = document.getElementById('fixedTopBar');
            const toggleBtn = document.getElementById('fixedBarToggleBtn');
            const toggleText = document.getElementById('fixedBarToggleText');
            
            if (fixedTopBar && toggleBtn && toggleText && texts) {{
                fixedTopBar.classList.remove('hidden');
                toggleBtn.classList.add('active');
                toggleText.textContent = texts.hideFixedBar;
            }}
            
            // 初始状态：在开始页面时隐藏按钮
            if (currentQuestionIndex === -1) {{
                toggleFixedBarButton(false);
            }}
        }}
        
        // 检查拓扑和规约面板是否可见
        let lastVisibilityState = false;
        function checkTopologyAndSpecVisibility() {{
            // 如果固定栏被禁用，直接隐藏
            if (!fixedBarEnabled) {{
            const fixedTopBar = document.getElementById('fixedTopBar');
                if (fixedTopBar && lastVisibilityState) {{
                    lastVisibilityState = false;
                    fixedTopBar.classList.remove('visible');
                    const container = document.querySelector('.container');
                    if (container) {{
                        container.style.paddingTop = '';
                    }}
                }}
                return;
            }}
            
            const fixedTopBar = document.getElementById('fixedTopBar');
            const container = document.querySelector('.container');
            
            // 检查是否在答案解释页面 - 这些页面应该显示固定窗口
            const answerPagesContainer = document.getElementById('answerPagesContainer');
            const isAnswerPagesVisible = answerPagesContainer && 
                answerPagesContainer.style.display !== 'none' && 
                window.getComputedStyle(answerPagesContainer).display !== 'none';
            
            // 如果答案解释页面可见，允许显示固定窗口（继续后续逻辑）
            if (isAnswerPagesVisible) {{
                // 不返回，继续执行后续显示逻辑
            }} else {{
                // 检查是否在completion页面（SUS/Survey页面）- 这些页面不应该显示固定窗口
                const completionScreen = document.querySelector('.completion-screen');
                const isCompletionVisible = completionScreen && 
                    (completionScreen.style.display !== 'none' && 
                     window.getComputedStyle(completionScreen).display !== 'none');
                
                // 如果在completion页面，隐藏固定工具栏
                if (isOnCompletionScreen || isCompletionVisible) {{
                    if (lastVisibilityState) {{
                        lastVisibilityState = false;
                        fixedTopBar.classList.remove('visible');
                        if (container) {{
                            container.style.paddingTop = '';
                        }}
                    }}
                    return;
                }}
            }}
            
            // 检查是否在问题页面或答案页面（通过检查 testContent 是否有内容）
            const testContent = document.getElementById('testContent');
            const hasContent = testContent && testContent.innerHTML.trim() !== '';
            
            // 如果没有内容，隐藏固定工具栏
            if (!hasContent) {{
                if (lastVisibilityState) {{
                    lastVisibilityState = false;
                    fixedTopBar.classList.remove('visible');
                    if (container) {{
                        container.style.paddingTop = '';
                    }}
                }}
                return;
            }}
            
            // 查找当前可见的面板（优先查找激活的答案页面中的面板，否则查找问题页面的面板）
            let topologyPanel = null;
            let specPanel = null;
            
            // 首先尝试在激活的答案页面中查找
            const activeAnswerPage = document.querySelector('.answer-page.active');
            if (activeAnswerPage) {{
                topologyPanel = activeAnswerPage.querySelector('.panel-topology');
                specPanel = activeAnswerPage.querySelector('.panel-specification');
            }}
            
            // 如果没找到，则在问题页面中查找
            if (!topologyPanel || !specPanel) {{
                topologyPanel = document.querySelector('.panel-topology');
                specPanel = document.querySelector('.panel-specification');
            }}
            
            // 如果没有找到面板，不显示固定工具栏
            if (!topologyPanel || !specPanel || !fixedTopBar) {{
                return;
            }}
            
            const rectTopology = topologyPanel.getBoundingClientRect();
            const rectSpec = specPanel.getBoundingClientRect();
            
            // 计算拓扑图的高度和中间位置
            const topologyHeight = rectTopology.height;
            const topologyMiddle = rectTopology.top + topologyHeight / 2;
            
            // 使用迟滞机制（hysteresis）避免反复横跳
            // 当未显示时：需要覆盖一半以上（中间点到达视口顶部）才显示
            // 当已显示时：需要中间点回到视口顶部以上一定距离才隐藏（提供缓冲区）
            let shouldShow;
            if (!lastVisibilityState) {{
                // 未显示状态：拓扑图中间点到达或超过视口顶部时显示
                shouldShow = topologyMiddle <= 0;
            }} else {{
                // 已显示状态：拓扑图中间点回到视口顶部以上20px才隐藏（提供缓冲区避免抖动）
                shouldShow = topologyMiddle <= 20;
            }}
            
            // 只在状态改变时更新，避免频繁切换造成抖动
            if (shouldShow !== lastVisibilityState) {{
                lastVisibilityState = shouldShow;
                
                if (shouldShow) {{
                    fixedTopBar.classList.add('visible');
                    // 窄屏下单列布局时，固定栏占满顶部宽度
                }} else {{
                    fixedTopBar.classList.remove('visible');
                }}
            }}
        }}
        
        // 防抖函数
        function debounce(func, wait) {{
            let timeout;
            return function executedFunction(...args) {{
                const later = () => {{
                    clearTimeout(timeout);
                    func(...args);
                }};
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            }};
        }}
        
        // 创建防抖版本的可见性检查函数
        const debouncedCheckVisibility = debounce(checkTopologyAndSpecVisibility, 50);
        
        // 初始化滚动检测
        let scrollDetectionInitialized = false;
        function initScrollDetection() {{
            // 重置可见性状态
            lastVisibilityState = false;
            
            // 移除旧的滚动监听器
            if (scrollDetectionInitialized) {{
                window.removeEventListener('scroll', debouncedCheckVisibility);
                window.removeEventListener('resize', debouncedCheckVisibility);
            }}
            
            // 立即检查一次（不使用防抖）
            checkTopologyAndSpecVisibility();
            
            // 添加滚动和窗口大小改变监听器（使用防抖）
            window.addEventListener('scroll', debouncedCheckVisibility, {{ passive: true }});
            window.addEventListener('resize', debouncedCheckVisibility, {{ passive: true }});
            
            scrollDetectionInitialized = true;
        }}
        
        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {{
            detectBrowserAndAdjustFontWeight();
            // initFixedBarState() is now called in initTest() after texts are initialized
            initTest();
            
            // Add event listeners for page refresh and back button
            // Push initial state to history to enable back button detection
            window.history.pushState(null, '', window.location.href);
            
            // Listen for browser back button
            window.addEventListener('popstate', handlePopState);
            
            // Listen for keyboard shortcuts for refresh (F5, Ctrl+R, etc.)
            document.addEventListener('keydown', handleKeyDown);
            
            // Listen for browser refresh button click (beforeunload event)
            // We handle this to show custom modal instead of browser's default dialog
            window.addEventListener('beforeunload', handleBeforeUnload);
        }});

    </script>
</body>
</html>"""

    # 生成 Group A 英文版本
    group_a_en_content = html_content.replace(
        "let userGroup = Math.random() < 0.5 ? 'A' : 'B'; // Random grouping",
        "let userGroup = 'A'; // Fixed Group A"
    ).replace(
        "let currentLanguage = 'en'; // Current language - will be auto-detected",
        "let currentLanguage = 'en'; // Fixed English"
    )
    
    with open(OUTPUT_DIR / 'groupA_en.html', 'w', encoding='utf-8') as f:
        f.write(group_a_en_content)
    
    # 生成 Group A 中文版本
    group_a_zh_content = html_content.replace(
        "let userGroup = Math.random() < 0.5 ? 'A' : 'B'; // Random grouping",
        "let userGroup = 'A'; // Fixed Group A"
    ).replace(
        "let currentLanguage = 'en'; // Current language - will be auto-detected",
        "let currentLanguage = 'zh'; // Fixed Chinese"
    )
    
    with open(OUTPUT_DIR / 'groupA_zh.html', 'w', encoding='utf-8') as f:
        f.write(group_a_zh_content)
    
    # 生成 Group B 英文版本
    group_b_en_content = html_content.replace(
        "let userGroup = Math.random() < 0.5 ? 'A' : 'B'; // Random grouping",
        "let userGroup = 'B'; // Fixed Group B"
    ).replace(
        "let currentLanguage = 'en'; // Current language - will be auto-detected",
        "let currentLanguage = 'en'; // Fixed English"
    )
    
    with open(OUTPUT_DIR / 'groupB_en.html', 'w', encoding='utf-8') as f:
        f.write(group_b_en_content)
    
    # 生成 Group B 中文版本
    group_b_zh_content = html_content.replace(
        "let userGroup = Math.random() < 0.5 ? 'A' : 'B'; // Random grouping",
        "let userGroup = 'B'; // Fixed Group B"
    ).replace(
        "let currentLanguage = 'en'; // Current language - will be auto-detected",
        "let currentLanguage = 'zh'; // Fixed Chinese"
    )
    
    with open(OUTPUT_DIR / 'groupB_zh.html', 'w', encoding='utf-8') as f:
        f.write(group_b_zh_content)
    
    print("✅ User-study HTML files generated successfully!")
    print("📁 Generated files:")
    print("   • generated/index.html (Study Entry Page)")
    print("   • generated/groupA_en.html (Group A - English)")
    print("   • generated/groupA_zh.html (Group A - Chinese)")
    print("   • generated/groupB_en.html (Group B - English)")
    print("   • generated/groupB_zh.html (Group B - Chinese)")
    print("🎯 Experimental design: Balanced group distribution")
    print("📊 Questions: 4 evaluated (+ 1 warm-up)")
    print("⏱️  Features: Timer, validation, confirmation mechanism")
    print("📱 Responsive design with mobile support")
    print("🌐 Language support: English/中文 switching")

def generate_coursera_html():
    """生成独立的 Coursera 练习页面 HTML 文件"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 加载 Coursera 问题数据
    coursera_data_en = load_coursera_question_data('en')
    coursera_data_zh = load_coursera_question_data('zh')
    
    # 生成英文版本
    html_content_en = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Explainable Network Verification via Localized Subspecification - User Study</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Times New Roman', Times, serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            font-size: 16px;
            font-weight: 525;
        }}

        .container {{
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }}

        .header {{
            text-align: center;
            margin-bottom: 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            position: relative;
        }}

        .header h1 {{
            font-size: 2.2em;
            margin-bottom: 10px;
        }}
        
        .language-switcher {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
        }}
        
        .lang-btn {{
            background: rgba(255, 255, 255, 0.2);
            border: 2px solid rgba(255, 255, 255, 0.3);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
            font-weight: bold;
        }}

        .lang-btn:hover {{
            background: rgba(255, 255, 255, 0.3);
        }}

        .lang-btn.active {{
            background: white;
            color: #667eea;
            border-color: white;
        }}

        .lang-btn.active:hover {{
            background: white;
        }}

        .coursera-question {{
            margin-bottom: 40px;
            background: white;
            border-radius: 8px;
            border: 1px solid #e9ecef;
            overflow: hidden;
        }}
        
        .coursera-question-layout {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0;
        }}
        
        .coursera-question-left {{
            padding: 20px;
            border-right: 1px solid #e9ecef;
        }}
        
        .coursera-question-right {{
            padding: 20px;
        }}
        
        .coursera-question h4 {{
            font-size: 22px;
            font-weight: 600;
        }}
        
        @media (max-width: 1200px) {{
            .coursera-question-layout {{
                grid-template-columns: 1fr;
            }}
            
            .coursera-question-left {{
                border-right: none;
                border-bottom: 1px solid #e9ecef;
            }}
        }}

        .coursera-check-btn {{
            padding: 8px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            height: 38px;
            box-sizing: border-box;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            white-space: nowrap;
        }}

        .coursera-check-btn:hover {{
            opacity: 0.9;
        }}

        .question-text {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            margin-bottom: 20px;
            line-height: 1.4;
            color: #333;
            text-align: left;
        }}

        .question-instruction {{
            background: #e3f2fd;
            border: 2px solid #2196f3;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 20px;
            font-size: 1.05em;
            color: #1976d2;
            text-align: left;
        }}
        
        /* Note 样式 - 淡灰色 */
        .question-instruction.note-instruction {{
            background: #f5f5f5;
            border: 1px solid #9e9e9e;
            color: #666;
        }}

        .question-instruction .instruction-line {{
            display: block;
            margin-bottom: 4px;
        }}

        .question-instruction .instruction-line:last-child {{
            margin-bottom: 0;
        }}

        .option-item {{
            display: flex;
            align-items: center;
            margin: 15px 0;
            padding: 15px;
            background: white;
            border-radius: 8px;
            border: 2px solid #e9ecef;
            transition: all 0.3s ease;
        }}

        .option-item input[type="checkbox"] {{
            margin-right: 15px;
            transform: scale(1.2);
            accent-color: #667eea;
            cursor: pointer;
        }}

        .option-item input[type="checkbox"]:hover {{
            transform: scale(1.3);
        }}

        .option-item .option-content-wrapper {{
            flex: 1;
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            color: #333;
        }}

        .option-diff-content {{
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525;
            line-height: 1.5;
            background: white;
            border: 1px solid #9e9e9e;
            border-radius: 4px;
            padding: 10px;
            margin: 5px 0;
            color: #222;
        }}

        .browser-chrome .option-diff-content,
        .browser-edge .option-diff-content,
        .browser-other .option-diff-content {{
            font-weight: 600 !important;
        }}

        .option-text-content {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.5;
            background: white;
            border: 1px solid #9e9e9e;
            border-radius: 4px;
            padding: 10px;
            margin: 5px 0;
            white-space: pre-wrap;
            color: #222;
        }}

        .diff-line {{
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525;
            line-height: 1.5;
            white-space: pre-wrap;
        }}

        .browser-chrome .diff-line,
        .browser-edge .diff-line,
        .browser-other .diff-line {{
            font-weight: 600 !important;
        }}

        .diff-removed {{
            color: #C73E3E !important;
        }}

        .diff-removed * {{
            color: #C73E3E !important;
        }}

        .diff-added {{
            color: #388E3C !important;
        }}

        .diff-added * {{
            color: #388E3C !important;
        }}

        /* 在 diff-added 和 diff-removed 背景下加深子规约颜色 */
        /* Field-level subspec 在 diff 背景下加深 */
        .diff-added .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .diff-removed .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .config-line-highlighted .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .config-line-highlighted-added .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .config-line-highlighted-removed .config-field:not(.line-level):not(.empty-subspec):not(:hover) {{
            background: #8FC5E8 !important; /* 从 #B8DCF9 加深 */
        }}

        /* Line-level subspec 在 diff 背景下加深 */
        .diff-added .config-field.line-level:not(.empty-subspec):not(:hover),
        .diff-removed .config-field.line-level:not(.empty-subspec):not(:hover),
        .config-line-highlighted .config-field.line-level:not(.empty-subspec):not(:hover),
        .config-line-highlighted-added .config-field.line-level:not(.empty-subspec):not(:hover),
        .config-line-highlighted-removed .config-field.line-level:not(.empty-subspec):not(:hover) {{
            background: #C99DD4 !important; /* 从 #E2C0E8 加深 */
        }}

        /* Empty field-level subspec 在 diff 背景下明显加深（但仍保持浅色以区分） */
        .diff-added .config-field.empty-subspec:not(.line-level):not(:hover),
        .diff-removed .config-field.empty-subspec:not(.line-level):not(:hover),
        .config-line-highlighted .config-field.empty-subspec:not(.line-level):not(:hover),
        .config-line-highlighted-added .config-field.empty-subspec:not(.line-level):not(:hover),
        .config-line-highlighted-removed .config-field.empty-subspec:not(.line-level):not(:hover) {{
            background: rgba(180, 220, 255, 0.75) !important; /* 从 rgba(220, 240, 255, 0.5) 加深 */
        }}

        /* Empty line-level subspec 在 diff 背景下明显加深（但仍保持浅色以区分） */
        .diff-added .config-field.line-level.empty-subspec:not(:hover),
        .diff-removed .config-field.line-level.empty-subspec:not(:hover),
        .config-line-highlighted .config-field.line-level.empty-subspec:not(:hover),
        .config-line-highlighted-added .config-field.line-level.empty-subspec:not(:hover),
        .config-line-highlighted-removed .config-field.line-level.empty-subspec:not(:hover) {{
            background: rgba(220, 200, 240, 0.75) !important; /* 从 rgba(240, 220, 250, 0.5) 加深 */
        }}

        /* 排除选项框中的子规约，保持原色 */
        .option-diff-content .diff-added .config-field:not(.line-level):not(.empty-subspec):not(:hover),
        .option-diff-content .config-line-highlighted .config-field:not(.line-level):not(.empty-subspec):not(:hover) {{
            background: #B8DCF9 !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的子规约高亮，与配置中（-）一致，使用加深的背景色 */
        .option-diff-content .diff-removed .config-field:not(.line-level):not(.empty-subspec):not(:hover) {{
            background: #8FC5E8 !important; /* 与配置中（-）一致，从 #B8DCF9 加深 */
        }}

        .option-diff-content .diff-added .config-field.line-level:not(.empty-subspec):not(:hover),
        .option-diff-content .config-line-highlighted .config-field.line-level:not(.empty-subspec):not(:hover) {{
            background: #E2C0E8 !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的 line-level 子规约高亮，与配置中（-）一致 */
        .option-diff-content .diff-removed .config-field.line-level:not(.empty-subspec):not(:hover) {{
            background: #C99DD4 !important; /* 与配置中（-）一致，从 #E2C0E8 加深 */
        }}

        .option-diff-content .diff-added .config-field.empty-subspec:not(.line-level):not(:hover),
        .option-diff-content .config-line-highlighted .config-field.empty-subspec:not(.line-level):not(:hover) {{
            background: rgba(220, 240, 255, 0.5) !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的 empty field-level 子规约高亮，与配置中（-）一致 */
        .option-diff-content .diff-removed .config-field.empty-subspec:not(.line-level):not(:hover) {{
            background: rgba(180, 220, 255, 0.75) !important; /* 与配置中（-）一致，从 rgba(220, 240, 255, 0.5) 加深 */
        }}

        .option-diff-content .diff-added .config-field.line-level.empty-subspec:not(:hover),
        .option-diff-content .config-line-highlighted .config-field.line-level.empty-subspec:not(:hover) {{
            background: rgba(240, 220, 250, 0.5) !important; /* 恢复原色 */
        }}

        /* 选项配置中（-）对应的 empty line-level 子规约高亮，与配置中（-）一致 */
        .option-diff-content .diff-removed .config-field.line-level.empty-subspec:not(:hover) {{
            background: rgba(220, 200, 240, 0.75) !important; /* 与配置中（-）一致，从 rgba(240, 220, 250, 0.5) 加深 */
        }}

        .diff-context {{
            color: #000;
        }}

        .config-reference {{
            color: #0066cc;
            cursor: pointer;
            text-decoration: underline;
            text-decoration-style: dotted;
            transition: all 0.2s ease;
            font-weight: 525;
        }}

        .browser-chrome .config-reference,
        .browser-edge .config-reference,
        .browser-other .config-reference {{
            font-weight: 525 !important;
        }}

        .config-reference:hover {{
            color: #004499;
            text-decoration-style: solid;
            text-decoration-thickness: 2px;
        }}

        .config-field {{
            background: #B8DCF9;
            color: #000;
            padding: 1px 2px;
            border-radius: 2px;
            cursor: pointer;
            transition: background-color 0.3s ease, box-shadow 0.3s ease;
            position: relative;
            font-weight: 525;
            display: inline;
            box-sizing: content-box;
        }}

        .browser-chrome .config-field,
        .browser-edge .config-field,
        .browser-other .config-field {{
            font-weight: 600 !important;
        }}

        /* 所有 config-field 悬停时统一为灰色 */
        .config-field:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }}

        /* Config field showing tooltip - 灰色高亮显示正在显示 tooltip 的字段 */
        .config-field-showing-tooltip {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        .config-field.line-level.config-field-showing-tooltip {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 确保在 diff 内容中，显示 tooltip 的 config-field 也使用白色字体 */
        .diff-removed .config-field-showing-tooltip,
        .diff-added .config-field-showing-tooltip {{
            color: #fff !important;
        }}

        .diff-removed .config-field-showing-tooltip *,
        .diff-added .config-field-showing-tooltip * {{
            color: #fff !important;
        }}

        .config-field.line-level {{
            background: #E2C0E8;
            color: #000;
            font-weight: 525;
            padding: 1px 2px;
            border-radius: 2px;
        }}

        /* 所有 config-field 悬停时统一为灰色 */
        .config-field.line-level:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }}

        /* Missing subspec (not found in subspec files) 亮黄色 */
        .config-field.missing-subspec {{
            background: rgba(255, 255, 0, 0.85);
        }}

        /* Missing subspec hover 效果 - 统一为灰色 */
        .config-field.missing-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* Missing line-level subspec 亮黄色 */
        .config-field.line-level.missing-subspec {{
            background: rgba(255, 255, 0, 0.85);
        }}

        /* Missing line-level subspec hover 效果 - 统一为灰色 */
        .config-field.line-level.missing-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        .config-field.empty-subspec {{
            background: rgba(220, 240, 255, 0.5);
        }}

        .config-field.line-level.empty-subspec {{
            background: rgba(240, 220, 250, 0.5);
        }}

        /* Empty field-level subspec hover 效果 - 统一为灰色 */
        .config-field.empty-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* Empty line-level subspec hover 效果 - 统一为灰色 */
        .config-field.line-level.empty-subspec:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 确保 diff 区域中的 config-field 悬停时也是灰色 */
        .diff-added .config-field:hover,
        .diff-removed .config-field:hover,
        .config-line-highlighted .config-field:hover,
        .config-line-highlighted-added .config-field:hover,
        .config-line-highlighted-removed .config-field:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 确保选项区域中的 config-field 悬停时也是灰色 */
        .option-diff-content .config-field:hover,
        .option-text-content .config-field:hover {{
            background: #9e9e9e !important;
            color: #fff !important;
        }}

        /* 空的 symbolic spacer，只增加宽度，不设置背景颜色 */
        .config-field-empty-spacer {{
            padding: 1px 2px;
            border-radius: 2px;
            display: inline;
            box-sizing: content-box;
        }}

        .browser-chrome .config-field.line-level,
        .browser-edge .config-field.line-level,
        .browser-other .config-field.line-level {{
            font-weight: 600 !important;
        }}

        .config-line-highlighted {{
            background-color: #fff3cd !important;
            border-left: 4px solid #ffc107 !important;
            padding-left: 8px !important;
            margin: 0 !important;
            animation: highlight-pulse 0.5s ease-in-out;
        }}

        .config-line-highlighted-removed {{
            background-color: #ffebee !important;
            border-left: 4px solid #d32f2f !important;
            padding-left: 8px !important;
            margin: 0 !important;
            animation: highlight-pulse-removed 0.5s ease-in-out;
        }}

        .config-line-highlighted-added {{
            background-color: #e8f5e9 !important;
            border-left: 4px solid #388e3c !important;
            padding-left: 8px !important;
            margin: 0 !important;
        }}

        .config-line-added-display {{
            background-color: #e8f5e9 !important;
            border-left: 4px solid #388e3c !important;
            padding-left: 8px !important;
            margin: 0 !important;
            opacity: 0.9;
        }}

        @keyframes highlight-pulse {{
            0% {{ background-color: #fff3cd; }}
            50% {{ background-color: #ffeaa7; }}
            100% {{ background-color: #fff3cd; }}
        }}

        @keyframes highlight-pulse-removed {{
            0% {{ background-color: #ffebee; }}
            50% {{ background-color: #ffcdd2; }}
            100% {{ background-color: #ffebee; }}
        }}

        .tooltip {{
            position: fixed;
            background: #eeeeee;
            color: #9e9e9e;
            padding: 16px 20px;
            border-radius: 10px;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 14px;
            font-weight: 600;
            max-width: 500px;
            z-index: 10000;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            opacity: 0;
            transition: opacity 0.2s ease;
            visibility: hidden;
            pointer-events: none;
            word-wrap: break-word;
            line-height: 1.5;
            border: 1px solid #9e9e9e;
            transform: translateZ(0);
            backface-visibility: hidden;
        }}

        .tooltip.show {{
            opacity: 1;
            visibility: visible;
        }}

        .tooltip::after {{
            content: '';
            position: absolute;
            top: var(--arrow-top, 100%);
            left: var(--arrow-left, 20px);
            border-width: 6px;
            border-style: solid;
            border-color: var(--arrow-border, #9e9e9e transparent transparent transparent);
            transform: translateX(-50%);
        }}

        .tooltip-header {{
            font-weight: bold;
            color: #000 !important;
            margin-bottom: 8px;
            font-size: 14px;
            border-bottom: 1px solid #9e9e9e;
            padding-bottom: 6px;
        }}

        .tooltip-content {{
            font-family: 'Courier New', monospace;
            background: rgba(0, 0, 0, 0.05);
            padding: 10px;
            border-radius: 6px;
            margin-top: 8px;
            border-left: 3px solid #9e9e9e;
        }}

        .tooltip-simple {{
            color: #000 !important;
            font-style: italic;
        }}

        .tooltip-type {{
            color: #9e9e9e;
            font-size: 12px;
            margin: 4px 0;
            font-style: italic;
        }}

        .tooltip-detail {{
            color: #000 !important;
            font-size: 11px;
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px solid #9e9e9e;
        }}

        .tooltip-formula {{
            color: #9e9e9e;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            margin-top: 8px;
            padding-top: 8px;
        }}

        .tooltip-separator {{
            color: #999;
            margin: 8px 0;
            font-size: 12px;
        }}

        .tooltip-translated {{
            color: #000 !important;
            font-size: 13px;
            margin-top: 6px;
            line-height: 1.4;
        }}

        .tooltip .tooltip-translated .highlight-action,
        .tooltip-translated .highlight-action {{
            color: #0080ff !important;
            font-weight: 900 !important;
        }}

        .tooltip .tooltip-translated .highlight-network,
        .tooltip-translated .highlight-network {{
            color: #ff8800 !important;
            font-weight: 900 !important;
        }}

        .tooltip .tooltip-translated .highlight-range,
        .tooltip-translated .highlight-range {{
            color: #16a34a !important;
            font-weight: 900 !important;
        }}

        .coursera-overall-feedback {{
            display: flex;
            align-items: center;
            justify-content: center;
            height: 38px;
            box-sizing: border-box;
            padding: 8px 15px;
            border-radius: 4px;
            font-family: 'Times New Roman', Times, serif;
            font-size: 17px;
            font-weight: 525;
            line-height: 1.4;
            text-align: center;
            flex: 1;
            color: #333;
            visibility: hidden;
        }}
        
        .coursera-overall-feedback.show {{
            visibility: visible;
        }}

        .config-content {{
            background: white;
            padding: 15px 10px;
            display: block;
            border-top: 1px solid #9e9e9e;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 15px;
            font-weight: 525; /* Default for Safari/Firefox */
            line-height: 1.5;
            color: #222;
            white-space: pre-wrap;
            word-wrap: break-word;
            overflow-wrap: break-word;
            max-width: 100%;
            overflow-x: auto;
            text-align: left;
        }}

        /* Chrome/Edge/Other specific font-weight for config content */
        .browser-chrome .config-content,
        .browser-edge .config-content,
        .browser-other .config-content {{
            font-weight: 600 !important;
        }}

        .config-line {{
            margin: 0;
            position: relative;
            white-space: pre;
            display: block;
            line-height: 1.4;
        }}

        /* 配置行号样式 - 灰色，字体粗细正常，以便区分 */
        .config-line-number {{
            color: #666;
            font-weight: normal;
        }}

        .config-field {{
            background: #B8DCF9;
            color: #000;
            padding: 1px 2px;
            border-radius: 2px;
            cursor: pointer;
        }}

        .highlight-route-map {{
            color: #e65100 !important;
            font-weight: 600 !important;
        }}

        .highlight-prefix-list {{
            color: #1565c0 !important;
            font-weight: 600 !important;
        }}

        .highlight-community-list {{
            color: #2e7d32 !important;
            font-weight: 600 !important;
        }}

        .highlight-number {{
            color: #8B4513 !important;
            font-weight: 525 !important;
            background: rgba(139, 69, 19, 0.05);
            padding: 1px 2px;
            border-radius: 2px;
        }}

        /* Chrome/Edge/Other specific font-weight for highlight-number */
        .browser-chrome .highlight-number,
        .browser-edge .highlight-number,
        .browser-other .highlight-number {{
            font-weight: 600 !important;
        }}

        /* Chrome/Edge/Other specific font-weight for categorized highlights */
        .browser-chrome .highlight-route-map,
        .browser-edge .highlight-route-map,
        .browser-other .highlight-route-map,
        .browser-chrome .highlight-prefix-list,
        .browser-edge .highlight-prefix-list,
        .browser-other .highlight-prefix-list,
        .browser-chrome .highlight-community-list,
        .browser-edge .highlight-community-list,
        .browser-other .highlight-community-list {{
            font-weight: 700 !important;
        }}

        @media (max-width: 768px) {{
            body {{
                overflow-x: hidden;
            }}

            .container {{
                padding: 10px;
                max-width: 100%;
            }}

            .header {{
                padding: 16px 12px;
            }}

            .header h1 {{
                font-size: 1.35em;
                line-height: 1.35;
            }}

            .language-switcher {{
                bottom: 12px;
                right: 12px;
            }}

            .lang-btn {{
                font-size: 12px;
                padding: 6px 12px;
            }}

            .coursera-question-left,
            .coursera-question-right {{
                padding: 14px;
            }}

            .coursera-question h4 {{
                font-size: 18px;
            }}

            .config-content {{
                font-size: 13px;
                padding: 12px;
                -webkit-overflow-scrolling: touch;
            }}
        }}

    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="language-switcher">
                <button class="lang-btn active" id="lang-en" onclick="switchLanguage('en')">English</button>
                <button class="lang-btn" id="lang-zh" onclick="switchLanguage('zh')">中文</button>
            </div>
            <h1 id="header-title">Explainable Network Verification via Localized Subspecification - User Study</h1>
        </div>

        <div id="testContent">
            <!-- 动态生成的内容 -->
        </div>
    </div>

    <script>
        let currentLanguage = 'en';
        
        const textConstants = {{
            'en': {{
                'title': 'Explainable Network Verification via Localized Subspecification - User Study',
                'questionLabel': 'Question',
                'checkButton': 'CHECK',
                'courseraIncorrect': '✗ You have selected some incorrect options.',
                'courseraIncomplete': '⚠ Please select all correct options.',
                'courseraCorrect': '✓ All correct! Well done!'
            }},
            'zh': {{
                'title': '基于局部子规约的可解释网络验证 - 用户研究',
                'questionLabel': '问题',
                'checkButton': '确认',
                'courseraIncorrect': '✗ 您选择了一些不正确的选项。',
                'courseraIncomplete': '⚠ 请选择所有正确的选项。',
                'courseraCorrect': '✓ 全部正确！做得好！'
            }}
        }};

        let texts = textConstants[currentLanguage];
        
        const questionData = {{
            'coursera': {{
                'en': {coursera_data_en},
                'zh': {coursera_data_zh}
            }}
        }};

        // Language switching function
        function switchLanguage(lang) {{
            currentLanguage = lang;
            texts = textConstants[lang];
            
            // Update language buttons
            document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.remove('active'));
            document.getElementById(`lang-${{lang}}`).classList.add('active');
            
            // Update header title
            document.getElementById('header-title').textContent = texts.title;
            
            // Reload page content
            showCourseraPage();
            
            // Update config reference tooltips
            updateConfigReferenceTooltips();
        }}

        // 解析 subspec 内容的辅助函数
        function parseSubspecContent(configSubspecContent, lineSubspecContent, configSubspecTransContent, lineSubspecTransContent) {{
            // 解析config-level subspec数据
            const configSubspecData = {{}};
            const configLines = (configSubspecContent || '').split('\\n');
            let currentVar = null;
            
            for (const line of configLines) {{
                if (line.startsWith('Config Variable:')) {{
                    currentVar = line.split('Config Variable: ')[1].trim();
                }} else if (line.trim().startsWith('1.') && currentVar) {{
                    const subspec = line.trim().substring(2).trim();
                    configSubspecData[currentVar] = subspec;
                }}
            }}
            
            // 解析line-level subspec数据
            const lineSubspecData = {{}};
            const lineSubspecNames = new Set();
            const lineLines = (lineSubspecContent || '').split('\\n');
            let currentLineGroup = null;
            
            for (const line of lineLines) {{
                if (line.startsWith('Line Group:')) {{
                    currentLineGroup = line.split('Line Group: ')[1].trim();
                    if (currentLineGroup) {{
                        lineSubspecNames.add(currentLineGroup);
                    }}
                }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                    const subspec = line.trim().substring(2).trim();
                    lineSubspecData[currentLineGroup] = subspec;
                }}
            }}
            
            // 解析转换后的config-level subspec数据
            const configSubspecTransData = {{}};
            if (configSubspecTransContent) {{
                const configTransLines = configSubspecTransContent.split('\\n');
                let currentVar = null;
                
                for (const line of configTransLines) {{
                    if (line.startsWith('Config Variable:')) {{
                        currentVar = line.split('Config Variable: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentVar) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        configSubspecTransData[currentVar] = subspecTrans;
                    }}
                }}
            }}
            
            // 解析转换后的line-level subspec数据
            const lineSubspecTransData = {{}};
            if (lineSubspecTransContent) {{
                const lineTransLines = lineSubspecTransContent.split('\\n');
                let currentLineGroup = null;
                
                for (const line of lineTransLines) {{
                    if (line.startsWith('Line Group:')) {{
                        currentLineGroup = line.split('Line Group: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        lineSubspecTransData[currentLineGroup] = subspecTrans;
                    }}
                }}
            }}
            
            // 合并两种subspec数据
            const subspecData = {{...configSubspecData, ...lineSubspecData}};
            
            return {{
                subspecData,
                configSubspecData,
                lineSubspecData,
                lineSubspecNames,
                configSubspecTransData,
                lineSubspecTransData
            }};
        }}

        function showCourseraPage() {{
            const courseraData = questionData.coursera[currentLanguage] || questionData.coursera['en'];
            const questions = courseraData.questions;
            
            // 解析默认的 subspec 数据（用于非 question6 的问题）
            const defaultConfigSubspecContent = courseraData.configSubspecContent || '';
            const defaultLineSubspecContent = courseraData.lineSubspecContent || '';
            const defaultConfigSubspecTransContent = courseraData.configSubspecTransContent || '';
            const defaultLineSubspecTransContent = courseraData.lineSubspecTransContent || '';
            
            const defaultSubspecParsed = parseSubspecContent(defaultConfigSubspecContent, defaultLineSubspecContent, defaultConfigSubspecTransContent, defaultLineSubspecTransContent, '');
            
            const courseraHtml = generateCourseraPageHTML(questions, defaultSubspecParsed, courseraData);
            document.getElementById('testContent').innerHTML = courseraHtml;
            addCourseraEventListeners();
        }}

        function generateCourseraPageHTML(questions, defaultSubspecParsed, courseraData) {{
            return `
                <div style="margin-top: 20px;">
                    ${{questions.map((q, idx) => {{
                        // 如果问题有单独的子规约内容，使用问题的子规约；否则使用默认的
                        let questionSubspecParsed = defaultSubspecParsed;
                        // 检查问题是否有单独的子规约（不是 null 或 undefined，且不是空字符串）
                        if (q.configSubspecContent != null || q.lineSubspecContent != null) {{
                            // 问题有单独的子规约
                            questionSubspecParsed = parseSubspecContent(
                                q.configSubspecContent || '',
                                q.lineSubspecContent || '',
                                q.configSubspecTransContent || '',
                                q.lineSubspecTransContent || ''
                            );
                        }}
                        return generateCourseraQuestionHTML(q, idx, questionSubspecParsed);
                    }}).join('')}}
                </div>
            `;
        }}

        function generateCourseraQuestionHTML(question, index, subspecParsed) {{
            const {{ subspecData, configSubspecData, lineSubspecData, lineSubspecNames, configSubspecTransData, lineSubspecTransData }} = subspecParsed;
            const questionId = `coursera-${{index}}`;
            
            let configHtml = '';
            if (question.config) {{
                const highlightTerms = extractHighlightTerms(question.config);
                const categorizedTerms = categorizeConfigTerms(highlightTerms);
                
                const configLines = question.config.split('\\n');
                const processedLines = configLines.map((line, lineIdx) => {{
                    // 提取实际行号（如果存在）
                    let actualLineNumber = lineIdx + 1; // 默认使用索引
                    const lineNumberMatch = line.match(/^(\\s*)(\\d+)(\\s+)/);
                    if (lineNumberMatch) {{
                        actualLineNumber = parseInt(lineNumberMatch[2]);
                    }}
                    
                    let processedLine = processLineNumber(line);
                    processedLine = processCourseraConfigLine(processedLine, categorizedTerms, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, configSubspecTransData, lineSubspecTransData);
                    return `<span class="config-line" data-line="${{actualLineNumber}}">${{processedLine}}</span>`;
                }}).join('');
                
                configHtml = `<div class="config-content" style="display: block; text-align: left;">${{processedLines}}</div>`;
            }}
            
            const optionsHtml = question.options.map((option, optIdx) => {{
                const optionId = `${{questionId}}-option-${{optIdx}}`;
                let optionText = option.text || '';
                optionText = optionText.replace(/^```\s*/gm, '').replace(/\\s*```$/gm, '');
                
                // 判断是否为 diff 格式
                const isDiff = option.is_diff || false;
                let optionContent = '';
                let contentClass = '';
                
                if (isDiff) {{
                    // diff 格式：使用 formatDiffContent 格式化，使用等宽字体，支持 subspec
                    const lines = optionText.split('\\n');
                    optionContent = formatDiffContent(lines, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, true, configSubspecTransData, lineSubspecTransData);
                    contentClass = 'option-diff-content';
                }} else {{
                    // 普通文本：处理配置引用和 subspec
                    optionContent = processOptionText(optionText, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, true, configSubspecTransData, lineSubspecTransData);
                    contentClass = 'option-text-content';
                }}
                
                return `
                    <div class="option-item">
                        <input type="checkbox" id="${{optionId}}" name="${{questionId}}-options" value="option${{optIdx}}">
                        <div class="option-content-wrapper">
                            <div class="${{contentClass}}">${{optionContent}}</div>
                        </div>
                    </div>
                `;
            }}).join('');
            
            return `
                <div class="coursera-question">
                    <div class="coursera-question-layout">
                        <!-- 左边：问题描述和配置 -->
                        <div class="coursera-question-left">
                            <h4 style="margin: 0 0 15px 0; color: #667eea; text-align: left;">${{texts.questionLabel}} ${{question.num}}</h4>
                            <div class="question-text">
                                ${{question.text}}
                            </div>
                            <div style="text-align: left; margin-top: 15px;">
                                ${{configHtml}}
                            </div>
                            ${{question.note ? `<div class="question-instruction note-instruction" id="${{questionId}}-note" style="margin-top: 15px; display: none;">
                                <div class="instruction-line">${{question.note}}</div>
                            </div>` : ''}}
                        </div>
                        
                        <!-- 右边：选项 -->
                        <div class="coursera-question-right">
                            <div class="question-options" style="text-align: left;">
                                ${{optionsHtml}}
                            </div>
                            <!-- 底部：提示信息和 Check 按钮 -->
                            <div style="display: flex; justify-content: flex-end; align-items: center; margin-top: 20px; padding-top: 15px; border-top: 1px solid #e9ecef; gap: 15px; min-height: 38px;">
                                <div id="${{questionId}}-overall-feedback" class="coursera-overall-feedback"></div>
                                <button class="coursera-check-btn" onclick="checkCourseraQuestion('${{questionId}}')">${{texts.checkButton}}</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }}

        function processLineNumber(line) {{
            const pattern = /^(\\s*)(\\d+)(\\s+)(.*)$/;
            const match = line.match(pattern);
            if (match) {{
                const leadingSpaces = match[1];
                const lineNumber = match[2];
                const trailingSpaces = match[3];
                const content = match[4];
                return `${{leadingSpaces}}<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{content}}`;
            }}
            return line;
        }}

        function processCourseraConfigLine(line, categorizedTerms, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, configSubspecTransData, lineSubspecTransData) {{
            // HTML 转义函数，用于转义 HTML 属性值中的特殊字符
            function escapeHtmlForAttribute(html) {{
                if (!html) return '';
                return html
                    .replace(/&/g, '&amp;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
            }}
            
            let processedLine = line;
            
            // 处理subspec
            if (/\\[/.test(processedLine) && /\\(/.test(processedLine)) {{
                processedLine = processedLine.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, (match, fieldName, subspecName) => {{
                    // 检查 subspecName 是否真的存在于 subspecData 中
                    const isMissing = !(subspecName in subspecData);
                    const subspec = isMissing ? 'empty' : (subspecData[subspecName] || 'empty');
                    let displaySubspec;
                    
                    if (subspecName in configSubspecData) {{
                        // Config-level: 将 Config_xxx 替换为 VAR，但对 ip/mask 字段特殊处理
                        displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                            // 检查是否以 __ip 或 __mask 结尾
                            if (match.endsWith('__ip')) {{
                                return 'VAR_IP';
                            }} else if (match.endsWith('__mask')) {{
                                return 'VAR_MASK';
                            }} else {{
                                return 'VAR';
                            }}
                        }});
                    }} else {{
                        // Line-level: 将 Config_xxx_Line_..._xxx 保留最后一个 _xxx 并转换为 VAR_XXX
                        displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                            const parts = match.split('_');
                            if (parts.length > 1) {{
                                const lastPart = parts[parts.length - 1].toUpperCase();
                                return `VAR_${{lastPart}}`;
                            }}
                            return 'VAR';
                        }});
                    }}
                    
                    // 获取语义概括（subspecTrans），这是语义概括，不是翻译
                    let subspecTrans = null;
                    if (subspecName in configSubspecData && configSubspecTransData && subspecName in configSubspecTransData) {{
                        subspecTrans = configSubspecTransData[subspecName];
                    }} else if (subspecName in lineSubspecData && lineSubspecTransData && subspecName in lineSubspecTransData) {{
                        subspecTrans = lineSubspecTransData[subspecName];
                    }}
                    
                    // 构建完整的tooltip内容：语义概括 + 分隔线 + 原始subspec
                    let tooltipContent;
                    if (isMissing) {{
                        // 如果 subspec 不存在，显示 "none" 和 "No subspec found"
                        const missingText = currentLanguage === 'zh' ? '没有找到子规约' : 'No subspec found';
                        tooltipContent = '<div class="tooltip-translated">' + missingText + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">none</div>';
                    }} else {{
                        if (subspecTrans) {{
                            // 翻译文本已经在 Python 中静态处理，添加了高亮标签
                            tooltipContent = '<div class="tooltip-translated">' + subspecTrans + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">' + displaySubspec + '</div>';
                        }} else {{
                            tooltipContent = '<div class="tooltip-formula">' + displaySubspec + '</div>';
                        }}
                    }}
                    
                    // 转义 tooltipContent 以便安全地插入到 HTML 属性中
                    const escapedTooltipContent = escapeHtmlForAttribute(tooltipContent);
                    
                    // 判断是 line-level 还是 config-level subspec
                    let cssClass = "config-field";
                    let isEmpty = (subspec === 'empty');
                    
                    if (lineSubspecNames.has(subspecName)) {{
                        cssClass += " line-level";
                    }}
                    
                    if (isMissing) {{
                        // 如果 subspec 根本不存在，使用 missing-subspec 类（亮黄色）
                        cssClass += " missing-subspec";
                    }} else if (isEmpty) {{
                        // 如果 subspec 存在但值为 'empty'，使用 empty-subspec 类
                        cssClass += " empty-subspec";
                    }}
                    
                    return `<span class="${{cssClass}}" data-subspec="${{escapedTooltipContent}}" data-subspec-name="${{subspecName}}">${{fieldName}}</span>`;
                }});
            }}
            
            if (categorizedTerms) {{
                processedLine = applyCategorizedHighlighting(processedLine, categorizedTerms);
            }}
            processedLine = applyNumberHighlighting(processedLine);
            return processedLine;
        }}

        function extractHighlightTerms(config) {{
            const terms = [];
            const lines = config.split('\\n');
            for (const line of lines) {{
                // 提取 route-map name（支持大小写混合）
                const routeMapMatch = line.match(/route-map\\s+([A-Za-z0-9_]+)/i);
                if (routeMapMatch) terms.push(routeMapMatch[1]);
                // 提取 prefix-list name（支持大小写混合，支持带或不带 ip 前缀）
                const prefixListMatch = line.match(/(?:ip\\s+)?prefix-list\\s+([A-Za-z0-9_]+)/i);
                if (prefixListMatch) terms.push(prefixListMatch[1]);
                // 提取 community-list name（支持大小写混合，支持带或不带 ip 前缀）
                const communityListMatch = line.match(/(?:ip\\s+)?community-list\\s+([A-Za-z0-9_]+)/i);
                if (communityListMatch) terms.push(communityListMatch[1]);
            }}
            return terms;
        }}

        function categorizeConfigTerms(terms) {{
            const routeMaps = [];
            const prefixLists = [];
            const communityLists = [];
            const otherTerms = [];
            for (const term of terms) {{
                const trimmedTerm = term.trim();
                if (!trimmedTerm) continue;
                // 路由策略模式：R1_IN_FROM_ISP1, R2_OUT_TO_R3 等，或全大写字母数字下划线
                if (/R\\d+_(IN|OUT)_(FROM|TO)_\\w+/.test(trimmedTerm) || /^[A-Z0-9_]+$/.test(trimmedTerm)) {{
                    routeMaps.push(trimmedTerm);
                }}
                // 前缀列表模式：isp1_network, private_ips, network_10_0_0_0 等，或包含 prefix
                else if (/(default_ips|isp\\d+_network|other_network|private_ips|network_\\d+_\\d+_\\d+_\\d+)/.test(trimmedTerm) || trimmedTerm.toLowerCase().includes('prefix')) {{
                    prefixLists.push(trimmedTerm);
                }}
                // 社区列表模式：纯数字，或包含 community
                else if (/^\\d+$/.test(trimmedTerm) || trimmedTerm.toLowerCase().includes('community')) {{
                    communityLists.push(trimmedTerm);
                }}
                else {{
                    otherTerms.push(trimmedTerm);
                }}
            }}
            return {{ routeMaps, prefixLists, communityLists, otherTerms }};
        }}

        function applyCategorizedHighlighting(line, categorizedTerms) {{
            let processedLine = line;
            for (const term of categorizedTerms.routeMaps) {{
                if (term.trim()) {{
                    const highlightPattern = new RegExp('\\\\b' + term.trim().replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'gi');
                    processedLine = processedLine.replace(highlightPattern, `<span class="highlight-route-map">${{term.trim()}}</span>`);
                }}
            }}
            for (const term of categorizedTerms.prefixLists) {{
                if (term.trim()) {{
                    const highlightPattern = new RegExp('\\\\b' + term.trim().replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'gi');
                    processedLine = processedLine.replace(highlightPattern, `<span class="highlight-prefix-list">${{term.trim()}}</span>`);
                }}
            }}
            for (const term of categorizedTerms.communityLists) {{
                if (term.trim()) {{
                    const highlightPattern = new RegExp('\\\\b' + term.trim().replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'gi');
                    processedLine = processedLine.replace(highlightPattern, `<span class="highlight-community-list">${{term.trim()}}</span>`);
                }}
            }}
            return processedLine;
        }}

        function applyNumberHighlighting(line) {{
            let processedLine = line;
            const subspecPlaceholders = {{}};
            let placeholderCounter = 0;
            const subspecPattern = /<span class="[^"]*" data-subspec="[^"]*" data-subspec-name="[^"]*">.*?<\\/span>/g;
            processedLine = processedLine.replace(subspecPattern, (match) => {{
                const placeholder = `__SUBSPEC_PLACEHOLDER_${{placeholderCounter}}__`;
                subspecPlaceholders[placeholder] = match;
                placeholderCounter++;
                return placeholder;
            }});
            // 数字高亮模式 - 保留原始空格数量
            processedLine = processedLine.replace(/\\bseq(\\s+)(\\d+)\\b/g, (match, spaces, number) => {{
                return `seq${{spaces}}<span class="highlight-number">${{number}}</span>`;
            }});
            processedLine = processedLine.replace(/\\b(ge|le|eq)(\\s+)(\\d+)\\b/g, (match, op, spaces, number) => {{
                return `${{op}}${{spaces}}<span class="highlight-number">${{number}}</span>`;
            }});
            processedLine = processedLine.replace(/\\b(\\d+\\.\\d+\\.\\d+\\.\\d+)\\/(\\d+)\\b/g, '<span class="highlight-number">$1</span>/<span class="highlight-number">$2</span>');
            processedLine = processedLine.replace(/\\b(\\d+):(\\d+)\\b/g, '<span class="highlight-number">$1</span>:<span class="highlight-number">$2</span>');
            processedLine = processedLine.replace(/\\b(permit|deny)(\\s+)(\\d+)\\b/g, (match, op, spaces, number) => {{
                return `${{op}}${{spaces}}<span class="highlight-number">${{number}}</span>`;
            }});
            for (const [placeholder, original] of Object.entries(subspecPlaceholders)) {{
                processedLine = processedLine.replace(placeholder, original);
            }}
            return processedLine;
        }}

        // 格式化diff内容，添加颜色高亮
        function processConfigReferences(text) {{
            // 支持两种格式：
            // 1. @@ R1 Configuration 2,4 @@ (带路由器前缀)
            // 2. @@ Configuration 2,4 @@ (不带路由器前缀)
            const patternWithRouter = /@@\s+(R\d+)\s+Configuration\s+(\d+(?:,\d+)*)\s+@@/g;
            const patternWithoutRouter = /@@\s+Configuration\s+(\d+(?:,\d+)*)\s+@@/g;
            
            // 根据当前语言设置提示文本
            const isChinese = currentLanguage === 'zh';
            
            // 先处理带路由器前缀的
            text = text.replace(patternWithRouter, (match, router, lineRange) => {{
                const title = isChinese ? 
                    `点击高亮 ${{router}} 配置行 ${{lineRange}}` : 
                    `Click to highlight ${{router}} Configuration lines ${{lineRange}}`;
                return `<span class="config-reference" data-router="${{router}}" data-lines="${{lineRange}}" title="${{title}}">@@ ${{router}} Configuration ${{lineRange}} @@</span>`;
            }});
            
            // 再处理不带路由器前缀的
            text = text.replace(patternWithoutRouter, (match, lineRange) => {{
                const title = isChinese ? 
                    `点击高亮配置行 ${{lineRange}}` : 
                    `Click to highlight Configuration lines ${{lineRange}}`;
                return `<span class="config-reference" data-lines="${{lineRange}}" title="${{title}}">@@ Configuration ${{lineRange}} @@</span>`;
            }});
            
            return text;
        }}

        // 更新配置引用的提示文本（用于语言切换时）
        function updateConfigReferenceTooltips() {{
            const configReferences = document.querySelectorAll('.config-reference');
            const isChinese = currentLanguage === 'zh';
            configReferences.forEach(ref => {{
                const router = ref.getAttribute('data-router');
                const lines = ref.getAttribute('data-lines');
                if (router) {{
                    const title = isChinese ? 
                        `点击高亮 ${{router}} 配置行 ${{lines}}` : 
                        `Click to highlight ${{router}} Configuration lines ${{lines}}`;
                    ref.setAttribute('title', title);
                }} else {{
                    const title = isChinese ? 
                        `点击高亮配置行 ${{lines}}` : 
                        `Click to highlight Configuration lines ${{lines}}`;
                    ref.setAttribute('title', title);
                }}
            }});
        }}

        // 解析 subspec 数据（用于 options）
        function parseSubspecData(configSubspecContent, lineSubspecContent, configSubspecTransContent, lineSubspecTransContent) {{
            const configSubspecData = {{}};
            const configLines = (configSubspecContent || '').split('\\n');
            let currentVar = null;
            
            for (const line of configLines) {{
                if (line.startsWith('Config Variable:')) {{
                    currentVar = line.split('Config Variable: ')[1].trim();
                }} else if (line.trim().startsWith('1.') && currentVar) {{
                    const subspec = line.trim().substring(2).trim();
                    configSubspecData[currentVar] = subspec;
                }}
            }}
            
            const lineSubspecData = {{}};
            const lineSubspecNames = new Set();
            const lineLines = (lineSubspecContent || '').split('\\n');
            let currentLineGroup = null;
            
            for (const line of lineLines) {{
                if (line.startsWith('Line Group:')) {{
                    currentLineGroup = line.split('Line Group: ')[1].trim();
                    if (currentLineGroup) {{
                        lineSubspecNames.add(currentLineGroup);
                    }}
                }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                    const subspec = line.trim().substring(2).trim();
                    lineSubspecData[currentLineGroup] = subspec;
                }}
            }}
            
            const configSubspecTransData = {{}};
            if (configSubspecTransContent) {{
                const configTransLines = configSubspecTransContent.split('\\n');
                let currentVar = null;
                
                for (const line of configTransLines) {{
                    if (line.startsWith('Config Variable:')) {{
                        currentVar = line.split('Config Variable: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentVar) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        configSubspecTransData[currentVar] = subspecTrans;
                    }}
                }}
            }}
            
            const lineSubspecTransData = {{}};
            if (lineSubspecTransContent) {{
                const lineTransLines = lineSubspecTransContent.split('\\n');
                let currentLineGroup = null;
                
                for (const line of lineTransLines) {{
                    if (line.startsWith('Line Group:')) {{
                        currentLineGroup = line.split('Line Group: ')[1].trim();
                    }} else if (line.trim().startsWith('1.') && currentLineGroup) {{
                        const subspecTrans = line.trim().substring(2).trim();
                        lineSubspecTransData[currentLineGroup] = subspecTrans;
                    }}
                }}
            }}
            
            const subspecData = {{...configSubspecData, ...lineSubspecData}};
            
            return {{
                subspecData,
                configSubspecData,
                lineSubspecData,
                lineSubspecNames,
                configSubspecTransData,
                lineSubspecTransData
            }};
        }}

        // 处理 options 文本，支持配置引用和 subspec
        // 只处理 [text](subspec) 格式，不处理单纯的 []
        function processOptionText(text, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs, configSubspecTransData, lineSubspecTransData) {{
            // HTML 转义函数，用于转义 HTML 属性值中的特殊字符
            function escapeHtmlForAttribute(html) {{
                if (!html) return '';
                return html
                    .replace(/&/g, '&amp;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
            }}
            
            // 先处理配置引用
            let processed = processConfigReferences(text);
            
            // 如果显示 subspec 且有 subspec 数据，处理 subspec
            // 使用更智能的方法处理嵌套方括号，如 [[400:100]](...)
            if (showSubspecs && subspecData && text.includes('[') && text.includes('](')) {{
                // 从右到左查找所有 ]( 位置，然后向前查找匹配的 [
                let result = processed;
                let lastIndex = result.length;
                
                // 从右到左查找所有 ]( 模式
                while (true) {{
                    const bracketParenIndex = result.lastIndexOf('](', lastIndex);
                    if (bracketParenIndex === -1) break;
                    
                    // 从 ]( 位置向前查找匹配的 [
                    let bracketCount = 0;
                    let startIndex = -1;
                    for (let i = bracketParenIndex; i >= 0; i--) {{
                        if (result[i] === ']') {{
                            bracketCount++;
                        }} else if (result[i] === '[') {{
                            bracketCount--;
                            if (bracketCount === 0) {{
                                startIndex = i;
                                break;
                            }}
                        }}
                    }}
                    
                    if (startIndex !== -1) {{
                        // 查找匹配的 )
                        let parenCount = 0;
                        let endIndex = -1;
                        for (let i = bracketParenIndex + 1; i < result.length; i++) {{
                            if (result[i] === '(') {{
                                parenCount++;
                            }} else if (result[i] === ')') {{
                                parenCount--;
                                if (parenCount === 0) {{
                                    endIndex = i;
                                    break;
                                }}
                            }}
                        }}
                        
                        if (endIndex !== -1) {{
                            const fieldName = result.substring(startIndex + 1, bracketParenIndex);
                            const subspecName = result.substring(bracketParenIndex + 2, endIndex);
                            
                            // 处理 subspec
                            // 检查 subspecName 是否真的存在于 subspecData 中
                            const isMissing = !(subspecName in subspecData);
                            const subspec = isMissing ? 'empty' : (subspecData[subspecName] || 'empty');
                            let displaySubspec;
                            
                            // 判断是config-level还是line-level subspec
                            if (subspecName in configSubspecData) {{
                                // Config-level: 将 Config_xxx 替换为 VAR，但对 ip/mask 字段特殊处理
                                displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                                    // 检查是否以 __ip 或 __mask 结尾
                                    if (match.endsWith('__ip')) {{
                                        return 'VAR_IP';
                                    }} else if (match.endsWith('__mask')) {{
                                        return 'VAR_MASK';
                                    }} else {{
                                        return 'VAR';
                                    }}
                                }});
                            }} else {{
                                // Line-level: 将 Config_xxx_Line_..._xxx 保留最后一个 _xxx 并转换为 VAR_XXX
                                displaySubspec = subspec.replace(/Config_[a-zA-Z0-9_]+/g, (match) => {{
                                    const parts = match.split('_');
                                    if (parts.length > 1) {{
                                        const lastPart = parts[parts.length - 1].toUpperCase();
                                        return `VAR_${{lastPart}}`;
                                    }}
                                    return 'VAR';
                                }});
                            }}
                            
                            // 获取转换后的subspec
                            let subspecTrans = null;
                            if (subspecName in configSubspecData && configSubspecTransData && subspecName in configSubspecTransData) {{
                                subspecTrans = configSubspecTransData[subspecName];
                            }} else if (subspecName in lineSubspecData && lineSubspecTransData && subspecName in lineSubspecTransData) {{
                                subspecTrans = lineSubspecTransData[subspecName];
                            }}
                            
                            // 构建完整的tooltip内容
                            let tooltipContent;
                            if (isMissing) {{
                                // 如果 subspec 不存在，显示 "none" 和 "No subspec found"
                                const missingText = currentLanguage === 'zh' ? '没有找到子规约' : 'No subspec found';
                                tooltipContent = '<div class="tooltip-translated">' + missingText + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">none</div>';
                            }} else {{
                                if (subspecTrans) {{
                                    // 翻译文本已经在 Python 中静态处理，添加了高亮标签
                                    tooltipContent = '<div class="tooltip-translated">' + subspecTrans + '</div><div class="tooltip-separator">─────────────────────</div><div class="tooltip-formula">' + displaySubspec + '</div>';
                                }} else {{
                                    tooltipContent = '<div class="tooltip-formula">' + displaySubspec + '</div>';
                                }}
                            }}
                            
                            // 转义 tooltipContent 以便安全地插入到 HTML 属性中
                            const escapedTooltipContent = escapeHtmlForAttribute(tooltipContent);
                            
                            // 判断是 line-level 还是 config-level subspec
                            let cssClass = "config-field";
                            let isEmpty = (subspec === 'empty');
                            
                            if (lineSubspecNames && lineSubspecNames.has(subspecName)) {{
                                cssClass += " line-level";
                            }}
                            
                            if (isMissing) {{
                                // 如果 subspec 根本不存在，使用 missing-subspec 类（亮黄色）
                                cssClass += " missing-subspec";
                            }} else if (isEmpty) {{
                                // 如果 subspec 存在但值为 'empty'，使用 empty-subspec 类
                                cssClass += " empty-subspec";
                            }}
                            
                            const replacement = `<span class="${{cssClass}}" data-subspec="${{escapedTooltipContent}}" data-subspec-name="${{subspecName}}">${{fieldName}}</span>`;
                            result = result.substring(0, startIndex) + replacement + result.substring(endIndex + 1);
                            lastIndex = startIndex - 1;
                            continue;
                        }}
                    }}
                    
                    lastIndex = bracketParenIndex - 1;
                }}
                
                processed = result;
            }} else if (!showSubspecs && text.includes('[') && text.includes('](')) {{
                // 不显示subspec，直接移除标注
                // 使用同样的方法处理嵌套方括号
                let result = processed;
                let lastIndex = result.length;
                
                while (true) {{
                    const bracketParenIndex = result.lastIndexOf('](', lastIndex);
                    if (bracketParenIndex === -1) break;
                    
                    // 从 ]( 位置向前查找匹配的 [
                    let bracketCount = 0;
                    let startIndex = -1;
                    for (let i = bracketParenIndex; i >= 0; i--) {{
                        if (result[i] === ']') {{
                            bracketCount++;
                        }} else if (result[i] === '[') {{
                            bracketCount--;
                            if (bracketCount === 0) {{
                                startIndex = i;
                                break;
                            }}
                        }}
                    }}
                    
                    if (startIndex !== -1) {{
                        // 查找匹配的 )
                        let parenCount = 0;
                        let endIndex = -1;
                        for (let i = bracketParenIndex + 1; i < result.length; i++) {{
                            if (result[i] === '(') {{
                                parenCount++;
                            }} else if (result[i] === ')') {{
                                parenCount--;
                                if (parenCount === 0) {{
                                    endIndex = i;
                                    break;
                                }}
                            }}
                        }}
                        
                        if (endIndex !== -1) {{
                            const fieldName = result.substring(startIndex + 1, bracketParenIndex);
                            result = result.substring(0, startIndex) + fieldName + result.substring(endIndex + 1);
                            lastIndex = startIndex - 1;
                            continue;
                        }}
                    }}
                    
                    lastIndex = bracketParenIndex - 1;
                }}
                
                processed = result;
            }}
            
            // 处理空的 symbolic [config]<> 格式
            // 如果显示 subspec，则增加宽度但不设置背景颜色
            // 如果不显示 subspec，则直接移除
            if (text.includes('[') && text.includes(']<>')) {{
                let result = processed;
                let lastIndex = result.length;
                
                // 从右到左查找所有 ]<> 位置
                while (true) {{
                    const bracketAngleIndex = result.lastIndexOf(']<>', lastIndex);
                    if (bracketAngleIndex === -1) break;
                    
                    // 从 ]<> 位置向前查找匹配的 [
                    let bracketCount = 0;
                    let startIndex = -1;
                    for (let i = bracketAngleIndex; i >= 0; i--) {{
                        if (result[i] === ']') {{
                            bracketCount++;
                        }} else if (result[i] === '[') {{
                            bracketCount--;
                            if (bracketCount === 0) {{
                                startIndex = i;
                                break;
                            }}
                        }}
                    }}
                    
                    if (startIndex !== -1) {{
                        const fieldName = result.substring(startIndex + 1, bracketAngleIndex);
                        if (showSubspecs) {{
                            // 显示 subspec：创建一个空的 span，只增加宽度，不设置背景颜色
                            const replacement = `<span class="config-field-empty-spacer">${{fieldName}}</span>`;
                            result = result.substring(0, startIndex) + replacement + result.substring(bracketAngleIndex + 3);
                        }} else {{
                            // 不显示 subspec：直接移除 [config]<>，只保留内容
                            result = result.substring(0, startIndex) + fieldName + result.substring(bracketAngleIndex + 3);
                        }}
                        lastIndex = startIndex - 1;
                        continue;
                    }}
                    
                    lastIndex = bracketAngleIndex - 1;
                }}
                
                processed = result;
            }}
            
            // 处理 [[Config_X]<>] 或 [[Config_X](Config_X_xxx)] 格式，加上 [] 突出强调
            // 匹配 [[...]<>] 或 [[...](...)] 格式（双重方括号）
            processed = processed.replace(/\[\[([^\]]+)\](\<\>|\([^)]+\))\]/g, (match, innerContent, suffix) => {{
                // 在外层加上 [] 突出强调
                return `<span style="font-weight: bold; color: #0066cc;">[</span>${{innerContent}}${{suffix}}<span style="font-weight: bold; color: #0066cc;">]</span>`;
            }});
            
            return processed;
        }}

        function formatDiffContent(diffLines, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs, configSubspecTransData, lineSubspecTransData) {{
            if (typeof diffLines === 'string') {{
                diffLines = diffLines.split('\\n');
            }}
            
            // 如果没有提供 subspec 数据，使用默认处理（向后兼容）
            const hasSubspecData = subspecData && configSubspecData && lineSubspecData && lineSubspecNames;
            
            return diffLines.map(line => {{
                const trimmedLine = line.trim();
                let processedLine = line;
                
                // 处理 subspec 和配置引用
                if (hasSubspecData) {{
                    processedLine = processOptionText(line, subspecData, configSubspecData, lineSubspecData, lineSubspecNames, showSubspecs !== undefined ? showSubspecs : true, configSubspecTransData, lineSubspecTransData);
                }} else {{
                    processedLine = processConfigReferences(line);
                }}
                
                if (trimmedLine.startsWith('-')) {{
                    // 删除的行 - 红色
                    return `<div class="diff-line diff-removed">${{processedLine}}</div>`;
                }} else if (trimmedLine.startsWith('+')) {{
                    // 添加的行 - 绿色
                    return `<div class="diff-line diff-added">${{processedLine}}</div>`;
                }} else if (trimmedLine.startsWith('@@') && trimmedLine.includes('Configuration')) {{
                    // diff提示行 - 转换为可交互的配置引用
                    return `<div class="diff-line diff-context">${{processedLine}}</div>`;
                }} else {{
                    // 普通行 - 默认颜色
                    return `<div class="diff-line diff-context">${{processedLine}}</div>`;
                }}
            }}).join('');
        }}

        function checkCourseraQuestion(questionId) {{
            const firstCheckbox = document.getElementById(`${{questionId}}-option-0`);
            if (!firstCheckbox) return;
            const questionElement = firstCheckbox.closest('.coursera-question');
            if (!questionElement) return;
            const checkboxes = questionElement.querySelectorAll(`input[name^="${{questionId}}-options"]`);
            const courseraData = questionData.coursera[currentLanguage] || questionData.coursera['en'];
            let currentQuestion = null;
            const questionNum = questionElement.querySelector('h4').textContent.match(/(?:Question|问题)\\s*(\\d+)/);
            if (questionNum) {{
                const num = questionNum[1];
                currentQuestion = courseraData.questions.find(q => q.num === num);
            }}
            if (!currentQuestion) return;
            const correctOptions = currentQuestion.options.filter(opt => opt.correct);
            const selectedOptions = Array.from(checkboxes).filter(cb => cb.checked);
            const correctSelected = [];
            selectedOptions.forEach(cb => {{
                const optionIndex = parseInt(cb.value.replace('option', ''));
                if (currentQuestion.options[optionIndex] && currentQuestion.options[optionIndex].correct) {{
                    correctSelected.push(cb);
                }}
            }});
            const incorrectSelected = [];
            selectedOptions.forEach(cb => {{
                const optionIndex = parseInt(cb.value.replace('option', ''));
                if (currentQuestion.options[optionIndex] && !currentQuestion.options[optionIndex].correct) {{
                    incorrectSelected.push(cb);
                }}
            }});
            
            // 处理 note 的显示逻辑
            const noteElement = document.getElementById(`${{questionId}}-note`);
            if (noteElement && currentQuestion.note) {{
                // 默认隐藏 note
                noteElement.style.display = 'none';
                
                // 检查是否只选择了正确的选项（且没有选择错误的选项）
                const onlyCorrectSelected = correctSelected.length === correctOptions.length && 
                                           selectedOptions.length === correctOptions.length && 
                                           incorrectSelected.length === 0;
                
                // 对于问题3，特殊处理：如果只选择了选项2（索引1），也显示 note
                let shouldShowNote = false;
                if (currentQuestion.num === "3" && selectedOptions.length === 1) {{
                    const selectedOptionIndex = parseInt(selectedOptions[0].value.replace('option', ''));
                    if (selectedOptionIndex === 1) {{
                        shouldShowNote = true;
                    }}
                }}
                
                // 如果只选择了正确的选项，或者问题3只选择了选项2，显示 note
                if (onlyCorrectSelected || shouldShowNote) {{
                    noteElement.style.display = 'block';
                }}
            }}
            
            const overallFeedback = document.getElementById(`${{questionId}}-overall-feedback`);
            if (!overallFeedback) return;
            if (incorrectSelected.length > 0) {{
                overallFeedback.classList.add('show');
                overallFeedback.style.background = '#f8d7da';
                overallFeedback.style.color = '#721c24';
                overallFeedback.style.border = '1px solid #f5c6cb';
                overallFeedback.innerHTML = texts.courseraIncorrect;
            }} else if (correctSelected.length < correctOptions.length) {{
                overallFeedback.classList.add('show');
                overallFeedback.style.background = '#fff3cd';
                overallFeedback.style.color = '#856404';
                overallFeedback.style.border = '1px solid #ffeaa7';
                overallFeedback.innerHTML = texts.courseraIncomplete;
            }} else if (correctSelected.length === correctOptions.length && selectedOptions.length === correctOptions.length) {{
                overallFeedback.classList.add('show');
                overallFeedback.style.background = '#d4edda';
                overallFeedback.style.color = '#155724';
                overallFeedback.style.border = '1px solid #c3e6cb';
                overallFeedback.innerHTML = texts.courseraCorrect;
            }} else {{
                overallFeedback.classList.remove('show');
            }}
        }}

        // Create a single global tooltip for subspecs
        let globalTooltip = null;

        // 设置 subspec tooltip 事件委托（Coursera）
        function setupCourseraSubspecTooltipDelegation() {{
            // Create a single global tooltip if it doesn't exist
            if (!globalTooltip) {{
                globalTooltip = document.createElement('div');
                globalTooltip.className = 'tooltip';
                document.body.appendChild(globalTooltip);
            }}
            
            // 如果已经设置过事件委托，不再重复设置
            if (window.courseraHoverEventsInitialized) {{
                    return;
                }}
                
            // 在 document 上使用事件委托，监听所有 .config-field 的鼠标事件
            document.addEventListener('mouseover', (e) => {{
                // 检查事件目标是否是 .config-field 或其子元素
                const field = e.target.closest('.config-field');
                if (!field) return;
                
                // 移除之前所有字段的高亮
                document.querySelectorAll('.config-field-showing-tooltip').forEach(f => {{
                    f.classList.remove('config-field-showing-tooltip');
                }});
                
                // 为当前字段添加灰色高亮
                field.classList.add('config-field-showing-tooltip');
                
                const subspec = field.getAttribute('data-subspec');
                    
                // Always hide tooltip first to ensure clean state
                globalTooltip.classList.remove('show');
                globalTooltip.style.display = 'none';
                globalTooltip.style.visibility = 'hidden';
                globalTooltip.style.opacity = '0';
                    
                // If no subspec, don't show tooltip
                if (!subspec) return;
                    
                // Set content and force reflow
                globalTooltip.innerHTML = subspec;
                globalTooltip.style.display = 'block';
                    
                    // Use requestAnimationFrame to ensure Safari completes layout before positioning
                    requestAnimationFrame(() => {{
                        // Get field position and dimensions
                        const fieldRect = field.getBoundingClientRect();
                        const tooltipHeight = globalTooltip.offsetHeight;
                        
                        // Get actual tooltip width after content is set
                        const tooltipWidth = globalTooltip.offsetWidth;
                        const maxTooltipWidth = 550;
                        
                        // Calculate tooltip position relative to the field
                        // Center tooltip horizontally over the field
                        let left = fieldRect.left + (fieldRect.width / 2) - (tooltipWidth / 2);
                        // Position tooltip above the field with consistent spacing
                        let top = fieldRect.top - tooltipHeight - 20;
                        
                        // Calculate arrow position (center of the field)
                        const arrowLeft = fieldRect.left + (fieldRect.width / 2);
                        
                        // Ensure tooltip stays within viewport bounds horizontally
                        if (left < 10) {{
                            left = 10;
                        }} else if (left + tooltipWidth > window.innerWidth - 10) {{
                            left = window.innerWidth - tooltipWidth - 10;
                        }}
                        
                        // Adjust vertical position if tooltip would go off-screen
                        let arrowPosition = 'bottom'; // Default: arrow points down from tooltip
                        if (top < 10) {{
                            // Tooltip goes below the field
                            top = fieldRect.bottom + 20;
                            arrowPosition = 'top'; // Arrow points up from tooltip
                        }}
                        
                        // Set arrow position and style
                        if (arrowPosition === 'top') {{
                            // Tooltip is below the field: arrow should be above the tooltip and point up
                            globalTooltip.style.setProperty('--arrow-top', '-12px');
                            // Bottom border colored → triangle points up
                            globalTooltip.style.setProperty('--arrow-border', 'transparent transparent #9e9e9e transparent');
                        }} else {{
                            // Arrow at bottom of tooltip, pointing down
                            globalTooltip.style.setProperty('--arrow-top', '100%');
                            globalTooltip.style.setProperty('--arrow-border', '#9e9e9e transparent transparent transparent');
                        }}
                        
                        // Calculate arrow horizontal position relative to tooltip
                        // Use actual tooltip width for accurate positioning
                        const arrowOffset = arrowLeft - left;
                        const minArrowPos = 20;
                        const maxArrowPos = tooltipWidth - 20;
                        globalTooltip.style.setProperty('--arrow-left', Math.max(minArrowPos, Math.min(maxArrowPos, arrowOffset)) + 'px');
                        
                        // Set final position and show tooltip immediately
                        globalTooltip.style.left = left + 'px';
                        globalTooltip.style.top = top + 'px';
                        globalTooltip.style.visibility = 'visible';
                        globalTooltip.style.opacity = '1';
                        globalTooltip.classList.add('show');
                    }});
            }}, true); // 使用捕获阶段，确保能捕获到动态添加的元素
            
            // 添加点击事件，复制 subspec 翻译内容到剪贴板
            document.addEventListener('click', (e) => {{
                // 检查事件目标是否是 .config-field 或其子元素
                const field = e.target.closest('.config-field');
                if (!field) return;
                
                // 阻止默认行为
                e.preventDefault();
                e.stopPropagation();
                
                const subspec = field.getAttribute('data-subspec');
                if (!subspec) return;
                
                // 创建一个临时 div 来解析 HTML 内容
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = subspec;
                
                // 查找 tooltip-translated 元素
                const translatedElement = tempDiv.querySelector('.tooltip-translated');
                if (!translatedElement) {{
                    // 如果没有 tooltip-translated，尝试获取所有文本内容
                    const allText = tempDiv.innerText || tempDiv.textContent || '';
                    if (allText.trim()) {{
                        copyToClipboardCoursera(allText.trim());
                    }}
                    return;
                }}
                
                // 获取翻译文本（去除 HTML 标签，保留文本内容）
                const translatedText = translatedElement.innerText || translatedElement.textContent || '';
                
                if (translatedText.trim()) {{
                    copyToClipboardCoursera(translatedText.trim());
                }}
            }}, true); // 使用捕获阶段
            
            // 复制到剪贴板的辅助函数（Coursera）
            function copyToClipboardCoursera(text) {{
                // 优先使用现代 Clipboard API（支持 HTTPS 和 localhost）
                // 兼容性：Chrome 66+, Firefox 63+, Safari 13.1+, Edge 79+
                if (navigator.clipboard && navigator.clipboard.writeText) {{
                    // 检查是否在安全上下文中（HTTPS 或 localhost）
                    const isSecureContext = window.isSecureContext || location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
                    if (isSecureContext) {{
                        navigator.clipboard.writeText(text).then(() => {{
                            showCopyFeedbackCoursera();
                        }}).catch(err => {{
                            console.error('复制失败:', err);
                            // 降级到传统方法
                            fallbackCopyToClipboardCoursera(text);
                        }});
                        return;
                    }}
                }}
                // 降级到传统方法（支持所有浏览器，包括旧版本）
                fallbackCopyToClipboardCoursera(text);
            }}
            
            // 降级复制方法（Coursera，兼容所有浏览器和操作系统）
            function fallbackCopyToClipboardCoursera(text) {{
                const textArea = document.createElement('textarea');
                textArea.value = text;
                // 设置样式，确保元素不可见但可选中
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                textArea.style.top = '-999999px';
                textArea.style.opacity = '0';
                textArea.style.pointerEvents = 'none';
                // 设置 readonly 以防止 iOS Safari 弹出键盘
                textArea.setAttribute('readonly', '');
                document.body.appendChild(textArea);
                
                // 对于 iOS Safari，需要特殊处理
                if (/iPad|iPhone|iPod/.test(navigator.userAgent)) {{
                    const range = document.createRange();
                    range.selectNodeContents(textArea);
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    textArea.setSelectionRange(0, 999999);
                }} else {{
                    textArea.focus();
                    textArea.select();
                }}
                
                try {{
                    const successful = document.execCommand('copy');
                    if (successful) {{
                        showCopyFeedbackCoursera();
                    }} else {{
                        console.error('复制命令执行失败');
                    }}
                }} catch (err) {{
                    console.error('复制失败:', err);
                }}
                
                document.body.removeChild(textArea);
            }}
            
            // 显示复制反馈（Coursera）
            function showCopyFeedbackCoursera() {{
                // 创建或获取反馈元素
                let feedback = document.getElementById('copy-feedback');
                if (!feedback) {{
                    feedback = document.createElement('div');
                    feedback.id = 'copy-feedback';
                    feedback.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #4caf50; color: white; padding: 10px 20px; border-radius: 4px; z-index: 10000; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); transition: opacity 0.3s ease;';
                    document.body.appendChild(feedback);
                }}
                
                // 获取当前语言：优先从 window.currentLanguage，其次从 texts 对象，最后从 URL 参数
                let currentLanguage = 'en';
                if (typeof window !== 'undefined' && window.currentLanguage) {{
                    currentLanguage = window.currentLanguage;
                }} else if (typeof texts !== 'undefined' && texts) {{
                    // 通过检查 texts 对象的内容来判断语言
                    const langBtn = document.querySelector('.lang-btn.active');
                    if (langBtn) {{
                        const langId = langBtn.id;
                        if (langId && langId.includes('zh')) {{
                            currentLanguage = 'zh';
                        }}
                    }}
                }} else {{
                    // 从 URL 参数获取
                    const urlParams = new URLSearchParams(window.location.search);
                    const urlLang = urlParams.get('lang');
                    if (urlLang === 'zh') {{
                        currentLanguage = 'zh';
                    }}
                }}
                
                feedback.textContent = currentLanguage === 'zh' ? '已复制到剪贴板' : 'Copied to clipboard';
                feedback.style.display = 'block';
                feedback.style.opacity = '1';
                
                // 2秒后淡出
                setTimeout(() => {{
                    feedback.style.opacity = '0';
                    setTimeout(() => {{
                        feedback.style.display = 'none';
                    }}, 300);
                }}, 2000);
            }}
            
            document.addEventListener('mouseout', (e) => {{
                // 检查事件目标是否是 .config-field 或其子元素
                const field = e.target.closest('.config-field');
                if (!field) return;
                
                // 检查鼠标是否移动到另一个 .config-field
                const relatedField = e.relatedTarget?.closest('.config-field');
                if (relatedField) return; // 如果移动到另一个 field，不隐藏 tooltip
                
                // 移除灰色高亮
                field.classList.remove('config-field-showing-tooltip');
                
                // Always hide tooltip when leaving a field
                globalTooltip.classList.remove('show');
                globalTooltip.style.display = 'none';
                globalTooltip.style.visibility = 'hidden';
                globalTooltip.style.opacity = '0';
            }}, true); // 使用捕获阶段
            
            // 标记为已初始化
            window.courseraHoverEventsInitialized = true;
        }}
        
        function addCourseraEventListeners() {{
            // 使用事件委托而不是直接绑定
            setupCourseraSubspecTooltipDelegation();
            
            // Bit-map 机制：跟踪每个配置引用的状态（Coursera 问题）
            let courseraConfigReferenceBitMap = new Map(); // key: "optionId-lines", value: {{optionId, isActive}}
            let currentActiveCourseraOption = null; // 当前激活的选项ID
            
            // 生成配置引用的唯一标识（Coursera）
            function getCourseraConfigRefId(lines, optionId) {{
                return `${{optionId}}-${{lines}}`;
            }}
            
            // 获取配置引用所在的选项ID（Coursera）
            function getCourseraOptionId(element) {{
                const optionItem = element.closest('.option-item');
                if (optionItem) {{
                    const input = optionItem.querySelector('input[type="checkbox"]');
                    if (input && input.id) {{
                        return input.id;
                    }}
                }}
                return null;
            }}
            
            // 检查配置引用是否已激活（Coursera）
            function isCourseraConfigRefActive(lines, optionId) {{
                const refId = getCourseraConfigRefId(lines, optionId);
                return courseraConfigReferenceBitMap.has(refId) && courseraConfigReferenceBitMap.get(refId).isActive;
            }}
            
            // 激活配置引用（Coursera）
            function activateCourseraConfigRef(lines, optionId) {{
                const refId = getCourseraConfigRefId(lines, optionId);
                courseraConfigReferenceBitMap.set(refId, {{ optionId, isActive: true }});
            }}
            
            // 停用配置引用（Coursera）
            function deactivateCourseraConfigRef(lines, optionId) {{
                const refId = getCourseraConfigRefId(lines, optionId);
                if (courseraConfigReferenceBitMap.has(refId)) {{
                    courseraConfigReferenceBitMap.delete(refId);
                }}
            }}
            
            // 更新配置引用提示文本（Coursera）
            function updateCourseraConfigReferenceTooltips() {{
                const configReferences = document.querySelectorAll('.config-reference');
                configReferences.forEach(ref => {{
                    const lines = ref.getAttribute('data-lines');
                    if (!lines) return;
                    
                    const optionId = getCourseraOptionId(ref);
                    const isChinese = currentLanguage === 'zh';
                    
                    // 如果配置引用在选项内
                    if (optionId) {{
                        const isActive = isCourseraConfigRefActive(lines, optionId);
                        if (isActive) {{
                            const title = isChinese ? 
                                `点击清除配置行 ${{lines}} 的高亮` : 
                                `Click to clear the highlight of Configuration lines ${{lines}}`;
                            ref.setAttribute('title', title);
                        }} else {{
                            const title = isChinese ? 
                                `点击高亮配置行 ${{lines}}` : 
                                `Click to highlight Configuration lines ${{lines}}`;
                            ref.setAttribute('title', title);
                        }}
                    }} else {{
                        // 配置引用不在选项内（例如在 sample question 的问题描述中）
                        const refId = `sample-${{lines}}`;
                        const isActive = courseraConfigReferenceBitMap.has(refId) && courseraConfigReferenceBitMap.get(refId).isActive;
                        if (isActive) {{
                            const title = isChinese ? 
                                `点击清除配置行 ${{lines}} 的高亮` : 
                                `Click to clear the highlight of Configuration lines ${{lines}}`;
                            ref.setAttribute('title', title);
                        }} else {{
                            const title = isChinese ? 
                                `点击高亮配置行 ${{lines}}` : 
                                `Click to highlight Configuration lines ${{lines}}`;
                            ref.setAttribute('title', title);
                        }}
                    }}
                }});
            }}
            
            // 清除指定选项的所有配置引用（Coursera）
            function clearCourseraOptionConfigRefs(optionId) {{
                const refsToRemove = [];
                // 找到选项所在的问题元素
                const optionElement = document.getElementById(optionId);
                const questionElement = optionElement ? optionElement.closest('.coursera-question') : null;
                
                for (let [refId, data] of courseraConfigReferenceBitMap) {{
                    if (data.optionId === optionId) {{
                        // 清除对应的高亮
                        // refId 格式: "optionId-lines"，需要提取 lines 部分
                        const lines = refId.substring(optionId.length + 1); // 跳过 "optionId-"
                        clearCourseraConfigLinesHighlight(lines, questionElement);
                        // 标记为待删除
                        refsToRemove.push(refId);
                    }}
                }}
                // 从 Map 中删除这些引用
                refsToRemove.forEach(refId => {{
                    courseraConfigReferenceBitMap.delete(refId);
                }});
            }}
            
            // 清除特定配置行的高亮（Coursera）
            function clearCourseraConfigLinesHighlight(lineRange, questionElement) {{
                // 解析行号范围
                const [startLine, endLine] = lineRange.split(',').map(num => parseInt(num.trim()));
                
                // 在指定问题范围内查找配置行
                if (questionElement) {{
                    const configContent = questionElement.querySelector('.config-content');
                    if (configContent) {{
                        const configLines = configContent.querySelectorAll('.config-line');
                        configLines.forEach(line => {{
                            const lineNumberSpan = line.querySelector('.config-line-number');
                            let actualLineNumber = null;
                            if (lineNumberSpan) {{
                                actualLineNumber = parseInt(lineNumberSpan.textContent.trim());
                            }} else {{
                                actualLineNumber = parseInt(line.getAttribute('data-line'));
                            }}
                            
                            if (actualLineNumber && actualLineNumber >= startLine && actualLineNumber <= endLine) {{
                                line.classList.remove('config-line-highlighted');
                                line.classList.remove('config-line-highlighted-removed');
                                line.classList.remove('config-line-highlighted-added');
                                
                                // 恢复原始内容（如果之前保存过）
                                if (line.hasAttribute('data-original-html')) {{
                                    line.innerHTML = line.getAttribute('data-original-html');
                                    line.removeAttribute('data-original-html');
                                }}
                            }}
                        }});
                        
                        // 移除新增行显示
                        configContent.querySelectorAll('.config-line-added-display').forEach(el => {{
                            el.remove();
                        }});
                    }}
                }}
            }}
            
            // 高亮配置行（Coursera）- 支持 - / + / none 高亮形式
            function highlightCourseraConfigLines(lineRange, optionId, questionElement) {{
                // 解析行号范围
                const [startLine, endLine] = lineRange.split(',').map(num => parseInt(num.trim()));
                
                // 在指定问题范围内查找配置区域
                if (!questionElement) return;
                    const configContent = questionElement.querySelector('.config-content');
                if (!configContent) return;
                
                // 查找选项的 diff 内容，检查是否有 - 或 + 标记
                const diffInfo = {{}}; // key: lineNumber, value: 'removed' | 'added' | null
                const addedLinesInfo = []; // 存储新增行的信息
                let removedLines = []; // 存储删除行的信息，用于匹配新增行和替换内容（在函数作用域内初始化）
                
                if (optionId) {{
                    const optionElement = document.getElementById(optionId)?.closest('.option-item');
                    if (optionElement) {{
                        const diffContent = optionElement.querySelector('.option-diff-content');
                        if (diffContent) {{
                            const diffLines = Array.from(diffContent.querySelectorAll('.diff-line'));
                            let configRefIndex = -1;
                            
                            // 找到配置引用所在的行
                            for (let i = 0; i < diffLines.length; i++) {{
                                const lineText = diffLines[i].textContent || diffLines[i].innerText;
                                const trimmedText = lineText.trim();
                                
                                // 检查是否包含配置引用（不带路由器前缀）
                                const configRefPattern = new RegExp(`Configuration\\\\s+${{lineRange}}`);
                                
                                if (configRefPattern.test(trimmedText)) {{
                                    configRefIndex = i;
                                    break;
                                }}
                            }}
                            
                            // 如果找到配置引用，检查后续行的标记
                            if (configRefIndex >= 0) {{
                                let currentLineNum = startLine;
                                
                                for (let i = configRefIndex + 1; i < diffLines.length; i++) {{
                                    const diffLine = diffLines[i];
                                    // 获取文本内容用于检测标记
                                    const lineText = diffLine.textContent || diffLine.innerText;
                                    const trimmedText = lineText.trim();
                                    // 获取 HTML 内容用于保留格式（包括 [[Config_X](Config_X_xxx)]）
                                    let lineHTML = diffLine.innerHTML || '';
                                                
                                    // 检查是否是删除行或新增行（通过类名）
                                    const isRemoved = diffLine.classList && diffLine.classList.contains('diff-removed');
                                    const isAdded = diffLine.classList && diffLine.classList.contains('diff-added');
                                                
                                    // 如果遇到下一个配置引用，停止
                                    if (trimmedText.startsWith('@@') && trimmedText.includes('Configuration')) {{
                                        break;
                                    }}
                                    
                                    // 如果遇到 <br> 标签，停止（这是配置块的结束标记）
                                    if (trimmedText === '<br>' || trimmedText.includes('<br>')) {{
                                        break;
                                    }}
                                    
                                    // 跳过空行
                                    if (trimmedText === '') {{
                                        continue;
                                    }}
                                    
                                    // 检查行的标记（优先使用类名，如果没有则使用文本内容）
                                    if (isRemoved || trimmedText.startsWith('-')) {{
                                        // 处理所有删除行，不限制在 j,k 范围内（因为配置块到 <br> 或结束）
                                        if (currentLineNum >= startLine && currentLineNum <= endLine) {{
                                            diffInfo[currentLineNum] = 'removed';
                                            // 提取删除行的内容（保留 HTML 格式，包括 [] 和 [[Config_X](Config_X_xxx)]）
                                            let removedContent = '';
                                            // 优先使用 lineHTML，因为它包含完整的 HTML 结构（包括 .config-field 元素）
                                            if (lineHTML && lineHTML.trim().length > 0) {{
                                                // 如果 HTML 中包含 .config-field，说明已经处理过，直接使用
                                                if (lineHTML.includes('config-field') || lineHTML.includes('data-subspec')) {{
                                                    // HTML 已经包含完整的结构，直接使用（可能需要去除开头的 - 号）
                                                    if (lineHTML.trim().startsWith('-')) {{
                                                        removedContent = lineHTML.trim().substring(1).trim();
                                                    }} else {{
                                                        removedContent = lineHTML.trim();
                                                    }}
                                                }} else if (lineHTML.includes('-')) {{
                                                    // HTML 中包含 - 号，尝试提取 - 号后的内容
                                                    const minusMatch = lineHTML.match(/[-]\\s*(.+)/);
                                                    if (minusMatch) {{
                                                        removedContent = minusMatch[1].trim();
                                                    }} else {{
                                                        const minusIndex = lineHTML.indexOf('-');
                                                        removedContent = lineHTML.substring(minusIndex + 1).trim();
                                                    }}
                                                }} else {{
                                                    // HTML 中没有 - 号，直接使用
                                                    removedContent = lineHTML.trim();
                                                }}
                                            }} else {{
                                                // 如果 HTML 为空，使用文本内容（去除 - 号）
                                                removedContent = trimmedText.substring(1).trim();
                                            }}
                                            // 存储删除行信息，用于后续匹配新增行和替换内容
                                            removedLines.push({{lineNum: currentLineNum, content: removedContent}});
                                        }}
                                        currentLineNum++;
                                    }} else if (isAdded || trimmedText.startsWith('+')) {{
                                        // 新增行：找到对应的删除行（通常是最近的删除行）
                                        // 提取新增行的内容（保留 HTML 格式，包括 [[Config_X](Config_X_xxx)]）
                                        let addedContent = '';
                                        // 优先使用 lineHTML，因为它包含完整的 HTML 结构（包括 .config-field 元素）
                                        if (lineHTML && lineHTML.trim().length > 0) {{
                                            // 如果 HTML 中包含 .config-field，说明已经处理过，直接使用
                                            if (lineHTML.includes('config-field') || lineHTML.includes('data-subspec')) {{
                                                // HTML 已经包含完整的结构，直接使用（可能需要去除开头的 + 号）
                                                if (lineHTML.trim().startsWith('+')) {{
                                                    addedContent = lineHTML.trim().substring(1).trim();
                                                }} else {{
                                                    addedContent = lineHTML.trim();
                                                }}
                                            }} else if (lineHTML.includes('+')) {{
                                                // HTML 中包含 + 号，尝试提取 + 号后的内容
                                                const plusMatch = lineHTML.match(/[+]\\s*(.+)/);
                                                if (plusMatch) {{
                                                    addedContent = plusMatch[1].trim();
                                                }} else {{
                                                    const plusIndex = lineHTML.indexOf('+');
                                                    addedContent = lineHTML.substring(plusIndex + 1).trim();
                                                }}
                                            }} else {{
                                                // HTML 中没有 + 号，直接使用
                                                addedContent = lineHTML.trim();
                                            }}
                                        }} else {{
                                            // 如果 HTML 为空，使用文本内容（去除 + 号）
                                            addedContent = trimmedText.substring(1).trim();
                                        }}
                                        // 如果最近有删除行，将新增行关联到该删除行
                                        // 对于多个 + 行，每个 + 行应该关联到对应的 - 行（按顺序）
                                        if (removedLines.length > 0) {{
                                            // 计算这个 + 行应该关联到哪个 - 行
                                            // 如果这是第一个 + 行，关联到第一个 - 行；如果是第二个 + 行，关联到第二个 - 行，以此类推
                                            // 使用 addedLinesInfo 的长度来确定这是第几个 + 行
                                            const addedLineIndex = addedLinesInfo.length;
                                            let targetRemovedLineIndex = addedLineIndex;
                                            // 如果 + 行数量超过 - 行数量，则最后一个 + 行关联到最后一个 - 行
                                            if (targetRemovedLineIndex >= removedLines.length) {{
                                                targetRemovedLineIndex = removedLines.length - 1;
                                            }}
                                            const targetRemovedLine = removedLines[targetRemovedLineIndex];
                                            const removedLineNum = targetRemovedLine.lineNum;
                                            addedLinesInfo.push({{lineNum: removedLineNum, content: addedContent}});
                                        }} else {{
                                            // 如果没有删除行，仍然记录新增行信息（但需要确保行号在范围内）
                                            if (currentLineNum >= startLine && currentLineNum <= endLine) {{
                                                diffInfo[currentLineNum] = 'added';
                                                addedLinesInfo.push({{lineNum: currentLineNum, content: addedContent}});
                                            }}
                                        }}
                                        // 新增行不增加行号计数（因为它不在原始配置中）
                                    }} else if (trimmedText && !trimmedText.startsWith('@@')) {{
                                        // 普通行，继续计数
                                        currentLineNum++;
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
                
                // 查找配置行并应用高亮
                        const configLines = configContent.querySelectorAll('.config-line');
                let highlightedCount = 0;
                
                // 创建一个映射：实际行号 -> DOM 元素
                const lineNumberToElement = new Map();
                configLines.forEach((line) => {{
                    // 尝试从行内容中提取实际行号
                    const lineNumberSpan = line.querySelector('.config-line-number');
                    let actualLineNumber = null;
                    if (lineNumberSpan) {{
                        actualLineNumber = parseInt(lineNumberSpan.textContent.trim());
                    }} else {{
                        // 如果没有行号 span，使用 data-line 作为后备
                        actualLineNumber = parseInt(line.getAttribute('data-line'));
                    }}
                    
                    if (actualLineNumber) {{
                        lineNumberToElement.set(actualLineNumber, line);
                        
                        if (actualLineNumber >= startLine && actualLineNumber <= endLine) {{
                            // 根据 diff 信息决定高亮颜色
                            if (diffInfo[actualLineNumber] === 'removed') {{
                                line.classList.add('config-line-highlighted-removed');
                                // 用 diff 中的内容替换配置行的内容（保留 HTML 格式，包括 []）
                                const removedLineInfo = removedLines && removedLines.length > 0 ? removedLines.find(r => r.lineNum === actualLineNumber) : null;
                                if (removedLineInfo) {{
                                    // 保存原始内容（如果还没有保存）
                                    if (!line.hasAttribute('data-original-html')) {{
                                        line.setAttribute('data-original-html', line.innerHTML);
                                    }}
                                    
                                    // 保留行号部分，只替换内容部分，并在行号前添加 - 号
                                    const lineNumberSpan = line.querySelector('.config-line-number');
                                    if (lineNumberSpan) {{
                                        const removedLineHTML = line.innerHTML;
                                        const lineNumberMatch = removedLineHTML.match(/^(\\s*)<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                        if (lineNumberMatch) {{
                                            const lineNumber = lineNumberMatch[2];
                                            const trailingSpaces = lineNumberMatch[3];
                                            // 在行号前添加 - 号，去掉前导空格（更紧凑）
                                            line.innerHTML = `-<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{removedLineInfo.content}}`;
                                        }} else {{
                                            // 如果无法匹配，使用简单格式，在行号前添加 - 号
                                            const lineNumber = lineNumberSpan.textContent.trim();
                                            line.innerHTML = `-<span class="config-line-number">${{lineNumber}}</span> ${{removedLineInfo.content}}`;
                                        }}
                                    }}
                                }} else {{
                                    // 如果没有 removedLineInfo，仍然需要添加 - 号
                                    const lineNumberSpan = line.querySelector('.config-line-number');
                                    if (lineNumberSpan) {{
                                        const currentHTML = line.innerHTML;
                                        // 检查是否已经有 - 号
                                        if (!currentHTML.trim().startsWith('-')) {{
                                            // 保存原始内容（如果还没有保存）
                                            if (!line.hasAttribute('data-original-html')) {{
                                                line.setAttribute('data-original-html', currentHTML);
                                            }}
                                            // 在行号前添加 - 号，去掉前导空格（更紧凑）
                                            const lineNumberMatch = currentHTML.match(/^(\\s*)<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                            if (lineNumberMatch) {{
                                                const lineNumber = lineNumberMatch[2];
                                                const trailingSpaces = lineNumberMatch[3];
                                                const contentAfter = currentHTML.substring(lineNumberMatch[0].length);
                                                line.innerHTML = `-<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{contentAfter}}`;
                                            }} else {{
                                                // 简单格式
                                                const lineNumber = lineNumberSpan.textContent.trim();
                                                const contentAfter = currentHTML.replace(/<span class="config-line-number">.*?<\\/span>\\s*/, '');
                                                line.innerHTML = `-<span class="config-line-number">${{lineNumber}}</span> ${{contentAfter}}`;
                                            }}
                                        }}
                                    }}
                                }}
                            }} else if (diffInfo[actualLineNumber] === 'added') {{
                                line.classList.add('config-line-highlighted-added');
                                // 在行号前添加 + 号，去掉前导空格（更紧凑）
                                const lineNumberSpan = line.querySelector('.config-line-number');
                                if (lineNumberSpan) {{
                                    const currentHTML = line.innerHTML;
                                    // 检查是否已经有 + 号
                                    if (!currentHTML.trim().startsWith('+')) {{
                                        // 保存原始内容（如果还没有保存）
                                        if (!line.hasAttribute('data-original-html')) {{
                                            line.setAttribute('data-original-html', currentHTML);
                                        }}
                                        // 在行号前添加 + 号
                                        const lineNumberMatch = currentHTML.match(/^(\\s*)<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                        if (lineNumberMatch) {{
                                            const lineNumber = lineNumberMatch[2];
                                            const trailingSpaces = lineNumberMatch[3];
                                            const contentAfter = currentHTML.substring(lineNumberMatch[0].length);
                                            line.innerHTML = `+<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{contentAfter}}`;
                                        }} else {{
                                            // 简单格式
                                            const lineNumber = lineNumberSpan.textContent.trim();
                                            const contentAfter = currentHTML.replace(/<span class="config-line-number">.*?<\\/span>\\s*/, '');
                                            line.innerHTML = `+<span class="config-line-number">${{lineNumber}}</span> ${{contentAfter}}`;
                                        }}
                                    }}
                                }}
                            }} else {{
                                line.classList.add('config-line-highlighted');
                            }}
                            
                            highlightedCount++;
                        }}
                            }}
                        }});
                
                // 如果有新增行，在对应的删除行后显示
                // 先显示所有删除行，再显示所有新增行（按行号排序）
                if (addedLinesInfo.length > 0) {{
                    
                    // 按行号分组新增行
                    const addedLinesByRemovedLineNum = new Map();
                    addedLinesInfo.forEach((addedInfo) => {{
                        if (!addedLinesByRemovedLineNum.has(addedInfo.lineNum)) {{
                            addedLinesByRemovedLineNum.set(addedInfo.lineNum, []);
                        }}
                        addedLinesByRemovedLineNum.get(addedInfo.lineNum).push(addedInfo);
                    }});
                    
                    // 获取所有删除行的行号，按行号排序
                    const removedLineNums = removedLines && removedLines.length > 0 ? Array.from(removedLines.map(r => r.lineNum)).sort((a, b) => a - b) : [];
                    
                    // 找到最后一个删除行的位置，所有新增行将插入到它之后
                    let lastRemovedLine = null;
                    if (removedLineNums.length > 0) {{
                        const lastRemovedLineNum = removedLineNums[removedLineNums.length - 1];
                        lastRemovedLine = lineNumberToElement.get(lastRemovedLineNum);
                        if (!lastRemovedLine || diffInfo[lastRemovedLineNum] !== 'removed') {{
                            // 如果最后一个删除行不存在，尝试找到最后一个有效的删除行
                            for (let i = removedLineNums.length - 1; i >= 0; i--) {{
                                const lineNum = removedLineNums[i];
                                const line = lineNumberToElement.get(lineNum);
                                if (line && diffInfo[lineNum] === 'removed') {{
                                    lastRemovedLine = line;
                                    break;
                                }}
                            }}
                        }}
                    }}
                    
                    // 如果找到了最后一个删除行，将所有新增行插入到它之后
                    if (lastRemovedLine) {{
                        let insertAfter = lastRemovedLine;
                        
                        // 按删除行行号顺序，依次插入所有新增行
                        removedLineNums.forEach((removedLineNum) => {{
                            const addedLinesForThisRemoved = addedLinesByRemovedLineNum.get(removedLineNum) || [];
                            if (addedLinesForThisRemoved.length > 0) {{
                                // 使用行号映射找到对应的删除行（用于获取行号格式）
                                const targetRemovedLine = lineNumberToElement.get(removedLineNum);
                                
                                // 验证这确实是删除行
                                if (targetRemovedLine && diffInfo[removedLineNum] === 'removed') {{
                                    // 为这个删除行的所有新增行创建元素
                                    addedLinesForThisRemoved.forEach((addedInfo, index) => {{
                                        // 创建新增行元素
                                        const addedLine = document.createElement('span');
                                        addedLine.className = 'config-line config-line-added-display';
                                        addedLine.setAttribute('data-line', removedLineNum);
                                        
                                        // 构建内容：行号 + 内容
                                        // 需要保持与删除行相同的行号格式（去掉前导空格，更紧凑）
                                        const lineNumberSpan = targetRemovedLine.querySelector('.config-line-number');
                                        if (lineNumberSpan) {{
                                            // 优先从原始 HTML 中提取格式（如果保存了），否则从当前 HTML 中提取
                                            let removedLineHTML = targetRemovedLine.getAttribute('data-original-html') || targetRemovedLine.innerHTML;
                                            // 查找行号前后的空格（考虑可能包含 - 或 + 号的情况）
                                            // 匹配格式：前导空格 + 可选的 - 或 + 号 + 行号 span + 后置空格
                                            const lineNumberMatch = removedLineHTML.match(/^(\\s*)(?:[-+]\\s*)?<span class="config-line-number">(\\d+)<\\/span>(\\s+)/);
                                            if (lineNumberMatch) {{
                                                const lineNumber = lineNumberMatch[2];
                                                const trailingSpaces = lineNumberMatch[3];
                                                // 使用相同的格式，但内容使用新增行的内容（保留 HTML 格式，包括 [[Config_X](Config_X_xxx)]），并在行号前添加 + 号，去掉前导空格（更紧凑）
                                                addedLine.innerHTML = `+<span class="config-line-number">${{lineNumber}}</span>${{trailingSpaces}}${{addedInfo.content}}`;
                                            }} else {{
                                                // 如果无法匹配，使用简单格式，在行号前添加 + 号
                                                const lineNumber = lineNumberSpan.textContent.trim();
                                                addedLine.innerHTML = `+<span class="config-line-number">${{lineNumber}}</span> ${{addedInfo.content}}`;
                                            }}
                                        }} else {{
                                            // 如果没有行号，使用 removedLineNum，在行号前添加 + 号
                                            addedLine.innerHTML = `+<span class="config-line-number">${{removedLineNum}}</span> ${{addedInfo.content}}`;
                                        }}
                                        
                                        // 插入到 insertAfter 之后
                                        const parent = insertAfter.parentNode;
                                        if (parent) {{
                                            parent.insertBefore(addedLine, insertAfter.nextSibling);
                                            // 事件委托已经处理了所有元素，不需要单独绑定
                                            // 更新 insertAfter 为刚插入的行，以便下一个新增行插入到它之后
                                            insertAfter = addedLine;
                                        }}
                                    }});
                                }}
                            }}
                        }});
                    }}
                }}
            }}
            
            // 添加 config-reference 点击事件，高亮配置行（Coursera）
            document.querySelectorAll('.config-reference').forEach(ref => {{
                ref.addEventListener('click', function(e) {{
                    e.preventDefault();
                    e.stopPropagation();
                    const lines = this.getAttribute('data-lines');
                    if (!lines) return;
                    
                    const currentOptionId = getCourseraOptionId(this);
                    // 获取当前问题元素
                    const questionElement = this.closest('.coursera-question');
                    
                    // 如果配置引用在选项内，使用选项相关的逻辑
                    if (currentOptionId) {{
                    // 检查当前配置引用是否已激活
                    const isCurrentlyActive = isCourseraConfigRefActive(lines, currentOptionId);
                    
                    if (isCurrentlyActive) {{
                        // 场景1: 当前配置引用已激活，点击则关闭
                        deactivateCourseraConfigRef(lines, currentOptionId);
                        clearCourseraConfigLinesHighlight(lines, questionElement);
                        
                        // 检查当前选项是否还有其他激活的配置引用
                        const hasOtherActiveRefs = Array.from(courseraConfigReferenceBitMap.values())
                            .some(data => data.optionId === currentOptionId && data.isActive);
                        
                        if (!hasOtherActiveRefs) {{
                            currentActiveCourseraOption = null;
                        }}
                    }} else {{
                        // 场景2: 当前配置引用未激活
                        if (currentActiveCourseraOption && currentActiveCourseraOption !== currentOptionId) {{
                            // 场景2a: 当前有其他选项激活，先清除其他选项的所有配置引用
                            clearCourseraOptionConfigRefs(currentActiveCourseraOption);
                        }}
                        
                        // 激活当前配置引用
                        activateCourseraConfigRef(lines, currentOptionId);
                        currentActiveCourseraOption = currentOptionId;
                        
                            // 高亮配置行（传入选项ID以便检查diff内容）
                            highlightCourseraConfigLines(lines, currentOptionId, questionElement);
                        }}
                    }} else {{
                        // 配置引用不在选项内（例如在 sample question 的问题描述中）
                        // 使用简单的切换逻辑
                        const refId = `sample-${{lines}}`;
                        const isCurrentlyActive = courseraConfigReferenceBitMap.has(refId) && courseraConfigReferenceBitMap.get(refId).isActive;
                        
                        if (isCurrentlyActive) {{
                            // 清除高亮
                            courseraConfigReferenceBitMap.delete(refId);
                            clearCourseraConfigLinesHighlight(lines, questionElement);
                        }} else {{
                            // 清除其他 sample question 的配置引用
                            for (let [key, data] of courseraConfigReferenceBitMap) {{
                                if (key.startsWith('sample-')) {{
                                    const otherLines = key.substring(7); // 跳过 "sample-"
                                    clearCourseraConfigLinesHighlight(otherLines, questionElement);
                                    courseraConfigReferenceBitMap.delete(key);
                                }}
                            }}
                            
                            // 激活当前配置引用
                            courseraConfigReferenceBitMap.set(refId, {{ optionId: null, isActive: true }});
                            
                            // 高亮配置行（没有选项ID，使用普通高亮）
                            highlightCourseraConfigLines(lines, null, questionElement);
                        }}
                    }}
                    
                    // 更新 tooltip
                    updateCourseraConfigReferenceTooltips();
                }});
            }});
        }}

        // 浏览器检测和字体粗细调整
        function detectBrowserAndAdjustFontWeight() {{
            const userAgent = navigator.userAgent.toLowerCase();
            const body = document.body;
            
            // 移除之前的浏览器类
            body.classList.remove('browser-chrome', 'browser-edge', 'browser-safari', 'browser-firefox', 'browser-other');
            
            // 简化的Safari检测
            const isSafari = userAgent.includes('safari') && !userAgent.includes('chrome');
            const isFirefox = userAgent.includes('firefox');
            const isChrome = userAgent.includes('chrome') || userAgent.includes('edg');
            
            if (isSafari) {{
                body.classList.add('browser-safari');
            }} else if (isFirefox) {{
                body.classList.add('browser-firefox');
            }} else if (isChrome) {{
                body.classList.add('browser-chrome');
            }} else {{
                body.classList.add('browser-other');
            }}
        }}

        // Initialize
        detectBrowserAndAdjustFontWeight();
        showCourseraPage();
    </script>
</body>
</html>"""
    
    # 生成中文版本
    html_content_zh = html_content_en.replace(
        "let currentLanguage = 'en';",
        "let currentLanguage = 'zh';"
    ).replace(
        "<title>Explainable Network Verification via Localized Subspecification - User Study</title>",
        "<title>基于局部子规约的可解释网络验证 - 用户研究</title>"
    ).replace(
        "<h1 id=\"header-title\">Explainable Network Verification via Localized Subspecification - User Study</h1>",
        "<h1 id=\"header-title\">基于局部子规约的可解释网络验证 - 用户研究</h1>"
    ).replace(
        '<button class="lang-btn active" id="lang-en"',
        '<button class="lang-btn" id="lang-en"'
    ).replace(
        '<button class="lang-btn" id="lang-zh"',
        '<button class="lang-btn active" id="lang-zh"'
    )
    
    # 保存文件
    with open(OUTPUT_DIR / 'coursera_en.html', 'w', encoding='utf-8') as f:
        f.write(html_content_en)
    
    with open(OUTPUT_DIR / 'coursera_zh.html', 'w', encoding='utf-8') as f:
        f.write(html_content_zh)
    
    print("✅ Coursera HTML files generated successfully!")
    print("📁 Generated files:")
    print("   • generated/coursera_en.html")
    print("   • generated/coursera_zh.html")

if __name__ == "__main__":
    print("🚀 Generating user study HTML files...")
    generate_userstudy_html()
    print("\n🚀 Generating Coursera practice HTML files...")
    generate_coursera_html()
