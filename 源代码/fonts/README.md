# 字体目录

本目录用于存放打包时随程序内置的中文字体，**仓库中不包含任何字体文件**。

## 为什么是空的？

程序原本内置 `simhei.ttf`（SimHei 黑体），用于在缺少中文字体的系统上避免出现「方块字」。
但 SimHei 的版权归 **微软 / 中易** 所有，属于专有字体，**不适合随开源项目公开再分发**，因此已从仓库中移除。

## 程序如何应对？

`main.py` 中的字体加载逻辑为「内置优先，系统兜底」：

1. 若 `fonts/` 下存在字体文件，注册并使用它；
2. 否则依次尝试系统中的 `Microsoft YaHei UI`、`Microsoft YaHei`、`SimHei`、`PingFang SC`、`Noto Sans CJK SC`、`Source Han Sans SC`、`WenQuanYi Micro Hei` 等常见中文字体。

因此在正常的中文 Windows 系统上，**移除字体文件不会影响中文显示**。

## 需要内置字体怎么办？

请自行准备**可合法分发**的字体（推荐开源的思源黑体 / Noto Sans SC），放入本目录并命名为 `simhei.ttf`，
或在 `main.py` 的 `_setup_font()` 中修改对应的文件名。
