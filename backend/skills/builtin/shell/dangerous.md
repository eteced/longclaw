---
name: shell_dangerous
category: shell
description: 危险Shell命令警告和使用注意
---

# 危险命令警告

## When to Use
在执行任何删除、清空、格式化操作前务必先查阅此 Skill。

## ⚠️ 高危命令

### 删除操作
```bash
rm -rf /              # 绝对不要执行！删除根目录
rm -rf /home/*        # 删除所有用户目录
rm -rf ./*            # 在错误目录执行会删除所有文件
rm -rf node_modules   # 可能删错目录

# 安全替代
rm -ri                # 交互式确认每个文件
trash-cli             # 使用回收站
```

### 清空操作
```bash
> file.txt            # 清空文件内容
: > file.txt          # 同样清空文件
dd if=/dev/zero of=/dev/sda  # 绝对不要执行！格式化磁盘
```

### 网络操作
```bash
curl | sh             # 绝对不要执行！可能运行恶意脚本
wget | sh             # 同上
```

## 安全检查清单

1. **确认当前目录**: `pwd` 执行前务必确认
2. **确认目标路径**: 使用绝对路径而非相对路径
3. **备份重要数据**: 涉及删除前先备份
4. **使用 dry-run**: 许多命令支持 preview/dry-run 模式
5. **添加保护 alias**: `alias rm='rm -i'`

## 恢复误删

如果误删，可以使用以下方法尝试恢复：
- `git checkout` 从 Git 恢复
- `extundelete` 从 ext4 恢复
- 停止写入，防止覆盖

## 示例场景

### 安全删除 node_modules
```bash
# 1. 确认目录
pwd
ls node_modules | head -5

# 2. 使用 trash
trash node_modules

# 或者确认后删除
rm -rf node_modules
```

### 安全清空日志
```bash
# 保留文件，只清空内容
> /var/log/syslog

# 或使用 truncate
truncate -s 0 /var/log/syslog
```
