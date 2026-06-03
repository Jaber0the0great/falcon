import re
import sys

def check_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract <script> blocks
    scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
    if not scripts:
        print("No script blocks found.")
        return
        
    for idx, script in enumerate(scripts):
        print(f"Checking script block {idx+1}...")
        stack = []
        mapping = {')': '(', '}': '{', ']': '['}
        lines = script.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # Ignore comments and string literals to keep bracket matching simple
            # (Remove single line comments)
            line = re.sub(r'//.*', '', line)
            # (Remove strings)
            line = re.sub(r'"[^"]*"', '""', line)
            line = re.sub(r"'[^']*'", "''", line)
            line = re.sub(r'`[^`]*`', '``', line)
            
            for char in line:
                if char in ['(', '{', '[']:
                    stack.append((char, line_num, line.strip()))
                elif char in [')', '}', ']']:
                    if not stack:
                        print(f"Error: Unmatched closing bracket '{char}' at line {line_num}: {line.strip()}")
                        return False
                    top_char, top_line, top_content = stack.pop()
                    if mapping[char] != top_char:
                        print(f"Error: Mismatched bracket. Found '{char}' at line {line_num} but expected matching for '{top_char}' from line {top_line}: {top_content}")
                        return False
        if stack:
            print("Error: Unclosed brackets remaining at end of script:")
            for char, line_num, content in stack:
                print(f"  Unclosed '{char}' from line {line_num}: {content}")
            return False
        print("All brackets matched successfully in this block.")
    return True

if __name__ == '__main__':
    check_file('d:/Downloads/web_app/falcon/templates/admin/admin_dashboard.html')
