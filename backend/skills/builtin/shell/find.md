---
name: shell_find
category: shell
description: find, grep, sed, awk 等shell命令使用指南
---

# Shell 常用命令

## When to Use
当需要查找文件、搜索内容、文本处理时使用此 Skill。

## find - 查找文件
```bash
# 按名称查找
find . -name "*.py"
find . -name "config*"

# 按类型查找
find . -type f -name "*.md"    # 文件
find . -type d -name "node_modules"  # 目录

# 按时间查找
find . -mtime -7               # 7天内修改的文件
find . -atime +30              # 30天前访问的文件

# 按大小查找
find . -size +100M             # 大于100M的文件

# 执行命令
find . -name "*.tmp" -delete   # 删除所有tmp文件
find . -name "*.py" -exec grep -l "pattern" {} \;
```

## grep - 搜索内容
```bash
# 基本搜索
grep "pattern" file.txt
grep -r "pattern" directory/

# 忽略大小写
grep -i "pattern" file.txt

# 显示行号
grep -n "pattern" file.txt

# 只显示文件名
grep -l "pattern" *.txt

# 反向匹配
grep -v "pattern" file.txt

# 正则表达式
grep -E "^[0-9]+" file.txt
```

## sed - 文本替换
```bash
# 替换
sed 's/old/new/g' file.txt

# 原地替换
sed -i 's/old/new/g' file.txt

# 删除行
sed '/pattern/d' file.txt

# 显示特定行
sed -n '10,20p' file.txt
```

## awk - 文本分析
```bash
# 打印列
awk '{print $1}' file.txt

# 指定分隔符
awk -F',' '{print $2}' file.csv

# 条件过滤
awk '$3 > 100' file.txt

# 求和
awk '{sum += $2} END {print sum}' file.txt
```

## xargs - 组合命令
```bash
find . -name "*.py" | xargs grep "pattern"
find . -name "*.tmp" | xargs rm
```
