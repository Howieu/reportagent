#!/bin/bash
# Vercel 构建：前端 + 把 LightGBM 需要的 libgomp 打包进函数（运行环境不一定自带）。
set -e
(cd web && npm ci && npm run build)

mkdir -p reportagent/native
dnf install -y libgomp || echo "警告：dnf 安装 libgomp 失败，继续查找系统里已有的版本"
lib=$(find /usr/lib64 /lib64 -name 'libgomp.so.1*' 2>/dev/null | head -1)
if [ -n "$lib" ]; then
  cp -L "$lib" reportagent/native/libgomp.so.1
  echo "已打包 $lib"
else
  echo "警告：没有找到 libgomp，线上预测会退回基线"
fi
