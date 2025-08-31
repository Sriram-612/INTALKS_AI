#!/usr/bin/env python3
"""
Fix Logger Errors in main.py
Replaces all incorrect logger.error.error() and logger.error.warning() calls
"""

import re

def fix_logger_errors():
    """Fix all logger errors in main.py"""
    
    file_path = "/home/cyberdude/Documents/Projects/voice/main.py"
    
    print("🔧 Fixing logger errors in main.py...")
    
    # Read the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Track replacements
    replacements = 0
    
    # Fix logger.error.error() -> logger.error()
    content, count1 = re.subn(r'logger\.error\.error\(', 'logger.error(', content)
    replacements += count1
    
    # Fix logger.error.warning() -> logger.warning()
    content, count2 = re.subn(r'logger\.error\.warning\(', 'logger.warning(', content)
    replacements += count2
    
    # Write the fixed content back
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"✅ Fixed {replacements} logger errors:")
    print(f"   - logger.error.error() → logger.error(): {count1} replacements")
    print(f"   - logger.error.warning() → logger.warning(): {count2} replacements")
    
    if replacements > 0:
        print("🎉 All logger errors have been fixed!")
    else:
        print("ℹ️  No logger errors found to fix")

if __name__ == "__main__":
    fix_logger_errors()
