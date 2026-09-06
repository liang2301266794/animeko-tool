#!/usr/bin/env bash
# =================================================
#  Animeko 一键去"相关推荐"工具入口
#  用法: ./animeko_patch.sh <原版APK路径> [输出APK路径]
#  依赖: python3, baksmali, smali, apksigner, keystore
# =================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$SCRIPT_DIR/remove_recommend.py"

# ---- 可配置项（也可通过环境变量覆盖）----
# keystore 路径：优先使用环境变量 KS，否则默认为脚本目录下的 modkey.jks
KS="${KS:-$SCRIPT_DIR/modkey.jks}"
export KS
export KS_ALIAS="${KS_ALIAS:-animeko}"
export KS_PASS="${KS_PASS:-123456}"
export KEY_PASS="${KEY_PASS:-123456}"

# ---- 密钥存在性检测与自动生成 ----
# 如果指定的 keystore 不存在，尝试：
#   1. 在脚本目录查找已有的 *.jks 文件（用户可能自己放了一个）
#   2. 若还是找不到，则用 keytool 自动生成一个临时密钥
if [ ! -f "$KS" ]; then
    echo "[!] 未找到 keystore: $KS"
    # 尝试在脚本目录下找已有的 .jks
    FOUND_JKS=""
    for f in "$SCRIPT_DIR"/*.jks; do
        if [ -f "$f" ]; then
            FOUND_JKS="$f"
            break
        fi
    done
    if [ -n "$FOUND_JKS" ]; then
        echo "[✓] 在脚本目录发现已有的 keystore: $FOUND_JKS"
        KS="$FOUND_JKS"
        export KS
    else
        echo "[!] 未发现已有密钥，将自动生成一个新的签名密钥..."
        # 使用 keytool 生成临时密钥（需要用户自行备份）
        if ! command -v keytool >/dev/null 2>&1; then
            echo "❌ 找不到 keytool 命令，请安装 JDK 后再试，或手动提供 keystore（用环境变量 KS 指定）。"
            exit 1
        fi
        keytool -genkeypair -v \
            -keystore "$KS" \
            -alias "$KS_ALIAS" \
            -keyalg RSA \
            -keysize 2048 \
            -validity 36500 \
            -storepass "$KS_PASS" \
            -keypass "$KEY_PASS" \
            -dname "CN=Animeko Tool, OU=Dev, O=Animeko, L=Unknown, ST=Unknown, C=CN"
        RC=$?
        if [ $RC -ne 0 ]; then
            echo "❌ 自动生成 keystore 失败 (exit=$RC)，请检查 keytool 是否可用，或手动指定 KS。"
            exit $RC
        fi
        echo "=============================================="
        echo "🚨 重要提示："
        echo "  已自动生成签名密钥: $KS"
        echo "  别名: $KS_ALIAS"
        echo "  ⚠️  请务必备份该密钥文件！"
        echo "  后续处理新版 APK 需要复用同一密钥才能平滑覆盖安装。"
        echo "  备份方法：cp \"$KS\" <安全位置>"
        echo "=============================================="
    fi
fi

if [ $# -lt 1 ]; then
    echo "用法: $0 <原版APK路径> [输出APK路径]"
    exit 1
fi
IN_APK="$1"
if [ ! -f "$IN_APK" ]; then
    echo "[!] 找不到 APK: $IN_APK"
    exit 1
fi
OUT="${2:-}"
# smali 汇编 API 级别：必须为 35，否则接口 default 方法标志丢失导致应用闪退
API="${API:-35}"
ARGS=("$IN_APK" --api "$API")
if [ -n "$OUT" ]; then
    ARGS+=(--out "$OUT")
fi

echo "=========================================="
echo " Animeko 一键去相关推荐工具"
echo " 输入: $IN_APK"
echo " Keystore: $KS"
echo "=========================================="
echo "运行工具中……（此过程需反编译多个 dex，请耐心等待）"
echo
python3 "$TOOL" "${ARGS[@]}"
RC=$?
echo
if [ $RC -eq 0 ]; then
    echo "✅ 全部完成！请到输出目录取用签名 APK。"
else
    echo "❌ 执行出错 (exit=$RC)，请查看上面的日志。"
fi
exit $RC
