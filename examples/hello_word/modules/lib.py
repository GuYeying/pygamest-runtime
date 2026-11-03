# modules/lib.py——嵌套脚本目录示例（build 时随游戏根全量 .py 内嵌进 exe）
# 开发者可在游戏根下自由组织脚本目录/库目录，打包器自动扫描收集。


def greet(name: str) -> str:
    return f"hello {name} from modules.lib"
