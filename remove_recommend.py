#!/usr/bin/env python3
"""
Animeko 去"相关推荐"模块自动化工具 v1.0
====================================
功能：给定一个 Animeko 原版 APK，自动完成：
  1. 枚举 APK 内所有 classes*.dex
  2. 从 APK 提取每个 dex，用 baksmali 反编译为 smali
  3. 全局搜索字符串锚点 subject_recommendation_header 定位"相关推荐"渲染方法
  4. 将该方法整体替换为空壳（保留签名 .method ...，方法体立即 return Lkotlin/Unit.INSTANCE）
  5. 用 smali assemble 只重编被修改的那个 dex
  6. 用 zipfile 将新 dex 替换回 APK（其余条目原样）
  7. 用 apksigner 签名（复用同一 keystore，便于后续平滑升级安装）

用法：
  python3 remove_recommend.py <输入APK路径> [--out 输出APK路径] [--api <数字>]

示例：
  python3 remove_recommend.py /tmp/Animeko_new.apk --out /tmp/result.apk

环境变量(可选覆盖)：
  BAKSMALI, SMALI, APKSIGNER
  KS (keystore路径), KS_ALIAS, KS_PASS, KEY_PASS
"""
import os, re, shutil, subprocess, sys, tempfile, zipfile, argparse

# ---------- 锚点 ----------
ANCHOR = "subject_recommendation_header"

SHELL_BODY = [
    "    .locals 1",
    "",
    "    sget-object v0, Lkotlin/Unit;->INSTANCE:Lkotlin/Unit;",
    "",
    "    return-object v0",
]

# ---------- 配置 ----------
def tool(exe, envvar, default):
    v = os.environ.get(envvar)
    if v and os.path.exists(v):
        return v
    found = shutil.which(exe)
    if found:
        return found
    return default

BAKSMALI  = tool("baksmali", "BAKSMALI",  "/usr/bin/baksmali")
SMALI     = tool("smali",    "SMALI",     "/usr/bin/smali")
APKSIGNER = tool("apksigner","APKSIGNER", "/tmp/bt34/android-14/apksigner")
ZALIGN    = tool("zipalign", "ZALIGN",    "/usr/bin/zipalign")
KEYSTORE  = os.environ.get("KS", "/tmp/modkey.jks")
KS_ALIAS  = os.environ.get("KS_ALIAS", "animeko")
KS_PASS   = os.environ.get("KS_PASS", "123456")
KEY_PASS  = os.environ.get("KEY_PASS", "123456")


def log(msg):
    print(msg, flush=True)


def dex_files(apk_path):
    with zipfile.ZipFile(apk_path) as z:
        names = [n for n in z.namelist()
                 if re.fullmatch(r'classes\d*\.dex', n)]
    def num(n):
        m = re.search(r'(\d*)', n)
        return int(m.group(1)) if m.group(1) else 1
    names.sort(key=num)
    return names


def find_method_in_smali(file_path):
    """定位包含 ANCHOR 的方法，返回 (start,end,header)。"""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    tgt = None
    for i, ln in enumerate(lines):
        if ANCHOR in ln:
            tgt = i
            break
    if tgt is None:
        return None, None, None
    m_start = None
    for i in range(tgt, -1, -1):
        if re.match(r'^\s*\.method', lines[i]):
            m_start = i
            break
    if m_start is None:
        return None, None, None
    depth = 0
    m_end = None
    for i in range(m_start, len(lines)):
        if re.match(r'^\s*\.method', lines[i]):
            depth += 1
        elif re.match(r'^\s*\.end\s+method', lines[i]):
            depth -= 1
            if depth == 0:
                m_end = i
                break
    if m_end is None:
        return None, None, None
    return m_start, m_end, lines[m_start].strip()


