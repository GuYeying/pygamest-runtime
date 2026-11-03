# assets/hotfix.py——热更脚本示例（属**资源**而非脚本）
# 打包器不把它内嵌进 exe，而是随资源目录走 bundle 加密散文件（.sfx）；
# 运行时经 io 解密链 + modload/modfind 热更口加载——替换 .sfx 即热更，无需重出 exe。


def hotfix_version() -> int:
    return 1
