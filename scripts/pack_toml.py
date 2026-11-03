"""pack.toml 手解析器（纯 Python 子集——KEY=VALUE + [节头] + 注释）
被 build.py 和 build_xxx.py 共用——不依赖 toml 库"""
import os

def load(path):
    if not os.path.isfile(path):
        return {}
    result = {}
    section = "base"
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            result.setdefault(section, {})
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result.setdefault(section, {})[key.strip()] = val.strip().strip('"').strip("'")
    return result

def merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out

def get_target(config, target):
    base = {}
    for sec in ("base", "game", "build", "pack", "scripts", "resources"):
        base.update(config.get(sec, {}))
    plat = config.get(target, {})
    for k, v in plat.items():
        base[k] = v
    base["_target"] = target
    return base
