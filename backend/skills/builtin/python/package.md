---
name: python_package
category: python
description: pip, venv 等 Python 包管理指南
---

# Python 包管理

## When to Use
当需要安装、卸载 Python 包或管理虚拟环境时使用此 Skill。

## pip 使用

### 安装包
```bash
pip install package_name           # 安装最新版本
pip install package==1.2.3        # 安装指定版本
pip install package>=1.0,<2.0     # 版本范围
pip install -r requirements.txt    # 从文件安装
```

### 升级包
```bash
pip install --upgrade package
pip install --upgrade pip         # 升级 pip 本身
```

### 卸载包
```bash
pip uninstall package
pip uninstall -r requirements.txt  # 批量卸载
```

### 查看已安装的包
```bash
pip list                          # 列出所有包
pip list --outdated               # 列出可升级的包
pip show package_name            # 显示包详情
```

### 导出依赖
```bash
pip freeze > requirements.txt
pip freeze | grep -v "^-e" > requirements.txt  # 排除 editable 安装
```

## 虚拟环境

### 创建虚拟环境
```bash
python -m venv myenv              # 创建
source myenv/bin/activate         # 激活 (Linux/Mac)
myenv\Scripts\activate           # 激活 (Windows)
```

### 使用 virtualenv
```bash
pip install virtualenv
virtualenv myenv
source myenv/bin/activate
```

### 管理环境
```bash
deactivate                        # 退出虚拟环境
rm -rf myenv                      # 删除虚拟环境
```

## pipenv 和 poetry

### pipenv
```bash
pip install pipenv
pipenv install package
pipenv install --dev package
pipenv shell
```

### poetry
```bash
pip install poetry
poetry add package
poetry add --dev package
poetry shell
poetry install                    # 安装所有依赖
```

## 镜像源

### 临时使用
```bash
pip install package -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 设为默认
```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 常用镜像
- 清华: https://pypi.tuna.tsinghua.edu.cn/simple
- 阿里: https://mirrors.aliyun.com/pypi/simple
- 腾讯: https://mirrors.cloud.tencent.com/pypi/simple