def process_one_dex(apk_path, dex_name, workdir, api):
    dex_file = os.path.join(workdir, dex_name)
    with zipfile.ZipFile(apk_path) as z:
        with z.open(dex_name) as src, open(dex_file, "wb") as dst:
            shutil.copyfileobj(src, dst)

    out_dir = os.path.join(workdir, "out_" + (re.sub(r'\D', '', dex_name) or "1"))
    log(f"[*]  反编译 {dex_name} ...")
    cmd = [BAKSMALI, "disassemble", "-o", out_dir]
    if api:
        cmd += ["--api", str(api)]
    cmd.append(dex_file)
    subprocess.run(cmd, check=True)

    target_file = None
    for root, _, files in os.walk(out_dir):
        for fn in files:
            if fn.endswith(".smali"):
                p = os.path.join(root, fn)
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    if ANCHOR in f.read():
                        target_file = p
                        break
        if target_file:
            break
    if target_file is None:
        log(f"[~] {dex_name} 未包含目标锚点，跳过。")
        return None

    log(f"[*] {dex_name} 命中锚点: {os.path.relpath(target_file, out_dir)}")
    m_start, m_end, header = find_method_in_smali(target_file)
    if m_start is None:
        raise RuntimeError(f"无法定位目标方法边界于 {target_file}")
    log(f"[*] 定位到方法: {header}")

    with open(target_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    header_line = lines[m_start]
    rest = lines[m_end+1:]

    with open(target_file, "w", encoding="utf-8") as f:
        f.writelines(lines[:m_start])
        f.write(header_line)
        for b in SHELL_BODY:
            f.write(b + "\n")
        f.write(".end method\n")
        f.writelines(rest)
    log(f"[*]  已将方法替换为空壳。")

    new_dex = os.path.join(workdir, "new_" + dex_name)
    log(f"[*]  重新汇编 {dex_name} ...")
    scmd = [SMALI, "assemble", out_dir]
    if api:
        scmd += ["--api", str(api)]
    scmd += ["-o", new_dex]
    subprocess.run(scmd, check=True)
    log(f"[*]  生成新 dex: {new_dex}")
    return new_dex, os.path.relpath(target_file, out_dir)


def main():
    parser = argparse.ArgumentParser(description="Animeko 去相关推荐模块工具")
    parser.add_argument("apk", help="输入 Animeko 原版 APK 路径")
    parser.add_argument("--out", default=None, help="输出签名 APK 路径（默认 <name>_norecommend.apk）")
    parser.add_argument("--api", type=int, default=None, help="smali 编译 API 等级（可选）")
    parser.add_argument("--workdir", default=None, help="临时工作目录（可选）")
    args = parser.parse_args()

    workdir = args.workdir or tempfile.mkdtemp(prefix="animeko_tool_")
    if not os.path.isdir(workdir):
        os.makedirs(workdir, exist_ok=True)

    apk_path = os.path.abspath(args.apk)
    if not os.path.exists(apk_path):
        log(f"[!] 找不到 APK: {apk_path}")
        return 1
    base = os.path.basename(apk_path)
    stem = re.sub(r'\.apk$', '', base)
    out_patch = os.path.join(workdir, stem + "_patched.apk")
    out_final = os.path.abspath(args.out or (stem + "_norecommend.apk"))

    log(f"[工具] 工作目录: {workdir}")
    log(f"[工具] 输入: {apk_path}")
    dexs = dex_files(apk_path)
    log(f"[*] 检测到 {len(dexs)} 个 dex: {', '.join(dexs)}")

    patched = False
    for dex_name in dexs:
        log(f"[*] === {dex_name} ===")
        try:
            res = process_one_dex(apk_path, dex_name, workdir, args.api)
        except subprocess.CalledProcessError as e:
            log(f"[!] 处理 {dex_name} 出错: {e}")
            continue
        if res:
            new_dex, rel = res
            log(f"[*] 将新 dex 替换回 {dex_name} ...")
            with zipfile.ZipFile(apk_path) as zin:
                with zipfile.ZipFile(out_patch, "w", zipfile.ZIP_DEFLATED) as zout:
                    for item in zin.infolist():
                        data = zin.read(item.filename)
                        if item.filename == dex_name:
                            with open(new_dex, "rb") as f:
                                data = f.read()
                        # 保留原压缩方式（resources.arsc/.so 等 STORED 条目不能被压缩）
                        new_item = item
                        new_item.compress_type = item.compress_type
                        zout.writestr(new_item, data)
            patched = True
            log(f"[✓] 替换完成，生成 {out_patch}")
            break
    if not patched:
        log("[!] 未在任何 dex 中找到目标锚点，未能打补丁。")
        return 1

    log(f"[*] zipalign 对齐（resources.arsc 需 4 字节对齐以满足 Android 30+ 安装要求）...")
    out_aligned = os.path.join(workdir, stem + "_aligned.apk")
    zcmd = [ZALIGN, "-p", "-f", "4", out_patch, out_aligned]
    subprocess.run(zcmd, check=True)
    log(f"[✓] 对齐完成，生成 {out_aligned}")

    log(f"[*] apksigner 签名 ...")
    cmd = [APKSIGNER, "sign",
           "--ks", KEYSTORE,
           "--ks-key-alias", KS_ALIAS,
           "--ks-pass", "pass:" + KS_PASS,
           "--key-pass", "pass:" + KEY_PASS,
           "--out", out_final,
           out_aligned]
    subprocess.run(cmd, check=True)
    log(f"[✓] 已签名输出: {out_final}")
    log("[*] 验证签名 ...")
    subprocess.run([APKSIGNER, "verify", out_final], check=True)
    log("[✓] 全部完成喵！")
    return 0


if __name__ == "__main__":
    sys.exit(main())